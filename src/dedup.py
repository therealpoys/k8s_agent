import hashlib
import logging
from datetime import datetime, timedelta, timezone

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException

from src.config import config
from src.models import Finding

logger = logging.getLogger(__name__)

_GROUP = "k8s-agent.dev"
_VERSION = "v1alpha1"
_PLURAL = "seenfindings"
_MESSAGE_MAX_CHARS = 1000


def _truncate(text: str | None, limit: int = _MESSAGE_MAX_CHARS) -> str:
    if not text:
        return ""
    return text[:limit]


class Deduplicator:
    def __init__(self) -> None:
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()
        self._api = client.CustomObjectsApi()

    def filter_new(self, findings: list[Finding]) -> list[Finding]:
        new: list[Finding] = []
        for finding in findings:
            name = _cr_name(finding)
            try:
                existing = self._api.get_namespaced_custom_object(
                    _GROUP, _VERSION, finding.namespace, _PLURAL, name
                )
            except ApiException as exc:
                if exc.status == 404:
                    self._create(finding, name)
                    new.append(finding)
                else:
                    logger.warning(
                        "Dedup-Check für %s fehlgeschlagen (%s) — Finding wird trotzdem gemeldet",
                        name, exc,
                    )
                    new.append(finding)  # fail open: nie Findings wegen Dedup-Infra verschlucken
                continue
            self._touch(finding, name, existing)
        return new

    def update_recommendations(self, findings: list[Finding]) -> None:
        for finding in findings:
            if not finding.recommendation:
                continue
            name = _cr_name(finding)
            patch = {"spec": {"recommendation": finding.recommendation}}
            try:
                self._api.patch_namespaced_custom_object(
                    _GROUP, _VERSION, finding.namespace, _PLURAL, name, patch
                )
            except ApiException as exc:
                logger.warning(
                    "SeenFinding-CR %s konnte nicht mit Recommendation aktualisiert werden: %s",
                    name, exc,
                )

    def cleanup_resolved(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=config.dedup_lookback_minutes)
        for namespace in config.namespaces:
            try:
                items = self._api.list_namespaced_custom_object(
                    _GROUP, _VERSION, namespace, _PLURAL
                ).get("items", [])
            except ApiException as exc:
                logger.warning("Dedup-Cleanup in Namespace %s fehlgeschlagen: %s", namespace, exc)
                continue
            for item in items:
                last_seen = datetime.fromisoformat(item["spec"]["lastSeen"])
                if last_seen < cutoff:
                    self._delete(namespace, item["metadata"]["name"])

    def _create(self, finding: Finding, name: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        body = {
            "apiVersion": f"{_GROUP}/{_VERSION}",
            "kind": "SeenFinding",
            "metadata": {"name": name},
            "spec": {
                "source": finding.source,
                "resource": finding.resource,
                "fingerprint": finding.fingerprint,
                "severity": finding.severity,
                "message": _truncate(finding.message),
                "recommendation": finding.recommendation or "",
                "firstSeen": now,
                "lastSeen": now,
                "count": 1,
            },
        }
        try:
            self._api.create_namespaced_custom_object(
                _GROUP, _VERSION, finding.namespace, _PLURAL, body
            )
        except ApiException as exc:
            logger.warning("SeenFinding-CR %s konnte nicht angelegt werden: %s", name, exc)

    def _touch(self, finding: Finding, name: str, existing: dict) -> None:
        spec = existing.get("spec", {})
        patch = {
            "spec": {
                "lastSeen": datetime.now(timezone.utc).isoformat(),
                "count": spec.get("count", 0) + 1,
                "message": _truncate(finding.message),
            }
        }
        try:
            self._api.patch_namespaced_custom_object(
                _GROUP, _VERSION, finding.namespace, _PLURAL, name, patch
            )
        except ApiException as exc:
            logger.warning("SeenFinding-CR %s konnte nicht aktualisiert werden: %s", name, exc)

    def _delete(self, namespace: str, name: str) -> None:
        try:
            self._api.delete_namespaced_custom_object(
                _GROUP, _VERSION, namespace, _PLURAL, name
            )
        except ApiException as exc:
            if exc.status != 404:
                logger.warning("SeenFinding-CR %s konnte nicht gelöscht werden: %s", name, exc)


def _cr_name(finding: Finding) -> str:
    raw = f"{finding.source}|{finding.namespace}|{finding.fingerprint}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]
