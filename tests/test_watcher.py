"""Tests for the click / debounce state machine."""

from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from retry_clicker.config import WatcherConfig
from retry_clicker.watcher import Watcher
from tests.helpers import (
    FakeClock,
    RecordingClicker,
    SequenceScanner,
    make_finding,
)


logging.getLogger("retry_clicker.watcher").setLevel(logging.CRITICAL)


class WatcherTests(unittest.TestCase):
    def make_watcher(self, sequence, config, clock=None):
        clock = clock or FakeClock()
        clicker = RecordingClicker(clock)
        scanner = SequenceScanner(sequence)
        watcher = Watcher(
            scanner,
            clicker,
            config,
            clock=clock,
            sleep=lambda _seconds: None,
        )
        return watcher, clicker, clock, scanner

    def step_at(self, watcher, clock, seconds):
        clock.advance(seconds)
        return watcher.step()

    def test_clicks_once_then_waits_for_disappearance(self) -> None:
        finding = make_finding()
        watcher, clicker, clock, _ = self.make_watcher(
            [finding, finding, finding, finding, None, finding],
            WatcherConfig(
                failsafe=False,
                click_cooldown=1.5,
                reclick_delay=4.0,
                max_attempts=2,
                rate_limit=0,
            ),
        )
        watcher.step()  # t=0 -> click 1
        self.step_at(watcher, clock, 1.0)  # t=1 -> too soon
        self.step_at(watcher, clock, 1.0)  # t=2 -> too soon
        self.step_at(watcher, clock, 3.0)  # t=5 -> reclick (attempt 2)
        self.step_at(watcher, clock, 1.0)  # t=6 -> disappeared
        self.step_at(watcher, clock, 1.0)  # t=7 -> new appearance -> click 3

        self.assertEqual([click[2] for click in clicker.clicks], [0.0, 5.0, 7.0])
        self.assertEqual(watcher.stats.clicks, 3)
        self.assertEqual(watcher.stats.detections, 2)

    def test_does_not_spam_while_button_stays_visible(self) -> None:
        finding = make_finding()
        watcher, clicker, clock, _ = self.make_watcher(
            [finding],
            WatcherConfig(
                failsafe=False,
                click_cooldown=0.0,
                reclick_delay=0.0,
                max_attempts=1,
                rate_limit=0,
            ),
        )
        watcher.step()
        for _ in range(6):
            self.step_at(watcher, clock, 1.0)
        self.assertEqual(len(clicker.clicks), 1)

    def test_rate_limit(self) -> None:
        finding = make_finding()
        watcher, clicker, clock, _ = self.make_watcher(
            [finding, None, finding, None, finding, None, finding],
            WatcherConfig(
                failsafe=False,
                click_cooldown=0.0,
                reclick_delay=0.0,
                max_attempts=5,
                rate_limit=2,
                rate_window=60.0,
            ),
        )
        for _ in range(7):
            self.step_at(watcher, clock, 1.0)
        self.assertEqual(len(clicker.clicks), 2)
        self.assertGreaterEqual(watcher.stats.skipped, 2)

    def test_once_stops_after_first_click(self) -> None:
        finding = make_finding()
        watcher, clicker, _, _ = self.make_watcher(
            [finding],
            WatcherConfig(failsafe=False, once=True, rate_limit=0),
        )
        self.assertFalse(watcher.step())
        self.assertEqual(len(clicker.clicks), 1)

    def test_max_clicks_stops(self) -> None:
        finding = make_finding()
        watcher, clicker, clock, _ = self.make_watcher(
            [finding, None, finding, None, finding],
            WatcherConfig(
                failsafe=False,
                max_clicks=2,
                click_cooldown=0.0,
                rate_limit=0,
            ),
        )
        self.assertTrue(watcher.step())  # t=0 -> click 1
        self.step_at(watcher, clock, 1.0)  # t=1 -> absent
        self.assertFalse(watcher.step())  # t=2 -> click 2, limit reached
        self.assertEqual(len(clicker.clicks), 2)
        self.assertIn("点击上限", watcher.stats.stopped_reason)

    def test_duration_limit(self) -> None:
        watcher, _, clock, _ = self.make_watcher(
            [None],
            WatcherConfig(failsafe=False, duration=5.0),
        )
        self.assertTrue(watcher.step())  # t=0
        self.assertFalse(self.step_at(watcher, clock, 5.0))
        self.assertIn("运行时长", watcher.stats.stopped_reason)

    def test_stop_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stop"
            watcher, _, _, _ = self.make_watcher(
                [None],
                WatcherConfig(failsafe=False, stop_file=str(path)),
            )
            self.assertTrue(watcher.step())
            path.write_text("stop")
            self.assertFalse(watcher.step())
            self.assertFalse(path.exists())
            self.assertIn("停止文件", watcher.stats.stopped_reason)

    def test_click_error_is_counted_and_retried_later(self) -> None:
        class FailingClicker:
            def __init__(self):
                self.calls = 0

            def click(self, x, y):
                self.calls += 1
                raise RuntimeError("boom")

        finding = make_finding()
        clock = FakeClock()
        clicker = FailingClicker()
        watcher = Watcher(
            SequenceScanner([finding]),
            clicker,
            WatcherConfig(
                failsafe=False,
                click_cooldown=0.0,
                reclick_delay=4.0,
                max_attempts=2,
                rate_limit=0,
            ),
            clock=clock,
            sleep=lambda _seconds: None,
        )
        watcher.step()
        self.assertEqual(clicker.calls, 1)
        self.assertEqual(watcher.stats.errors, 1)
        self.step_at(watcher, clock, 5.0)
        self.assertEqual(clicker.calls, 2)
        self.assertEqual(watcher.stats.clicks, 0)


if __name__ == "__main__":
    unittest.main()
