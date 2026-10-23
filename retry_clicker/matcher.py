"""Multi-scale template matching with native-resolution verification.

The screen is normally captured at 2x on Retina displays, so the search runs
on a downscaled copy for speed.  The expected scale is derived from the
capture's pixel density and the template's own DPI, then the best candidate
is re-matched at full resolution before it is trusted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .config import MatcherConfig
from .screen import Capture, Display
from .templates import Template

#: Scores below this are treated as "nothing there" by the coarse pass.
_CANNY_LOW = 50
_CANNY_HIGH = 150


@dataclass
class Detection:
    template_name: str
    mode: str
    score: float
    coarse_score: float
    scale: float
    #: Center in native screenshot pixels.
    center_px: Tuple[float, float]
    #: Bounding box in native screenshot pixels: (x, y, w, h).
    rect_px: Tuple[int, int, int, int]
    display: Display
    #: Click point in global screen points.
    global_point: Tuple[float, float]

    @property
    def summary(self) -> str:
        x, y = self.global_point
        return (
            f"{self.template_name}/{self.mode} score={self.score:.3f} "
            f"scale={self.scale:.2f} at ({x:.0f},{y:.0f})"
        )


@dataclass
class _Candidate:
    template: Template
    mode: str
    scale: float
    coarse_score: float
    center_work: Tuple[float, float]
    size_work: Tuple[int, int]


def _top_left_to_center(
    x: int, y: int, width: int, height: int
) -> Tuple[float, float]:
    return (x + width / 2.0, y + height / 2.0)


def _darken(gray: np.ndarray) -> np.ndarray:
    """Create an approximate dark-theme variant of a light template."""
    source = gray.astype(np.float32)
    return np.clip(28.0 + (255.0 - source) * 0.88, 0.0, 255.0).astype(np.uint8)


def _resize(gray: np.ndarray, width: int, height: int) -> Optional[np.ndarray]:
    if width < 4 or height < 3:
        return None
    interpolation = cv2.INTER_AREA if width < gray.shape[1] else cv2.INTER_LINEAR
    return cv2.resize(gray, (width, height), interpolation=interpolation)


class Matcher:
    def __init__(self, templates: Sequence[Template], config: MatcherConfig) -> None:
        if not templates:
            raise ValueError("at least one template is required")
        self.templates = list(templates)
        self.config = config
        self._dark_cache: Dict[str, np.ndarray] = {
            template.name: _darken(template.gray) for template in self.templates
        }
        self._last_work_factor = 1.0
        self._last_scales: List[float] = []
        self._last_deep_at: Dict[int, float] = {}

    # ------------------------------------------------------------------ API
    def find(self, capture: Capture) -> List[Detection]:
        """Return verified detections in a capture, best score first.

        The first call for each display and one call every ``deep_interval``
        seconds run a wider scale range.  In between, the narrow range keeps
        the polling loop responsive without burning CPU.
        """
        height, width = capture.image.shape[:2]
        if width < 32 or height < 32:
            return []

        work_factor = min(
            1.0, self.config.max_search_edge / float(max(width, height))
        )
        if work_factor < 1.0:
            work = cv2.resize(
                capture.image,
                (max(1, int(round(width * work_factor))), max(1, int(round(height * work_factor)))),
                interpolation=cv2.INTER_AREA,
            )
        else:
            work = capture.image
        work_gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
        work_height, work_width = work_gray.shape[:2]

        base_scale = capture.scale / self.config.template_dpi
        if base_scale <= 0:
            return []
        now = time.monotonic()
        display_id = capture.display.display_id
        deep = (
            now - self._last_deep_at.get(display_id, -1e9)
            >= self.config.deep_interval
        )
        if deep:
            self._last_deep_at[display_id] = now
        scales = self._scales(base_scale, deep)
        self._last_work_factor = work_factor
        self._last_scales = scales

        for mode in self.config.modes:
            if mode == "edge":
                screen_variant = cv2.Canny(work_gray, _CANNY_LOW, _CANNY_HIGH)
                coarse_threshold = self.config.edge_coarse_threshold
            else:
                screen_variant = work_gray
                coarse_threshold = self.config.coarse_threshold

            candidates: List[_Candidate] = []
            for template in self.templates:
                source = (
                    self._dark_cache[template.name]
                    if mode == "dark"
                    else template.gray
                )
                for scale in scales:
                    work_scale = scale * work_factor
                    tw = int(round(template.width * work_scale))
                    th = int(round(template.height * work_scale))
                    scaled = _resize(source, tw, th)
                    if scaled is None:
                        continue
                    if tw >= work_width or th >= work_height:
                        continue
                    if mode == "edge":
                        scaled = cv2.Canny(scaled, _CANNY_LOW, _CANNY_HIGH)

                    result = cv2.matchTemplate(
                        screen_variant, scaled, cv2.TM_CCOEFF_NORMED
                    )
                    _, score, _, location = cv2.minMaxLoc(result)
                    if not np.isfinite(score) or score < coarse_threshold:
                        continue
                    candidate = _Candidate(
                        template=template,
                        mode=mode,
                        scale=scale,
                        coarse_score=float(score),
                        center_work=_top_left_to_center(
                            int(location[0]), int(location[1]), tw, th
                        ),
                        size_work=(tw, th),
                    )
                    if score >= self.config.early_exit_score:
                        # A near-perfect coarse hit is almost certainly the
                        # button; verify and return without testing the rest.
                        detection = self._verify(capture, candidate, work_factor)
                        if detection is not None:
                            return [detection]
                    candidates.append(candidate)

            if not candidates:
                continue
            candidates = self._dedupe(candidates)
            candidates.sort(key=lambda item: item.coarse_score, reverse=True)

            verified: List[Detection] = []
            for candidate in candidates[: self.config.max_candidates]:
                detection = self._verify(capture, candidate, work_factor)
                if detection is not None:
                    verified.append(detection)
            if verified:
                return self._nms(verified)
        return []

    # ------------------------------------------------------------- internals
    def _scales(self, base: float, deep: bool = False) -> List[float]:
        tolerance = self.config.scale_tolerance
        steps = self.config.scale_steps
        if steps == 1 or tolerance <= 0:
            values = [1.0]
        else:
            values = list(np.linspace(1.0 - tolerance, 1.0 + tolerance, steps))
        values.append(1.0)
        if deep:
            # Cover unusual window zoom / template DPI mismatches occasionally.
            values.extend([0.55, 0.7, 1.3, 1.55])
        # Try the expected scale first: an exact match then exits early.
        ordered = sorted(values, key=lambda value: abs(value - 1.0))
        unique: List[float] = []
        for value in ordered:
            scale = base * float(value)
            if scale <= 0.05 or scale > 8.0:
                continue
            if not unique or abs(scale - unique[-1]) > 1e-4:
                unique.append(scale)
        return unique

    @staticmethod
    def _dedupe(candidates: List[_Candidate]) -> List[_Candidate]:
        ordered = sorted(candidates, key=lambda item: item.coarse_score, reverse=True)
        kept: List[_Candidate] = []
        for candidate in ordered:
            duplicate = False
            for existing in kept:
                if existing.template.name != candidate.template.name:
                    continue
                distance = (
                    (existing.center_work[0] - candidate.center_work[0]) ** 2
                    + (existing.center_work[1] - candidate.center_work[1]) ** 2
                ) ** 0.5
                limit = max(4.0, 0.25 * min(existing.size_work))
                if distance < limit:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(candidate)
        return kept

    def _verify(
        self, capture: Capture, candidate: _Candidate, work_factor: float
    ) -> Optional[Detection]:
        native_gray = capture.gray
        native_height, native_width = native_gray.shape[:2]
        center_x = candidate.center_work[0] / work_factor
        center_y = candidate.center_work[1] / work_factor

        source = (
            self._dark_cache[candidate.template.name]
            if candidate.mode == "dark"
            else candidate.template.gray
        )
        if candidate.mode == "edge":
            screen = cv2.Canny(native_gray, _CANNY_LOW, _CANNY_HIGH)
        else:
            screen = native_gray

        if candidate.mode == "color":
            threshold = self.config.threshold
        elif candidate.mode == "dark":
            threshold = max(0.5, self.config.threshold - self.config.dark_threshold_delta)
        else:
            threshold = self.config.edge_threshold

        # The coarse scale is quantised; try a few nearby scales at full res.
        step = 0.03
        scales = [
            candidate.scale,
            candidate.scale * (1.0 - step),
            candidate.scale * (1.0 + step),
        ]
        best: Optional[Detection] = None
        for scale in scales:
            tw = int(round(candidate.template.width * scale))
            th = int(round(candidate.template.height * scale))
            scaled = _resize(source, tw, th)
            if scaled is None:
                continue
            if candidate.mode == "edge":
                scaled = cv2.Canny(scaled, _CANNY_LOW, _CANNY_HIGH)

            margin_x = max(8, int(round(tw * 0.15)))
            margin_y = max(8, int(round(th * 0.15)))
            left = int(round(center_x)) - tw // 2 - margin_x
            top = int(round(center_y)) - th // 2 - margin_y
            right = left + tw + margin_x * 2
            bottom = top + th + margin_y * 2
            # Clamp to the screen instead of rejecting buttons near an edge.
            left = max(0, left)
            top = max(0, top)
            right = min(native_width, right)
            bottom = min(native_height, bottom)
            if right - left < tw or bottom - top < th:
                continue
            crop = screen[top:bottom, left:right]
            if crop.shape[0] < th or crop.shape[1] < tw:
                continue
            result = cv2.matchTemplate(crop, scaled, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(result)
            if not np.isfinite(score) or score < threshold:
                continue
            if best is not None and score <= best.score:
                continue
            rect_x = left + int(location[0])
            rect_y = top + int(location[1])
            cx = rect_x + tw / 2.0
            cy = rect_y + th / 2.0
            gx, gy = capture.center_to_global(cx, cy)
            best = Detection(
                template_name=candidate.template.name,
                mode=candidate.mode,
                score=float(score),
                coarse_score=candidate.coarse_score,
                scale=float(scale),
                center_px=(cx, cy),
                rect_px=(rect_x, rect_y, tw, th),
                display=capture.display,
                global_point=(gx, gy),
            )

        if best is None or best.score < threshold:
            return None
        return best

    @staticmethod
    def _nms(detections: List[Detection]) -> List[Detection]:
        ordered = sorted(detections, key=lambda item: item.score, reverse=True)
        kept: List[Detection] = []
        for detection in ordered:
            duplicate = False
            for existing in kept:
                if existing.template_name != detection.template_name:
                    continue
                distance = (
                    (existing.center_px[0] - detection.center_px[0]) ** 2
                    + (existing.center_px[1] - detection.center_px[1]) ** 2
                ) ** 0.5
                limit = max(
                    6.0,
                    0.25
                    * min(
                        existing.rect_px[2],
                        existing.rect_px[3],
                        detection.rect_px[2],
                        detection.rect_px[3],
                    ),
                )
                if distance < limit:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(detection)
        return kept
