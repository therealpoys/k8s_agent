import logging
from datetime import datetime, timezone

import requests

from src.config import config
from src.models import Finding
from src.plugins.base import BasePlugin
from src.plugins.identity import stable_name

logger = logging.getLogger(__name__)

# Prometheus-Alert-Severity-Label-Konvention (kube-prometheus-stack Default-Regeln)
_SEVERITY_MAP: dict[str, str] = {
    "critical": "CRITICAL",
    "warning": "HIGH",
    "info": "info",
}

_REQUEST_TIMEOUT_SECONDS = 10


class PrometheusPlugin(BasePlugin):
    name = "prometheus"

    def run(self) -> list[Finding]:
        try:
            response = requests.get(
                f"{config.prometheus_url}/api/v1/alerts",
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning(
                "Prometheus unter %s nicht erreichbar: %s", config.prometheus_url, exc
            )
            return []

        try:
            data = response.json()
        except ValueError:
            logger.warning("Prometheus-Antwort von %s ist kein valides JSON", config.prometheus_url)
            return []

        alerts = data.get("data", {}).get("alerts", [])
        return self._alerts_to_findings(alerts)

    def _alerts_to_findings(self, alerts: list[dict]) -> list[Finding]:
        findings: list[Finding] = []
        for alert in alerts:
            if alert.get("state") != "firing":
                continue  # "pending" hat die for:-Dauer noch nicht überschritten

            labels = alert.get("labels", {})
            annotations = alert.get("annotations", {})

            severity_label = labels.get("severity", "").lower()
            severity = _SEVERITY_MAP.get(severity_label, "HIGH")

            alertname = labels.get("alertname", "unknown")
            namespace = labels.get("namespace", "")
            pod = labels.get("pod", "")

            resource = f"pod/{pod}" if pod else labels.get("instance", "unknown")
            fingerprint_resource = f"pod/{stable_name(pod)}" if pod else labels.get("instance", "unknown")
            message = annotations.get("summary") or annotations.get("description") or alertname

            try:
                timestamp = datetime.fromisoformat(alert["activeAt"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                timestamp = datetime.now(timezone.utc)

            findings.append(
                Finding(
                    source=self.name,
                    namespace=namespace,
                    resource=resource,
                    severity=severity,
                    message=f"{alertname}: {message}",
                    timestamp=timestamp,
                    fingerprint=f"{alertname}:{fingerprint_resource}",
                    raw={
                        "alertname": alertname,
                        "labels": labels,
                        "annotations": annotations,
                        "state": alert.get("state"),
                    },
                )
            )

        return findings
