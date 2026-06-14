# Prompt — Schritt 12: Plugin-Registry & dynamisches Plugin-Laden

## Kontext

Schritt 11 ist abgeschlossen. Der Agent läuft als Helm-Deployment im Cluster. `values.yaml` hat bereits
`plugins.optional.trivy/falco/prometheus` und `Config` kennt `core_plugins` / `optional_plugins` —
aber `graph.py` instanziert `PodLogsPlugin` noch hartkodiert. Neue Plugins lassen sich nicht
aktivieren ohne Codeänderungen.

Dieses Schritt macht das System tatsächlich erweiterbar: eine zentrale Registry, ein Loader der
Config liest, und Trivy als zweites vollständiges Plugin.

---

## Aufgabe

### 1. `src/plugins/__init__.py` — Plugin-Registry

Ersetzt die leere Datei durch eine Registry die alle bekannten Plugins auflistet:

```python
from src.plugins.pod_logs import PodLogsPlugin
from src.plugins.trivy import TrivyPlugin

PLUGIN_REGISTRY: dict[str, type] = {
    "pod_logs": PodLogsPlugin,
    "trivy": TrivyPlugin,
}
```

Konvention für neue Plugins:
- Neue Datei `src/plugins/<name>.py` anlegen, `BasePlugin` implementieren
- Klasse in `PLUGIN_REGISTRY` eintragen — ein Eintrag, fertig

---

### 2. `src/plugins/loader.py` — Plugin-Loader (neue Datei)

```python
import logging

from src.config import config
from src.plugins import PLUGIN_REGISTRY
from src.plugins.base import BasePlugin

logger = logging.getLogger(__name__)


def load_plugins() -> list[BasePlugin]:
    plugins: list[BasePlugin] = []

    for name in config.core_plugins:
        cls = PLUGIN_REGISTRY.get(name)
        if cls is None:
            logger.warning("Unbekanntes Core-Plugin '%s' in config — übersprungen", name)
            continue
        plugins.append(cls())
        logger.info("Plugin geladen: %s", name)

    for name, enabled in config.optional_plugins.items():
        if not enabled:
            continue
        cls = PLUGIN_REGISTRY.get(name)
        if cls is None:
            logger.warning("Unbekanntes optionales Plugin '%s' in config — übersprungen", name)
            continue
        plugins.append(cls())
        logger.info("Optionales Plugin geladen: %s", name)

    return plugins
```

`load_plugins()` wird bei jedem Graph-Run aufgerufen — Plugins sind zustandslos, das ist korrekt.

---

### 3. `src/graph.py` — Refactoring

`_collect_findings` hartkodiert `PodLogsPlugin` ersetzen durch `load_plugins()`.
Pro Plugin wird `run()` aufgerufen; ein einzelner Plugin-Fehler stoppt nicht die anderen.

```python
import logging
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from src.models import Finding, Alert
from src.plugins.loader import load_plugins
from src import analyzer
from src.outputs import console

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    findings: list[Finding]
    alert: Alert | None


def _collect_findings(state: AgentState) -> dict:
    all_findings: list[Finding] = []
    for plugin in load_plugins():
        try:
            findings = plugin.run()
            all_findings.extend(findings)
            logger.debug("Plugin %s: %d Findings", plugin.name, len(findings))
        except Exception as exc:
            logger.error("Plugin %s fehlgeschlagen: %s", plugin.name, exc)
    return {"findings": all_findings}


def _analyze_findings(state: AgentState) -> dict:
    alert = analyzer.analyze(state["findings"])
    return {"alert": alert}


def _send_output(state: AgentState) -> dict:
    console.send(state["alert"])
    return {}


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("collect_findings", _collect_findings)
    graph.add_node("analyze_findings", _analyze_findings)
    graph.add_node("send_output", _send_output)

    graph.add_edge(START, "collect_findings")
    graph.add_edge("collect_findings", "analyze_findings")
    graph.add_edge("analyze_findings", "send_output")
    graph.add_edge("send_output", END)

    return graph.compile()
```

---

### 4. `src/plugins/trivy.py` — TrivyPlugin (neue Datei)

Liest `VulnerabilityReport`-CRDs des Trivy Operators über die K8s Custom Objects API.
Ein Finding pro Report der mindestens ein HIGH oder CRITICAL enthält.

```python
import logging
from datetime import datetime, timezone

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException

from src.config import config
from src.models import Finding
from src.plugins.base import BasePlugin

logger = logging.getLogger(__name__)

_GROUP = "aquasecurity.github.io"
_VERSION = "v1alpha1"
_PLURAL = "vulnerabilityreports"


class TrivyPlugin(BasePlugin):
    name = "trivy"

    def __init__(self):
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()
        self._api = client.CustomObjectsApi()

    def run(self) -> list[Finding]:
        findings: list[Finding] = []
        for namespace in config.namespaces:
            findings.extend(self._scan_namespace(namespace))
        return findings

    def _scan_namespace(self, namespace: str) -> list[Finding]:
        try:
            response = self._api.list_namespaced_custom_object(
                group=_GROUP,
                version=_VERSION,
                namespace=namespace,
                plural=_PLURAL,
            )
        except ApiException as exc:
            if exc.status == 404:
                logger.debug(
                    "Trivy CRDs nicht gefunden in Namespace %s — Trivy Operator installiert?",
                    namespace,
                )
            elif exc.status in (401, 403):
                logger.warning(
                    "Kein Zugriff auf VulnerabilityReports in %s (HTTP %s)", namespace, exc.status
                )
            else:
                logger.error("Fehler beim Lesen von VulnerabilityReports in %s: %s", namespace, exc)
            return []

        findings: list[Finding] = []
        for report in response.get("items", []):
            finding = self._report_to_finding(report, namespace)
            if finding:
                findings.append(finding)
        return findings

    def _report_to_finding(self, report: dict, namespace: str) -> Finding | None:
        summary = report.get("report", {}).get("summary", {})
        critical = summary.get("criticalCount", 0)
        high = summary.get("highCount", 0)

        if critical == 0 and high == 0:
            return None

        meta = report.get("metadata", {})
        labels = meta.get("labels", {})
        container = labels.get("trivy-operator.container.name", "unknown")
        kind = labels.get("trivy-operator.resource.kind", "")
        resource_name = labels.get("trivy-operator.resource.name", meta.get("name", "unknown"))

        artifact = report.get("report", {}).get("artifact", {})
        image = f"{artifact.get('repository', '')}:{artifact.get('tag', 'unknown')}"

        severity = "CRITICAL" if critical > 0 else "HIGH"
        message = (
            f"{critical} kritische, {high} hohe CVEs in {image} "
            f"({kind}/{resource_name}, Container: {container})"
        )

        top_vulns = [
            v for v in report.get("report", {}).get("vulnerabilities", [])
            if v.get("severity") in ("CRITICAL", "HIGH")
        ][:5]

        return Finding(
            source=self.name,
            namespace=namespace,
            resource=f"{kind}/{resource_name}:{container}",
            severity=severity,
            message=message,
            timestamp=datetime.now(timezone.utc),
            raw={
                "summary": summary,
                "image": image,
                "top_vulnerabilities": [
                    {
                        "id": v.get("vulnerabilityID"),
                        "title": v.get("title"),
                        "severity": v.get("severity"),
                        "resource": v.get("resource"),
                        "installedVersion": v.get("installedVersion"),
                        "fixedVersion": v.get("fixedVersion"),
                    }
                    for v in top_vulns
                ],
            },
        )
```

**Fehlerbehandlung:**
- `404` → CRDs nicht installiert (kein Trivy Operator) → debug-Log, leer zurück
- `401/403` → RBAC fehlt → warning-Log, leer zurück
- Kein `high`/`critical` → Finding wird nicht erstellt (kein Noise für LOW/MEDIUM)

---

### 5. Helm ClusterRole erweitern — `deploy/helm/k8s-agent/templates/clusterrole.yaml`

Trivy-CRD-Zugriff nur hinzufügen wenn `plugins.optional.trivy: true`:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: {{ include "k8s-agent.fullname" . }}
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["list", "get"]
  - apiGroups: [""]
    resources: ["pods/log"]
    verbs: ["get"]
  - apiGroups: [""]
    resources: ["events"]
    verbs: ["list", "get"]
  {{- if .Values.agentConfig.plugins.optional.trivy }}
  - apiGroups: ["aquasecurity.github.io"]
    resources: ["vulnerabilityreports", "configauditreports", "exposedsecretreports"]
    verbs: ["list", "get"]
  {{- end }}
```

---

### 6. `config.yaml.example` — plugins-Block aktualisieren

Den Kommentar ergänzen damit klar ist was optional aktivierbar ist:

```yaml
plugins:
  core:
    - pod_logs        # immer aktiv
  optional:
    trivy: false      # Trivy Operator muss im Cluster installiert sein
    falco: false      # noch nicht implementiert
    prometheus: false # noch nicht implementiert
```

---

## Konvention: Neues Plugin hinzufügen

So sieht das Muster für jedes weitere Plugin aus (z.B. Falco):

1. `src/plugins/falco.py` anlegen, `BasePlugin` implementieren, `name = "falco"` setzen
2. In `src/plugins/__init__.py` importieren und in `PLUGIN_REGISTRY` eintragen
3. In `values.yaml` unter `agentConfig.plugins.optional.falco` auf `true` setzen
4. RBAC in `clusterrole.yaml` mit `{{- if .Values.agentConfig.plugins.optional.falco }}` erweitern
5. Fertig — `graph.py` und `loader.py` bleiben unverändert

---

## Tests

**`tests/test_loader.py`** (neue Datei):
- `test_load_core_plugins_only`: Config mit `core_plugins=["pod_logs"]`, `optional_plugins={}` → 1 Plugin
- `test_load_optional_when_enabled`: `optional_plugins={"trivy": True}` → 2 Plugins
- `test_skip_disabled_optional`: `optional_plugins={"trivy": False}` → 1 Plugin (nur core)
- `test_warn_unknown_plugin`: unbekannter Name in `core_plugins` → warning-Log, kein Crash

**`tests/test_trivy_plugin.py`** (neue Datei):
- `test_run_returns_empty_on_404`: `ApiException(status=404)` → `[]`, kein Crash
- `test_run_returns_empty_on_403`: `ApiException(status=403)` → `[]`, kein Crash
- `test_report_to_finding_skips_low_only`: Report mit nur LOW → kein Finding
- `test_report_to_finding_critical`: Report mit 2 CRITICAL → Finding mit severity="CRITICAL"
- `test_report_to_finding_high_only`: Report mit 0 CRITICAL, 3 HIGH → severity="HIGH"
- `test_run_aggregates_multiple_namespaces`: 2 Namespaces, je 1 Report → 2 Findings
- `test_run_filters_clean_reports`: Report mit 0 high/critical → keine Findings

**`tests/test_graph.py`** — bestehende Tests anpassen:
- Mock `load_plugins()` statt `PodLogsPlugin()` direkt

---

## Done when

```python
# config.yaml
plugins:
  core:
    - pod_logs
  optional:
    trivy: true

python agent.py
```

gibt Findings beider Plugins aus — Pod-Logs vom `PodLogsPlugin` und
VulnerabilityReports vom `TrivyPlugin` — ohne Codeänderung, nur Config.

Und:
```bash
# values.yaml mit trivy: true
helm upgrade k8s-agent deploy/helm/k8s-agent/
kubectl logs -f deployment/k8s-agent-k8s-agent
```

zeigt Trivy-Findings im Output wenn Trivy Operator CRDs vorhanden sind,
oder einen stillen debug-Log wenn nicht (`404` → kein Crash).
