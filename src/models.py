from dataclasses import dataclass
from datetime import datetime


@dataclass
class Finding:
    source: str
    namespace: str
    resource: str
    severity: str
    message: str
    timestamp: datetime
    raw: dict | None
    recommendation: str | None = None


@dataclass
class Alert:
    findings: list[Finding]
    severity: str
    summary: str
    recommendation: str
    generated_at: datetime
