"""Loading button template images."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

import cv2
import numpy as np


class TemplateError(RuntimeError):
    pass


SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


@dataclass(frozen=True)
class Template:
    name: str
    path: Path
    gray: np.ndarray

    @property
    def width(self) -> int:
        return int(self.gray.shape[1])

    @property
    def height(self) -> int:
        return int(self.gray.shape[0])

    def describe(self) -> str:
        return f"{self.name} ({self.width}x{self.height}px, {self.path})"


def discover_templates(directory: Path) -> List[Path]:
    """Return supported image files in a directory, sorted by name."""
    if not directory.is_dir():
        return []
    paths = [
        item
        for item in directory.iterdir()
        if item.is_file()
        and not item.name.startswith(".")
        and item.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    return sorted(paths, key=lambda item: item.name.lower())


def _read_image(path: Path) -> np.ndarray:
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError as exc:
        raise TemplateError(f"cannot read template {path}: {exc}") from exc
    if data.size == 0:
        raise TemplateError(f"template is empty: {path}")
    image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise TemplateError(f"unsupported or corrupt image: {path}")
    return image


def load_template(path: Path) -> Template:
    image = _read_image(path)

    # Flatten transparency onto a white background: Codex's button sits on a
    # white/very light card in the reference screenshot.
    if image.ndim == 3 and image.shape[2] == 4:
        alpha = image[:, :, 3:4].astype(np.float32) / 255.0
        bgr = image[:, :, :3].astype(np.float32)
        flattened = bgr * alpha + 255.0 * (1.0 - alpha)
        image = flattened.astype(np.uint8)
    elif image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.ndim == 3 and image.shape[2] == 3:
        pass
    else:
        raise TemplateError(f"unsupported channel count in {path}: {image.shape}")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    if width < 16 or height < 10:
        raise TemplateError(
            f"template {path.name} is too small ({width}x{height}); "
            "crop a little context around the button"
        )
    if int(gray.max()) - int(gray.min()) < 10:
        raise TemplateError(
            f"template {path.name} is almost uniform; it has no visible button"
        )
    return Template(name=path.stem, path=path, gray=np.ascontiguousarray(gray))


def load_templates(paths: Iterable[Path]) -> List[Template]:
    templates: List[Template] = []
    seen = set()
    errors: List[str] = []
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            templates.append(load_template(resolved))
        except TemplateError as exc:
            errors.append(str(exc))
    if not templates:
        detail = ("; ".join(errors)) if errors else "no image files found"
        raise TemplateError(f"no usable templates ({detail})")
    return templates


def resolve_template_paths(
    explicit: Sequence[str], directory: Path
) -> List[Path]:
    """Combine explicitly given templates with the default directory."""
    paths: List[Path] = []
    for item in explicit:
        paths.append(Path(item))
    if not paths:
        paths.extend(discover_templates(directory))
    return paths
