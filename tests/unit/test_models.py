from datetime import datetime
from src.models import Finding, Alert


def _finding(**kwargs) -> Finding:
    defaults = dict(
        source="test-plugin",
        namespace="default",
        resource="pod/my-pod",
        severity="warning",
        message="something went wrong",
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        raw=None,
    )
    return Finding(**{**defaults, **kwargs})


def _alert(**kwargs) -> Alert:
    defaults = dict(
        findings=[_finding()],
        severity="warning",
        summary="One issue found",
        recommendation="Check the pod logs",
        generated_at=datetime(2026, 1, 1, 12, 0, 0),
    )
    return Alert(**{**defaults, **kwargs})


class TestFinding:
    def test_fields_stored(self):
        ts = datetime(2026, 1, 1)
        f = _finding(timestamp=ts, raw={"key": "val"})
        assert f.source == "test-plugin"
        assert f.namespace == "default"
        assert f.resource == "pod/my-pod"
        assert f.severity == "warning"
        assert f.message == "something went wrong"
        assert f.timestamp == ts
        assert f.raw == {"key": "val"}

    def test_raw_can_be_none(self):
        f = _finding(raw=None)
        assert f.raw is None

    def test_two_findings_are_equal_when_fields_match(self):
        ts = datetime(2026, 1, 1)
        a = _finding(timestamp=ts)
        b = _finding(timestamp=ts)
        assert a == b

    def test_findings_differ_on_severity(self):
        ts = datetime(2026, 1, 1)
        assert _finding(severity="warning", timestamp=ts) != _finding(severity="critical", timestamp=ts)


class TestAlert:
    def test_fields_stored(self):
        f = _finding()
        a = _alert(findings=[f], severity="critical", summary="bad", recommendation="fix it")
        assert a.findings == [f]
        assert a.severity == "critical"
        assert a.summary == "bad"
        assert a.recommendation == "fix it"

    def test_empty_findings_list_allowed(self):
        a = _alert(findings=[])
        assert a.findings == []

    def test_multiple_findings(self):
        findings = [_finding(resource=f"pod/{i}") for i in range(3)]
        a = _alert(findings=findings)
        assert len(a.findings) == 3
