from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.exceptions import ApiException
from kubernetes.config import ConfigException

from src.plugins.trivy import TrivyPlugin


def _make_report(critical: int = 0, high: int = 0, low: int = 0, vulns: list = None) -> dict:
    return {
        "metadata": {
            "name": "replicaset-my-app-abc-my-container",
            "labels": {
                "trivy-operator.container.name": "my-container",
                "trivy-operator.resource.kind": "ReplicaSet",
                "trivy-operator.resource.name": "my-app-abc",
            },
        },
        "report": {
            "summary": {
                "criticalCount": critical,
                "highCount": high,
                "lowCount": low,
            },
            "artifact": {
                "repository": "docker.io/my-app",
                "tag": "1.0.0",
            },
            "vulnerabilities": vulns or [],
        },
    }


def _make_plugin() -> TrivyPlugin:
    with patch("src.plugins.trivy.k8s_config.load_incluster_config", side_effect=ConfigException):
        with patch("src.plugins.trivy.k8s_config.load_kube_config"):
            with patch("src.plugins.trivy.client.CustomObjectsApi"):
                return TrivyPlugin()


class TestTrivyPlugin:
    def test_run_returns_empty_on_404(self):
        plugin = _make_plugin()
        plugin._api.list_namespaced_custom_object.side_effect = ApiException(status=404)

        mock_config = MagicMock()
        mock_config.namespaces = ["default"]
        with patch("src.plugins.trivy.config", mock_config):
            result = plugin.run()

        assert result == []

    def test_run_returns_empty_on_403(self):
        plugin = _make_plugin()
        plugin._api.list_namespaced_custom_object.side_effect = ApiException(status=403)

        mock_config = MagicMock()
        mock_config.namespaces = ["default"]
        with patch("src.plugins.trivy.config", mock_config):
            result = plugin.run()

        assert result == []

    def test_report_to_finding_skips_low_only(self):
        plugin = _make_plugin()
        report = _make_report(critical=0, high=0, low=5)
        result = plugin._report_to_finding(report, "default")
        assert result is None

    def test_report_to_finding_critical(self):
        plugin = _make_plugin()
        report = _make_report(critical=2, high=1)
        finding = plugin._report_to_finding(report, "default")

        assert finding is not None
        assert finding.severity == "CRITICAL"
        assert "2 kritische" in finding.message
        assert finding.namespace == "default"

    def test_report_to_finding_high_only(self):
        plugin = _make_plugin()
        report = _make_report(critical=0, high=3)
        finding = plugin._report_to_finding(report, "default")

        assert finding is not None
        assert finding.severity == "HIGH"

    def test_run_aggregates_multiple_namespaces(self):
        plugin = _make_plugin()
        report = _make_report(critical=1)
        plugin._api.list_namespaced_custom_object.return_value = {"items": [report]}

        mock_config = MagicMock()
        mock_config.namespaces = ["default", "staging"]
        with patch("src.plugins.trivy.config", mock_config):
            result = plugin.run()

        assert len(result) == 2

    def test_run_filters_clean_reports(self):
        plugin = _make_plugin()
        clean_report = _make_report(critical=0, high=0, low=3)
        plugin._api.list_namespaced_custom_object.return_value = {"items": [clean_report]}

        mock_config = MagicMock()
        mock_config.namespaces = ["default"]
        with patch("src.plugins.trivy.config", mock_config):
            result = plugin.run()

        assert result == []
