# -*- coding: utf-8 -*-
"""DiffGuard 程序入口：初始化日志、加载配置并启动 GUI。

首次运行（未配置 API Key）时会在主窗口弹出后自动打开设置窗口。
首次运行新版本（配置中尚无 decision_assistant 字段）时会弹出
「决策助手」首启引导。
"""

import json

from loguru import logger

from models.config import Config, config_path, is_configured, load_config
from models.decision_prompt import DecisionMode
from ui.app import DiffGuardApp
from ui.settings_view import FirstRunDecisionDialog, FirstRunWizard
from utils.logger import setup_logger


def _needs_decision_first_run() -> bool:
    """配置中尚无 decision_assistant 字段时视为首启需引导。"""
    try:
        path = config_path()
        if not path.is_file():
            return True
        data = json.loads(path.read_text(encoding="utf-8"))
        return "decision_assistant" not in data
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("读取配置判定首启失败（按需引导）: {}", exc)
        return True


def _enable_dpi_awareness() -> None:
    """启用进程级 DPI 感知，避免 Tk 在高分屏（150% 等）下按钮命中错位。

    必须在创建任何 Tk 窗口前调用。Windows 8.1+ 用 shcore；失败时回退 user32。
    """
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # SYSTEM_DPI_AWARE
            logger.info("已启用 DPI 感知 (shcore)")
            return
        except Exception:
            pass
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            logger.info("已启用 DPI 感知 (user32)")
        except Exception as exc:
            logger.debug("启用 DPI 感知失败: {}", exc)
    except Exception as exc:
        logger.debug("DPI 感知初始化异常: {}", exc)


def main() -> None:
    """DiffGuard 应用入口。"""
    setup_logger()
    _enable_dpi_awareness()
    logger.info("DiffGuard 启动")

    config: Config = load_config()
    logger.info("当前模型: {}", config.model)
    logger.info("自动监听剪贴板: {}", config.auto_clipboard)
    logger.info("权限审批监控: {}", config.permission_monitor)
    logger.info("权限浮窗置顶: {}", config.floating_mode_enabled)
    logger.info("决策助手模式: {}", config.decision_assistant)

    app: DiffGuardApp = DiffGuardApp(config)

    # 首次配置向导（未配置 API Key 且首次运行时弹出）
    if not is_configured(config):
        logger.info("检测到未配置 API Key，弹出首次配置向导")
        app.after(500, lambda: FirstRunWizard(app, on_done=lambda c: app.on_wizard_done(c), config=config))

    # 决策助手首启引导（仅弹一次）
    elif _needs_decision_first_run():

        def _on_first_choice(mode: str) -> None:
            if mode != DecisionMode.OFF.value:
                # 用户在此前未启动决策监听，引导后启动
                app.restart_decision_watching()

        app.after(600, lambda: FirstRunDecisionDialog(app, on_choice=_on_first_choice))

    try:
        app.mainloop()
    except Exception as exc:  # GUI 主循环异常不希望程序静默退出
        logger.exception("应用主循环发生异常: {}", exc)


if __name__ == "__main__":
    main()
