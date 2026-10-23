"""Shared helpers for the test-suite."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

import cv2
import numpy as np

from retry_clicker.matcher import Detection
from retry_clicker.scanner import ScanFinding
from retry_clicker.screen import Capture, Display
from retry_clicker.templates import Template

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = ROOT / "assets" / "templates" / "retry_button.png"


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def make_capture(
    template: Template,
    *,
    display_width: float = 800.0,
    display_height: float = 500.0,
    pixel_scale: float = 2.0,
    template_scale: float = 1.0,
    position: tuple = (500, 300),
    background: int = 255,
    dark: bool = False,
) -> Capture:
    width = int(round(display_width * pixel_scale))
    height = int(round(display_height * pixel_scale))
    image = np.full((height, width, 3), background, dtype=np.uint8)
    scaled = cv2.resize(
        template.gray,
        None,
        fx=template_scale,
        fy=template_scale,
        interpolation=cv2.INTER_AREA,
    )
    x, y = position
    image[y : y + scaled.shape[0], x : x + scaled.shape[1]] = cv2.cvtColor(
        scaled, cv2.COLOR_GRAY2BGR
    )
    if dark:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
        image = cv2.cvtColor(
            np.clip(28.0 + (255.0 - gray) * 0.88, 0.0, 255.0).astype(np.uint8),
            cv2.COLOR_GRAY2BGR,
        )
    return Capture(
        display=Display(
            display_id=1,
            origin_x=0.0,
            origin_y=0.0,
            width=display_width,
            height=display_height,
        ),
        image=image,
    )


def make_detection(
    x: float = 100.0, y: float = 100.0, score: float = 0.99
) -> Detection:
    return Detection(
        template_name="retry_button",
        mode="color",
        score=score,
        coarse_score=0.95,
        scale=1.0,
        center_px=(x * 2, y * 2),
        rect_px=(int(x * 2) - 60, int(y * 2) - 34, 121, 68),
        display=Display(1, 0.0, 0.0, 800.0, 500.0),
        global_point=(x, y),
    )


def make_finding(
    x: float = 100.0, y: float = 100.0, score: float = 0.99, allowed: bool = True
) -> ScanFinding:
    image = np.full((1000, 1600, 3), 255, dtype=np.uint8)
    capture = Capture(Display(1, 0.0, 0.0, 800.0, 500.0), image)
    return ScanFinding(
        detection=make_detection(x, y, score),
        allowed=allowed,
        window_label="Test — Codex",
        capture=capture,
    )


class SequenceScanner:
    """Returns a fixed sequence of findings, then repeats the last item."""

    def __init__(self, items: Iterable[Optional[ScanFinding]]) -> None:
        self.items = list(items)
        self.index = 0

    def scan(self) -> Optional[ScanFinding]:
        if not self.items:
            return None
        if self.index < len(self.items):
            item = self.items[self.index]
            self.index += 1
            return item
        return self.items[-1]


class RecordingClicker:
    def __init__(self, clock: Optional[FakeClock] = None) -> None:
        self.clicks: list = []
        self._clock = clock

    def click(self, x: float, y: float) -> None:
        timestamp = self._clock.value if self._clock is not None else None
        self.clicks.append((x, y, timestamp))
