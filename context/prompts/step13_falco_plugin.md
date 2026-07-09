# Prompt — Schritt 13: FalcoPlugin

## Kontext

Schritt 12 ist abgeschlossen. Die Plugin-Registry ist aktiv, `TrivyPlugin` läuft als zweites Plugin.
`config.yaml.example` listet `falco: false` als optionales Plugin — bisher Platzhalter ohne
Implementierung.

Falco ist ein CNCF-Runtime-Security-Tool das Kernel-Syscalls und K8s-Audit-Events gegen
Sicherheitsregeln prüft und Alerts emittiert. Es läuft typischerweise als DaemonSet im
`falco`-Namespace. Mit `json_output: true` (Standard im offiziellen Helm-Chart) schreibt Falco
strukturierte JSON-Events auf stdout — eine pro Zeile.

Dieses Plugin liest diese Log-Zeilen, parst die JSON-Events, filtert nach Severity und erzeugt
Findings die das LLM analysieren kann.

**Voraussetzung:** Falco muss mit `falco.json_output=true` deployed sein (ist Standard-Helm-Default).

---

## Aufgabe

### 1. `src/config.py` — `falco_namespace` ergänzen

`Config` Dataclass bekommt ein neues optionales Feld:

```python
@dataclass
class Config:
    # ... bestehende Felder ...
    falco_namespace: str  # neu
```

In `_load_config()` aus dem `kubernetes`-Block lesen, Default `"falco"`:

```python
falco_namespace=k8s.get("falco_namespace", "falco"),
```

---

### 2. `config.yaml.example` — `falco_namespace` dokumentieren

```yaml
kubernetes:
  namespaces:
    - default
  log_lines: 100
  falco_namespace: falco   # Namespace in dem Falco läuft (für FalcoPlugin)
```

---

### 3. `src/plugins/falco.py` — FalcoPlugin (neue Datei)

```python
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException

from src.config import config
from src.models import Finding
from src.plugins.base import BasePlugin

logger = logging.getLogger(__name__)

# Falco-Prioritäten in absteigender Kritikalität
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
        # Nach Severity filtern und nach Regelname deduplizieren
        # Pro Regel: erstes Event als Repräsentant, Gesamtanzahl mitzählen
        filtered: dict[str, dict] = {}   # rule → {event, count}
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
                    resource=f"pod/{affected_pod}" if affected_pod else f"node/unknown",
                    severity=severity,
                    message=", ".join(parts),
                    timestamp=timestamp,
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
```

**Designentscheidungen:**
- `json_output: true` ist Pflicht auf Falco-Seite (Standard-Helm-Default, kein Workaround)
- Nicht-JSON-Zeilen (Falco-Startup, Kernel-Modul-Load) werden still ignoriert
- Deduplication nach Regelname: verhindert Flooding wenn eine Regel 50× in N Zeilen feuert
- Nur `WARNING` und höher → kein Noise für `Notice`/`Informational`/`Debug`
- `output_fields` wird als `raw` mitgegeben damit das LLM Pod-Name, Prozess etc. sehen kann

---

### 4. `src/plugins/__init__.py` — FalcoPlugin registrieren

```python
from src.plugins.pod_logs import PodLogsPlugin
from src.plugins.trivy import TrivyPlugin
from src.plugins.falco import FalcoPlugin

PLUGIN_REGISTRY: dict[str, type] = {
    "pod_logs": PodLogsPlugin,
    "trivy": TrivyPlugin,
    "falco": FalcoPlugin,
}
```

---

### 5. Helm ClusterRole — Falco-RBAC ergänzen

`deploy/helm/k8s-agent/templates/clusterrole.yaml` um einen konditionellen Block erweitern:

```yaml
  {{- if .Values.agentConfig.plugins.optional.falco }}
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["list", "get"]
    # Hinweis: pods/log bereits durch den allgemeinen Block oben abgedeckt
  {{- end }}
```

Da `pods: list/get` und `pods/log: get` bereits cluster-weit in der ClusterRole stehen, braucht
dieser Block nur zur Dokumentation — er kann auch entfallen. Besser: einen Kommentar in der
ClusterRole hinterlassen dass der Falco-Namespace mit abgedeckt ist.

---

### 6. `deploy/helm/k8s-agent/values.yaml` — Falco-Namespace ergänzen

Im `agentConfig`-Block den Falco-Namespace als konfigurierbaren Wert aufnehmen:

```yaml
agentConfig:
  kubernetes:
    namespaces:
      - default
    log_lines: 100
    falco_namespace: falco   # neu
  plugins:
    core:
      - pod_logs
    optional:
      trivy: false
      falco: false
```

---

## Tests

### `tests/test_falco_plugin.py` (neue Datei)

Alle Tests mocken `kubernetes.client.CoreV1Api` und `k8s_config.load_incluster_config`.

- `test_run_returns_empty_when_no_pods`: `list_namespaced_pod` gibt 0 Items → `[]`
- `test_run_returns_empty_on_403`: `list_namespaced_pod` wirft `ApiException(status=403)` → `[]`, warning-Log
- `test_run_returns_empty_on_404_namespace`: `ApiException(status=404)` → `[]`, debug-Log
- `test_read_pod_logs_skips_non_json`: Logs mit Mix aus JSON und Startup-Text → nur JSON-Events geparst
- `test_read_pod_logs_skips_events_without_rule`: JSON ohne `rule`-Key → nicht in Ergebnis
- `test_events_to_findings_filters_low_priority`: Events mit `priority: Notice` → kein Finding
- `test_events_to_findings_maps_critical`: `priority: Critical` → `severity="CRITICAL"`
- `test_events_to_findings_maps_warning`: `priority: Warning` → `severity="HIGH"`
- `test_events_to_findings_deduplicates_by_rule`: 5 Events gleiche Regel → 1 Finding mit `count=5`
- `test_events_to_findings_separate_rules`: 2 verschiedene Regeln → 2 Findings
- `test_run_aggregates_multiple_pods`: 2 Falco-Pods, je 1 kritisches Event → 2 Findings (verschiedene Regeln)
- `test_finding_includes_output_fields_in_raw`: `output_fields` mit `proc.name` + `fd.name` landen in `raw`
- `test_finding_message_includes_process_and_file`: `proc.name=cat`, `fd.name=/etc/shadow` → im `message`-String

### `tests/test_config.py` — bestehende Tests anpassen

`falco_namespace` zum Config-Fixture hinzufügen (Default `"falco"`).

---

## Done when

```yaml
# config.yaml
plugins:
  optional:
    falco: true
```

```bash
python agent.py
```

gibt Falco-Findings aus wenn Falco im Cluster läuft und `json_output: true` konfiguriert hat.
Bei fehlendem Falco: stiller `debug`-Log (`Keine Pods mit Label … gefunden`), kein Crash.

Und:

```bash
helm upgrade k8s-agent deploy/helm/k8s-agent/
kubectl logs -f deployment/k8s-agent-k8s-agent
```

zeigt `[CRITICAL]` oder `[HIGH]` Findings für aktive Falco-Regeln, korrekt dedupliziert,
mit Pod-Name und Prozess im `message`-Feld für das LLM.

Alle bestehenden 87 Tests bleiben grün, neue Tests für FalcoPlugin kommen hinzu.
