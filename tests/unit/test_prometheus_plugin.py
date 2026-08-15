from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.plugins.prometheus import PrometheusPlugin


def _mock_config(prometheus_url: str = "http://localhost:9090"):
    mock = MagicMock()
    mock.prometheus_url = prometheus_url
    return mock


def _make_alert(
    state: str = "firing",
    severity: str = "critical",
    alertname: str = "PodCrashLooping",
    namespace: str = "default",
    pod: str = "",
    instance: str = "",
    summary: str = "",
    description: str = "",
    active_at: str = "2024-01-15T10:00:00.000000000Z",
) -> dict:
    labels = {"alertname": alertname, "severity": severity, "namespace": namespace}
    if pod:
        labels["pod"] = pod
    if instance:
        labels["instance"] = instance

    annotations = {}
    if summary:
        annotations["summary"] = summary
    if description:
        annotations["description"] = description

    return {
        "state": state,
        "labels": labels,
        "annotations": annotations,
        "activeAt": active_at,
    }


def _mock_response(alerts: list[dict], status_code: int = 200):
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status = MagicMock()
    response.json.return_value = {"data": {"alerts": alerts}}
    return response


class TestPrometheusPluginRun:
    def test_run_returns_empty_on_connection_error(self):
        plugin = PrometheusPlugin()
        with patch("src.plugins.prometheus.config", _mock_config()):
            with patch(
                "src.plugins.prometheus.requests.get",
                side_effect=requests.ConnectionError("refused"),
            ):
                result = plugin.run()

        assert result == []

    def test_run_returns_empty_on_timeout(self):
        plugin = PrometheusPlugin()
        with patch("src.plugins.prometheus.config", _mock_config()):
            with patch(
                "src.plugins.prometheus.requests.get",
                side_effect=requests.Timeout("timed out"),
            ):
                result = plugin.run()

        assert result == []

    def test_run_returns_empty_on_http_error(self):
        plugin = PrometheusPlugin()
        response = MagicMock()
        response.raise_for_status.side_effect = requests.HTTPError("500")

        with patch("src.plugins.prometheus.config", _mock_config()):
            with patch("src.plugins.prometheus.requests.get", return_value=response):
                result = plugin.run()

        assert result == []

    def test_run_returns_empty_on_invalid_json(self):
        plugin = PrometheusPlugin()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.side_effect = ValueError("not json")

        with patch("src.plugins.prometheus.config", _mock_config()):
            with patch("src.plugins.prometheus.requests.get", return_value=response):
                result = plugin.run()

        assert result == []

    def test_run_returns_empty_when_no_alerts(self):
        plugin = PrometheusPlugin()
        response = _mock_response([])

        with patch("src.plugins.prometheus.config", _mock_config()):
            with patch("src.plugins.prometheus.requests.get", return_value=response):
                result = plugin.run()

        assert result == []


class TestAlertsToFindings:
    def test_alerts_to_findings_skips_pending(self):
        plugin = PrometheusPlugin()
        alerts = [_make_alert(state="pending")]

        result = plugin._alerts_to_findings(alerts)

        assert result == []

    def test_alerts_to_findings_maps_critical(self):
        plugin = PrometheusPlugin()
        alerts = [_make_alert(severity="critical")]

        result = plugin._alerts_to_findings(alerts)

        assert len(result) == 1
        assert result[0].severity == "critical"

    def test_alerts_to_findings_maps_warning(self):
        plugin = PrometheusPlugin()
        alerts = [_make_alert(severity="warning")]

        result = plugin._alerts_to_findings(alerts)

        assert len(result) == 1
        assert result[0].severity == "warning"

    def test_alerts_to_findings_unknown_severity_defaults_warning(self):
        plugin = PrometheusPlugin()
        alerts = [_make_alert(severity="")]

        result = plugin._alerts_to_findings(alerts)

        assert len(result) == 1
        assert result[0].severity == "warning"

    def test_alerts_to_findings_multiple_firing(self):
        plugin = PrometheusPlugin()
        alerts = [
            _make_alert(alertname="AlertA", severity="critical"),
            _make_alert(alertname="AlertB", severity="warning"),
        ]

        result = plugin._alerts_to_findings(alerts)

        assert len(result) == 2

    def test_finding_message_includes_alertname_and_summary(self):
        plugin = PrometheusPlugin()
        alerts = [_make_alert(alertname="PodCrashLooping", summary="Pod is crash looping")]

        result = plugin._alerts_to_findings(alerts)

        assert "PodCrashLooping" in result[0].message
        assert "Pod is crash looping" in result[0].message

    def test_finding_resource_uses_pod_label(self):
        plugin = PrometheusPlugin()
        alerts = [_make_alert(pod="my-pod")]

        result = plugin._alerts_to_findings(alerts)

        assert result[0].resource == "pod/my-pod"

    def test_finding_resource_falls_back_to_instance(self):
        plugin = PrometheusPlugin()
        alerts = [_make_alert(instance="10.0.0.1:9100")]

        result = plugin._alerts_to_findings(alerts)

        assert result[0].resource == "10.0.0.1:9100"

    def test_fingerprint_is_alertname_and_resource(self):
        plugin = PrometheusPlugin()
        alerts = [_make_alert(alertname="PodCrashLooping", pod="my-pod")]

        result = plugin._alerts_to_findings(alerts)

        assert result[0].fingerprint == "PodCrashLooping:pod/my-pod"

    def test_identity_is_fingerprint_resource(self):
        plugin = PrometheusPlugin()
        alerts = [_make_alert(alertname="PodCrashLooping", pod="my-pod")]

        result = plugin._alerts_to_findings(alerts)

        assert result[0].identity == "pod/my-pod"

    def test_identity_falls_back_to_instance_without_pod(self):
        plugin = PrometheusPlugin()
        alerts = [_make_alert(instance="10.0.0.1:9100")]

        result = plugin._alerts_to_findings(alerts)

        assert result[0].identity == "10.0.0.1:9100"

    def test_finding_raw_contains_labels_and_annotations(self):
        plugin = PrometheusPlugin()
        alerts = [_make_alert(summary="something broke")]

        result = plugin._alerts_to_findings(alerts)

        assert result[0].raw["labels"] == alerts[0]["labels"]
        assert result[0].raw["annotations"] == alerts[0]["annotations"]
