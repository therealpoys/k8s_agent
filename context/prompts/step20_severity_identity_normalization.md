# Prompt — Schritt 20: Severity- und Identity-Normalisierung über alle Plugins

## Kontext

Review des Live-Zustands im Cluster (`kubectl get sf -o yaml`, Konsolen-Ausgabe) am 2026-08-15
ergab drei zusammenhängende Beobachtungen:

1. **Severity uneinheitlich gecast** — mal `info`/`warning` (lowercase), mal `HIGH`/`CRITICAL`
   (uppercase) auf demselben `SeenFinding`-CR bzw. in derselben Konsolen-Ausgabe.
2. **`resource`-Spalte teils unerklärlich knapp** — z.B. nur `crashloop` statt `pod/crashloop`.
3. **Dieselbe Resource erzeugt mehrere `SeenFinding`-CRs statt einem** ("same seenfindings"
   wirkt unaufgeräumt) — genau das Problem, das Schritt 17 eigentlich lösen sollte.

Root-Cause-Analyse (`src/analyzer.py`, `src/dedup.py`, alle fünf Plugins):

**Severity:** `analyzer.py` (`_VALID_SEVERITIES`, `_SEVERITY_ORDER`) und `dedup.py`
(`_SEVERITY_ORDER`) gehen von einem lowercase 3-Stufen-Schema aus (`info`/`warning`/`critical`) —
das ist auch, was der LLM-Prompt vorschreibt. Nur `pod_logs.py` hält sich daran (`severity="info"`).
`k8s_events.py`, `falco.py`, `prometheus.py` und `trivy.py` setzen stattdessen uppercase
`"HIGH"`/`"CRITICAL"` — Werte, die in keinem der beiden `_SEVERITY_ORDER`-Dicts vorkommen. Da
`_highest_severity()` (in **beiden** Dateien, unabhängig voneinander) unbekannte Werte per
`_SEVERITY_ORDER.get(s, 0)` auf Gewicht 0 (niedrigste Stufe) abbildet, wird ein `CRITICAL`-Finding
aus Trivy oder Falco bei der Ermittlung der höchsten Severity faktisch wie `info` behandelt, sobald
es neben einem korrekt lowercase gesetzten Finding steht. Das ist kein rein kosmetischer Bug.

**Identity/Resource:** Das in Schritt 17 eingeführte `Finding.identity`-Feld (Gruppierungs-Schlüssel
für `SeenFinding`-CRs) wurde bereits in der Schritt-17-Spec pro Plugin uneinheitlich definiert:

| Plugin | aktuelles `identity` | Problem |
|---|---|---|
| `pod_logs.py:177` | `stable_name(pod_name)` | kein `kind`-Präfix — bare Name landet 1:1 als `spec.resource` in der CR |
| `k8s_events.py:95` | `f"{kind.lower()}/{stable_name(name)}"` | korrekt — Referenz-Format |
| `trivy.py:100` | `f"{kind}/{stable_name(resource_name)}"` | `kind` **nicht** lowercased (z.B. `Pod/foo` statt `pod/foo`) |
| `falco.py:143` | `f"pod/{stable_name(affected_pod)}"` | korrekt |
| `prometheus.py:82` | `fingerprint_resource` (= `f"pod/{stable_name(pod)}"` oder rohes `instance`-Label) | korrekt für Pod-Alerts |

Derselbe physische Pod erzeugt je nach meldendem Plugin unterschiedliche `identity`-Strings
(`myapp` vs. `pod/myapp` vs. `Pod/myapp`) — `dedup.py::filter_new()` gruppiert nach
`(namespace, identity)`, unterschiedliche Strings heißt unterschiedliche CRs statt einer
gemeinsamen. Das erklärt sowohl die Fragmentierung (Punkt 3) als auch die komische `resource`-
Anzeige (Punkt 2): `dedup.py:111` setzt `spec["resource"] = identity` direkt durch.

**Bewusst nicht Teil dieses Schritts:** Die vierte Beobachtung — ein einzelnes `SeenFinding` mit
sehr vielen Listen-Einträgen (z.B. 17 Findings mit 17 Einzel-Recommendations) — ist kein Bug,
sondern das seit Schritt 17 bestehende Verhalten von `_merge()`, das pro `(source, fingerprint)`
einen eigenen Listen-Eintrag führt. Ob das für chronisch flappende Resourcen die richtige
Granularität ist (vs. z.B. einer zusammengefassten Recommendation pro CR), ist eine eigene
Design-Frage und wird hier nicht entschieden — durch die Identity-Fixes in diesem Schritt werden
mehr Findings korrekt in dieselbe CR gruppiert, wodurch dieser Effekt kurzfristig eher sichtbarer
statt seltener wird. Für einen späteren Schritt vormerken.

---

## Aufgabe

### 1. Neues Modul `src/severity.py`

```python
INFO = "info"
WARNING = "warning"
CRITICAL = "critical"

VALID_SEVERITIES = {INFO, WARNING, CRITICAL}
SEVERITY_ORDER = {INFO: 0, WARNING: 1, CRITICAL: 2}
```

Einzige Quelle der Wahrheit für das Severity-Schema — bisher als `_VALID_SEVERITIES`/
`_SEVERITY_ORDER` in `analyzer.py` **und** separat als `_SEVERITY_ORDER` in `dedup.py` dupliziert.

- `analyzer.py`: eigene `_VALID_SEVERITIES`/`_SEVERITY_ORDER`-Definitionen entfernen, stattdessen
  `from src.severity import VALID_SEVERITIES, SEVERITY_ORDER` und alle Referenzen umbenennen.
- `dedup.py`: eigene `_SEVERITY_ORDER`-Definition entfernen, gleicher Import.

### 2. Plugin-Severities auf lowercase 3-Stufen-Schema umstellen

| Plugin | bisher | neu |
|---|---|---|
| `falco.py` `_SEVERITY_MAP` | `Emergency/Alert/Critical → "CRITICAL"`, `Error/Warning → "HIGH"` | `→ CRITICAL`, `→ WARNING` (aus `src.severity`) |
| `k8s_events.py:91` | `severity="HIGH"` | `severity=WARNING` (Feld ist bereits über `field_selector="type=Warning"` gescoped — Warning-Events sind konsistent "warning", nie "critical") |
| `prometheus.py` `_SEVERITY_MAP` | `critical→"CRITICAL"`, `warning→"HIGH"`, `info→"info"` | `critical→CRITICAL`, `warning→WARNING`, `info→INFO` |
| `trivy.py:81` | `"CRITICAL" if critical > 0 else "HIGH"` | `CRITICAL if critical > 0 else WARNING` |

Jeweils `from src.severity import CRITICAL, WARNING, INFO` (nur was gebraucht wird) ergänzen.

**Nicht anfassen:** `trivy.py`s `top_vulnerabilities`-Liste übernimmt `v.get("severity")` roh aus
den Trivy-CVE-Daten (externes Format, z.B. für die Prompt-Zeile `[{v.get('severity','?')}]`) —
das ist keine `Finding.severity` und bleibt wie es ist.

### 3. Neuer Helper `resource_identity()` in `src/plugins/identity.py`

```python
def resource_identity(kind: str, name: str) -> str:
    return f"{kind.lower()}/{stable_name(name)}"
```

Ersetzt die fünf leicht unterschiedlichen Ad-hoc-Konstruktionen:

| Plugin | bisher | neu |
|---|---|---|
| `pod_logs.py:177` | `identity=stable_name(pod_name)` | `identity=resource_identity("pod", pod_name)` |
| `k8s_events.py:95` | `identity=f"{kind.lower()}/{stable_name(name)}"` | `identity=resource_identity(kind, name)` |
| `trivy.py:100` | `identity=f"{kind}/{stable_name(resource_name)}"` | `identity=resource_identity(kind, resource_name)` |
| `falco.py:143` | `identity=f"pod/{stable_name(affected_pod)}" if affected_pod else "node/unknown"` | `identity=resource_identity("pod", affected_pod) if affected_pod else "node/unknown"` |
| `prometheus.py:65,82` | `fingerprint_resource = f"pod/{stable_name(pod)}" if pod else labels.get("instance", "unknown")` | `fingerprint_resource = resource_identity("pod", pod) if pod else labels.get("instance", "unknown")` |

Ergebnis: `pod_logs`, `k8s_events`, `trivy` und `falco` erzeugen für denselben Pod jetzt
garantiert denselben `identity`-String (`pod/<stable_name>`), unabhängig davon, welches Plugin
meldet.

### 4. Breaking Change — bestehende CRs vor Deploy löschen

`_cr_name()` hasht `f"{namespace}|{identity}"` (`dedup.py:220`). Da sich `identity` für
`pod_logs`- und `trivy`-Findings ändert (neues Präfix bzw. lowercased `kind`), ändern sich auch
die CR-Namen — bestehende CRs werden zu Waisen statt aktualisiert zu werden. Wie beim
Breaking-Change in Schritt 17: vor dem nächsten `helm upgrade`
`kubectl delete sf --all -A` ausführen. Kein CRD-Schema-Change nötig (`resource: {type: string}`
bleibt unverändert, akzeptiert weiterhin jeden String).

---

## Designentscheidungen

- **Shared `src/severity.py` statt weiterer lokaler Konstanten**: `_SEVERITY_ORDER` war bereits
  vor diesem Schritt in `analyzer.py` und `dedup.py` dupliziert (unabhängig von den eigentlichen
  Bugs hier) — ein Modul statt zwei Kopien verhindert, dass sich die beiden Stellen zukünftig
  wieder auseinanderentwickeln.
- **3-Stufen-Schema bleibt bei info/warning/critical, kein viertes "high"**: Der LLM-Prompt-Vertrag
  (`analyzer.py::_PROMPT_TEMPLATE`, `"severity": "<info|warning|critical>"`) bleibt unverändert.
  Quellen, die bisher zwischen `HIGH` und `CRITICAL` unterschieden, mappen `HIGH` auf `warning` —
  das ist bereits die Stufe, die im restlichen System für "ernst, aber nicht kritisch" steht.
- **`k8s_events` fest auf `warning` statt konfigurierbar**: Das Plugin liest ausschließlich
  `field_selector="type=Warning"` — die K8s-eigene Einstufung ist bereits "Warning", nicht
  "Critical". Es gibt keine Grundlage, hier zwischen zwei Stufen zu unterscheiden, solange nicht
  nach `reason` differenziert wird (kein Teil dieses Schritts).
- **`resource_identity()` in `identity.py`, nicht in einem neuen Modul**: Gehört inhaltlich zur
  bestehenden "wie identifizieren/gruppieren wir eine K8s-Resource stabil"-Zuständigkeit dieser
  Datei (`stable_name()`), kein eigenständiges Konzept.
- **`Finding.resource` (Anzeige-Feld) bleibt unangetastet**: Die in Schritt 17 getroffene Trennung
  Anzeige (`resource`, roh/volatil) vs. Gruppierung (`identity`, stabilisiert) bleibt bestehen —
  dieser Schritt vereinheitlicht nur Letzteres.
- **Punkt 4 (viele Listen-Einträge pro CR) bewusst nicht in diesem Schritt**: Erfordert eine
  eigene Entscheidung (z.B. Recommendation pro CR statt pro Fingerprint zusammenfassen), die
  unabhängig von der hier behobenen Formatinkonsistenz ist und den Diff sonst unnötig aufbläht.

---

## Tests

### `tests/unit/test_identity.py`
- `test_resource_identity_lowercases_kind` — `resource_identity("Pod", "foo-abc12")` ==
  `resource_identity("pod", "foo-abc12")` == `"pod/foo"` (bei passendem Hash-Suffix)
- `test_resource_identity_applies_stable_name` — volatiler Suffix wird entfernt

### Plugin-Tests — Severity-Assertions auf lowercase umstellen
- `test_falco_plugin.py`: `"CRITICAL"`/`"HIGH"` → `"critical"`/`"warning"`
- `test_k8s_events_plugin.py`: `"HIGH"` → `"warning"`
- `test_prometheus_plugin.py`: `"CRITICAL"`/`"HIGH"` → `"critical"`/`"warning"` (`"info"` unverändert)
- `test_trivy_plugin.py`: `"CRITICAL"`/`"HIGH"` → `"critical"`/`"warning"`

### Plugin-Tests — Identity-Assertions
- `test_pod_logs_plugin.py`: Identity-Erwartung von bare `stable_name(pod_name)` auf
  `f"pod/{stable_name(pod_name)}"` umstellen
- `test_trivy_plugin.py`: neuer Test `test_identity_lowercases_kind_from_label` (Trivy-Operator-
  Label liefert z.B. `"Pod"` als `kind` — Identity muss trotzdem `pod/...` sein)

### `tests/unit/test_dedup.py`
- `test_filter_new_groups_findings_from_different_plugins_with_same_pod_into_one_cr` — je ein
  Finding mit `source="k8s_events"` und `source="trivy"` für denselben Pod-Namen (unterschiedliche
  `kind`-Schreibweise simuliert, z.B. `"Pod"` vs. `"pod"` vor der Normalisierung) landen nach
  Fix in derselben Gruppe/CR (Regressionstest für den eigentlichen Bug hinter Beobachtung 3)

### `tests/unit/test_analyzer.py`
- bestehende Tests, die `"HIGH"`/`"CRITICAL"` als Finding-Severity-Fixtures verwenden, auf
  lowercase umstellen (falls vorhanden)

---

## Done when

`grep -rn '"HIGH"\|"CRITICAL"' src/plugins/*.py` liefert keine Treffer mehr als `Finding.severity`-
Wert (Trivy-CVE-`raw`-Daten ausgenommen, siehe oben). Für denselben physischen Pod erzeugen alle
meldenden Plugins denselben `identity`-Wert; `kubectl get sf` zeigt für eine Resource mit
Findings aus mehreren Quellen genau eine Zeile mit korrekt formatierter `RESOURCE`-Spalte
(`pod/<name>`, nie bare `<name>`). Alle bestehenden Tests bleiben grün (nach Anpassung der
Severity-/Identity-Fixtures), neue Tests kommen hinzu. `kubectl delete sf --all -A` vor dem
nächsten `helm upgrade` im Cluster (Breaking Change an bestehenden CR-Namen durch geänderte
Identity-Strings).
