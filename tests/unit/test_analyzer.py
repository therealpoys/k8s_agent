from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.models import Alert, Finding
from src.analyzer import _highest_severity, analyze


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_finding(severity: str) -> Finding:
    return Finding(
        source="pod_logs",
        namespace="default",
        resource="my-pod",
        severity=severity,
        message="test message",
        timestamp=datetime(2026, 1, 1),
        raw=None,
    )


def _make_llm_response(content: str) -> MagicMock:
    response = MagicMock()
    response.content = content
    return response


# ---------------------------------------------------------------------------
# _highest_severity
# ---------------------------------------------------------------------------

class TestHighestSeverity:
    def test_empty_list_returns_info(self):
        assert _highest_severity([]) == "info"

    def test_single_info(self):
        assert _highest_severity([_make_finding("info")]) == "info"

    def test_single_critical(self):
        assert _highest_severity([_make_finding("critical")]) == "critical"

    def test_mixed_returns_highest(self):
        findings = [_make_finding("info"), _make_finding("critical"), _make_finding("warning")]
        assert _highest_severity(findings) == "critical"

    def test_warning_beats_info(self):
        findings = [_make_finding("info"), _make_finding("warning")]
        assert _highest_severity(findings) == "warning"

    def test_unknown_severity_ignored(self):
        findings = [_make_finding("unknown"), _make_finding("info")]
        assert _highest_severity(findings) == "info"

    def test_all_unknown_returns_info(self):
        findings = [_make_finding("bogus"), _make_finding("also-bogus")]
        assert _highest_severity(findings) == "info"


# ---------------------------------------------------------------------------
# analyze — happy path
# ---------------------------------------------------------------------------

VALID_JSON = '{"severity": "warning", "summary": "Something is off.", "recommendation": "Check the pod."}'


class TestAnalyzeHappyPath:
    @patch("src.analyzer._build_llm")
    def test_returns_alert_with_llm_values(self, mock_build):
        mock_build.return_value.invoke.return_value = _make_llm_response(VALID_JSON)
        findings = [_make_finding("warning")]

        result = analyze(findings)

        assert isinstance(result, Alert)
        assert result.severity == "warning"
        assert result.summary == "Something is off."
        assert result.recommendation == "Check the pod."
        assert result.findings == findings
        assert isinstance(result.generated_at, datetime)

    @patch("src.analyzer._build_llm")
    def test_empty_findings_passes_no_findings_text(self, mock_build):
        mock_build.return_value.invoke.return_value = _make_llm_response(
            '{"severity": "info", "summary": "All clear.", "recommendation": "No action needed."}'
        )

        result = analyze([])

        assert result.severity == "info"
        assert result.findings == []

    @patch("src.analyzer._build_llm")
    def test_critical_severity_preserved(self, mock_build):
        mock_build.return_value.invoke.return_value = _make_llm_response(
            '{"severity": "critical", "summary": "Cluster is on fire.", "recommendation": "Restart everything."}'
        )

        result = analyze([_make_finding("critical")])
        assert result.severity == "critical"


# ---------------------------------------------------------------------------
# analyze — invalid severity fallback
# ---------------------------------------------------------------------------

class TestAnalyzeInvalidSeverity:
    @patch("src.analyzer._build_llm")
    def test_invalid_severity_defaults_to_warning(self, mock_build):
        mock_build.return_value.invoke.return_value = _make_llm_response(
            '{"severity": "unknown", "summary": "Hmm.", "recommendation": "Do something."}'
        )

        result = analyze([_make_finding("info")])
        assert result.severity == "warning"

    @patch("src.analyzer._build_llm")
    def test_invalid_severity_logs_warning(self, mock_build, caplog):
        import logging
        mock_build.return_value.invoke.return_value = _make_llm_response(
            '{"severity": "extreme", "summary": "Oops.", "recommendation": "Panic."}'
        )

        with caplog.at_level(logging.WARNING, logger="src.analyzer"):
            analyze([])

        assert any("invalid severity" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# analyze — degraded mode
# ---------------------------------------------------------------------------

class TestAnalyzeDegradedMode:
    @patch("src.analyzer._build_llm")
    def test_json_decode_error_returns_degraded_alert(self, mock_build):
        mock_build.return_value.invoke.return_value = _make_llm_response("not valid json {{{")

        result = analyze([_make_finding("critical")])

        assert result.severity == "critical"
        assert result.summary == "LLM analysis unavailable"
        assert result.recommendation == "Check logs manually"

    @patch("src.analyzer._build_llm")
    def test_llm_exception_returns_degraded_alert(self, mock_build):
        mock_build.return_value.invoke.side_effect = RuntimeError("connection refused")

        result = analyze([_make_finding("warning")])

        assert result.severity == "warning"
        assert result.summary == "LLM analysis unavailable"

    @patch("src.analyzer._build_llm")
    def test_degraded_mode_does_not_raise(self, mock_build):
        mock_build.return_value.invoke.side_effect = Exception("any error")

        result = analyze([])  # must not raise
        assert isinstance(result, Alert)

    @patch("src.analyzer._build_llm")
    def test_missing_json_fields_triggers_degraded(self, mock_build):
        mock_build.return_value.invoke.return_value = _make_llm_response(
            '{"severity": "info"}'  # missing summary and recommendation
        )

        result = analyze([_make_finding("warning")])

        assert result.summary == "LLM analysis unavailable"

    @patch("src.analyzer._build_llm")
    def test_degraded_uses_highest_severity_from_findings(self, mock_build):
        mock_build.return_value.invoke.side_effect = Exception("timeout")
        findings = [_make_finding("info"), _make_finding("critical"), _make_finding("warning")]

        result = analyze(findings)
        assert result.severity == "critical"

    @patch("src.analyzer._build_llm")
    def test_degraded_with_empty_findings_uses_info(self, mock_build):
        mock_build.return_value.invoke.side_effect = Exception("timeout")

        result = analyze([])
        assert result.severity == "info"
