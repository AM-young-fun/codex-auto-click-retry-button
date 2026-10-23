"""Console + rotating file logging."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


def setup_logging(
    log_dir: Optional[Path] = None,
    verbose: bool = False,
    quiet: bool = False,
) -> Optional[Path]:
    root = logging.getLogger("retry_clicker")
    root.setLevel(logging.DEBUG)
    root.propagate = False
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    level = logging.DEBUG if verbose else (logging.WARNING if quiet else logging.INFO)

    console = logging.StreamHandler(stream=sys.stdout)
    console.setLevel(level)
    console.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-5s %(message)s", "%H:%M:%S")
    )
    root.addHandler(console)

    log_path: Optional[Path] = None
    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "retry_clicker.log"
            file_handler = RotatingFileHandler(
                str(log_path), maxBytes=2 * 1024 * 1024, backupCount=3, delay=True, encoding="utf-8"
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)s [%(name)s:%(lineno)d] %(message)s"
                )
            )
            root.addHandler(file_handler)
        except OSError as exc:
            root.warning("无法写入日志文件 %s: %s", log_dir, exc)
            log_path = None

    return log_path
