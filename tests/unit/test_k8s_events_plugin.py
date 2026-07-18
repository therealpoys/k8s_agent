from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from kubernetes.client.exceptions import ApiException
from kubernetes.config import ConfigException

from src.plugins.k8s_events import K8sEventsPlugin


def _make_plugin() -> K8sEventsPlugin:
    with patch("src.plugins.k8s_events.k8s_config.load_incluster_config", side_effect=ConfigException):
        with patch("src.plugins.k8s_events.k8s_config.load_kube_config"):
            with patch("src.plugins.k8s_events.client.CoreV1Api"):
                return K8sEventsPlugin()


def _mock_config(namespaces: list[str] = None) -> MagicMock:
    cfg = MagicMock()
    cfg.namespaces = namespaces if namespaces is not None else ["default"]
    return cfg


def _make_event(
    kind: str = "Pod",
    name: str = "my-pod",
    reason: str = "FailedMount",
    message: str = "unable to mount volume",
    count: int = 1,
    event_type: str = "Warning",
) -> MagicMock:
    event = MagicMock()
    event.involved_object.kind = kind
    event.involved_object.name = name
    event.involved_object.field_path = ""
    event.reason = reason
    event.message = message
    event.count = count
    event.type = event_type
    event.last_timestamp = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    event.event_time = None
    event.reporting_component = "kubelet"
    event.source = None
    return event


class TestK8sEventsPluginRun:
    def test_run_returns_empty_when_no_events(self):
        plugin = _make_plugin()
        plugin._core.list_namespaced_event.return_value = MagicMock(items=[])

        with patch("src.plugins.k8s_events.config", _mock_config()):
            result = plugin.run()

        assert result == []

    def test_run_returns_empty_on_403(self):
        plugin = _make_plugin()
        plugin._core.list_namespaced_event.side_effect = ApiException(status=403)

        with patch("src.plugins.k8s_events.config", _mock_config()):
            result = plugin.run()

        assert result == []

    def test_run_returns_empty_on_404_namespace(self):
        plugin = _make_plugin()
        plugin._core.list_namespaced_event.side_effect = ApiException(status=404)

        with patch("src.plugins.k8s_events.config", _mock_config()):
            result = plugin.run()

        assert result == []

    def test_run_queries_all_configured_namespaces(self):
        plugin = _make_plugin()
        plugin._core.list_namespaced_event.return_value = MagicMock(items=[])

        with patch("src.plugins.k8s_events.config", _mock_config(namespaces=["a", "b"])):
            plugin.run()

        called_namespaces = [
            call.args[0] for call in plugin._core.list_namespaced_event.call_args_list
        ]
        assert called_namespaces == ["a", "b"]

    def test_run_aggregates_across_namespaces(self):
        plugin = _make_plugin()
        events_a = MagicMock(items=[_make_event(name="pod-a", reason="FailedMount")])
        events_b = MagicMock(items=[_make_event(name="pod-b", reason="FailedScheduling")])
        plugin._core.list_namespaced_event.side_effect = [events_a, events_b]

        with patch("src.plugins.k8s_events.config", _mock_config(namespaces=["ns-a", "ns-b"])):
            result = plugin.run()

        assert len(result) == 2
        assert {f.namespace for f in result} == {"ns-a", "ns-b"}


class TestEventsToFindings:
    def test_events_to_findings_maps_kind_and_name(self):
        plugin = _make_plugin()
        events = [_make_event(kind="Deployment", name="my-app", reason="ProgressDeadlineExceeded")]

        result = plugin._events_to_findings(events, "default")

        assert len(result) == 1
        assert result[0].resource == "deployment/my-app"

    def test_events_to_findings_deduplicates_by_kind_name_reason(self):
        plugin = _make_plugin()
        events = [
            _make_event(kind="Pod", name="my-pod", reason="FailedMount", count=1),
            _make_event(kind="Pod", name="my-pod", reason="FailedMount", count=1),
            _make_event(kind="Pod", name="my-pod", reason="FailedMount", count=1),
        ]

        result = plugin._events_to_findings(events, "default")

        assert len(result) == 1
        assert result[0].raw["count"] == 3

    def test_events_to_findings_sums_count_field(self):
        plugin = _make_plugin()
        events = [
            _make_event(kind="Pod", name="my-pod", reason="BackOff", count=5),
            _make_event(kind="Pod", name="my-pod", reason="BackOff", count=2),
        ]

        result = plugin._events_to_findings(events, "default")

        assert len(result) == 1
        assert result[0].raw["count"] == 7

    def test_events_to_findings_separate_groups_by_reason(self):
        plugin = _make_plugin()
        events = [
            _make_event(kind="Pod", name="my-pod", reason="FailedMount"),
            _make_event(kind="Pod", name="my-pod", reason="BackOff"),
        ]

        result = plugin._events_to_findings(events, "default")

        assert len(result) == 2

    def test_finding_severity_always_high(self):
        plugin = _make_plugin()
        events = [_make_event(reason="FailedScheduling")]

        result = plugin._events_to_findings(events, "default")

        assert result[0].severity == "HIGH"

    def test_finding_message_includes_reason_and_message(self):
        plugin = _make_plugin()
        events = [_make_event(reason="FailedMount", message="unable to mount volume")]

        result = plugin._events_to_findings(events, "default")

        assert "FailedMount" in result[0].message
        assert "unable to mount volume" in result[0].message

    def test_reporting_component_used_when_source_absent(self):
        plugin = _make_plugin()
        events = [_make_event()]
        events[0].source = None
        events[0].reporting_component = "kubelet"

        result = plugin._events_to_findings(events, "default")

        assert result[0].raw["reporting_component"] == "kubelet"

    def test_reporting_component_falls_back_to_source_when_unset(self):
        plugin = _make_plugin()
        events = [_make_event()]
        events[0].reporting_component = ""
        events[0].source = MagicMock(component="scheduler")

        result = plugin._events_to_findings(events, "default")

        assert result[0].raw["reporting_component"] == "scheduler"
