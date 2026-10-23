"""Tests for window filtering / exclusion policy."""

from __future__ import annotations

import unittest

from retry_clicker.windows import WindowInfo, WindowPolicy, window_at


def window(
    owner: str,
    title: str = "",
    x: float = 0.0,
    y: float = 0.0,
    width: float = 1440.0,
    height: float = 900.0,
    number: int = 1,
) -> WindowInfo:
    return WindowInfo(
        window_id=number,
        owner=owner,
        title=title,
        x=x,
        y=y,
        width=width,
        height=height,
    )


class WindowPolicyTests(unittest.TestCase):
    def test_frontmost_window_wins(self) -> None:
        windows = [
            window("DSH Desktop", number=1),
            window("Google Chrome", "Codex", number=2),
        ]
        self.assertEqual(window_at(windows, 100, 100).owner, "DSH Desktop")

    def test_excluded_window_is_rejected(self) -> None:
        policy = WindowPolicy(exclude_pattern=r"^DSH Desktop$")
        allowed, label = policy.evaluate([window("DSH Desktop")], 100, 100)
        self.assertFalse(allowed)
        self.assertIn("DSH Desktop", label)

    def test_chrome_codex_is_allowed_by_default(self) -> None:
        policy = WindowPolicy(exclude_pattern=r"^DSH Desktop$")
        allowed, label = policy.evaluate(
            [window("Google Chrome", "Codex")], 100, 100
        )
        self.assertTrue(allowed)
        self.assertIn("Codex", label)

    def test_include_pattern_restricts_targets(self) -> None:
        policy = WindowPolicy(include_pattern=r"Codex")
        allowed, _ = policy.evaluate([window("Google Chrome", "Codex")], 1, 1)
        self.assertTrue(allowed)
        allowed, _ = policy.evaluate([window("Google Chrome", "Gmail")], 1, 1)
        self.assertFalse(allowed)

    def test_include_and_exclude_precedence(self) -> None:
        policy = WindowPolicy(
            include_pattern=r"Codex", exclude_pattern=r"^DSH Desktop$"
        )
        allowed, _ = policy.evaluate([window("DSH Desktop", "Codex")], 1, 1)
        self.assertFalse(allowed)

    def test_empty_point_is_allowed(self) -> None:
        policy = WindowPolicy(exclude_pattern=r"^Preview$")
        allowed, _ = policy.evaluate([], 500, 500)
        self.assertTrue(allowed)

    def test_disabled_policy_allows_everything(self) -> None:
        policy = WindowPolicy(exclude_pattern=r"^DSH Desktop$", enabled=False)
        allowed, _ = policy.evaluate([window("DSH Desktop")], 1, 1)
        self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main()
