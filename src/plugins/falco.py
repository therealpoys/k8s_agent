import json
import logging
from datetime import datetime, timezone

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException

from src.config import config
from src.models import Finding
from src.plugins.base import BasePlugin

logger = logging.getLogger(__name__)

_SEVERITY_MAP: dict[str, str] = {
    "Emergency": "CRITICAL",
    "Alert": "CRITICAL",
    "Critical": "CRITICAL",
    "Error": "HIGH",
    "Warning": "HIGH",
}

_FALCO_LABEL_SELECTOR = "app.kubernetes.io/name=falco"


class FalcoPlugin(BasePlugin):
    name = "falco"

    def __init__(self):
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()
        self._core = client.CoreV1Api()

    def run(self) -> list[Finding]:
        namespace = config.falco_namespace
        try:
            pods = self._core.list_namespaced_pod(
                namespace=namespace,
                label_selector=_FALCO_LABEL_SELECTOR,
            )
        except ApiException as exc:
            if exc.status in (401, 403):
                logger.warning(
                    "Kein Zugriff auf Falco-Pods in Namespace %s (HTTP %s)",
                    namespace,
                    exc.status,
                )
            elif exc.status == 404:
                logger.debug("Namespace %s nicht gefunden — Falco installiert?", namespace)
            else:
                logger.error("Fehler beim Lesen der Falco-Pods: %s", exc)
            return []

        if not pods.items:
            logger.debug(
                "Keine Pods mit Label %s in Namespace %s — Falco installiert?",
                _FALCO_LABEL_SELECTOR,
                namespace,
            )
            return []

        raw_events: list[dict] = []
        for pod in pods.items:
            raw_events.extend(self._read_pod_logs(pod.metadata.name, namespace))

        return self._events_to_findings(raw_events, namespace)

    def _read_pod_logs(self, pod_name: str, namespace: str) -> list[dict]:
        try:
            logs = self._core.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                tail_lines=config.log_lines,
            )
        except ApiException as exc:
            logger.warning("Logs von Falco-Pod %s nicht lesbar (HTTP %s)", pod_name, exc.status)
            return []

        events: list[dict] = []
        for line in logs.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                if "rule" in event and "priority" in event:
                    events.append(event)
            except json.JSONDecodeError:
                pass  # Nicht-JSON-Zeilen (Startup-Logs etc.) stillschweigend überspringen
        return events

    def _events_to_findings(self, events: list[dict], namespace: str) -> list[Finding]:
        filtered: dict[str, dict] = {}
        for event in events:
            priority = event.get("priority", "")
            if priority not in _SEVERITY_MAP:
                continue
            rule = event.get("rule", "unknown")
            if rule not in filtered:
                filtered[rule] = {"event": event, "count": 0}
            filtered[rule]["count"] += 1

        findings: list[Finding] = []
        for rule, data in filtered.items():
            event = data["event"]
            count = data["count"]
            severity = _SEVERITY_MAP[event["priority"]]
            fields = event.get("output_fields", {})

            affected_pod = fields.get("k8s.pod.name", "")
            affected_ns = fields.get("k8s.ns.name", namespace)
            process = fields.get("proc.name", "")
            file_path = fields.get("fd.name", "")

            parts = [f"Regel: {rule}"]
            if affected_pod:
                parts.append(f"Pod: {affected_pod}")
            if process:
                parts.append(f"Prozess: {process}")
            if file_path:
                parts.append(f"Datei: {file_path}")
            if count > 1:
                parts.append(f"({count}× in den letzten {config.log_lines} Zeilen)")

            try:
                timestamp = datetime.fromisoformat(
                    event["time"].replace("Z", "+00:00")
                )
            except (KeyError, ValueError):
                timestamp = datetime.now(timezone.utc)

            findings.append(
                Finding(
                    source=self.name,
                    namespace=affected_ns,
                    resource=f"pod/{affected_pod}" if affected_pod else "node/unknown",
                    severity=severity,
                    message=", ".join(parts),
                    timestamp=timestamp,
                    fingerprint=rule,
                    raw={
                        "rule": rule,
                        "priority": event.get("priority"),
                        "count": count,
                        "output": event.get("output", ""),
                        "tags": event.get("tags", []),
                        "output_fields": fields,
                    },
                )
            )

        return findings
