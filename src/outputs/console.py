import logging
from src.models import Alert

logger = logging.getLogger(__name__)

_SEPARATOR = "━" * 50


def send(alert: Alert) -> None:
    timestamp = alert.generated_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    severity = alert.severity.upper()

    lines = [
        _SEPARATOR,
        f"[{severity}] K8s Observability Alert",
        f"Generated: {timestamp}",
        _SEPARATOR,
        "",
        "Summary:",
        f"  {alert.summary}",
        "",
        "Recommendation:",
        f"  {alert.recommendation}",
        "",
    ]

    if not alert.findings:
        lines.append("No findings")
    else:
        lines.append(f"Findings ({len(alert.findings)}):")
        for i, finding in enumerate(alert.findings, start=1):
            finding_ts = finding.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            msg = finding.message
            if msg.startswith("b'") or msg.startswith('b"'):
                msg = msg[2:-1].replace("\\n", " ").replace("\\'", "'")
            message = msg[:200]
            lines += [
                f"  [{i}] {finding.source} / {finding.namespace} / {finding.resource}",
                f"      Severity: {finding.severity}",
                f"      {finding_ts} | {message}",
            ]
            if finding.recommendation:
                lines.append(f"      → {finding.recommendation}")
            lines.append("")

    lines.append(_SEPARATOR)
    logger.info("\n" + "\n".join(lines))
