import logging
from datetime import datetime
from unittest.mock import patch

import pytest

from src.models import Alert, Finding
from src.outputs.console import send


def _make_finding(
    severity: str = "warning",
    message: str = "test message",
    source: str = "pod_logs",
    namespace: str = "default",
    resource: str = "my-pod",
) -> Finding:
    return Finding(
        source=source,
        namespace=namespace,
        resource=resource,
        severity=severity,
        message=message,
        timestamp=datetime(2024, 1, 15, 10, 29, 45),
        raw=None,
    )


def _make_alert(findings=None, severity="warning") -> Alert:
    return Alert(
        findings=findings if findings is not None else [],
        severity=severity,
        summary="Test summary.",
        recommendation="Test recommendation.",
        generated_at=datetime(2024, 1, 15, 10, 30, 0),
    )


class TestSend:
    def test_calls_logger_info(self):
        alert = _make_alert([_make_finding()])
        with patch("src.outputs.console.logger") as mock_logger:
            send(alert)
        mock_logger.info.assert_called_once()

    def test_severity_uppercase_in_header(self):
        alert = _make_alert([_make_finding()], severity="warning")
        with patch("src.outputs.console.logger") as mock_logger:
            send(alert)
        output = mock_logger.info.call_args[0][0]
        assert "[WARNING]" in output

    def test_critical_severity_uppercase(self):
        alert = _make_alert([_make_finding()], severity="critical")
        with patch("src.outputs.console.logger") as mock_logger:
            send(alert)
        output = mock_logger.info.call_args[0][0]
        assert "[CRITICAL]" in output

    def test_generated_at_format(self):
        alert = _make_alert()
        with patch("src.outputs.console.logger") as mock_logger:
            send(alert)
        output = mock_logger.info.call_args[0][0]
        assert "2024-01-15 10:30:00 UTC" in output

    def test_summary_and_recommendation_present(self):
        alert = _make_alert()
        with patch("src.outputs.console.logger") as mock_logger:
            send(alert)
        output = mock_logger.info.call_args[0][0]
        assert "Test summary." in output
        assert "Test recommendation." in output

    def test_no_findings_shows_no_findings_text(self):
        alert = _make_alert(findings=[])
        with patch("src.outputs.console.logger") as mock_logger:
            send(alert)
        output = mock_logger.info.call_args[0][0]
        assert "No findings" in output
        assert "Findings (" not in output

    def test_findings_numbered_and_formatted(self):
        alert = _make_alert(findings=[
            _make_finding(source="pod_logs", namespace="default", resource="my-pod"),
        ])
        with patch("src.outputs.console.logger") as mock_logger:
            send(alert)
        output = mock_logger.info.call_args[0][0]
        assert "[1] pod_logs / default / my-pod" in output
        assert "Findings (1):" in output

    def test_multiple_findings_numbered(self):
        alert = _make_alert(findings=[
            _make_finding(resource="pod-a"),
            _make_finding(resource="pod-b"),
        ])
        with patch("src.outputs.console.logger") as mock_logger:
            send(alert)
        output = mock_logger.info.call_args[0][0]
        assert "[1]" in output
        assert "[2]" in output
        assert "Findings (2):" in output

    def test_message_truncated_to_200_chars(self):
        long_message = "x" * 300
        alert = _make_alert(findings=[_make_finding(message=long_message)])
        with patch("src.outputs.console.logger") as mock_logger:
            send(alert)
        output = mock_logger.info.call_args[0][0]
        assert "x" * 200 in output
        assert "x" * 201 not in output

    def test_message_under_200_chars_not_truncated(self):
        short_message = "short message"
        alert = _make_alert(findings=[_make_finding(message=short_message)])
        with patch("src.outputs.console.logger") as mock_logger:
            send(alert)
        output = mock_logger.info.call_args[0][0]
        assert short_message in output

    def test_separator_present(self):
        alert = _make_alert()
        with patch("src.outputs.console.logger") as mock_logger:
            send(alert)
        output = mock_logger.info.call_args[0][0]
        assert "━" * 50 in output

    def test_finding_timestamp_formatted(self):
        alert = _make_alert(findings=[_make_finding()])
        with patch("src.outputs.console.logger") as mock_logger:
            send(alert)
        output = mock_logger.info.call_args[0][0]
        assert "2024-01-15 10:29:45" in output
