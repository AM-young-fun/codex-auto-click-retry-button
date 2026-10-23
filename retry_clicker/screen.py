"""Display enumeration and screen capture.

Quartz returns screenshots at *physical* pixel resolution while window bounds
and mouse coordinates use *points*.  A :class:`Capture` keeps both together so
that template matching (pixels) can be translated into click coordinates
(points) without guessing the Retina scale factor.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np

try:  # pragma: no cover - exercised implicitly on macOS
    import Quartz
except Exception:  # pragma: no cover - only on non-macOS/broken installs
    Quartz = None  # type: ignore[assignment]


class ScreenError(RuntimeError):
    """Raised when displays cannot be enumerated or captured."""


def _require_quartz() -> None:
    if Quartz is None:
        raise ScreenError(
            "PyObjC/Quartz is not available. Install it with "
            "`pip install pyobjc-framework-Quartz`."
        )


@dataclass(frozen=True)
class Display:
    """A physical display in the global (points) coordinate space."""

    display_id: int
    origin_x: float
    origin_y: float
    width: float
    height: float

    def pixel_to_global(self, x: float, y: float, scale: float) -> Tuple[float, float]:
        """Convert a pixel coordinate inside the display to global points."""
        if scale <= 0:
            raise ValueError("scale must be positive")
        return (self.origin_x + x / scale, self.origin_y + y / scale)

    def contains_point(self, x: float, y: float) -> bool:
        return (
            self.origin_x <= x < self.origin_x + self.width
            and self.origin_y <= y < self.origin_y + self.height
        )


@dataclass
class Capture:
    """A screenshot plus everything needed to map it back to the screen."""

    display: Display
    image: np.ndarray  # BGR, physical pixels
    _gray: Optional[np.ndarray] = field(default=None, repr=False, compare=False)

    @property
    def scale(self) -> float:
        """Physical pixels per point for this capture."""
        if self.display.width <= 0:
            return 1.0
        return float(self.image.shape[1]) / float(self.display.width)

    @property
    def gray(self) -> np.ndarray:
        if self._gray is None:
            self._gray = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)
        return self._gray

    def center_to_global(self, x: float, y: float) -> Tuple[float, float]:
        return self.display.pixel_to_global(x, y, self.scale)


def list_displays() -> List[Display]:
    """Return all active displays, primary first."""
    _require_quartz()
    err, ids, _count = Quartz.CGGetActiveDisplayList(32, None, None)
    if err != 0:
        raise ScreenError(f"CGGetActiveDisplayList failed with error {err}")
    result: List[Display] = []
    for display_id in ids:
        bounds = Quartz.CGDisplayBounds(display_id)
        origin = bounds.origin
        size = bounds.size
        if size.width <= 1 or size.height <= 1:
            continue
        result.append(
            Display(
                display_id=int(display_id),
                origin_x=float(origin.x),
                origin_y=float(origin.y),
                width=float(size.width),
                height=float(size.height),
            )
        )
    if not result:
        raise ScreenError("no active displays found")
    return result


def _bgr_from_cgimage(image) -> np.ndarray:
    """Convert a 32-bit CGImage to a BGR numpy array without re-encoding."""
    width = int(Quartz.CGImageGetWidth(image))
    height = int(Quartz.CGImageGetHeight(image))
    bpp = int(Quartz.CGImageGetBitsPerPixel(image))
    row_bytes = int(Quartz.CGImageGetBytesPerRow(image))
    info = int(Quartz.CGImageGetBitmapInfo(image))
    if bpp != 32:
        raise ScreenError(f"unsupported CGImage pixel format ({bpp} bits)")

    data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(image))
    raw = np.frombuffer(data, dtype=np.uint8)
    expected = row_bytes * height
    if raw.size < expected:
        raise ScreenError("CGImage data is shorter than expected")
    pixels = raw[:expected].reshape(height, row_bytes // 4, 4)

    byte_order = info & 0x7000  # kCGBitmapByteOrderMask
    alpha_info = info & 0x1F
    little_endian = byte_order == 0x2000  # kCGBitmapByteOrder32Little
    # Alpha-first layouts:  pre-multiplied alpha, straight alpha, skip alpha.
    alpha_first = alpha_info in (2, 4, 6)

    if little_endian and alpha_first:
        # memory: B G R A
        bgr = pixels[:, :, 0:3]
    elif little_endian:
        # memory: A B G R
        bgr = pixels[:, :, 1:4]
    elif alpha_first:
        # memory: A R G B
        bgr = pixels[:, :, [3, 2, 1]]
    else:
        # memory: R G B A
        bgr = pixels[:, :, [2, 1, 0]]

    image_bgr = np.ascontiguousarray(bgr[:, :width, :])
    return image_bgr


def _display_ordinal(display: Display) -> int:
    """1-based index used by the ``screencapture -D`` fallback."""
    for index, item in enumerate(list_displays(), start=1):
        if item.display_id == display.display_id:
            return index
    return 1


def _capture_with_screencapture(display: Display) -> np.ndarray:
    ordinal = _display_ordinal(display)
    fd, path = tempfile.mkstemp(prefix="retry-clicker-", suffix=".png")
    os.close(fd)
    try:
        command = ["screencapture", "-x", "-t", "png", "-D", str(ordinal), path]
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            raise ScreenError(
                "screencapture failed: "
                + (result.stderr.strip() or f"exit code {result.returncode}")
            )
        image = cv2.imread(path, cv2.IMREAD_COLOR)
        if image is None or image.size == 0:
            raise ScreenError("screencapture produced an empty image")
        return image
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def capture_display(display: Display) -> Capture:
    """Capture a single display at its native pixel resolution."""
    image: Optional[np.ndarray] = None
    if Quartz is not None:
        try:
            cg_image = Quartz.CGDisplayCreateImage(display.display_id)
            if cg_image is not None:
                image = _bgr_from_cgimage(cg_image)
        except Exception as exc:  # pragma: no cover - depends on OS state
            # Fall through to the CLI fallback; keep the reason for the error.
            fallback_reason = str(exc)
        else:
            fallback_reason = ""
    else:
        fallback_reason = "Quartz unavailable"

    if image is None or image.size == 0:
        try:
            image = _capture_with_screencapture(display)
        except Exception as exc:
            raise ScreenError(
                "could not capture the screen "
                f"({fallback_reason or 'unknown Quartz failure'}; fallback: {exc})"
            ) from exc

    if image.ndim != 3 or image.shape[2] != 3:
        raise ScreenError(f"unexpected screenshot shape {image.shape}")
    return Capture(display=display, image=image)


def capture_all() -> List[Capture]:
    return [capture_display(display) for display in list_displays()]


def screenshot_sanity(capture: Capture) -> Tuple[bool, str]:
    """Best-effort check that screen recording permission really works.

    A denied capture is usually a pure black (or fully transparent) image.
    A dark wallpaper is still not perfectly uniform, so require a tiny
    amount of variation before calling the capture broken.
    """
    gray = capture.gray
    low = int(gray.min())
    high = int(gray.max())
    if high - low < 2:
        return (
            False,
            "截图几乎是纯色，可能没有开启“屏幕录制”权限，或屏幕处于休眠状态",
        )
    return True, f"{capture.image.shape[1]}x{capture.image.shape[0]} 像素"
