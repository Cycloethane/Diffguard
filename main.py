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
from ui.settings_view import FirstRunDecisionDialog
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


def main() -> None:
    """DiffGuard 应用入口。"""
    setup_logger()
    logger.info("DiffGuard 启动")

    config: Config = load_config()
    logger.info("当前模型: {}", config.model)
    logger.info("自动监听剪贴板: {}", config.auto_clipboard)
    logger.info("权限审批监控: {}", config.permission_monitor)
    logger.info("权限浮窗置顶: {}", config.floating_mode_enabled)
    logger.info("决策助手模式: {}", config.decision_assistant)

    app: DiffGuardApp = DiffGuardApp(config)

    # 决策助手首启引导（仅弹一次）
    if _needs_decision_first_run():

        def _on_first_choice(mode: str) -> None:
            if mode != DecisionMode.OFF.value:
                # 用户在此前未启动决策监听，引导后启动
                app.restart_decision_watching()

        app.after(600, lambda: FirstRunDecisionDialog(app, on_choice=_on_first_choice))

    if not is_configured(config):
        logger.info("检测到未配置 API Key，准备弹出设置窗口")
        # 主窗口绘制完成后自动打开设置
        app.after(400, app._open_settings)

    try:
        app.mainloop()
    except Exception as exc:  # GUI 主循环异常不希望程序静默退出
        logger.exception("应用主循环发生异常: {}", exc)


if __name__ == "__main__":
    main()
