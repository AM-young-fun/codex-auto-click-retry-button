"""Tests for screen coordinate mapping and template matching."""

from __future__ import annotations

import unittest
from pathlib import Path

import cv2
import numpy as np

from retry_clicker.config import MatcherConfig
from retry_clicker.matcher import Matcher
from retry_clicker.screen import Capture, Display
from retry_clicker.templates import load_template
from tests.helpers import TEMPLATE_PATH, make_capture


class CoordinateTests(unittest.TestCase):
    def test_retina_pixel_to_global(self) -> None:
        display = Display(1, origin_x=1440.0, origin_y=100.0, width=1440.0, height=900.0)
        capture = Capture(display=display, image=np.zeros((1800, 2880, 3), np.uint8))
        self.assertEqual(capture.scale, 2.0)
        self.assertEqual(capture.center_to_global(200.0, 100.0), (1540.0, 150.0))

    def test_non_retina_pixel_to_global(self) -> None:
        display = Display(2, origin_x=-100.0, origin_y=0.0, width=1200.0, height=800.0)
        capture = Capture(display=display, image=np.zeros((800, 1200, 3), np.uint8))
        self.assertEqual(capture.scale, 1.0)
        self.assertEqual(capture.center_to_global(10.0, 20.0), (-90.0, 20.0))


class MatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.template = load_template(TEMPLATE_PATH)

    def matcher(self, **overrides) -> Matcher:
        config = MatcherConfig(**overrides)
        return Matcher([self.template], config)

    def test_detects_button_on_retina_screen(self) -> None:
        capture = make_capture(
            self.template,
            display_width=800,
            display_height=500,
            pixel_scale=2.0,
            template_scale=1.0,
            position=(500, 300),
        )
        hits = self.matcher().find(capture)
        self.assertEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual(hit.mode, "color")
        self.assertGreater(hit.score, 0.95)
        # Button center in display points: (500 + 60) / 2, (300 + 34) / 2
        self.assertAlmostEqual(hit.global_point[0], 280.5, delta=1.0)
        self.assertAlmostEqual(hit.global_point[1], 167.0, delta=1.0)

    def test_detects_half_size_button_on_non_retina_screen(self) -> None:
        capture = make_capture(
            self.template,
            display_width=1200,
            display_height=800,
            pixel_scale=1.0,
            template_scale=0.5,
            position=(400, 250),
        )
        hits = self.matcher().find(capture)
        self.assertEqual(len(hits), 1)
        self.assertGreater(hits[0].score, 0.92)
        self.assertAlmostEqual(hits[0].scale, 0.5, delta=0.06)
        self.assertAlmostEqual(hits[0].global_point[0], 430.0, delta=1.5)

    def test_detects_scaled_button_at_1_5x(self) -> None:
        capture = make_capture(
            self.template,
            display_width=1000,
            display_height=700,
            pixel_scale=1.5,
            template_scale=0.75,
            position=(600, 400),
        )
        hits = self.matcher().find(capture)
        self.assertEqual(len(hits), 1)
        self.assertAlmostEqual(hits[0].global_point[0], 430.0, delta=1.5)

    def test_dark_theme_fallback(self) -> None:
        capture = make_capture(
            self.template,
            display_width=800,
            display_height=500,
            pixel_scale=2.0,
            template_scale=1.0,
            position=(500, 300),
            dark=True,
        )
        hits = self.matcher().find(capture)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].mode, "dark")
        self.assertGreater(hits[0].score, 0.9)

    def test_blank_screen_has_no_hits(self) -> None:
        capture = Capture(
            display=Display(1, 0.0, 0.0, 800.0, 500.0),
            image=np.full((1000, 1600, 3), 255, dtype=np.uint8),
        )
        self.assertEqual(self.matcher().find(capture), [])

    def test_low_contrast_text_does_not_false_positive(self) -> None:
        image = np.full((1000, 1600, 3), 255, dtype=np.uint8)
        cv2.putText(
            image,
            "Retried model request",
            (300, 500),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (120, 120, 120),
            2,
            cv2.LINE_AA,
        )
        capture = Capture(Display(1, 0.0, 0.0, 800.0, 500.0), image)
        self.assertEqual(self.matcher().find(capture), [])

    def test_strict_threshold_can_reject_blurred_button(self) -> None:
        capture = make_capture(
            self.template,
            display_width=800,
            display_height=500,
            pixel_scale=2.0,
            template_scale=1.0,
            position=(500, 300),
        )
        blurred = cv2.GaussianBlur(capture.image, (0, 0), 2.0)
        capture_blurred = Capture(capture.display, blurred)
        lenient = self.matcher(threshold=0.75).find(capture_blurred)
        strict = self.matcher(threshold=0.99).find(capture_blurred)
        self.assertTrue(lenient)
        self.assertEqual(strict, [])


if __name__ == "__main__":
    unittest.main()
