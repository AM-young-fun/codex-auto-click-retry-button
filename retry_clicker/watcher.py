"""The polling / click / debounce state machine."""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Optional, Protocol

from .clicker import Clicker, cursor_position
from .config import WatcherConfig
from .scanner import ScanFinding

logger = logging.getLogger(__name__)


class ScanSource(Protocol):
    def scan(self) -> Optional[ScanFinding]:
        ...


@dataclass
class WatcherStats:
    scans: int = 0
    detections: int = 0
    clicks: int = 0
    skipped: int = 0
    errors: int = 0
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    stopped_reason: str = ""

    @property
    def duration(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.ended_at if self.ended_at is not None else time.monotonic()
        return max(0.0, end - self.started_at)

    def summary(self) -> str:
        return (
            f"运行 {self.duration:.1f}s，扫描 {self.scans} 次，"
            f"检测 {self.detections} 次，点击 {self.clicks} 次，"
            f"跳过 {self.skipped} 次，错误 {self.errors} 次"
            + (f"；停止原因: {self.stopped_reason}" if self.stopped_reason else "")
        )


class Watcher:
    """Watches the screen and clicks Retry once per fresh appearance.

    The state machine is deliberately conservative:

    * the first detection of an appearance triggers one click;
    * while the same button stays visible, at most ``max_attempts`` clicks are
      sent, spaced by ``reclick_delay``;
    * once the button disappears the appearance is over, so a later failure
      (button reappearing) is clicked again;
    * a global rate limit and a long-stuck warning prevent runaway clicking.
    """

    def __init__(
        self,
        scanner: ScanSource,
        clicker: Clicker,
        config: WatcherConfig,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        stop_event=None,
    ) -> None:
        self.scanner = scanner
        self.clicker = clicker
        self.config = config
        self._clock = clock
        self._sleep = sleep
        self._stop_event = stop_event

        self.stats = WatcherStats()
        self._started_at: Optional[float] = None
        self._click_times: Deque[float] = deque()
        self._present_since: Optional[float] = None
        self._attempts = 0
        self._stuck_logged = False
        self._last_rate_warning = -1e9
        self._last_click_attempt_at = -1e9

    # ------------------------------------------------------------------ API
    def run(self) -> WatcherStats:
        self._prepare()
        logger.info(
            "开始监控。按 Ctrl+C 停止；将鼠标移到屏幕左上角可紧急停止。"
        )
        while self.step():
            if self._stop_event is not None and self._stop_event.is_set():
                self.stats.stopped_reason = "收到停止信号"
                break
            self._sleep(self.config.poll_interval)
        self._finish("")
        return self.stats

    def step(self) -> bool:
        """Run one scan/decision cycle. Returns False when the watcher stops."""
        if self._started_at is None:
            self._prepare()
        now = self._clock()

        if self._stop_event is not None and self._stop_event.is_set():
            self._stop("收到停止信号")
            return False

        if self.config.duration and now - self._started_at >= self.config.duration:
            self._stop(f"已达到运行时长 {self.config.duration:g}s")
            return False

        if self._stop_file_requested():
            self._stop("检测到停止文件")
            return False

        if self._failsafe_triggered(now):
            self._stop("鼠标位于左上角（紧急停止）")
            return False

        finding = self.scanner.scan()
        self.stats.scans += 1
        now = self._clock()

        if finding is not None:
            self._handle_present(finding, now)
        else:
            self._handle_absent(now)

        if self.config.max_clicks and self.stats.clicks >= self.config.max_clicks:
            self._stop(f"已达到点击上限 {self.config.max_clicks}")
            return False
        if self.config.once and self.stats.clicks >= 1:
            self._stop("已点击一次（--once）")
            return False
        return True

    # ------------------------------------------------------------- lifecycle
    def stop(self, reason: str = "已停止") -> None:
        """Request a stop from outside the polling loop (e.g. Ctrl+C)."""
        self._stop(reason)

    def _prepare(self) -> None:
        self._started_at = self._clock()
        self.stats.started_at = self._started_at

    def _finish(self, reason: str) -> None:
        if self.stats.ended_at is None:
            self.stats.ended_at = self._clock()
        if reason:
            self.stats.stopped_reason = reason
        logger.info("监控结束：%s", self.stats.summary())

    def _stop(self, reason: str) -> None:
        self.stats.stopped_reason = reason
        logger.info("停止：%s", reason)
        if self.stats.ended_at is None:
            self.stats.ended_at = self._clock()

    # ---------------------------------------------------------- state machine
    def _handle_present(self, finding: ScanFinding, now: float) -> None:
        detection = finding.detection
        if self._present_since is None:
            self._present_since = now
            self._attempts = 0
            self._stuck_logged = False
            self.stats.detections += 1
            logger.info(
                "检测到 Retry：%s | 窗口：%s",
                detection.summary,
                finding.window_label,
            )

        if self._attempts == 0:
            if self._click_ready(now) and self._rate_limit_ok(now):
                self._click(finding, now, attempt=1)
            return

        if self._attempts >= self.config.max_attempts:
            stuck_for = now - (self._present_since or now)
            if stuck_for >= self.config.stuck_timeout and not self._stuck_logged:
                self._stuck_logged = True
                logger.warning(
                    "Retry 按钮已连续显示 %.0fs，且已点击 %d 次仍未消失。"
                    "为避免狂点，先暂停点击，等按钮消失或界面变化后自动恢复。"
                    "如果点击没有生效，请检查“辅助功能”权限，或先用 --dry-run 验证。",
                    stuck_for,
                    self._attempts,
                )
            return

        if (
            now - self._last_click_attempt_at >= self.config.reclick_delay
            and self._click_ready(now)
            and self._rate_limit_ok(now)
        ):
            logger.info(
                "Retry 仍然可见，重试点击（第 %d/%d 次）",
                self._attempts + 1,
                self.config.max_attempts,
            )
            self._click(finding, now, attempt=self._attempts + 1)

    def _handle_absent(self, now: float) -> None:
        if self._present_since is not None:
            logger.info(
                "按钮已消失（可见 %.1fs，点击 %d 次），继续监控。",
                now - self._present_since,
                self._attempts,
            )
        self._present_since = None
        self._attempts = 0
        self._stuck_logged = False

    # ------------------------------------------------------------------ click
    def _click_ready(self, now: float) -> bool:
        return now - self._last_click_attempt_at >= self.config.click_cooldown

    def _click(self, finding: ScanFinding, now: float, attempt: int) -> None:
        detection = finding.detection
        x, y = detection.global_point
        self._last_click_attempt_at = now
        self._attempts = attempt
        try:
            self.clicker.click(x, y)
        except Exception as exc:
            self.stats.errors += 1
            logger.error("点击失败：%s", exc)
            return
        self.stats.clicks += 1
        self._click_times.append(now)
        logger.info(
            "已点击 Retry #%d：模板=%s 模式=%s 分数=%.3f 位置=(%.0f, %.0f) 窗口=%s",
            self.stats.clicks,
            detection.template_name,
            detection.mode,
            detection.score,
            x,
            y,
            finding.window_label,
        )

    # ----------------------------------------------------------- rate limiting
    def _rate_limit_ok(self, now: float) -> bool:
        if not self.config.rate_limit:
            return True
        window_start = now - self.config.rate_window
        while self._click_times and self._click_times[0] < window_start:
            self._click_times.popleft()
        if len(self._click_times) < self.config.rate_limit:
            return True
        self.stats.skipped += 1
        if now - self._last_rate_warning >= 10.0:
            self._last_rate_warning = now
            logger.warning(
                "已达到速率限制（%d 次 / %.0fs），暂时不点击，稍后自动恢复。",
                self.config.rate_limit,
                self.config.rate_window,
            )
        return False

    # ---------------------------------------------------------------- safety
    def _failsafe_triggered(self, now: float) -> bool:
        if not self.config.failsafe:
            return False
        if self._started_at is not None and (
            now - self._started_at < self.config.failsafe_grace
        ):
            return False
        position = cursor_position()
        if position is None:
            return False
        return position[0] <= 2.0 and position[1] <= 2.0

    def _stop_file_requested(self) -> bool:
        path = self.config.stop_file
        if not path:
            return False
        if not os.path.exists(path):
            return False
        try:
            os.unlink(path)
        except OSError:
            pass
        return True
