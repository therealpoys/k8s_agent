from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.exceptions import ApiException
from kubernetes.config import ConfigException

from src.plugins.falco import FalcoPlugin, _SEVERITY_MAP


def _make_plugin() -> FalcoPlugin:
    with patch("src.plugins.falco.k8s_config.load_incluster_config", side_effect=ConfigException):
        with patch("src.plugins.falco.k8s_config.load_kube_config"):
            with patch("src.plugins.falco.client.CoreV1Api"):
                return FalcoPlugin()


def _make_event(rule: str = "Read sensitive file", priority: str = "Warning", **output_fields) -> dict:
    return {
        "rule": rule,
        "priority": priority,
        "time": "2024-01-15T10:00:00.000000000Z",
        "output": f"{priority} {rule}",
        "tags": ["filesystem"],
        "output_fields": output_fields,
    }


def _mock_config(falco_namespace: str = "falco", log_lines: int = 100):
    mock = MagicMock()
    mock.falco_namespace = falco_namespace
    mock.log_lines = log_lines
    return mock


class TestFalcoPluginRun:
    def test_run_returns_empty_when_no_pods(self):
        plugin = _make_plugin()
        plugin._core.list_namespaced_pod.return_value = MagicMock(items=[])

        with patch("src.plugins.falco.config", _mock_config()):
            result = plugin.run()

        assert result == []

    def test_run_returns_empty_on_403(self):
        plugin = _make_plugin()
        plugin._core.list_namespaced_pod.side_effect = ApiException(status=403)

        with patch("src.plugins.falco.config", _mock_config()):
            result = plugin.run()

        assert result == []

    def test_run_returns_empty_on_404_namespace(self):
        plugin = _make_plugin()
        plugin._core.list_namespaced_pod.side_effect = ApiException(status=404)

        with patch("src.plugins.falco.config", _mock_config()):
            result = plugin.run()

        assert result == []

    def test_run_aggregates_multiple_pods(self):
        plugin = _make_plugin()

        pod_a = MagicMock()
        pod_a.metadata.name = "falco-abc"
        pod_b = MagicMock()
        pod_b.metadata.name = "falco-xyz"
        plugin._core.list_namespaced_pod.return_value = MagicMock(items=[pod_a, pod_b])

        event_a = _make_event(rule="Rule A", priority="Critical")
        event_b = _make_event(rule="Rule B", priority="Warning")
        logs_a = '{"rule":"Rule A","priority":"Critical","time":"2024-01-15T10:00:00Z","output":"","output_fields":{}}'
        logs_b = '{"rule":"Rule B","priority":"Warning","time":"2024-01-15T10:00:00Z","output":"","output_fields":{}}'

        plugin._core.read_namespaced_pod_log.side_effect = [logs_a, logs_b]

        with patch("src.plugins.falco.config", _mock_config()):
            result = plugin.run()

        assert len(result) == 2


class TestReadPodLogs:
    def test_read_pod_logs_skips_non_json(self):
        plugin = _make_plugin()
        logs = "\n".join([
            "time=\"2024-01-15T10:00:00Z\" level=info msg=\"Falco initialized\"",
            '{"rule":"Write below etc","priority":"Warning","time":"2024-01-15T10:00:01Z","output":"","output_fields":{}}',
            "Loading rules from file /etc/falco/falco_rules.yaml",
        ])
        plugin._core.read_namespaced_pod_log.return_value = logs

        with patch("src.plugins.falco.config", _mock_config()):
            result = plugin._read_pod_logs("falco-pod", "falco")

        assert len(result) == 1
        assert result[0]["rule"] == "Write below etc"

    def test_read_pod_logs_skips_events_without_rule(self):
        plugin = _make_plugin()
        logs = "\n".join([
            '{"priority":"Warning","time":"2024-01-15T10:00:00Z","output":""}',
            '{"rule":"Valid Rule","priority":"Warning","time":"2024-01-15T10:00:01Z","output":"","output_fields":{}}',
        ])
        plugin._core.read_namespaced_pod_log.return_value = logs

        with patch("src.plugins.falco.config", _mock_config()):
            result = plugin._read_pod_logs("falco-pod", "falco")

        assert len(result) == 1
        assert result[0]["rule"] == "Valid Rule"


class TestEventsToFindings:
    def test_events_to_findings_filters_low_priority(self):
        plugin = _make_plugin()
        events = [_make_event(priority="Notice"), _make_event(priority="Informational"), _make_event(priority="Debug")]

        with patch("src.plugins.falco.config", _mock_config()):
            result = plugin._events_to_findings(events, "falco")

        assert result == []

    def test_events_to_findings_maps_critical(self):
        plugin = _make_plugin()
        events = [_make_event(rule="Syscall", priority="Critical")]

        with patch("src.plugins.falco.config", _mock_config()):
            result = plugin._events_to_findings(events, "falco")

        assert len(result) == 1
        assert result[0].severity == "critical"

    def test_events_to_findings_maps_warning(self):
        plugin = _make_plugin()
        events = [_make_event(rule="Read /etc", priority="Warning")]

        with patch("src.plugins.falco.config", _mock_config()):
            result = plugin._events_to_findings(events, "falco")

        assert len(result) == 1
        assert result[0].severity == "warning"

    def test_events_to_findings_deduplicates_by_rule(self):
        plugin = _make_plugin()
        events = [_make_event(rule="Same Rule", priority="Warning")] * 5

        with patch("src.plugins.falco.config", _mock_config()):
            result = plugin._events_to_findings(events, "falco")

        assert len(result) == 1
        assert result[0].raw["count"] == 5

    def test_events_to_findings_separate_rules(self):
        plugin = _make_plugin()
        events = [
            _make_event(rule="Rule A", priority="Warning"),
            _make_event(rule="Rule B", priority="Critical"),
        ]

        with patch("src.plugins.falco.config", _mock_config()):
            result = plugin._events_to_findings(events, "falco")

        assert len(result) == 2

    def test_finding_includes_output_fields_in_raw(self):
        plugin = _make_plugin()
        events = [_make_event(rule="Passwd read", priority="Warning", **{"proc.name": "cat", "fd.name": "/etc/passwd"})]

        with patch("src.plugins.falco.config", _mock_config()):
            result = plugin._events_to_findings(events, "falco")

        assert result[0].raw["output_fields"]["proc.name"] == "cat"
        assert result[0].raw["output_fields"]["fd.name"] == "/etc/passwd"

    def test_fingerprint_is_rule_name(self):
        plugin = _make_plugin()
        events = [_make_event(rule="Read sensitive file", priority="Warning")]

        with patch("src.plugins.falco.config", _mock_config()):
            result = plugin._events_to_findings(events, "falco")

        assert result[0].fingerprint == "Read sensitive file"

    def test_identity_is_pod_with_stable_name_when_pod_present(self):
        plugin = _make_plugin()
        events = [_make_event(rule="Read sensitive file", priority="Warning", **{"k8s.pod.name": "myapp-7d9f8c6b5-xk2pl"})]

        with patch("src.plugins.falco.config", _mock_config()):
            result = plugin._events_to_findings(events, "falco")

        assert result[0].identity == "pod/myapp"

    def test_identity_falls_back_to_node_unknown_without_pod(self):
        plugin = _make_plugin()
        events = [_make_event(rule="Read sensitive file", priority="Warning")]

        with patch("src.plugins.falco.config", _mock_config()):
            result = plugin._events_to_findings(events, "falco")

        assert result[0].identity == "node/unknown"

    def test_finding_message_includes_process_and_file(self):
        plugin = _make_plugin()
        events = [_make_event(rule="Shadow read", priority="Critical", **{"proc.name": "cat", "fd.name": "/etc/shadow"})]

        with patch("src.plugins.falco.config", _mock_config()):
            result = plugin._events_to_findings(events, "falco")

        assert "cat" in result[0].message
        assert "/etc/shadow" in result[0].message
