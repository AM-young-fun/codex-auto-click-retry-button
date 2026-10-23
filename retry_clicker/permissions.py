"""Accessibility / Screen Recording permission helpers."""

from __future__ import annotations

import ctypes
import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

_APPLICATION_SERVICES = (
    "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
)


def accessibility_trusted() -> Optional[bool]:
    """Whether this process may post synthetic mouse events.

    Returns ``None`` if the check itself is unavailable (e.g. on Linux).
    """
    try:
        framework = ctypes.CDLL(_APPLICATION_SERVICES)
        framework.AXIsProcessTrusted.restype = ctypes.c_bool
        framework.AXIsProcessTrusted.argtypes = []
        return bool(framework.AXIsProcessTrusted())
    except Exception as exc:  # pragma: no cover - platform dependent
        logger.debug("AXIsProcessTrusted unavailable: %s", exc)
        return None


def open_privacy_settings(kind: str) -> bool:
    """Open the relevant System Settings pane."""
    panes = {
        "accessibility": (
            "x-apple.systempreferences:"
            "com.apple.preference.security?Privacy_Accessibility"
        ),
        "screen": (
            "x-apple.systempreferences:"
            "com.apple.preference.security?Privacy_ScreenCapture"
        ),
    }
    url = panes.get(kind)
    if not url:
        return False
    try:
        subprocess.Popen(["open", url])
        return True
    except OSError as exc:
        logger.debug("could not open settings: %s", exc)
        return False


def accessibility_help() -> str:
    return (
        "需要“辅助功能”权限才能模拟鼠标点击：\n"
        "  系统设置 → 隐私与安全性 → 辅助功能\n"
        "  勾选正在运行本程序的终端 App（Terminal / iTerm / Warp / VS Code 等），\n"
        "  授权后请完全退出并重新打开该终端，再重新运行本程序。\n"
        "  也可以运行 `./run.sh --open-permissions` 直接打开设置面板。"
    )


def screen_recording_help() -> str:
    return (
        "需要“屏幕录制”权限才能看到 Retry 按钮：\n"
        "  系统设置 → 隐私与安全性 → 屏幕录制\n"
        "  勾选正在运行本程序的终端 App，授权后重启该终端。\n"
        "  如果截图是全黑的，基本就是这个原因。"
    )
