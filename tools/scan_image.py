#!/usr/bin/env python3
"""Run the matcher against a saved screenshot (no clicking).

Useful for checking a template or tuning thresholds without touching the
live screen::

    .venv/bin/python tools/scan_image.py screenshot.png --image-dpi 2

The output uses image pixel coordinates.  ``--debug`` writes an annotated PNG.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from retry_clicker.config import MatcherConfig  # noqa: E402
from retry_clicker.matcher import Matcher  # noqa: E402
from retry_clicker.screen import Capture, Display  # noqa: E402
from retry_clicker.templates import load_templates  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="screenshot to search")
    parser.add_argument("--template", action="append", default=[], help="template path (repeatable)")
    parser.add_argument(
        "--template-dir",
        default=str(ROOT / "assets" / "templates"),
        help="default template directory",
    )
    parser.add_argument("--image-dpi", type=float, default=2.0, help="screenshot pixel density")
    parser.add_argument("--template-dpi", type=float, default=2.0, help="template pixel density")
    parser.add_argument("--threshold", type=float, default=0.88)
    parser.add_argument("--modes", default="color,dark", help="color,dark,edge")
    parser.add_argument("--scale-tolerance", type=float, default=0.18)
    parser.add_argument("--scale-steps", type=int, default=9)
    parser.add_argument("--debug", default="", help="write an annotated PNG here")
    args = parser.parse_args()

    image = cv2.imread(args.image, cv2.IMREAD_COLOR)
    if image is None:
        print(f"无法读取图片: {args.image}")
        return 2
    height, width = image.shape[:2]
    display = Display(1, 0.0, 0.0, width / args.image_dpi, height / args.image_dpi)
    capture = Capture(display, image)

    paths = [Path(item) for item in args.template]
    if not paths:
        from retry_clicker.templates import discover_templates

        paths = discover_templates(Path(args.template_dir))
    templates = load_templates(paths)
    print(f"模板: {', '.join(t.name for t in templates)}")
    print(f"图片: {width}x{height}px @{args.image_dpi:g}x")

    config = MatcherConfig(
        threshold=args.threshold,
        template_dpi=args.template_dpi,
        modes=tuple(item.strip() for item in args.modes.split(",") if item.strip()),
        scale_tolerance=args.scale_tolerance,
        scale_steps=args.scale_steps,
    )
    matcher = Matcher(templates, config)
    hits = matcher.find(capture)
    if not hits:
        print("未找到匹配。")
        return 1
    for hit in hits:
        x, y, w, h = hit.rect_px
        print(
            f"命中: {hit.template_name}/{hit.mode} score={hit.score:.4f} "
            f"scale={hit.scale:.2f} rect=({x},{y},{w},{h})"
        )
    if args.debug:
        annotated = image.copy()
        for hit in hits:
            x, y, w, h = hit.rect_px
            cv2.rectangle(annotated, (x, y), (x + w, y + h), (60, 200, 60), 3)
            cv2.putText(
                annotated,
                f"{hit.score:.3f}",
                (x, max(20, y - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (60, 200, 60),
                2,
                cv2.LINE_AA,
            )
        ok, encoded = cv2.imencode(".png", annotated)
        if ok:
            encoded.tofile(args.debug)
            print(f"标注图: {args.debug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
