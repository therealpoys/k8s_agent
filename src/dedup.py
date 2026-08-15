import hashlib
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException

from src.config import config
from src.models import Finding
from src.severity import SEVERITY_ORDER

logger = logging.getLogger(__name__)

_GROUP = "k8s-agent.dev"
_VERSION = "v1alpha1"
_PLURAL = "seenfindings"
_MESSAGE_MAX_CHARS = 1000


def _truncate(text: str | None, limit: int = _MESSAGE_MAX_CHARS) -> str:
    if not text:
        return ""
    return text[:limit]


def _highest_severity(entries: list[dict]) -> str:
    return max(
        (e.get("severity", "info") for e in entries),
        key=lambda s: SEVERITY_ORDER.get(s, 0),
        default="info",
    )


class Deduplicator:
    def __init__(self) -> None:
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()
        self._api = client.CustomObjectsApi()

    def filter_new(self, findings: list[Finding]) -> list[Finding]:
        groups: dict[tuple[str, str], list[Finding]] = defaultdict(list)
        for f in findings:
            groups[(f.namespace, f.identity)].append(f)

        new: list[Finding] = []
        for (namespace, identity), group in groups.items():
            if not namespace:
                # Cluster-weite Findings ohne Namespace (z.B. Prometheus-Alerts ohne
                # namespace-Label) lassen sich nicht in einem Namespaced-CRD ablegen —
                # fail open ohne API-Call statt eines von vornherein aussichtslosen Requests.
                new.extend(group)
                continue
            name = _cr_name(namespace, identity)
            try:
                existing = self._api.get_namespaced_custom_object(
                    _GROUP, _VERSION, namespace, _PLURAL, name
                )
            except ApiException as exc:
                if exc.status == 404:
                    self._write(namespace, name, identity, self._merge([], group))
                    new.extend(group)
                else:
                    logger.warning(
                        "Dedup-Check für %s fehlgeschlagen (%s) — Findings werden trotzdem gemeldet",
                        name, exc,
                    )
                    new.extend(group)  # fail open: nie Findings wegen Dedup-Infra verschlucken
                continue

            existing_findings = existing.get("spec", {}).get("findings", [])
            known = {(e["source"], e["fingerprint"]) for e in existing_findings}
            has_new = any((f.source, f.fingerprint) not in known for f in group)

            merged = self._merge(existing_findings, group)
            self._write(namespace, name, identity, merged)

            if has_new:
                new.extend(group)  # voller Kontext: alt + neu für diese Resource

        return new

    def _merge(self, existing: list[dict], group: list[Finding]) -> list[dict]:
        now = datetime.now(timezone.utc).isoformat()
        by_key = {(e["source"], e["fingerprint"]): dict(e) for e in existing}
        for f in group:
            key = (f.source, f.fingerprint)
            entry = by_key.get(key)
            if entry is None:
                by_key[key] = {
                    "source": f.source,
                    "fingerprint": f.fingerprint,
                    "severity": f.severity,
                    "message": _truncate(f.message),
                    "recommendation": f.recommendation or "",
                    "firstSeen": now,
                    "lastSeen": now,
                    "count": 1,
                }
            else:
                entry["lastSeen"] = now
                entry["count"] = entry.get("count", 0) + 1
                entry["message"] = _truncate(f.message)
                entry["severity"] = f.severity
        return list(by_key.values())

    def _write(self, namespace: str, name: str, identity: str, findings: list[dict]) -> None:
        spec = {
            "resource": identity,
            "severity": _highest_severity(findings),
            "lastSeen": max((e["lastSeen"] for e in findings), default=datetime.now(timezone.utc).isoformat()),
            "findingCount": len(findings),
            "findings": findings,
        }
        body = {
            "apiVersion": f"{_GROUP}/{_VERSION}",
            "kind": "SeenFinding",
            "metadata": {"name": name},
            "spec": spec,
        }
        try:
            self._api.patch_namespaced_custom_object(_GROUP, _VERSION, namespace, _PLURAL, name, {"spec": spec})
        except ApiException as exc:
            if exc.status == 404:
                try:
                    self._api.create_namespaced_custom_object(_GROUP, _VERSION, namespace, _PLURAL, body)
                except ApiException as create_exc:
                    logger.warning("SeenFinding-CR %s konnte nicht angelegt werden: %s", name, create_exc)
            else:
                logger.warning("SeenFinding-CR %s konnte nicht aktualisiert werden: %s", name, exc)

    def update_recommendations(self, findings: list[Finding]) -> None:
        groups: dict[tuple[str, str], list[Finding]] = defaultdict(list)
        for f in findings:
            if f.recommendation:
                groups[(f.namespace, f.identity)].append(f)

        for (namespace, identity), group in groups.items():
            if not namespace:
                continue  # kein SeenFinding-CR für Findings ohne Namespace, siehe filter_new
            name = _cr_name(namespace, identity)
            try:
                existing = self._api.get_namespaced_custom_object(
                    _GROUP, _VERSION, namespace, _PLURAL, name
                )
            except ApiException as exc:
                logger.warning(
                    "SeenFinding-CR %s nicht gefunden für Recommendation-Update: %s", name, exc
                )
                continue

            existing_findings = existing.get("spec", {}).get("findings", [])
            by_key = {(e["source"], e["fingerprint"]): e for e in existing_findings}
            for f in group:
                entry = by_key.get((f.source, f.fingerprint))
                if entry is not None:
                    entry["recommendation"] = f.recommendation

            patch = {"spec": {"findings": list(by_key.values())}}
            try:
                self._api.patch_namespaced_custom_object(
                    _GROUP, _VERSION, namespace, _PLURAL, name, patch
                )
            except ApiException as exc:
                logger.warning(
                    "SeenFinding-CR %s konnte nicht mit Recommendations aktualisiert werden: %s",
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
                spec = item.get("spec", {})
                findings = spec.get("findings", [])
                fresh = [e for e in findings if datetime.fromisoformat(e["lastSeen"]) >= cutoff]
                name = item["metadata"]["name"]

                if not fresh:
                    self._delete(namespace, name)
                elif len(fresh) != len(findings):
                    patch = {
                        "spec": {
                            "findings": fresh,
                            "severity": _highest_severity(fresh),
                            "lastSeen": max(e["lastSeen"] for e in fresh),
                            "findingCount": len(fresh),
                        }
                    }
                    try:
                        self._api.patch_namespaced_custom_object(
                            _GROUP, _VERSION, namespace, _PLURAL, name, patch
                        )
                    except ApiException as exc:
                        logger.warning(
                            "Stale Findings in %s konnten nicht entfernt werden: %s", name, exc
                        )

    def _delete(self, namespace: str, name: str) -> None:
        try:
            self._api.delete_namespaced_custom_object(
                _GROUP, _VERSION, namespace, _PLURAL, name
            )
        except ApiException as exc:
            if exc.status != 404:
                logger.warning("SeenFinding-CR %s konnte nicht gelöscht werden: %s", name, exc)


def _cr_name(namespace: str, identity: str) -> str:
    raw = f"{namespace}|{identity}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]
