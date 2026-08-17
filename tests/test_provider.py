# -*- coding: utf-8 -*-
"""AI 提供方配置单元测试（SiliconFlow / OpenCode Zen / OpenCode Go）。"""
from models.config import (
    PROVIDER_OPENCODE_GO,
    PROVIDER_OPENCODE_ZEN,
    PROVIDER_SILICONFLOW,
    provider_base_url,
    provider_default_model,
    provider_models,
)
from models.config import Config


class TestProviderDefaults:
    def test_default_provider_is_siliconflow(self):
        cfg = Config()
        assert cfg.provider == PROVIDER_SILICONFLOW

    def test_base_urls(self):
        assert provider_base_url(PROVIDER_SILICONFLOW) == "https://api.siliconflow.cn/v1"
        assert provider_base_url(PROVIDER_OPENCODE_ZEN) == "https://opencode.ai/zen/v1"
        assert provider_base_url(PROVIDER_OPENCODE_GO) == "https://opencode.ai/zen/go/v1"

    def test_unknown_provider_falls_back(self):
        assert provider_base_url("bogus") == "https://api.siliconflow.cn/v1"
        assert provider_models("bogus")[0] == "deepseek-ai/DeepSeek-V4-Flash"


class TestProviderModels:
    def test_siliconflow_models(self):
        models = provider_models(PROVIDER_SILICONFLOW)
        assert "deepseek-ai/DeepSeek-V4-Flash" in models

    def test_zen_models(self):
        models = provider_models(PROVIDER_OPENCODE_ZEN)
        assert "deepseek-v4-flash" in models
        assert "claude-haiku-4-5" in models

    def test_go_models(self):
        models = provider_models(PROVIDER_OPENCODE_GO)
        assert "glm-5.2" in models
        assert "kimi-k3" in models

    def test_default_models(self):
        assert provider_default_model(PROVIDER_SILICONFLOW) == "deepseek-ai/DeepSeek-V4-Flash"
        assert provider_default_model(PROVIDER_OPENCODE_ZEN) == "deepseek-v4-flash"
        assert provider_default_model(PROVIDER_OPENCODE_GO) == "deepseek-v4-flash"
