"""Tests for template loading."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from retry_clicker.templates import (
    TemplateError,
    discover_templates,
    load_template,
    resolve_template_paths,
)
from tests.helpers import TEMPLATE_PATH


class TemplateTests(unittest.TestCase):
    def test_bundled_template_loads(self) -> None:
        template = load_template(TEMPLATE_PATH)
        self.assertEqual(template.name, "retry_button")
        self.assertGreaterEqual(template.width, 100)
        self.assertGreaterEqual(template.height, 50)
        self.assertGreater(int(template.gray.max()) - int(template.gray.min()), 10)

    def test_transparent_png_is_flattened_onto_white(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "alpha.png"
            image = np.zeros((40, 60, 4), dtype=np.uint8)
            image[:, :, 3] = 0  # fully transparent
            cv2.imwrite(str(path), image)
            with self.assertRaises(TemplateError):
                load_template(path)  # becomes uniform white -> rejected

    def test_uniform_image_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blank.png"
            cv2.imwrite(str(path), np.full((50, 50, 3), 255, dtype=np.uint8))
            with self.assertRaises(TemplateError):
                load_template(path)

    def test_discover_templates_ignores_dotfiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cv2.imwrite(str(root / "a.png"), np.zeros((20, 20, 3), np.uint8))
            cv2.imwrite(str(root / ".hidden.png"), np.zeros((20, 20, 3), np.uint8))
            (root / "notes.txt").write_text("x")
            found = discover_templates(root)
            self.assertEqual([item.name for item in found], ["a.png"])

    def test_resolve_template_paths_falls_back_to_directory(self) -> None:
        paths = resolve_template_paths([], TEMPLATE_PATH.parent)
        self.assertIn(TEMPLATE_PATH, [item.resolve() for item in paths])


if __name__ == "__main__":
    unittest.main()
