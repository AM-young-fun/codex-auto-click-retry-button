#!/usr/bin/env python3
"""Create a new Retry-button template from a screenshot.

Examples
--------
Interactive crop of the current screen::

    .venv/bin/python tools/make_template.py

Crop a previously saved screenshot (pixel coordinates)::

    .venv/bin/python tools/make_template.py shot.png \
        --box 39,50,101,48 --margin 10 --out assets/templates/retry_button.png

The button is the *pill*.  A margin of 8-12px around it helps the matcher
distinguish the button from surrounding text.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from retry_clicker.screen import capture_display, list_displays  # noqa: E402
from retry_clicker.templates import TemplateError, load_template  # noqa: E402


def parse_box(value: str) -> tuple:
    try:
        parts = [int(item.strip()) for item in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("box must be x,y,w,h") from exc
    if len(parts) != 4 or min(parts) < 0 or parts[2] <= 0 or parts[3] <= 0:
        raise argparse.ArgumentTypeError("box must be x,y,w,h with positive w/h")
    return tuple(parts)


def interactive_crop(image):
    height, width = image.shape[:2]
    scale = min(1.0, 1400.0 / width, 800.0 / height)
    preview = image
    if scale < 1.0:
        preview = cv2.resize(
            image,
            (int(width * scale), int(height * scale)),
            interpolation=cv2.INTER_AREA,
        )
    window = "Select the Retry button, then press ENTER (c = cancel)"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, preview.shape[1], preview.shape[0])
    x, y, w, h = cv2.selectROI(window, preview, showCrosshair=False, fromCenter=False)
    cv2.destroyWindow(window)
    if w <= 1 or h <= 1:
        raise SystemExit("cancelled")
    return (
        int(round(x / scale)),
        int(round(y / scale)),
        int(round(w / scale)),
        int(round(h / scale)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("screenshot", nargs="?", help="source image; omit to capture the screen")
    parser.add_argument("--box", type=parse_box, help="crop box in pixels: x,y,w,h")
    parser.add_argument("--margin", type=int, default=10, help="context margin in pixels")
    parser.add_argument(
        "--out",
        default=str(ROOT / "assets" / "templates" / "retry_button.png"),
        help="output template path",
    )
    parser.add_argument(
        "--preview",
        default="",
        help="optional path for an enlarged preview image",
    )
    args = parser.parse_args()

    if args.screenshot:
        image = cv2.imread(args.screenshot, cv2.IMREAD_COLOR)
        if image is None:
            print(f"无法读取图片: {args.screenshot}")
            return 2
    else:
        capture = capture_display(list_displays()[0])
        image = capture.image

    if args.box:
        x, y, w, h = args.box
    else:
        x, y, w, h = interactive_crop(image)

    margin = max(0, args.margin)
    left = max(0, x - margin)
    top = max(0, y - margin)
    right = min(image.shape[1], x + w + margin)
    bottom = min(image.shape[0], y + h + margin)
    crop = image[top:bottom, left:right]
    if crop.size == 0:
        print("裁剪区域为空")
        return 2

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(out.suffix or ".png", crop)
    if not ok:
        print(f"无法编码图片: {out}")
        return 2
    encoded.tofile(str(out))
    print(f"已保存模板: {out} ({crop.shape[1]}x{crop.shape[0]}px)")
    try:
        template = load_template(out)
        print(f"校验通过: {template.width}x{template.height}px, 对比度正常")
    except TemplateError as exc:
        print(f"警告: {exc}")
        return 1

    if args.preview:
        preview_path = Path(args.preview).expanduser()
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        enlarged = cv2.resize(
            crop,
            (crop.shape[1] * 4, crop.shape[0] * 4),
            interpolation=cv2.INTER_NEAREST,
        )
        cv2.imwrite(str(preview_path), enlarged)
        print(f"预览图: {preview_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
