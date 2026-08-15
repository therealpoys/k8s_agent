import logging
from datetime import datetime, timezone

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException

from src.config import config
from src.models import Finding
from src.plugins.base import BasePlugin
from src.plugins.identity import stable_name

logger = logging.getLogger(__name__)


class K8sEventsPlugin(BasePlugin):
    name = "k8s_events"

    def __init__(self) -> None:
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()
        self._core = client.CoreV1Api()

    def run(self) -> list[Finding]:
        findings: list[Finding] = []
        for namespace in config.namespaces:
            findings.extend(self._namespace_findings(namespace))
        return findings

    def _namespace_findings(self, namespace: str) -> list[Finding]:
        try:
            events = self._core.list_namespaced_event(
                namespace,
                field_selector="type=Warning",
                timeout_seconds=10,
            ).items
        except ApiException as exc:
            if exc.status in (401, 403):
                logger.error(
                    "Zugriff verweigert beim Abrufen von Events in Namespace '%s': %s",
                    namespace, exc,
                )
            elif exc.status == 404:
                logger.debug("Namespace '%s' nicht gefunden", namespace)
            else:
                logger.warning(
                    "Fehler beim Abrufen von Events in Namespace '%s': %s", namespace, exc
                )
            return []

        return self._events_to_findings(events, namespace)

    def _events_to_findings(self, events: list, namespace: str) -> list[Finding]:
        # Dedup nach (kind, name, reason) — count summieren statt einmal pro Wiederholung melden
        grouped: dict[tuple[str, str, str], dict] = {}
        for event in events:
            obj = event.involved_object
            key = (obj.kind or "unknown", obj.name or "unknown", event.reason or "unknown")
            count = event.count or 1
            if key not in grouped:
                grouped[key] = {"event": event, "count": 0}
            grouped[key]["count"] += count

        findings: list[Finding] = []
        for (kind, name, reason), data in grouped.items():
            event = data["event"]
            count = data["count"]
            obj = event.involved_object

            timestamp = event.last_timestamp or event.event_time or datetime.now(timezone.utc)

            findings.append(
                Finding(
                    source=self.name,
                    namespace=namespace,
                    resource=f"{kind.lower()}/{name}",
                    severity="HIGH",
                    message=f"{reason}: {event.message} ({count}x)",
                    timestamp=timestamp,
                    fingerprint=f"{kind}:{stable_name(name)}:{reason}",
                    identity=f"{kind.lower()}/{stable_name(name)}",
                    raw={
                        "kind": kind,
                        "name": name,
                        "reason": reason,
                        "count": count,
                        "type": event.type,
                        "component": obj.field_path or "",
                        "reporting_component": event.reporting_component or (event.source.component if event.source else ""),
                    },
                )
            )

        return findings
