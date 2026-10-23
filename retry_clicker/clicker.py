"""Synthetic mouse clicks (and cursor helpers) for macOS."""

from __future__ import annotations

import logging
import time
from typing import Optional, Protocol, Tuple

try:  # pragma: no cover - exercised implicitly on macOS
    import Quartz
except Exception:  # pragma: no cover
    Quartz = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class ClickError(RuntimeError):
    pass


class Clicker(Protocol):
    def click(self, x: float, y: float) -> None:
        ...


def cursor_position() -> Optional[Tuple[float, float]]:
    """Current cursor position in global points, or None if unavailable."""
    if Quartz is None:
        return None
    try:
        event = Quartz.CGEventCreate(None)
        if event is None:
            return None
        point = Quartz.CGEventGetLocation(event)
        return (float(point.x), float(point.y))
    except Exception:
        return None


class QuartzClicker:
    """Posts real mouse events and optionally puts the cursor back."""

    def __init__(
        self,
        restore_cursor: bool = True,
        activate_app: bool = True,
        settle_time: float = 0.10,
        press_time: float = 0.04,
    ) -> None:
        self.restore_cursor = restore_cursor
        self.activate_app = activate_app
        self.settle_time = settle_time
        self.press_time = press_time

    def click(self, x: float, y: float) -> None:
        if Quartz is None:
            raise ClickError(
                "PyObjC/Quartz is not available; cannot send mouse events."
            )
        original = cursor_position()
        if self.activate_app:
            self._activate_window_at(x, y)
        point = Quartz.CGPointMake(float(x), float(y))
        source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)

        # Warping is reliable on every macOS version; the move event afterwards
        # makes hover-sensitive UI react before the press is delivered.
        Quartz.CGWarpMouseCursorPosition(point)
        time.sleep(0.03)
        self._post(source, Quartz.kCGEventMouseMoved, point)
        time.sleep(self.settle_time)
        self._post(source, Quartz.kCGEventLeftMouseDown, point)
        time.sleep(self.press_time)
        self._post(source, Quartz.kCGEventLeftMouseUp, point)
        logger.debug("posted click at (%.1f, %.1f)", x, y)

        if self.restore_cursor and original is not None:
            time.sleep(0.12)
            Quartz.CGWarpMouseCursorPosition(
                Quartz.CGPointMake(float(original[0]), float(original[1]))
            )

    def _activate_window_at(self, x: float, y: float) -> None:
        """Bring the target window's app forward before clicking.

        Synthetic first clicks on an inactive window can be swallowed by the
        window server.  Activating the app first makes the click reliable;
        this is a no-op when the app is already frontmost.
        """
        try:
            from AppKit import NSWorkspace

            from .windows import list_windows, window_at

            window = window_at(list_windows(), x, y)
            if window is None:
                return
            for app in NSWorkspace.sharedWorkspace().runningApplications():
                if app.activationPolicy() != 0:  # regular apps only
                    continue
                if app.localizedName() != window.owner:
                    continue
                if not app.isActive():
                    # NSApplicationActivateAllWindows | IgnoringOtherApps
                    app.activateWithOptions_(3)
                    time.sleep(0.18)
                return
        except Exception as exc:  # optional best-effort enhancement
            logger.debug("could not activate app before click: %s", exc)

    @staticmethod
    def _post(source, event_type: int, point) -> None:
        event = Quartz.CGEventCreateMouseEvent(
            source, event_type, point, Quartz.kCGMouseButtonLeft
        )
        if event is None:
            raise ClickError("CGEventCreateMouseEvent returned NULL")
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


class DryRunClicker:
    """Logs clicks instead of sending them."""

    def __init__(self) -> None:
        self.clicks: list[Tuple[float, float]] = []

    def click(self, x: float, y: float) -> None:
        self.clicks.append((x, y))
        logger.info("[dry-run] 本应点击 (%.1f, %.1f)", x, y)
