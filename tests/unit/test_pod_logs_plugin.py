from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.exceptions import ApiException

from src.models import Finding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pod(name: str, namespace: str) -> MagicMock:
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.namespace = namespace
    return pod


def _api_exception(status: int) -> ApiException:
    exc = ApiException(status=status)
    exc.status = status
    return exc


def _mock_config(namespaces: list[str] = None, log_lines: int = 50) -> MagicMock:
    cfg = MagicMock()
    cfg.namespaces = namespaces if namespaces is not None else ["default"]
    cfg.log_lines = log_lines
    return cfg


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_k8s():
    """Patches K8s config loading and returns a CoreV1Api mock."""
    with (
        patch("src.plugins.pod_logs.k8s_config.load_incluster_config") as in_cluster,
        patch("src.plugins.pod_logs.k8s_config.load_kube_config") as kube_config,
        patch("src.plugins.pod_logs.client.CoreV1Api") as api_cls,
    ):
        v1 = MagicMock()
        api_cls.return_value = v1
        yield {"in_cluster": in_cluster, "kube_config": kube_config, "v1": v1}


# ---------------------------------------------------------------------------
# __init__ — config loading
# ---------------------------------------------------------------------------

class TestInit:
    def test_uses_incluster_when_available(self, mock_k8s):
        from src.plugins.pod_logs import PodLogsPlugin

        PodLogsPlugin()

        mock_k8s["in_cluster"].assert_called_once()
        mock_k8s["kube_config"].assert_not_called()

    def test_falls_back_to_kubeconfig(self, mock_k8s):
        import kubernetes
        from src.plugins.pod_logs import PodLogsPlugin

        mock_k8s["in_cluster"].side_effect = kubernetes.config.ConfigException()

        PodLogsPlugin()

        mock_k8s["kube_config"].assert_called_once()


# ---------------------------------------------------------------------------
# run() — happy path
# ---------------------------------------------------------------------------

class TestRunHappyPath:
    def test_returns_finding_per_pod_with_logs(self, mock_k8s):
        import importlib
        import src.plugins.pod_logs as module

        mock_cfg = _mock_config(namespaces=["default"], log_lines=50)
        with patch.object(module, "config", mock_cfg):
            from src.plugins.pod_logs import PodLogsPlugin

            v1 = mock_k8s["v1"]
            v1.list_namespaced_pod.return_value.items = [_make_pod("web-abc", "default")]
            v1.read_namespaced_pod_log.return_value = "line1\nline2\nline3"

            plugin = PodLogsPlugin()
            findings = plugin.run()

        assert len(findings) == 1
        f = findings[0]
        assert isinstance(f, Finding)
        assert f.source == "pod_logs"
        assert f.namespace == "default"
        assert f.resource == "web-abc"
        assert f.severity == "info"
        assert f.message == "line1\nline2\nline3"
        assert isinstance(f.timestamp, datetime)
        assert f.raw == {"pod_name": "web-abc", "namespace": "default", "log_lines": 3}

    def test_log_lines_passed_to_api(self, mock_k8s):
        import src.plugins.pod_logs as module

        mock_cfg = _mock_config(namespaces=["kube-system"], log_lines=100)
        with patch.object(module, "config", mock_cfg):
            from src.plugins.pod_logs import PodLogsPlugin

            v1 = mock_k8s["v1"]
            v1.list_namespaced_pod.return_value.items = [_make_pod("dns-pod", "kube-system")]
            v1.read_namespaced_pod_log.return_value = "log"

            PodLogsPlugin().run()

        _, kwargs = v1.read_namespaced_pod_log.call_args
        assert kwargs["tail_lines"] == 100
        assert kwargs["timeout_seconds"] == 10

    def test_returns_empty_list_when_no_pods(self, mock_k8s):
        import src.plugins.pod_logs as module

        with patch.object(module, "config", _mock_config()):
            from src.plugins.pod_logs import PodLogsPlugin

            mock_k8s["v1"].list_namespaced_pod.return_value.items = []

            findings = PodLogsPlugin().run()

        assert findings == []

    def test_iterates_multiple_namespaces(self, mock_k8s):
        import src.plugins.pod_logs as module

        mock_cfg = _mock_config(namespaces=["ns-a", "ns-b"])
        with patch.object(module, "config", mock_cfg):
            from src.plugins.pod_logs import PodLogsPlugin

            v1 = mock_k8s["v1"]
            v1.list_namespaced_pod.return_value.items = [_make_pod("pod-1", "ns")]
            v1.read_namespaced_pod_log.return_value = "log"

            findings = PodLogsPlugin().run()

        assert v1.list_namespaced_pod.call_count == 2
        assert len(findings) == 2


# ---------------------------------------------------------------------------
# run() — skip empty logs
# ---------------------------------------------------------------------------

class TestRunEmptyLogs:
    def test_skips_pod_with_empty_log_string(self, mock_k8s):
        import src.plugins.pod_logs as module

        with patch.object(module, "config", _mock_config()):
            from src.plugins.pod_logs import PodLogsPlugin

            v1 = mock_k8s["v1"]
            v1.list_namespaced_pod.return_value.items = [_make_pod("silent-pod", "default")]
            v1.read_namespaced_pod_log.return_value = ""

            findings = PodLogsPlugin().run()

        assert findings == []


# ---------------------------------------------------------------------------
# run() — error handling on list_namespaced_pod
# ---------------------------------------------------------------------------

class TestRunListPodsErrors:
    def test_401_on_list_returns_early(self, mock_k8s):
        import src.plugins.pod_logs as module

        with patch.object(module, "config", _mock_config(namespaces=["ns-a", "ns-b"])):
            from src.plugins.pod_logs import PodLogsPlugin

            mock_k8s["v1"].list_namespaced_pod.side_effect = _api_exception(401)

            findings = PodLogsPlugin().run()

        assert findings == []
        assert mock_k8s["v1"].list_namespaced_pod.call_count == 1

    def test_403_on_list_returns_early(self, mock_k8s):
        import src.plugins.pod_logs as module

        with patch.object(module, "config", _mock_config(namespaces=["ns-a", "ns-b"])):
            from src.plugins.pod_logs import PodLogsPlugin

            mock_k8s["v1"].list_namespaced_pod.side_effect = _api_exception(403)

            findings = PodLogsPlugin().run()

        assert findings == []
        assert mock_k8s["v1"].list_namespaced_pod.call_count == 1

    def test_other_api_error_on_list_skips_namespace(self, mock_k8s):
        import src.plugins.pod_logs as module

        mock_cfg = _mock_config(namespaces=["bad-ns", "good-ns"])
        with patch.object(module, "config", mock_cfg):
            from src.plugins.pod_logs import PodLogsPlugin

            v1 = mock_k8s["v1"]
            v1.list_namespaced_pod.side_effect = [
                _api_exception(500),
                MagicMock(items=[_make_pod("pod-1", "good-ns")]),
            ]
            v1.read_namespaced_pod_log.return_value = "log"

            findings = PodLogsPlugin().run()

        assert len(findings) == 1
        assert findings[0].namespace == "good-ns"


# ---------------------------------------------------------------------------
# run() — error handling on read_namespaced_pod_log
# ---------------------------------------------------------------------------

class TestRunReadLogsErrors:
    def test_404_skips_pod_continues(self, mock_k8s):
        import src.plugins.pod_logs as module

        with patch.object(module, "config", _mock_config()):
            from src.plugins.pod_logs import PodLogsPlugin

            v1 = mock_k8s["v1"]
            v1.list_namespaced_pod.return_value.items = [
                _make_pod("gone-pod", "default"),
                _make_pod("live-pod", "default"),
            ]
            v1.read_namespaced_pod_log.side_effect = [
                _api_exception(404),
                "live logs",
            ]

            findings = PodLogsPlugin().run()

        assert len(findings) == 1
        assert findings[0].resource == "live-pod"

    def test_401_on_read_returns_early(self, mock_k8s):
        import src.plugins.pod_logs as module

        with patch.object(module, "config", _mock_config()):
            from src.plugins.pod_logs import PodLogsPlugin

            v1 = mock_k8s["v1"]
            v1.list_namespaced_pod.return_value.items = [_make_pod("pod-1", "default")]
            v1.read_namespaced_pod_log.side_effect = _api_exception(401)

            findings = PodLogsPlugin().run()

        assert findings == []

    def test_unexpected_exception_skips_pod(self, mock_k8s):
        import src.plugins.pod_logs as module

        with patch.object(module, "config", _mock_config()):
            from src.plugins.pod_logs import PodLogsPlugin

            v1 = mock_k8s["v1"]
            v1.list_namespaced_pod.return_value.items = [
                _make_pod("crashy-pod", "default"),
                _make_pod("ok-pod", "default"),
            ]
            v1.read_namespaced_pod_log.side_effect = [
                RuntimeError("connection reset"),
                "ok logs",
            ]

            findings = PodLogsPlugin().run()

        assert len(findings) == 1
        assert findings[0].resource == "ok-pod"
