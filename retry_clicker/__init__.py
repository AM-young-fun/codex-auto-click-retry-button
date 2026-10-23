"""Automatically find and click the Codex "Retry" button on macOS.

The package is split into small, testable pieces:

- :mod:`retry_clicker.screen`      screen/display capture via Quartz
- :mod:`retry_clicker.windows`     window lookup + include/exclude policy
- :mod:`retry_clicker.templates`   template image loading
- :mod:`retry_clicker.matcher`     multi-scale template matching
- :mod:`retry_clicker.clicker`     synthetic mouse clicks
- :mod:`retry_clicker.watcher`     the polling / debounce state machine
- :mod:`retry_clicker.cli`         command line interface
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["__version__"]
