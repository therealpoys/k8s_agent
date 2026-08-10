# Prompt — Schritt 16: Generisches Cross-Run-Dedup via Custom Resource

## Kontext

Ersetzt den ursprünglichen Ansatz aus `step16_event_lookback_window.md` (reines Zeitfenster,
nur für `K8sEventsPlugin`). Der Agent ist als CronJob zustandslos (`* * * * *`,
`concurrencyPolicy: Forbid`, kein Cursor zwischen Läufen — `graph.py:19-28`). Nicht nur
`K8sEventsPlugin` ist davon betroffen: `PrometheusPlugin` meldet ein `firing`-Alert bei jedem
Lauf erneut, `FalcoPlugin` dieselbe Regel bei jedem Log-Read, `TrivyPlugin` denselben
CVE-Befund bis das Image ausgetauscht wird, `PodLogsPlugin` denselben CrashLoop bei jedem
Restart-losen Minuten-Takt — überall dieselbe Alert-Fatigue, nicht nur bei K8s-Events.

Statt eines Zeitfensters pro Plugin führt dieser Schritt einen **generischen, plugin-
übergreifenden Dedup-Mechanismus** ein: eine neue Custom Resource `SeenFinding`, die der Agent
selbst anlegt/aktualisiert/löscht. Jedes Finding bekommt einen stabilen `fingerprint`
(Identität der zugrunde liegenden Bedingung, unabhängig von variablen Details wie Log-Inhalt,
Occurrence-Count oder exaktem Messwert). Vor dem Analyzer prüft ein neuer Graph-Node, ob zu
einem Finding bereits eine `SeenFinding`-CR existiert:

- **existiert nicht** → CR anlegen (`firstSeen`/`lastSeen` = jetzt, `count = 1`), Finding geht
  wie bisher an den Analyzer.
- **existiert bereits** → `lastSeen`/`count` aktualisieren, Finding wird **nicht** erneut an den
  Analyzer weitergereicht (bereits gemeldet).
- **CR ist seit `dedup_lookback_minutes` nicht mehr aktualisiert worden** (Bedingung ist in
  keinem Lauf mehr aufgetreten) → CR wird gelöscht ("auto-resolved"). Tritt dieselbe Bedingung
  danach erneut auf, gilt sie als neu und alarmiert wieder — analog zum Resolve-Verhalten von
  Alertmanager, nur ohne externe Storage-Abhängigkeit (State lebt in der K8s-API, nicht in einer
  neuen DB).

---

## Aufgabe

### 1. `src/models.py` — `fingerprint`-Feld

```python
@dataclass
class Finding:
    source: str
    namespace: str
    resource: str
    severity: str
    message: str
    timestamp: datetime
    raw: dict | None
    fingerprint: str
    recommendation: str | None = None
```

`fingerprint` ist **Pflichtfeld** (kein Default) — zwingt jedes Plugin, bewusst zu entscheiden,
was "dieselbe Bedingung" bei einem erneuten Lauf bedeutet, statt sich auf einen zu groben
Auto-Fallback zu verlassen.

### 2. Plugins — `fingerprint` setzen

Pro Plugin die bereits vorhandene (oder naheliegende) Identität wiederverwenden, **ohne**
variable Anteile (Counts, Messwerte, Log-Text):

| Plugin | `fingerprint` | Begründung |
|---|---|---|
| `k8s_events.py` | `f"{kind}:{name}:{reason}"` | bereits der bestehende Dedup-Key aus `grouped` (`k8s_events.py:58`) |
| `falco.py` | `rule` | bereits der bestehende Dedup-Key aus `filtered` (`falco.py:97`) |
| `pod_logs.py` | `resource` (= `f"{pod_name}/{container}"`) | Log-Inhalt ist der variable Teil, Pod/Container die stabile Identität |
| `trivy.py` | `resource` (= `f"{kind}/{resource_name}:{container}"`) | CVE-Counts variieren, Workload/Container-Identität nicht |
| `prometheus.py` | `f"{alertname}:{resource}"` | `message` enthält variable Messwerte, `alertname` + `resource` sind stabil |

### 3. `crds/seenfinding.yaml` (bzw. `deploy/helm/k8s-agent/templates/crd.yaml`) — neue CRD

```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: seenfindings.k8s-agent.dev
  labels:
    {{- include "k8s-agent.labels" . | nindent 4 }}
spec:
  group: k8s-agent.dev
  scope: Namespaced
  names:
    plural: seenfindings
    singular: seenfinding
    kind: SeenFinding
    shortNames: ["sf"]
  versions:
    - name: v1alpha1
      served: true
      storage: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              required: [source, resource, fingerprint, lastSeen, count]
              properties:
                source: {type: string}
                resource: {type: string}
                fingerprint: {type: string}
                severity: {type: string}
                firstSeen: {type: string, format: date-time}
                lastSeen: {type: string, format: date-time}
                count: {type: integer}
      additionalPrinterColumns:
        - {name: Source, type: string, jsonPath: .spec.source}
        - {name: Resource, type: string, jsonPath: .spec.resource}
        - {name: Count, type: integer, jsonPath: .spec.count}
        - {name: LastSeen, type: string, jsonPath: .spec.lastSeen}
```

Liegt unter `templates/`, nicht im Helm-eigenen `crds/`-Ordner — die Chart-Version trackt die
CRD mit, `helm upgrade` aktualisiert sie wie jede andere Ressource (kein `crds/`-Sonderverhalten
mit "wird nach Install nie wieder angefasst").

### 4. `src/dedup.py` — neues Modul

```python
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

    def _create(self, finding: Finding, name: str) -> None: ...  # POST mit spec (firstSeen=lastSeen=now, count=1)
    def _touch(self, finding: Finding, name: str, existing: dict) -> None: ...  # PATCH lastSeen=now, count += 1
    def _delete(self, namespace: str, name: str) -> None: ...  # DELETE, 404 still ignorieren (Race)


def _cr_name(finding: Finding) -> str:
    raw = f"{finding.source}|{finding.namespace}|{finding.fingerprint}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]
```

`_cr_name`: CR-Namen müssen gültige DNS-1123-Subdomains sein — `fingerprint` selbst (z.B. ein
Falco-Regelname mit Leer-/Sonderzeichen) ist das nicht zuverlässig. Hash statt Klarname, dafür
`fingerprint` unverändert im `spec` gespeichert (für `kubectl get seenfinding -o yaml`
Debugging).

### 5. `src/graph.py` — neuer Node zwischen Collect und Analyze

```python
def _dedup_findings(state: AgentState) -> dict:
    try:
        dedup = Deduplicator()
        new_findings = dedup.filter_new(state["findings"])
        dedup.cleanup_resolved()
    except Exception as exc:
        logger.error("Dedup fehlgeschlagen (%s) — Findings ungefiltert weitergereicht", exc)
        return {"findings": state["findings"]}
    return {"findings": new_findings}
```

Graph-Fluss: `START → collect_findings → dedup_findings → analyze_findings → send_output → END`.
Fail-open auf oberster Ebene (nicht nur pro Finding in `filter_new`): ein kompletter Ausfall der
Dedup-Infrastruktur (z.B. CRD versehentlich gelöscht) darf niemals dazu führen, dass gar keine
Alerts mehr rausgehen — lieber wieder Alert-Fatigue als Blindflug.

### 6. `src/config.py` / `config.yaml.example` — `dedup_lookback_minutes`

Top-Level (nicht unter `kubernetes:`, da plugin-übergreifend):

```python
dedup_lookback_minutes: int
...
dedup_lookback_minutes=raw.get("dedup_lookback_minutes", 15),
```

```yaml
# config.yaml
dedup_lookback_minutes: 15  # Findings gelten nach N Minuten ohne erneutes Auftreten als "resolved" und alarmieren bei Wiederauftreten erneut
```

### 7. Helm — RBAC-Erweiterung

`deploy/helm/k8s-agent/templates/clusterrole.yaml`:

```yaml
  - apiGroups: ["k8s-agent.dev"]
    resources: ["seenfindings"]
    verbs: ["get", "list", "create", "patch", "delete"]
```

---

## Designentscheidungen

- **State in der K8s-API statt externer DB**: kein neuer Storage-Baustein, keine neuen Secrets/
  Connection-Strings — die CR lebt in demselben Cluster, RBAC-Modell wie alles andere im Agent
  (analog zu `TrivyPlugin`, das ja bereits fremde CRDs via `CustomObjectsApi` liest — hier
  schreibt der Agent erstmals selbst welche).
- **Generischer Mechanismus statt Pro-Plugin-Lösung**: `PrometheusPlugin`, `FalcoPlugin` & Co.
  haben exakt dasselbe Problem wie `K8sEventsPlugin` — eine zentrale Lösung in einem eigenen
  Graph-Node vermeidet fünf Mal dieselbe Zeitfenster-/Cursor-Logik in jedem Plugin.
  Plugins bleiben bei ihrer eigentlichen Verantwortung ("was ist passiert"), nicht "haben wir das
  schon gemeldet".
- **`fingerprint` als Pflichtfeld, nicht Auto-Fallback aus `resource`**: `resource` allein ist in
  mehreren Plugins zu grob (z.B. `PrometheusPlugin`: gleicher Pod, aber zwei unterschiedliche
  Alerts würden kollidieren; `K8sEventsPlugin`: gleiche Resource, aber `BackOff` vs.
  `FailedMount` sind unterschiedliche Probleme). Jedes Plugin muss das explizit entscheiden.
- **Fail-open auf zwei Ebenen** (pro Finding in `filter_new`, gesamter Node in `graph.py`):
  konsistent mit der bestehenden Philosophie im Rest des Codebase (Plugins crashen nie, Analyzer
  hat Degraded Mode) — Dedup ist ein Signal-Verbesserer, keine Voraussetzung fürs Alerting.
  Ein Ausfall degradiert zurück auf das alte (lautere) Verhalten, nicht auf Stille.
- **Auto-Resolve statt permanenter Unterdrückung**: eine CR wird gelöscht, sobald ihre Bedingung
  `dedup_lookback_minutes` lang nicht mehr aufgetreten ist — ein andauerndes Problem (z.B.
  dauerhaftes `BackOff`) bleibt so lange stumm, wie es andauert, alarmiert aber erneut, falls es
  nach einer Pause wiederkehrt. Verhindert das Szenario aus der permanenten Variante ("nach dem
  ersten Alert für immer stumm, auch wenn's nie behoben wurde").
- **Cleanup unabhängig von aktuellen Findings**: `cleanup_resolved()` iteriert alle
  `SeenFinding`-CRs, nicht nur die im aktuellen Lauf gesehenen — sonst würde eine CR nie gelöscht,
  wenn die zugrunde liegende Quelle (z.B. Prometheus-Alert) irgendwann klemmt und keine Findings
  mehr liefert.
- **Kein Umbau der bestehenden Intra-Run-Dedup-Logik** in `k8s_events.py`/`falco.py` (Gruppierung
  nach Key + Count-Summierung innerhalb eines einzelnen Laufs): bleibt bestehen, ist orthogonal
  zum neuen Cross-Run-Dedup und wird nur als `fingerprint`-Quelle wiederverwendet.

---

## Tests

### `tests/unit/test_dedup.py` — neu

- `test_filter_new_creates_cr_for_unseen_finding_and_keeps_it`
- `test_filter_new_drops_finding_with_existing_fresh_cr`
- `test_filter_new_patches_last_seen_and_count_on_existing_cr`
- `test_filter_new_fails_open_on_non_404_api_error` (Finding bleibt erhalten)
- `test_cleanup_resolved_deletes_cr_older_than_lookback`
- `test_cleanup_resolved_keeps_cr_within_lookback`
- `test_cr_name_is_deterministic_and_valid_k8s_name` (gleicher Finding-Fingerprint → gleicher
  Name; enthält nur `[a-f0-9]`)

### `src/graph.py` — Tests ergänzen

- `test_dedup_node_wired_between_collect_and_analyze`
- `test_dedup_failure_does_not_block_pipeline` (Deduplicator wirft Exception → Findings
  unverändert an `analyze_findings`)

### Bestehende Plugin-Tests — anpassen

Jede bestehende `Finding(...)`-Konstruktion in `tests/unit/test_k8s_events_plugin.py`,
`test_pod_logs_plugin.py`, `test_trivy_plugin.py`, `test_falco_plugin.py`,
`test_prometheus_plugin.py`, `test_analyzer.py`, `test_console_output.py` um `fingerprint=`
ergänzen (Pflichtfeld ohne Default bricht sonst alle bestehenden Aufrufe). Zusätzlich je Plugin
ein Test, der den korrekten `fingerprint`-Wert für ein bekanntes Beispiel-Finding prüft.

---

## Done when

```yaml
# config.yaml
dedup_lookback_minutes: 15
```

Ein Finding, das in zwei aufeinanderfolgenden Läufen mit identischem `fingerprint` auftritt,
erzeugt beim zweiten Lauf **keinen** neuen Alert-Eintrag mehr (nur CR-Update). Bleibt die
Bedingung länger als `dedup_lookback_minutes` unbeobachtet, wird die CR gelöscht und ein erneutes
Auftreten alarmiert wieder. Ein Ausfall der Dedup-Infrastruktur (z.B. CRD fehlt, RBAC fehlt)
führt dazu, dass **alle** Findings ungefiltert durchgereicht werden statt dass der Agent
schweigt.

Alle bestehenden Tests bleiben grün (nach `fingerprint`-Ergänzung), neue Dedup-Tests kommen
hinzu.
