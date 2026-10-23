"""Command line interface for the Codex Retry auto-clicker."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from . import __version__
from .clicker import DryRunClicker, QuartzClicker
from .config import MatcherConfig, RuntimeConfig, WatcherConfig
from .logging_setup import setup_logging
from .matcher import Matcher
from .permissions import (
    accessibility_help,
    accessibility_trusted,
    open_privacy_settings,
    screen_recording_help,
)
from .scanner import ScreenScanner
from .screen import (
    ScreenError,
    capture_display,
    list_displays,
    screenshot_sanity,
)
from .templates import TemplateError, load_templates, resolve_template_paths
from .watcher import Watcher
from .windows import WindowPolicy

logger = logging.getLogger("retry_clicker")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE_DIR = PROJECT_ROOT / "assets" / "templates"
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"

#: Applications that commonly display screenshots of the button.  The built-in
#: default prevents clicking a preview of the template itself (e.g. this chat).
DEFAULT_EXCLUDE = (
    r"^(?:DSH Desktop|Preview|Photos|QuickTime Player|Screenshot|"
    r"CleanShot(?: X)?|Xnip|Snipaste|Shottr|Image Viewer)$"
)


def _parse_modes(value: str) -> Tuple[str, ...]:
    modes = tuple(item.strip().lower() for item in value.split(",") if item.strip())
    if not modes:
        raise argparse.ArgumentTypeError("至少需要一个模式，例如 color,dark")
    invalid = [item for item in modes if item not in ("color", "dark", "edge")]
    if invalid:
        raise argparse.ArgumentTypeError(
            f"未知模式: {', '.join(invalid)}（可用: color, dark, edge）"
        )
    return modes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-retry",
        description=(
            "自动寻找并点击 Codex 的 Retry 按钮（基于屏幕模板匹配）。"
            "默认持续监控，按钮出现即点击，消失后继续等待下一次。"
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    templates = parser.add_argument_group("模板")
    templates.add_argument(
        "--template",
        action="append",
        default=[],
        metavar="PATH",
        help="额外的模板图片（可重复）；不指定时使用模板目录中的所有图片",
    )
    templates.add_argument(
        "--template-dir",
        default=str(DEFAULT_TEMPLATE_DIR),
        metavar="DIR",
        help="默认模板目录",
    )
    templates.add_argument(
        "--list-templates",
        action="store_true",
        help="列出会被使用的模板并退出",
    )

    matching = parser.add_argument_group("匹配")
    matching.add_argument(
        "--threshold",
        type=float,
        default=0.88,
        help="全分辨率验证的最低匹配分数（0-1，越高越严格）",
    )
    matching.add_argument(
        "--coarse-threshold",
        type=float,
        default=0.68,
        help="缩略图粗匹配的最低分数",
    )
    matching.add_argument(
        "--template-dpi",
        type=float,
        default=2.0,
        help="模板截图对应的像素密度；macOS @2x 截图为 2",
    )
    matching.add_argument(
        "--max-search-edge",
        type=int,
        default=1024,
        help="粗匹配工作图的长边像素（越小越快）",
    )
    matching.add_argument(
        "--scale-tolerance",
        type=float,
        default=0.12,
        help="在预期缩放比例附近的搜索范围（±比例）",
    )
    matching.add_argument(
        "--scale-steps",
        type=int,
        default=7,
        help="缩放搜索步数",
    )
    matching.add_argument(
        "--deep-interval",
        type=float,
        default=4.0,
        help="每隔多少秒做一次更宽范围的深度扫描",
    )
    matching.add_argument(
        "--modes",
        type=_parse_modes,
        default=("color", "dark"),
        metavar="LIST",
        help="尝试的匹配模式：color,dark,edge",
    )

    watcher = parser.add_argument_group("点击行为")
    watcher.add_argument("--poll-interval", type=float, default=0.6, help="扫描间隔（秒）")
    watcher.add_argument(
        "--click-cooldown", type=float, default=1.5, help="两次点击之间的最短间隔（秒）"
    )
    watcher.add_argument(
        "--reclick-delay",
        type=float,
        default=4.0,
        help="按钮仍可见时，重试点击的间隔（秒）",
    )
    watcher.add_argument(
        "--max-attempts",
        type=int,
        default=2,
        help="同一次按钮显示期间最多点击几次",
    )
    watcher.add_argument(
        "--stuck-timeout",
        type=float,
        default=180.0,
        help="按钮持续显示多久后停止狂点并告警（秒）",
    )
    watcher.add_argument(
        "--rate-limit",
        type=int,
        default=12,
        help="每 60 秒最多点击次数（0 表示不限制）",
    )
    watcher.add_argument(
        "--max-clicks", type=int, default=0, help="最多点击多少次后停止（0 表示不限制）"
    )
    watcher.add_argument(
        "--duration", type=float, default=0.0, help="运行多少秒后停止（0 表示不限制）"
    )
    watcher.add_argument(
        "--once", action="store_true", help="点击成功一次后退出"
    )
    watcher.add_argument(
        "--no-failsafe",
        dest="failsafe",
        action="store_false",
        help="禁用“鼠标移到左上角紧急停止”",
    )
    watcher.add_argument(
        "--stop-file",
        default="",
        metavar="PATH",
        help="监控期间若该文件出现则停止（文件会被删除）",
    )

    scope = parser.add_argument_group("窗口过滤")
    scope.add_argument(
        "--no-window-filter",
        dest="window_filter",
        action="store_false",
        help="不检查窗口，直接搜索整个屏幕（更容易误点）",
    )
    scope.add_argument(
        "--include-owner",
        default="",
        metavar="REGEX",
        help="只允许这些窗口（匹配“应用名 — 标题”）",
    )
    scope.add_argument(
        "--exclude-owner",
        default=DEFAULT_EXCLUDE,
        metavar="REGEX",
        help=(
            "永不点击这些窗口（匹配应用名或标题）。"
            "传空字符串可关闭默认排除（默认排除截图查看器，防止点中模板预览）"
        ),
    )

    run = parser.add_argument_group("运行")
    run.add_argument("--dry-run", action="store_true", help="只检测和记录，不真正点击")
    run.add_argument(
        "--no-cursor-restore",
        dest="restore_cursor",
        action="store_false",
        help="点击后不把鼠标移回原位置",
    )
    run.add_argument(
        "--no-activate-app",
        dest="activate_app",
        action="store_false",
        help="点击前不激活目标窗口所属的 App（默认会先激活，点击更可靠）",
    )
    run.add_argument(
        "--scan",
        action="store_true",
        help="扫描一次并输出结果（不点击、不循环）",
    )
    run.add_argument(
        "--debug",
        nargs="?",
        const="debug",
        default="",
        metavar="DIR",
        help="保存带标注的命中截图",
    )
    run.add_argument(
        "--log-dir",
        default=str(DEFAULT_LOG_DIR),
        metavar="DIR",
        help="日志目录；传空字符串关闭文件日志",
    )
    run.add_argument("--no-countdown", action="store_true", help="跳过启动倒计时")
    run.add_argument(
        "--check-permissions",
        action="store_true",
        help="检查辅助功能/屏幕录制权限并退出",
    )
    run.add_argument(
        "--open-permissions",
        action="store_true",
        help="打开系统设置的权限面板并退出",
    )
    run.add_argument(
        "--skip-permission-check",
        action="store_true",
        help="即使辅助功能权限检测失败也继续（不推荐）",
    )
    run.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    run.add_argument("-q", "--quiet", action="store_true", help="只输出警告和错误")
    return parser


# --------------------------------------------------------------------------- #
# startup helpers
# --------------------------------------------------------------------------- #
def _print_header(
    templates,
    displays,
    capture,
    policy: WindowPolicy,
    matcher_config: MatcherConfig,
    watcher_config: WatcherConfig,
    log_path: Optional[Path],
) -> None:
    print("=" * 68)
    print(f" Codex Retry 自动点击器  v{__version__}")
    print("-" * 68)
    print(" 模板:")
    for template in templates:
        print(f"   - {template.describe()}")
    scale = capture.scale
    print(f" 屏幕: {len(displays)} 块")
    for index, display in enumerate(displays):
        marker = " (主)" if index == 0 else ""
        suffix = f" @{scale:g}x" if index == 0 else "（缩放按截图自动计算）"
        print(
            f"   - Display {display.display_id}{marker}: "
            f"{display.width:.0f}x{display.height:.0f}pt{suffix}"
        )
    print(f" 窗口过滤: {policy.describe()}")
    print(
        " 匹配: "
        f"{', '.join(matcher_config.modes)} | 阈值 {matcher_config.threshold:.2f} | "
        f"轮询 {watcher_config.poll_interval:.1f}s"
    )
    if log_path:
        print(f" 日志: {log_path}")
    print("=" * 68)


def _probe_screen() -> Tuple[List, object]:
    displays = list_displays()
    capture = capture_display(displays[0])
    return displays, capture


def _check_permissions() -> int:
    print("权限检查：")
    trusted = accessibility_trusted()
    if trusted is None:
        print("  辅助功能: 无法检测（非 macOS 或 PyObjC 不可用）")
    elif trusted:
        print("  辅助功能: ✅ 已授权，可以模拟点击")
    else:
        print("  辅助功能: ❌ 未授权，无法模拟点击")
        print(accessibility_help())
    try:
        displays = list_displays()
        capture = capture_display(displays[0])
        ok, detail = screenshot_sanity(capture)
    except ScreenError as exc:
        print(f"  屏幕录制: ❌ 截图失败：{exc}")
        print(screen_recording_help())
        ok = False
    else:
        if ok:
            print(f"  屏幕录制: ✅ 正常（{detail}）")
        else:
            print(f"  屏幕录制: ❌ {detail}")
            print(screen_recording_help())
    return 0 if trusted is not False and ok else 1


def _countdown(seconds: int = 3) -> None:
    for remaining in range(seconds, 0, -1):
        print(f"\r{remaining} 秒后开始监控……（Ctrl+C 取消）", end="", flush=True)
        time.sleep(1)
    print("\r开始！" + " " * 30)


def _apply_watcher_args(args, runtime: RuntimeConfig) -> None:
    runtime.watcher = WatcherConfig(
        poll_interval=args.poll_interval,
        click_cooldown=args.click_cooldown,
        reclick_delay=args.reclick_delay,
        max_attempts=args.max_attempts,
        stuck_timeout=args.stuck_timeout,
        rate_limit=args.rate_limit,
        max_clicks=args.max_clicks,
        duration=args.duration,
        once=args.once,
        failsafe=args.failsafe,
        stop_file=args.stop_file,
    )


def _print_scan(
    findings,
    scanner: ScreenScanner,
    debug_dir: str,
) -> int:
    if not findings:
        print("\n未找到 Retry 按钮。")
        print("排查建议：")
        print("  1. 确认按钮当前真的显示在屏幕上（未被其他窗口遮挡）")
        print("  2. 用 --dry-run --debug 看看匹配到了什么，或调低 --threshold 0.82")
        print("  3. 按钮主题变化（深色模式）时，用 --modes color,dark,edge")
        print("  4. 截图全黑时检查“屏幕录制”权限")
        print("  5. 按钮尺寸变化很大时，调整 --scale-tolerance / --template-dpi")
        return 1

    clickable = 0
    print(f"\n找到 {len(findings)} 个候选：")
    for index, finding in enumerate(findings, start=1):
        detection = finding.detection
        x, y = detection.global_point
        status = "✅ 可点击" if finding.allowed else "⛔ 已过滤"
        if finding.allowed:
            clickable += 1
        print(
            f"  {index}. {status} | 分数 {detection.score:.3f} "
            f"({detection.mode}, 粗匹配 {detection.coarse_score:.3f}, "
            f"缩放 {detection.scale:.2f})\n"
            f"     位置 ({x:.0f}, {y:.0f}) | 模板 {detection.template_name} | "
            f"窗口: {finding.window_label}"
        )
    if debug_dir:
        saved = scanner.save_debug(findings, directory=Path(debug_dir), prefix="scan")
        for path in saved:
            print(f"  调试截图: {path}")
    print(f"\n合计: {clickable} 个可点击，{len(findings) - clickable} 个被窗口过滤。")
    return 0 if clickable else 2


def _run_scan(args, templates, matcher_config) -> int:
    matcher = Matcher(templates, matcher_config)
    policy = WindowPolicy(
        exclude_pattern=args.exclude_owner,
        include_pattern=args.include_owner,
        enabled=args.window_filter,
    )
    scanner = ScreenScanner(matcher, policy, debug_dir=args.debug)
    findings = scanner.scan_findings()
    return _print_scan(findings, scanner, args.debug)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    log_dir = Path(args.log_dir).expanduser() if args.log_dir else None
    log_path = setup_logging(log_dir, verbose=args.verbose, quiet=args.quiet)

    if args.open_permissions:
        opened = open_privacy_settings("accessibility") | open_privacy_settings("screen")
        if not opened:
            print("无法自动打开系统设置，请手动打开：系统设置 → 隐私与安全性")
            return 1
        print("已打开系统设置的“辅助功能”和“屏幕录制”面板。")
        print("授权/勾选运行本程序的终端 App 后，请重启终端再运行。")
        return 0

    if args.check_permissions:
        return _check_permissions()

    try:
        matcher_config = MatcherConfig(
            threshold=args.threshold,
            coarse_threshold=args.coarse_threshold,
            template_dpi=args.template_dpi,
            max_search_edge=args.max_search_edge,
            scale_tolerance=args.scale_tolerance,
            scale_steps=args.scale_steps,
            modes=args.modes,
            deep_interval=args.deep_interval,
        )
        runtime = RuntimeConfig(matcher=matcher_config)
        _apply_watcher_args(args, runtime)
        runtime.restore_cursor = args.restore_cursor
        runtime.activate_app = args.activate_app
    except ValueError as exc:
        logger.error("参数错误：%s", exc)
        return 2

    template_paths = resolve_template_paths(
        args.template, Path(args.template_dir).expanduser()
    )
    if not template_paths:
        logger.error(
            "没有找到模板图片。请把 Retry 按钮截图放入 %s，"
            "或用 --template 指定图片。",
            args.template_dir,
        )
        return 2
    try:
        templates = load_templates(template_paths)
    except TemplateError as exc:
        logger.error("%s", exc)
        return 2

    if args.list_templates:
        print("使用的模板：")
        for template in templates:
            print(f"  - {template.describe()}")
        return 0

    try:
        displays, capture = _probe_screen()
    except ScreenError as exc:
        logger.error("无法访问屏幕：%s", exc)
        logger.error(screen_recording_help())
        return 3
    ok, detail = screenshot_sanity(capture)
    if not ok:
        logger.error("屏幕截图异常：%s", detail)
        logger.error(screen_recording_help())
        return 3
    logger.debug("screen capture OK: %s", detail)

    if args.scan:
        print(f"屏幕截图: {detail}")
        return _run_scan(args, templates, matcher_config)

    trusted = accessibility_trusted()
    if trusted is False and not args.dry_run and not args.skip_permission_check:
        logger.error("没有“辅助功能”权限，模拟点击不会生效，已停止。")
        logger.error(accessibility_help())
        logger.error("如果确认权限没问题，可加 --skip-permission-check 继续。")
        return 3
    if trusted is False and args.dry_run:
        logger.warning(
            "辅助功能权限未授权；dry-run 不需要点击，继续运行。"
        )
    elif trusted is False:
        logger.warning("辅助功能权限检测为未授权，仍然继续（--skip-permission-check）。")
    elif trusted is None:
        logger.warning("无法检测辅助功能权限，继续运行；如果点击无效请检查系统设置。")

    policy = WindowPolicy(
        exclude_pattern=args.exclude_owner,
        include_pattern=args.include_owner,
        enabled=args.window_filter,
    )
    _print_header(
        templates,
        displays,
        capture,
        policy,
        matcher_config,
        runtime.watcher,
        log_path,
    )
    if args.dry_run:
        print(" 模式: DRY-RUN（只记录，不点击）")
    else:
        print(f" 点击前激活窗口: {'是' if args.activate_app else '否'}")
    if not policy.enabled:
        logger.warning("窗口过滤已关闭，任何位置的匹配都可能被点击。")

    if not args.no_countdown:
        try:
            _countdown()
        except KeyboardInterrupt:
            print("\n已取消。")
            return 0

    matcher = Matcher(templates, matcher_config)
    scanner = ScreenScanner(matcher, policy, debug_dir=args.debug)
    clicker = (
        DryRunClicker()
        if args.dry_run
        else QuartzClicker(
            restore_cursor=args.restore_cursor,
            activate_app=args.activate_app,
        )
    )
    watcher = Watcher(scanner, clicker, runtime.watcher)

    try:
        stats = watcher.run()
    except KeyboardInterrupt:
        watcher.stop("用户按下 Ctrl+C")
        stats = watcher.stats
    print()
    print(stats.summary())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
