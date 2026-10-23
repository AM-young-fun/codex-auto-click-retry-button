"""Configuration objects shared by the matcher, scanner and watcher."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

#: Match modes, in the order they are attempted.
VALID_MODES: Tuple[str, ...] = ("color", "dark", "edge")


@dataclass
class MatcherConfig:
    """How screenshots are searched for the button template."""

    #: Minimum score of the *native resolution* verification.
    threshold: float = 0.88
    #: Minimum score of the (cheaper) downscaled first pass.
    coarse_threshold: float = 0.68
    #: Physical pixels per point of the screen the template came from.
    #: macOS screenshots are normally 2x ("@2x"), so this defaults to 2.
    template_dpi: float = 2.0
    #: Long edge of the working image used for the coarse search.
    max_search_edge: int = 1024
    #: Relative search range around the expected template scale.
    scale_tolerance: float = 0.12
    #: Number of scale steps inside that range.
    scale_steps: int = 7
    #: Seconds between "deep" scans (wider scale range).
    deep_interval: float = 4.0
    #: Coarse score that triggers an immediate native verification and return.
    early_exit_score: float = 0.96
    #: Match modes to try, in order. "color" is the normal light theme,
    #: "dark" is a synthetic dark-theme variant and "edge" matches edges
    #: only (theme independent, but noisier).
    modes: Tuple[str, ...] = ("color", "dark")
    #: Maximum number of coarse candidates verified at native resolution.
    max_candidates: int = 6
    #: Verify threshold for the synthetic dark template (slightly lower).
    dark_threshold_delta: float = 0.02
    #: Thresholds used by the edge-only fallback.
    edge_coarse_threshold: float = 0.55
    edge_threshold: float = 0.65

    def __post_init__(self) -> None:
        unknown = [m for m in self.modes if m not in VALID_MODES]
        if unknown:
            raise ValueError(f"unknown match mode(s): {', '.join(unknown)}")
        if not self.modes:
            raise ValueError("at least one match mode is required")
        if not 0.0 < self.threshold <= 1.0:
            raise ValueError("threshold must be in (0, 1]")
        if not 0.0 < self.coarse_threshold <= 1.0:
            raise ValueError("coarse threshold must be in (0, 1]")
        if self.template_dpi <= 0:
            raise ValueError("template_dpi must be positive")
        if self.max_search_edge < 320:
            raise ValueError("max_search_edge must be at least 320")
        if not 0.0 <= self.scale_tolerance < 0.9:
            raise ValueError("scale_tolerance must be in [0, 0.9)")
        if self.scale_steps < 1:
            raise ValueError("scale_steps must be positive")
        if self.deep_interval <= 0:
            raise ValueError("deep_interval must be positive")
        if not 0.0 < self.early_exit_score <= 1.0:
            raise ValueError("early_exit_score must be in (0, 1]")


@dataclass
class WatcherConfig:
    """How often and how aggressively the watcher clicks."""

    poll_interval: float = 0.6
    #: Minimum quiet time after a click before any new click is allowed.
    click_cooldown: float = 1.5
    #: Delay before clicking again while the same button is still visible.
    reclick_delay: float = 4.0
    #: Number of clicks allowed for one continuous button appearance.
    max_attempts: int = 2
    #: After this long with the button still visible, stop clicking and warn.
    stuck_timeout: float = 180.0
    #: Hard limit of clicks inside ``rate_window`` seconds (0 disables).
    rate_limit: int = 12
    rate_window: float = 60.0
    #: Stop after N clicks (0 = unlimited).
    max_clicks: int = 0
    #: Stop after N seconds of runtime (0 = unlimited).
    duration: float = 0.0
    #: Stop after the first click.
    once: bool = False
    #: Emergency stop: moving the cursor into the top-left corner quits.
    failsafe: bool = True
    failsafe_grace: float = 2.0
    #: Stop when this file appears (empty string disables).
    stop_file: str = ""

    def __post_init__(self) -> None:
        if self.poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        if self.click_cooldown < 0 or self.reclick_delay < 0:
            raise ValueError("cooldowns must not be negative")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.rate_limit < 0:
            raise ValueError("rate_limit must not be negative")
        if self.max_clicks < 0 or self.duration < 0:
            raise ValueError("max_clicks and duration must not be negative")
        if self.stuck_timeout < 0:
            raise ValueError("stuck_timeout must not be negative")


@dataclass
class RuntimeConfig:
    """Everything the application needs at runtime."""

    matcher: MatcherConfig = field(default_factory=MatcherConfig)
    watcher: WatcherConfig = field(default_factory=WatcherConfig)
    template_paths: Tuple[str, ...] = ()
    #: Regex matched against "owner — title".
    include_owner: str = ""
    #: Regex of windows that must never be clicked.
    exclude_owner: str = ""
    use_window_filter: bool = True
    restore_cursor: bool = True
    activate_app: bool = True
    dry_run: bool = False
    debug_dir: str = ""
