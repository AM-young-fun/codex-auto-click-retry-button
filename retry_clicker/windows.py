"""On-screen window lookup and the include/exclude click policy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Pattern, Sequence, Tuple

try:  # pragma: no cover - exercised implicitly on macOS
    import Quartz
except Exception:  # pragma: no cover
    Quartz = None  # type: ignore[assignment]


@dataclass(frozen=True)
class WindowInfo:
    window_id: int
    owner: str
    title: str
    x: float
    y: float
    width: float
    height: float
    layer: int = 0

    def contains(self, x: float, y: float) -> bool:
        return (
            self.x <= x < self.x + self.width
            and self.y <= y < self.y + self.height
        )

    @property
    def label(self) -> str:
        if self.title and self.title != self.owner:
            return f"{self.owner} — {self.title}"
        return self.owner or "unknown"


def list_windows() -> List[WindowInfo]:
    """Return normal application windows, frontmost first.

    Requires no special permission for bounds/owner names.  Window *titles*
    are only visible when the process has Screen Recording permission, which
    is why matching is primarily done on the owner name.
    """
    if Quartz is None:
        return []
    options = (
        Quartz.kCGWindowListOptionOnScreenOnly
        | Quartz.kCGWindowListExcludeDesktopElements
    )
    raw = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []
    windows: List[WindowInfo] = []
    for entry in raw:
        try:
            layer = int(entry.get("kCGWindowLayer", 0))
            if layer != 0:
                continue
            alpha = float(entry.get("kCGWindowAlpha", 1.0))
            if alpha <= 0.01:
                continue
            bounds = entry.get("kCGWindowBounds") or {}
            width = float(bounds.get("Width", 0.0))
            height = float(bounds.get("Height", 0.0))
            if width < 20 or height < 20:
                continue
            windows.append(
                WindowInfo(
                    window_id=int(entry.get("kCGWindowNumber", 0)),
                    owner=str(entry.get("kCGWindowOwnerName") or ""),
                    title=str(entry.get("kCGWindowName") or ""),
                    x=float(bounds.get("X", 0.0)),
                    y=float(bounds.get("Y", 0.0)),
                    width=width,
                    height=height,
                    layer=layer,
                )
            )
        except (TypeError, ValueError):
            continue
    return windows


def window_at(
    windows: Sequence[WindowInfo], x: float, y: float
) -> Optional[WindowInfo]:
    """Return the frontmost window containing a global point."""
    for window in windows:  # list is front-to-back
        if window.contains(x, y):
            return window
    return None


class WindowPolicy:
    """Decides whether a point may be clicked based on its window."""

    def __init__(
        self,
        exclude_pattern: str = "",
        include_pattern: str = "",
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self.exclude: Optional[Pattern[str]] = (
            re.compile(exclude_pattern, re.IGNORECASE) if exclude_pattern else None
        )
        self.include: Optional[Pattern[str]] = (
            re.compile(include_pattern, re.IGNORECASE) if include_pattern else None
        )

    def evaluate(
        self, windows: Sequence[WindowInfo], x: float, y: float
    ) -> Tuple[bool, str]:
        """Return ``(allowed, description)`` for a global point."""
        if not self.enabled:
            return True, "window filter disabled"
        window = window_at(windows, x, y)
        if window is None:
            # Desktop / wallpaper: not one of the screenshot-viewing apps.
            return True, "桌面（未匹配到窗口）"
        label = window.label
        # Exclusion patterns are usually app names.  Check both the owner and
        # the full label so that titled windows can be filtered too.
        if self.exclude and (
            self.exclude.search(window.owner) or self.exclude.search(window.title)
        ):
            return False, f"已排除窗口: {label}"
        if self.include and not self.include.search(label):
            return False, f"不在允许的窗口列表中: {label}"
        return True, label

    def describe(self) -> str:
        if not self.enabled:
            return "关闭（搜索整个屏幕）"
        parts = []
        if self.include:
            parts.append(f"仅允许: /{self.include.pattern}/i")
        if self.exclude:
            parts.append(f"排除: /{self.exclude.pattern}/i")
        return "; ".join(parts) if parts else "允许所有窗口"
