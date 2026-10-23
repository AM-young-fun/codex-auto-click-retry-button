"""Tests for the screen scanner and debug overlays."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from retry_clicker.matcher import Detection
from retry_clicker.scanner import ScreenScanner
from retry_clicker.screen import Capture, Display
from retry_clicker.windows import WindowPolicy
from tests.helpers import make_capture, make_detection
from retry_clicker.templates import load_template
from tests.helpers import TEMPLATE_PATH


class FakeMatcher:
    def __init__(self, detections):
        self.detections = detections

    def find(self, capture):
        return [item for item in self.detections]


class ScannerTests(unittest.TestCase):
    def test_scan_returns_best_allowed_finding(self) -> None:
        template = load_template(TEMPLATE_PATH)
        capture = make_capture(template, position=(500, 300))
        high = make_detection(100, 100, 0.99)
        low = make_detection(200, 200, 0.95)
        scanner = ScreenScanner(FakeMatcher([low, high]), WindowPolicy(enabled=False))
        scanner.capture_all = lambda: [capture]  # type: ignore[assignment]
        finding = scanner.scan()
        self.assertIsNotNone(finding)
        assert finding is not None
        self.assertEqual(finding.detection.score, 0.99)
        self.assertTrue(finding.allowed)

    def test_scan_returns_none_when_all_hits_are_filtered(self) -> None:
        template = load_template(TEMPLATE_PATH)
        capture = make_capture(template, position=(500, 300))
        detection = make_detection(100, 100, 0.99)
        policy = WindowPolicy(exclude_pattern=".*")
        scanner = ScreenScanner(FakeMatcher([detection]), policy)
        scanner.capture_all = lambda: [capture]  # type: ignore[assignment]
        self.assertIsNone(scanner.scan())

    def test_save_debug_writes_annotated_png(self) -> None:
        template = load_template(TEMPLATE_PATH)
        capture = make_capture(template, position=(500, 300))
        detection = make_detection(100, 100, 0.99)
        scanner = ScreenScanner(FakeMatcher([detection]), WindowPolicy(enabled=False))
        scanner.capture_all = lambda: [capture]  # type: ignore[assignment]
        finding = scanner.scan()
        assert finding is not None
        with tempfile.TemporaryDirectory() as directory:
            paths = scanner.save_debug([finding], directory=Path(directory), prefix="t")
            self.assertEqual(len(paths), 1)
            self.assertTrue(paths[0].exists())
            image = cv2.imread(str(paths[0]))
            self.assertIsNotNone(image)
            self.assertEqual(image.shape, capture.image.shape)

    def test_scan_findings_keeps_excluded_hits_for_reporting(self) -> None:
        template = load_template(TEMPLATE_PATH)
        capture = make_capture(template, position=(500, 300))
        detection = make_detection(100, 100, 0.99)
        policy = WindowPolicy(exclude_pattern=".*")
        scanner = ScreenScanner(FakeMatcher([detection]), policy)
        scanner.capture_all = lambda: [capture]  # type: ignore[assignment]
        findings = scanner.scan_findings()
        self.assertEqual(len(findings), 1)
        self.assertFalse(findings[0].allowed)


if __name__ == "__main__":
    unittest.main()
