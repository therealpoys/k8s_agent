from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.models import Alert, Finding
from src.analyzer import _FALLBACK_PREFIX, _format_k8s_events_finding, _highest_severity, analyze


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
        fingerprint="my-pod",
        identity="my-pod",
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
# _format_k8s_events_finding
# ---------------------------------------------------------------------------

class TestFormatK8sEventsFinding:
    def test_format_k8s_events_finding_includes_reason_and_count(self):
        finding = Finding(
            source="k8s_events",
            namespace="default",
            resource="pod/my-pod",
            severity="warning",
            message="FailedMount: unable to mount volume (3x)",
            timestamp=datetime(2026, 1, 1),
            raw={"reason": "FailedMount", "count": 3},
            fingerprint="Pod:my-pod:FailedMount",
            identity="pod/my-pod",
        )

        result = _format_k8s_events_finding(1, finding)

        assert "FailedMount" in result
        assert "3" in result


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
        assert result.findings[0].fingerprint == findings[0].fingerprint
        assert result.findings[0].recommendation == _FALLBACK_PREFIX + "Check the pod."
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
# analyze — per-finding enrichment (severity + recommendation)
# ---------------------------------------------------------------------------

class TestAnalyzePerFindingEnrichment:
    @patch("src.analyzer._build_llm")
    def test_applies_per_finding_severity_and_recommendation(self, mock_build):
        mock_build.return_value.invoke.return_value = _make_llm_response(
            '{"severity": "warning", "summary": "s", "recommendation": "r", '
            '"findings": [{"index": 1, "severity": "critical", "recommendation": "Bump memory limit."}]}'
        )
        original = _make_finding("info")

        result = analyze([original])

        assert result.summary == "s"
        enriched = result.findings[0]
        assert enriched.severity == "critical"
        assert enriched.recommendation == "Bump memory limit."
        assert enriched.fingerprint == original.fingerprint

    @patch("src.analyzer._build_llm")
    def test_analyze_preserves_identity_field_when_enriching_findings(self, mock_build):
        mock_build.return_value.invoke.return_value = _make_llm_response(
            '{"severity": "warning", "summary": "s", "recommendation": "r", '
            '"findings": [{"index": 1, "severity": "critical", "recommendation": "Bump memory limit."}]}'
        )
        original = _make_finding("info")

        result = analyze([original])

        enriched = result.findings[0]
        assert enriched.identity == original.identity

    @patch("src.analyzer._build_llm")
    def test_out_of_range_index_is_ignored(self, mock_build):
        mock_build.return_value.invoke.return_value = _make_llm_response(
            '{"severity": "warning", "summary": "s", "recommendation": "r", '
            '"findings": [{"index": 99, "severity": "critical", "recommendation": "n/a"}]}'
        )
        original = _make_finding("info")

        result = analyze([original])

        assert result.summary == "s"
        assert result.findings[0].fingerprint == original.fingerprint
        assert result.findings[0].severity == original.severity
        assert result.findings[0].recommendation == _FALLBACK_PREFIX + "r"


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
# analyze — fallback recommendation for incomplete LLM responses
# ---------------------------------------------------------------------------

class TestAnalyzeFallbackRecommendation:
    @patch("src.analyzer._build_llm")
    def test_finding_without_llm_entry_gets_fallback_recommendation(self, mock_build):
        mock_build.return_value.invoke.return_value = _make_llm_response(
            '{"severity": "warning", "summary": "s", "recommendation": "Restart the pod.", '
            '"findings": [{"index": 1, "severity": "warning", "recommendation": "Bump memory limit."}]}'
        )
        findings = [_make_finding("warning"), _make_finding("critical")]

        result = analyze(findings)

        assert result.findings[0].recommendation == "Bump memory limit."
        assert result.findings[1].recommendation == _FALLBACK_PREFIX + "Restart the pod."

    @patch("src.analyzer._build_llm")
    def test_finding_with_empty_recommendation_string_gets_fallback(self, mock_build):
        mock_build.return_value.invoke.return_value = _make_llm_response(
            '{"severity": "warning", "summary": "s", "recommendation": "Restart the pod.", '
            '"findings": [{"index": 1, "severity": "warning", "recommendation": ""}]}'
        )

        result = analyze([_make_finding("warning")])

        assert result.findings[0].recommendation == _FALLBACK_PREFIX + "Restart the pod."

    @patch("src.analyzer._build_llm")
    def test_finding_with_explicit_recommendation_keeps_it(self, mock_build):
        mock_build.return_value.invoke.return_value = _make_llm_response(
            '{"severity": "warning", "summary": "s", "recommendation": "Restart the pod.", '
            '"findings": [{"index": 1, "severity": "warning", "recommendation": "Bump memory limit."}]}'
        )

        result = analyze([_make_finding("warning")])

        assert result.findings[0].recommendation == "Bump memory limit."

    @patch("src.analyzer._build_llm")
    def test_degraded_mode_does_not_apply_fallback_text(self, mock_build):
        mock_build.return_value.invoke.side_effect = Exception("timeout")

        result = analyze([_make_finding("warning")])

        assert result.findings[0].recommendation is None


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
