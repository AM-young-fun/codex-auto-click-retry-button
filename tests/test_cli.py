"""CLI parsing smoke tests (no screen access)."""

from __future__ import annotations

import contextlib
import io
import unittest

from retry_clicker.cli import _parse_modes, build_parser, main


class CliTests(unittest.TestCase):
    def test_modes_parser(self) -> None:
        self.assertEqual(_parse_modes("color,dark"), ("color", "dark"))
        self.assertEqual(_parse_modes(" edge "), ("edge",))
        with self.assertRaises(Exception):
            _parse_modes("color,bogus")

    def test_defaults(self) -> None:
        args = build_parser().parse_args([])
        self.assertEqual(args.threshold, 0.88)
        self.assertEqual(args.poll_interval, 0.6)
        self.assertTrue(args.window_filter)
        self.assertTrue(args.failsafe)
        self.assertTrue(args.restore_cursor)
        self.assertFalse(args.dry_run)
        self.assertFalse(args.scan)
        self.assertIn("DSH Desktop", args.exclude_owner)

    def test_list_templates_exits_zero(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(["--list-templates", "--log-dir", ""])
        self.assertEqual(code, 0)
        self.assertIn("retry_button", buffer.getvalue())

    def test_missing_template_returns_two(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            code = main(
                ["--template", "/definitely/not/here.png", "--scan", "--log-dir", ""]
            )
        self.assertEqual(code, 2)

    def test_invalid_threshold_returns_two(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            code = main(["--threshold", "2.0", "--scan", "--log-dir", ""])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
