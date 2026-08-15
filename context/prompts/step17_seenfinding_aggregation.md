# Prompt — Schritt 17: SeenFinding-Aggregation pro Resource

## Kontext

Seit Schritt 16 (+ Bugfix-Runde "stabile Fingerprints") legt `src/dedup.py` ein `SeenFinding`-CR
pro `(source, namespace, fingerprint)` an. Ein Pod mit mehreren unabhängigen Problemen
(CrashLoop-Event, hoher Restart-Count, dazu eine Trivy-CVE im selben Image) erzeugt drei separate
CRs — `kubectl get sf` wird schnell unübersichtlich, und jedes CR trägt nur einen Bruchteil des
Bilds für die betroffene Resource.

Dieser Schritt bündelt alle Findings einer Resource in **einem** `SeenFinding`-CR
(`spec.findings` als Liste statt flacher Felder). Der bestehende Cross-Run-Dedup-Mechanismus
(fail-open, Auto-Resolve nach `dedup_lookback_minutes`) bleibt inhaltlich unverändert — er
verschiebt sich nur von CR-Granularität auf Listen-Eintrags-Granularität innerhalb eines CRs.

Zusätzlich löst dieser Schritt einen Kontextverlust: Bisher sieht der Analyzer nur die *neuen*
Findings eines Laufs. Hat eine Resource ein andauerndes Problem (z.B. dauerhaftes CrashLoop, das
seit dem ersten Auftreten gededupt wird) und tritt *danach* ein zweites, neues Problem an
derselben Resource auf (z.B. eine neue CVE), sieht das LLM nur die neue CVE — ohne zu wissen, dass
der Pod ohnehin schon crasht. Ab jetzt gilt: Sobald sich für eine Resource **irgendetwas** ändert,
bekommt das LLM den **vollständigen** aktuellen Findings-Stand dieser Resource (alt + neu aus dem
laufenden Durchlauf) — Resourcen ohne Änderung werden komplett aus dem Prompt ausgelassen (spart
Prompt-Text, ohne die Call-Anzahl zu erhöhen: weiterhin ein LLM-Call pro Durchlauf für alle
betroffenen Resourcen zusammen).

**Wichtiger Fallstrick:** `finding.resource` (das Anzeige-Feld) enthält bei mehreren Plugins nach
wie vor volatile K8s-generierte Suffixe (Pod-Hash, ReplicaSet-Template-Hash) — nur `fingerprint`
wird bereits über `stable_name()` stabilisiert (`src/plugins/identity.py`). Würde nach
`(namespace, resource)` gruppiert, bekäme jeder Pod nach einem Neustart wieder ein neues CR —
derselbe Bug, der in der letzten Bugfix-Runde für `fingerprint` behoben wurde, nur eine Ebene
höher. Deshalb: neues Pflichtfeld `Finding.identity`, das den Gruppierungs-Schlüssel trägt
(container-/reason-/CVE-unabhängig, aber stabil über Pod-Neustarts hinweg via `stable_name()`).
`resource` bleibt unverändert als roher Anzeigename für Log-/Prompt-Ausgabe.

---

## Aufgabe

### 1. `src/models.py` — `identity`-Feld

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
    identity: str
    recommendation: str | None = None
```

Pflichtfeld wie `fingerprint` (kein Default) — zwingt jedes Plugin, die Gruppierungs-Identität
explizit zu setzen statt sich auf einen zu groben Auto-Fallback aus `resource` zu verlassen.

### 2. Plugins — `identity` setzen

Pro Plugin eine Ebene gröber als `fingerprint` (Container/Reason/CVE-Anteil weglassen), aber mit
`stable_name()` stabilisiert:

| Plugin | bisheriges `fingerprint` | neues `identity` |
|---|---|---|
| `pod_logs.py:176` | `f"{stable_name(pod_name)}/{container}"` | `stable_name(pod_name)` |
| `k8s_events.py:81` | `f"{kind}:{stable_name(name)}:{reason}"` | `f"{kind.lower()}/{stable_name(name)}"` |
| `trivy.py:99` | `f"{kind}/{stable_name(resource_name)}:{container}"` | `f"{kind}/{stable_name(resource_name)}"` |
| `falco.py:141` | `rule` (kein `stable_name`) | `f"pod/{stable_name(affected_pod)}" if affected_pod else "node/unknown"` |
| `prometheus.py:65,81` | `f"{alertname}:{fingerprint_resource}"` | `fingerprint_resource` (Variable existiert bereits, direkt wiederverwenden) |

`falco.py` importiert `stable_name` bisher nicht (`fingerprint = rule` brauchte es nicht) — Import
ergänzen.

### 3. `deploy/helm/k8s-agent/templates/crd.yaml` — Schema auf Liste umstellen

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
              required: [resource, severity, lastSeen, findingCount, findings]
              properties:
                resource: {type: string}
                severity: {type: string}
                lastSeen: {type: string, format: date-time}
                findingCount: {type: integer}
                findings:
                  type: array
                  items:
                    type: object
                    required: [source, fingerprint, lastSeen, count]
                    properties:
                      source: {type: string}
                      fingerprint: {type: string}
                      severity: {type: string}
                      message: {type: string}
                      recommendation: {type: string}
                      firstSeen: {type: string, format: date-time}
                      lastSeen: {type: string, format: date-time}
                      count: {type: integer}
      additionalPrinterColumns:
        - {name: Resource, type: string, jsonPath: .spec.resource}
        - {name: Severity, type: string, jsonPath: .spec.severity}
        - {name: Findings, type: integer, jsonPath: .spec.findingCount}
        - {name: LastSeen, type: string, jsonPath: .spec.lastSeen}
```

`findingCount` ist redundant zu `len(spec.findings)`, aber `additionalPrinterColumns` unterstützt
keine Funktionen auf `jsonPath` — separates Feld, vom Agent bei jedem Schreiben mitgepflegt, damit
`kubectl get sf` die Anzahl ohne `-o yaml` zeigt.

**Breaking Change:** Bestehende CRs folgen dem alten Flach-Schema (`source`/`fingerprint`/`count`
direkt unter `spec`) und werden mit dem neuen Schema nicht mehr valide beschreibbar. Vor dem
`helm upgrade` müssen alle bestehenden `SeenFinding`-CRs gelöscht werden:
`kubectl delete sf --all -A`.

### 4. `src/dedup.py` — Umbau auf Gruppierung

```python
import hashlib
import logging
from collections import defaultdict
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
_SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


def _truncate(text: str | None, limit: int = _MESSAGE_MAX_CHARS) -> str: ...  # unverändert


def _highest_severity(entries: list[dict]) -> str:
    return max(
        (e.get("severity", "info") for e in entries),
        key=lambda s: _SEVERITY_ORDER.get(s, 0),
        default="info",
    )


class Deduplicator:
    def __init__(self) -> None: ...  # unverändert

    def filter_new(self, findings: list[Finding]) -> list[Finding]:
        groups: dict[tuple[str, str], list[Finding]] = defaultdict(list)
        for f in findings:
            groups[(f.namespace, f.identity)].append(f)

        new: list[Finding] = []
        for (namespace, identity), group in groups.items():
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

    def _delete(self, namespace: str, name: str) -> None: ...  # unverändert


def _cr_name(namespace: str, identity: str) -> str:
    raw = f"{namespace}|{identity}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]
```

### 5. `src/analyzer.py` — Enrichment um `identity` ergänzen

Die letzte Bugfix-Runde hat bereits einen Fall gefunden, in dem `Finding` beim Anreichern mit
LLM-Recommendations ohne `fingerprint` rekonstruiert wurde und dadurch bei jedem Lauf in Degraded
Mode fiel. Derselbe Fehlertyp droht jetzt für `identity` — beim Rekonstruieren in `analyze()`
(`enriched[idx] = Finding(...)`) muss `identity=f.identity` mit übernommen werden.

### 6. `src/graph.py` / RBAC / Config

Keine Änderung nötig — `_dedup_findings`-Node, Fail-open-Verhalten, RBAC (`get/list/create/patch/
delete` auf `seenfindings`) und `dedup_lookback_minutes` bleiben unverändert; die Verschiebung
passiert vollständig innerhalb von `dedup.py`.

---

## Designentscheidungen

- **Generalisierung auf `identity` statt Sonderfall "nur Pods"**: `k8s_events`/`trivy`/`falco`
  betreffen auch Nicht-Pod-Resourcen (Deployments, Nodes, PVCs). Ein einheitliches Konzept über
  alle Plugins hinweg vermeidet eine Sonderbehandlung für `pod_logs` und hält `dedup.py` generisch
  — konsistent mit der bestehenden "generischer Mechanismus statt Pro-Plugin-Lösung"-Entscheidung
  aus Schritt 16.
- **`identity` als eigenes Pflichtfeld statt Wiederverwendung von `resource` oder `fingerprint`**:
  `resource` ist nicht stabil über Pod-Neustarts (volatile Suffixe), `fingerprint` ist zu granular
  (enthält Container/Reason/CVE-Anteil — genau der Unterschied, den die Gruppierung auflösen soll).
  Ein drittes Feld macht die drei Zwecke (Anzeige / Gruppierung / Cross-Run-Identität einer
  einzelnen Bedingung) explizit statt sie zu vermischen.
- **Full-Context-Resend nur bei Änderung**: Eine Resource ohne neue Findings erzeugt in diesem Lauf
  keinen Prompt-Text — nur Resourcen mit mindestens einem neuen `(source, fingerprint)`-Eintrag
  werden (vollständig, inkl. bereits bekannter Findings) an den Analyzer weitergereicht. Das spart
  Prompt-Volumen bei andauernden, unveränderten Problemen, ohne den bestehenden Ein-Call-pro-Lauf-
  Ansatz aus Schritt 8 anzutasten.
- **Merge behält unberührte Einträge unverändert**: `_merge()` lässt Einträge, die im aktuellen
  Lauf nicht erneut auftauchen (die Quelle liefert sie z.B. gerade nicht, weil das Plugin nur
  Warnings meldet und der Zustand kurzzeitig OK ist), unangetastet im CR stehen — sie verschwinden
  erst über `cleanup_resolved()`, nicht sofort. Verhindert Flackern zwischen "gemeldet" und
  "verschwunden" bei jedem einzelnen Lauf.
- **Cleanup pro Listen-Eintrag statt pro CR**: Ein CR mit einem andauernden Problem (z.B.
  chronisches CrashLoop) und einem länger nicht mehr aufgetretenen zweiten Problem (z.B. eine
  längst gefixte CVE) soll nicht das ganze CR am Leben halten — einzelne Einträge fallen individuell
  nach `dedup_lookback_minutes` raus, das CR nur, wenn dadurch die Liste leer wird.
- **Kein neuer LLM-Call pro Resource**: bewusst nicht umgesetzt (siehe Antwort auf die Rückfrage) —
  ein globaler Call pro Lauf bleibt bestehen, nur der Input dazu wird pro betroffener Resource
  vollständig statt fragmentiert zusammengestellt.
- **Breaking CRD-Schema-Change**: bewusst kein Migrations-/Kompatibilitätscode für das alte
  Flach-Schema — `SeenFinding` ist reine Dedup-Bookkeeping-Infrastruktur ohne Business-Value über
  eine `dedup_lookback_minutes`-Fenster hinaus; sauberes Löschen und Neuaufbau ist einfacher und
  robuster als zwei Schemas parallel zu unterstützen.

---

## Tests

### `tests/unit/test_dedup.py` — größtenteils neu

- `test_filter_new_creates_cr_with_single_finding_for_unseen_identity`
- `test_filter_new_groups_multiple_findings_of_same_identity_into_one_cr`
- `test_filter_new_returns_full_group_when_one_finding_is_new` (bereits bekanntes + neues Finding
  derselben Identity im selben Lauf → beide landen in `new`)
- `test_filter_new_skips_group_when_nothing_new` (alle Findings der Gruppe bereits bekannt → `new`
  bleibt für diese Gruppe leer, CR wird trotzdem mit aktualisiertem `lastSeen`/`count` beschrieben)
- `test_filter_new_preserves_untouched_entries_in_merge` (CR hat bereits Eintrag A, Lauf bringt nur
  Eintrag B derselben Identity → gemergtes CR enthält A unverändert und B neu)
- `test_filter_new_fails_open_on_non_404_api_error` (ganze Gruppe bleibt erhalten)
- `test_update_recommendations_patches_matching_entry_only`
- `test_cleanup_resolved_removes_stale_entry_keeps_fresh_entry_in_same_cr`
- `test_cleanup_resolved_deletes_cr_when_all_entries_stale`
- `test_cleanup_resolved_keeps_cr_when_all_entries_fresh`
- `test_cr_name_is_deterministic_and_valid_k8s_name` (gleiche `(namespace, identity)` → gleicher
  Name; enthält nur `[a-f0-9]`)

### `src/analyzer.py`

- `test_analyze_preserves_identity_field_when_enriching_findings` (Regression-Test analog zum
  bereits gefundenen `fingerprint`-Bug — stellt sicher, dass `identity` beim Rekonstruieren in
  `enriched[idx] = Finding(...)` nicht verloren geht)

### Plugin-Tests — anpassen

Jede bestehende `Finding(...)`-Konstruktion in `tests/unit/test_pod_logs_plugin.py`,
`test_k8s_events_plugin.py`, `test_trivy_plugin.py`, `test_falco_plugin.py`,
`test_prometheus_plugin.py`, `test_analyzer.py`, `test_console_output.py`,
`test_graph.py` um `identity=` ergänzen (Pflichtfeld ohne Default bricht sonst alle bestehenden
Aufrufe). Zusätzlich je Plugin ein Test, der den korrekten `identity`-Wert für ein bekanntes
Beispiel-Finding prüft — insbesondere `test_falco_plugin.py`, da `stable_name()` dort neu
hinzukommt.

---

## Done when

Ein Pod mit mehreren gleichzeitigen oder nacheinander auftretenden Findings über verschiedene
Quellen hinweg erzeugt genau **ein** `SeenFinding`-CR (`kubectl get sf` zeigt eine Zeile statt
mehrerer). Tritt an einer bereits bekannten Resource ein neues Finding auf, bekommt der Analyzer
alle Findings dieser Resource (alt + neu) im selben Prompt-Block; Resourcen ohne Änderung
erzeugen keinen Prompt-Text in diesem Lauf. Einzelne Findings innerhalb eines CRs verschwinden
nach `dedup_lookback_minutes` ohne erneutes Auftreten, das CR selbst erst wenn dadurch keine
Findings mehr übrig sind. Ein Ausfall der Dedup-Infrastruktur führt weiterhin dazu, dass alle
Findings ungefiltert durchgereicht werden.

Alle bestehenden Tests bleiben grün (nach `identity`-Ergänzung), neue Aggregations-Tests kommen
hinzu. `kubectl delete sf --all -A` vor dem nächsten `helm upgrade` im Cluster (Breaking Change am
CRD-Schema).
