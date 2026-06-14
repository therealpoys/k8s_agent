import logging
from unittest.mock import MagicMock, patch

import pytest

from src.plugins.loader import load_plugins


def _make_mock_plugin_class(name: str):
    cls = MagicMock()
    instance = MagicMock()
    instance.name = name
    cls.return_value = instance
    return cls


class TestLoadPlugins:
    def test_load_core_plugins_only(self):
        mock_cls = _make_mock_plugin_class("pod_logs")
        mock_config = MagicMock()
        mock_config.core_plugins = ["pod_logs"]
        mock_config.optional_plugins = {}

        with (
            patch("src.plugins.loader.config", mock_config),
            patch("src.plugins.loader.PLUGIN_REGISTRY", {"pod_logs": mock_cls}),
        ):
            plugins = load_plugins()

        assert len(plugins) == 1
        mock_cls.assert_called_once()

    def test_load_optional_when_enabled(self):
        pod_cls = _make_mock_plugin_class("pod_logs")
        trivy_cls = _make_mock_plugin_class("trivy")
        mock_config = MagicMock()
        mock_config.core_plugins = ["pod_logs"]
        mock_config.optional_plugins = {"trivy": True}

        with (
            patch("src.plugins.loader.config", mock_config),
            patch("src.plugins.loader.PLUGIN_REGISTRY", {"pod_logs": pod_cls, "trivy": trivy_cls}),
        ):
            plugins = load_plugins()

        assert len(plugins) == 2

    def test_skip_disabled_optional(self):
        pod_cls = _make_mock_plugin_class("pod_logs")
        trivy_cls = _make_mock_plugin_class("trivy")
        mock_config = MagicMock()
        mock_config.core_plugins = ["pod_logs"]
        mock_config.optional_plugins = {"trivy": False}

        with (
            patch("src.plugins.loader.config", mock_config),
            patch("src.plugins.loader.PLUGIN_REGISTRY", {"pod_logs": pod_cls, "trivy": trivy_cls}),
        ):
            plugins = load_plugins()

        assert len(plugins) == 1
        trivy_cls.assert_not_called()

    def test_warn_unknown_plugin(self, caplog):
        mock_config = MagicMock()
        mock_config.core_plugins = ["nonexistent"]
        mock_config.optional_plugins = {}

        with (
            patch("src.plugins.loader.config", mock_config),
            patch("src.plugins.loader.PLUGIN_REGISTRY", {}),
            caplog.at_level(logging.WARNING, logger="src.plugins.loader"),
        ):
            plugins = load_plugins()

        assert plugins == []
        assert "nonexistent" in caplog.text
