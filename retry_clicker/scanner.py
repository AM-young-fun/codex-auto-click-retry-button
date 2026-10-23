"""Screen scanning: capture every display, match, and apply window policy."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2

from .matcher import Detection, Matcher
from .screen import (
    Capture,
    Display,
    ScreenError,
    capture_display,
    list_displays,
)
from .windows import WindowPolicy, list_windows

logger = logging.getLogger(__name__)


@dataclass
class ScanFinding:
    detection: Detection
    allowed: bool
    window_label: str
    capture: Capture = field(repr=False, compare=False)


def _timestamp() -> str:
    now = time.time()
    milliseconds = int((now - int(now)) * 1000)
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + f"-{milliseconds:03d}"


class ScreenScanner:
    """Reusable scanner for one watcher session."""

    def __init__(
        self,
        matcher: Matcher,
        policy: WindowPolicy,
        debug_dir: str = "",
        display_refresh_interval: float = 15.0,
    ) -> None:
        self.matcher = matcher
        self.policy = policy
        self.debug_dir = Path(debug_dir).expanduser() if debug_dir else None
        self.display_refresh_interval = display_refresh_interval
        self._displays: List[Display] = []
        self._displays_loaded_at = -1e9
        self._last_capture_warning = -1e9
        self._skip_log_at: Dict[str, float] = {}
        self._last_debug_at = -1e9
        self._last_debug_key: Optional[Tuple[int, int, int]] = None

    # ------------------------------------------------------------------ API
    def displays(self) -> List[Display]:
        now = time.monotonic()
        if not self._displays or now - self._displays_loaded_at > self.display_refresh_interval:
            self._displays = list_displays()
            self._displays_loaded_at = now
            logger.debug("displays refreshed: %s", self._displays)
        return self._displays

    def capture_all(self) -> List[Capture]:
        captures: List[Capture] = []
        for display in self.displays():
            try:
                captures.append(capture_display(display))
            except ScreenError as exc:
                now = time.monotonic()
                if now - self._last_capture_warning > 10.0:
                    logger.warning("截图失败: %s", exc)
                    self._last_capture_warning = now
        return captures

    def scan_findings(self) -> List[ScanFinding]:
        windows = list_windows() if self.policy.enabled else []
        findings: List[ScanFinding] = []
        for capture in self.capture_all():
            for detection in self.matcher.find(capture):
                allowed, label = self.policy.evaluate(
                    windows, detection.global_point[0], detection.global_point[1]
                )
                findings.append(
                    ScanFinding(
                        detection=detection,
                        allowed=allowed,
                        window_label=label,
                        capture=capture,
                    )
                )
        findings.sort(key=lambda item: item.detection.score, reverse=True)
        return findings

    def scan(self) -> Optional[ScanFinding]:
        findings = self.scan_findings()
        if not findings:
            return None
        allowed = [item for item in findings if item.allowed]
        if not allowed:
            self._log_skipped(findings[0])
            return None
        best = allowed[0]
        self._maybe_save_debug(best)
        return best

    # ------------------------------------------------------------- debugging
    def save_debug(
        self,
        findings: Sequence[ScanFinding],
        directory: Optional[Path] = None,
        prefix: str = "hit",
    ) -> List[Path]:
        target = Path(directory) if directory is not None else self.debug_dir
        if target is None or not findings:
            return []
        target.mkdir(parents=True, exist_ok=True)
        by_display: Dict[int, Tuple[Capture, List[ScanFinding]]] = {}
        for finding in findings:
            display_id = finding.detection.display.display_id
            if display_id not in by_display:
                by_display[display_id] = (finding.capture, [])
            by_display[display_id][1].append(finding)

        saved: List[Path] = []
        for display_id, (capture, group) in by_display.items():
            annotated = capture.image.copy()
            for finding in group:
                x, y, width, height = finding.detection.rect_px
                color = (60, 200, 60) if finding.allowed else (40, 40, 230)
                cv2.rectangle(
                    annotated,
                    (x, y),
                    (x + width, y + height),
                    color,
                    3,
                )
                label = (
                    f"{finding.detection.mode} {finding.detection.score:.3f} "
                    f"{'OK' if finding.allowed else 'SKIP'}"
                )
                cv2.putText(
                    annotated,
                    label,
                    (x, max(24, y - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    color,
                    2,
                    cv2.LINE_AA,
                )
            filename = f"{prefix}-{_timestamp()}-display{display_id}.png"
            path = target / filename
            ok, encoded = cv2.imencode(".png", annotated)
            if ok:
                encoded.tofile(str(path))
                saved.append(path)
        if saved:
            logger.info("调试截图已保存: %s", ", ".join(str(path) for path in saved))
        return saved

    # ------------------------------------------------------------- internals
    def _log_skipped(self, finding: ScanFinding) -> None:
        key = f"{finding.window_label}"
        now = time.monotonic()
        last = self._skip_log_at.get(key, -1e9)
        if now - last < 30.0:
            return
        self._skip_log_at[key] = now
        detection = finding.detection
        logger.info(
            "匹配到 Retry (%s)，但%s；为避免误点已跳过。可用 --no-window-filter 关闭过滤。",
            detection.summary,
            finding.window_label,
        )

    def _maybe_save_debug(self, finding: ScanFinding) -> None:
        if self.debug_dir is None:
            return
        now = time.monotonic()
        x, y = finding.detection.global_point
        key = (
            finding.detection.display.display_id,
            int(x // 20),
            int(y // 20),
        )
        if key == self._last_debug_key and now - self._last_debug_at < 2.0:
            return
        self._last_debug_key = key
        self._last_debug_at = now
        self.save_debug([finding], prefix="hit")
