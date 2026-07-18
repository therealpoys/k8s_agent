# Prompt — Schritt 15: K8sEventsPlugin

## Kontext

Schritt 14 ist abgeschlossen. Vier Plugins laufen: `pod_logs` (core), `trivy`, `falco`, `prometheus`
(optional). `pod_logs.py` liest bereits Events *pro Pod* als Kontext (`_get_pod_events()`), aber nur
für Pods die auch tatsächlich existieren und durchlaufen werden — Events für andere Objekttypen
(Deployment, ReplicaSet, Node, PVC, ...) sowie Events für Pods die z.B. nie gestartet sind
(`FailedScheduling`, `FailedMount`) gehen verloren.

`project-overview.md` listet `k8s_events` als eigenständiges **Core-Plugin** (`kubectl get events`)
neben `pod_logs`. Dieser Schritt schließt diese Lücke: ein eigenständiges Plugin das alle
Warning-Events der konfigurierten Namespaces liest, unabhängig vom Objekttyp.

**RBAC:** `events: list/get` ist bereits cluster-weit in der ClusterRole vorhanden (Schritt 11) —
keine Helm-Änderung nötig.

---

## Aufgabe

### 1. `src/plugins/k8s_events.py` (neue Datei)

```python
import logging
from datetime import datetime, timezone

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException

from src.config import config
from src.models import Finding
from src.plugins.base import BasePlugin

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
                    raw={
                        "kind": kind,
                        "name": name,
                        "reason": reason,
                        "count": count,
                        "type": event.type,
                        "component": obj.field_path or "",
                        "reporting_component": event.reporting_component or event.source.component if event.source else "",
                    },
                )
            )

        return findings
```

**Designentscheidungen:**
- `field_selector="type=Warning"` filtert serverseitig — kein Client-seitiges Post-Filtering nötig
  für `Normal`-Events (Rauschen wie `Scheduled`, `Pulled`, `Started`)
- Dedup nach `(kind, name, reason)`: verhindert Flooding wenn z.B. `FailedMount` 20× für denselben
  Pod feuert; `count` wird über alle Vorkommen summiert (K8s selbst dedupliziert bereits serverseitig
  über `event.count`, hier zusätzlich über mehrere Event-Objekte mit gleichem Grund)
- `resource` nutzt `involvedObject.kind/name` statt nur `pod/name` — deckt Deployment/ReplicaSet/
  Node/PVC/etc. ab, nicht nur Pods
- Severity fest `"HIGH"` (analog zu `FalcoPlugin`s `Warning`-Mapping) — Events sind bereits
  server-seitig auf `type=Warning` gefiltert, eine weitere Abstufung bringt ohne semantische
  Analyse keinen Mehrwert
- Kein Fallback auf `Normal`-Events — die sind für Anomalie-Erkennung nicht relevant

---

### 2. `src/plugins/__init__.py` — Plugin registrieren

```python
from src.plugins.pod_logs import PodLogsPlugin
from src.plugins.k8s_events import K8sEventsPlugin
from src.plugins.trivy import TrivyPlugin
from src.plugins.falco import FalcoPlugin
from src.plugins.prometheus import PrometheusPlugin

PLUGIN_REGISTRY: dict[str, type] = {
    "pod_logs": PodLogsPlugin,
    "k8s_events": K8sEventsPlugin,
    "trivy": TrivyPlugin,
    "falco": FalcoPlugin,
    "prometheus": PrometheusPlugin,
}
```

---

### 3. `config.yaml.example` — als Core-Plugin ergänzen

```yaml
plugins:
  core:
    - pod_logs        # immer aktiv
    - k8s_events       # immer aktiv
  optional:
    trivy: false
    falco: false
    prometheus: false
```

---

### 4. `deploy/helm/k8s-agent/values.yaml` — Core-Liste ergänzen

```yaml
agentConfig:
  plugins:
    core:
      - pod_logs
      - k8s_events
    optional:
      trivy: false
      falco: false
      prometheus: false
```

---

### 5. `src/analyzer.py` — dedizierter Formatter

```python
def _format_k8s_events_finding(i: int, f: Finding) -> str:
    raw = f.raw or {}
    return "\n".join(
        [
            f"Finding #{i} [{f.severity.upper()}] (K8s Event)",
            f"Resource: {f.resource} (namespace: {f.namespace})",
            f"Reason: {raw.get('reason', '?')} | Count: {raw.get('count', 1)}",
            f.message,
        ]
    )
```

In `_FINDING_FORMATTERS` ergänzen:

```python
_FINDING_FORMATTERS = {
    "pod_logs": _format_pod_logs_finding,
    "k8s_events": _format_k8s_events_finding,
    "prometheus": _format_prometheus_finding,
    "trivy": _format_trivy_finding,
    "falco": _format_falco_finding,
}
```

---

## Tests

### `tests/test_k8s_events_plugin.py` (neue Datei)

Alle Tests mocken `kubernetes.client.CoreV1Api` und `k8s_config.load_incluster_config`.

- `test_run_returns_empty_when_no_events`: `list_namespaced_event` gibt 0 Items → `[]`
- `test_run_returns_empty_on_403`: `ApiException(status=403)` → `[]`, error-Log
- `test_run_returns_empty_on_404_namespace`: `ApiException(status=404)` → `[]`, debug-Log
- `test_run_queries_all_configured_namespaces`: `config.namespaces = ["a", "b"]` → `list_namespaced_event`
  wird für beide Namespaces aufgerufen
- `test_events_to_findings_maps_kind_and_name`: `involvedObject.kind="Deployment"`,
  `name="my-app"` → `resource="deployment/my-app"`
- `test_events_to_findings_deduplicates_by_kind_name_reason`: 3 Events gleiches
  `(kind, name, reason)` mit `count=1` je → 1 Finding mit `count=3`
- `test_events_to_findings_sums_count_field`: 2 Events gleicher Gruppe mit `count=5` und `count=2`
  → Finding mit `count=7`
- `test_events_to_findings_separate_groups_by_reason`: gleicher Pod, unterschiedliche `reason` →
  2 Findings
- `test_finding_severity_always_high`: beliebiges Event → `severity="HIGH"`
- `test_finding_message_includes_reason_and_message`: `reason="FailedMount"`,
  `message="unable to mount volume"` → beides im `message`-String
- `test_run_aggregates_across_namespaces`: Events in 2 Namespaces → Findings aus beiden im Ergebnis

### `tests/test_analyzer.py` — `_format_k8s_events_finding` Test ergänzen

- `test_format_k8s_events_finding_includes_reason_and_count`

---

## Done when

```yaml
# config.yaml
plugins:
  core:
    - pod_logs
    - k8s_events
```

```bash
python agent.py
```

gibt `[HIGH]`-Findings für Warning-Events aus (z.B. `FailedScheduling`, `BackOff`,
`FailedMount`), dedupliziert nach `(kind, name, reason)`, für alle konfigurierten Namespaces —
auch für Objekte die kein Pod sind.

Alle bestehenden 116 Tests bleiben grün, neue Tests für `K8sEventsPlugin` kommen hinzu.
