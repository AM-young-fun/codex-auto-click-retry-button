#!/usr/bin/env python3
"""Entry point for `python main.py` and `./run.sh`."""

from __future__ import annotations

import sys

from retry_clicker.cli import main

if __name__ == "__main__":
    sys.exit(main())
