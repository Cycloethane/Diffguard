# -*- coding: utf-8 -*-
"""配置模块：基于 pydantic-settings 管理 DiffGuard 的配置。

配置以 JSON 形式保存在平台用户配置目录中（Windows 下为
%APPDATA%\\DiffGuard\\config.json），支持环境变量覆盖（前缀 DIFFGUARD_）。
"""

import json
from pathlib import Path
from typing import Any

import platformdirs
from loguru import logger
from pydantic_settings import BaseSettings, SettingsConfigDict

# 默认模型
_DEFAULT_MODEL: str = "deepseek-ai/DeepSeek-V4-Flash"
# SiliconFlow OpenAI 兼容接口地址
DEFAULT_BASE_URL: str = "https://api.siliconflow.cn/v1"


class Config(BaseSettings):
    """DiffGuard 应用配置模型。

    属性:
        api_key: SiliconFlow 平台 API Key。
        model: 使用的模型名称。
        auto_clipboard: 是否自动监听剪贴板中的 git diff。
        permission_monitor: 是否启用权限审批监控（UIA 主通道 + 剪贴板辅助）。
        floating_mode_enabled: 权限审批浮窗是否置顶显示。
        theme: 界面主题（dark / light）。
        accent: 强调色方案（blue/green/purple/orange）。
        auto_allow_low_risk: 低风险权限请求是否自动放行。
        auto_allow_threshold: 自动放行的风险阈值（score < 阈值 时放行）。
        tray_notify: 高风险权限请求是否发送系统托盘通知。
        keyboard_inject: 是否启用键盘注入回写（TUI，默认关闭）。
        check_updates: 启动时是否检查新版本。
        decision_assistant: 决策助手模式（off / ask / on）。
        decision_level: 决策解析措辞水平（beginner / normal / advanced）。
        decision_show_overlay: 前台模式是否显示决策徽标。
        decision_auto: 检测到决策是否自动调用 AI 解析（ask 模式下忽略）。
        decision_max_len: 送入 AI 解析的原始文本长度上限。
        opencode_bridge: 是否启用 OpenCode 桥接（决策反馈回写）。
        opencode_mcp: 是否启用 OpenCode 集成（Agent 决策请求精确通道）。
    """

    api_key: str = ""
    model: str = _DEFAULT_MODEL
    auto_clipboard: bool = True
    permission_monitor: bool = True
    floating_mode_enabled: bool = True
    theme: str = "dark"
    accent: str = "blue"
    auto_allow_low_risk: bool = False
    auto_allow_threshold: int = 20
    tray_notify: bool = True
    keyboard_inject: bool = False
    check_updates: bool = True
    decision_assistant: str = "off"
    decision_level: str = "normal"
    decision_show_overlay: bool = True
    decision_auto: bool = True
    decision_max_len: int = 4000
    opencode_bridge: bool = True
    opencode_mcp: bool = True

    model_config = SettingsConfigDict(
        env_prefix="DIFFGUARD_",
        extra="ignore",
    )


def config_path() -> Path:
    """返回配置文件完整路径。"""
    return Path(platformdirs.user_config_dir("DiffGuard")) / "config.json"


def load_config() -> Config:
    """从磁盘加载配置；文件不存在或解析失败时返回默认配置。"""
    path: Path = config_path()
    data: dict[str, Any] = {}
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            logger.info("已从 {} 加载配置", path)
        else:
            logger.info("配置文件不存在，使用默认配置")
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("读取配置文件失败，使用默认配置: {}", exc)
    return Config(**data)


def save_config(cfg: Config) -> None:
    """将配置写入磁盘 JSON 文件。"""
    path: Path = config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cfg.model_dump_json(exclude_none=True, indent=2), encoding="utf-8")
        logger.info("配置已保存到 {}", path)
    except OSError as exc:
        logger.error("保存配置文件失败: {}", exc)


def is_configured(cfg: Config) -> bool:
    """判断是否已完成基本配置（拥有 API Key）。"""
    return bool(cfg.api_key and cfg.api_key.strip())