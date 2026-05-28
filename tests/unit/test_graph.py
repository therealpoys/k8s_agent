from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.models import Alert, Finding
from src.graph import _collect_findings, _analyze_findings, _send_output, build_graph


def _make_finding() -> Finding:
    return Finding(
        source="pod_logs",
        namespace="default",
        resource="my-pod",
        severity="warning",
        message="Something went wrong",
        timestamp=datetime(2026, 1, 1),
        raw=None,
    )


def _make_alert(findings: list[Finding]) -> Alert:
    return Alert(
        findings=findings,
        severity="warning",
        summary="Test summary",
        recommendation="Check logs",
        generated_at=datetime(2026, 1, 1),
    )


# ---------------------------------------------------------------------------
# _collect_findings
# ---------------------------------------------------------------------------

class TestCollectFindings:
    def test_happy_path_returns_findings(self):
        finding = _make_finding()
        mock_plugin = MagicMock()
        mock_plugin.run.return_value = [finding]

        with patch("src.graph.PodLogsPlugin", return_value=mock_plugin):
            result = _collect_findings({})

        assert result == {"findings": [finding]}

    def test_plugin_exception_returns_empty_list(self):
        mock_plugin = MagicMock()
        mock_plugin.run.side_effect = RuntimeError("k8s unreachable")

        with patch("src.graph.PodLogsPlugin", return_value=mock_plugin):
            result = _collect_findings({})

        assert result == {"findings": []}

    def test_plugin_instantiation_error_returns_empty_list(self):
        with patch("src.graph.PodLogsPlugin", side_effect=Exception("no kubeconfig")):
            result = _collect_findings({})

        assert result == {"findings": []}

    def test_empty_findings_returned_as_is(self):
        mock_plugin = MagicMock()
        mock_plugin.run.return_value = []

        with patch("src.graph.PodLogsPlugin", return_value=mock_plugin):
            result = _collect_findings({})

        assert result == {"findings": []}


# ---------------------------------------------------------------------------
# _analyze_findings
# ---------------------------------------------------------------------------

class TestAnalyzeFindings:
    def test_delegates_to_analyzer(self):
        finding = _make_finding()
        alert = _make_alert([finding])
        state = {"findings": [finding], "alert": None}

        with patch("src.graph.analyzer.analyze", return_value=alert) as mock_analyze:
            result = _analyze_findings(state)

        mock_analyze.assert_called_once_with([finding])
        assert result == {"alert": alert}

    def test_passes_empty_findings(self):
        alert = _make_alert([])
        state = {"findings": [], "alert": None}

        with patch("src.graph.analyzer.analyze", return_value=alert):
            result = _analyze_findings(state)

        assert result["alert"] is alert


# ---------------------------------------------------------------------------
# _send_output
# ---------------------------------------------------------------------------

class TestSendOutput:
    def test_delegates_to_console(self):
        finding = _make_finding()
        alert = _make_alert([finding])
        state = {"findings": [finding], "alert": alert}

        with patch("src.graph.console.send") as mock_send:
            result = _send_output(state)

        mock_send.assert_called_once_with(alert)
        assert result == {}

    def test_returns_empty_dict(self):
        alert = _make_alert([])
        state = {"findings": [], "alert": alert}

        with patch("src.graph.console.send"):
            result = _send_output(state)

        assert result == {}


# ---------------------------------------------------------------------------
# build_graph
# ---------------------------------------------------------------------------

class TestBuildGraph:
    def test_compiles_without_error(self):
        graph = build_graph()
        assert graph is not None

    def test_graph_is_invocable(self):
        finding = _make_finding()
        alert = _make_alert([finding])

        with (
            patch("src.graph.PodLogsPlugin") as mock_plugin_cls,
            patch("src.graph.analyzer.analyze", return_value=alert),
            patch("src.graph.console.send"),
        ):
            mock_plugin_cls.return_value.run.return_value = [finding]
            graph = build_graph()
            result = graph.invoke({"findings": [], "alert": None})

        assert result["alert"] is alert
        assert result["findings"] == [finding]
