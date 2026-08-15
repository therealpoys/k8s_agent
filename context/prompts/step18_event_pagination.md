# Prompt — Schritt 18: Pagination für `list_namespaced_event`

## Kontext

`K8sEventsPlugin._namespace_findings` (`k8s_events.py:31-36`) ruft `list_namespaced_event` ohne
`limit`/`continue` auf und erwartet die komplette Ergebnismenge in einer einzigen Antwort. Das ist
der durchgängige Stil im gesamten Codebase (`pod_logs.py` verhält sich bei `list_namespaced_pod`
identisch) — bislang unkritisch, weil bisherige Namespaces/Testumgebungen klein sind.

Bei Namespaces mit sehr vielen Events (hohe Pod-Churn, viele Deployments, verrauschte
Warning-Events über Zeit) kann eine unpaginierte Anfrage jedoch zu einer sehr großen einzelnen
API-Response führen — mit entsprechendem Speicherverbrauch im Agent-Pod und Risiko, an
`timeout_seconds=10` oder API-Server-seitige Response-Size-Limits zu stoßen. Dieser Schritt macht
das Abrufen robust gegen große Namespaces, indem explizit seitenweise über `continue`-Token
iteriert wird.

Scope: nur `k8s_events.py` / `list_namespaced_event` — das ist die Datei mit dem größten Risiko
(potenziell sehr viele Events pro Namespace über Zeit). `pod_logs.py`/`list_namespaced_pod` bleibt
hier bewusst außen vor (Pod-Anzahl pro Namespace ist typischerweise viel kleiner als Event-Anzahl);
das gleiche Muster lässt sich bei Bedarf später 1:1 übertragen.

---

## Aufgabe

### 1. `src/plugins/k8s_events.py` — paginiertes Fetching

```python
_PAGE_SIZE = 200
```

`_namespace_findings` umbauen, um seitenweise zu sammeln:

```python
def _namespace_findings(self, namespace: str) -> list[Finding]:
    events: list = []
    continue_token: str | None = None

    while True:
        try:
            response = self._core.list_namespaced_event(
                namespace,
                field_selector="type=Warning",
                timeout_seconds=10,
                limit=_PAGE_SIZE,
                _continue=continue_token,
            )
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
            return self._events_to_findings(events, namespace) if events else []

        events.extend(response.items)
        continue_token = response.metadata._continue
        if not continue_token:
            break

    return self._events_to_findings(events, namespace)
```

---

## Designentscheidungen

- **`limit=200`**: bewusst klein genug, um einzelne Responses handhabbar zu halten, aber groß genug,
  dass die meisten Namespaces in einer einzigen Seite durchlaufen (kein unnötiger Overhead im
  Normalfall).
- **Fehler mitten in der Pagination**: Wenn eine spätere Seite fehlschlägt (z.B. 403 nach
  erfolgreicher erster Seite — selten, aber möglich bei RBAC-Änderungen zur Laufzeit), werden die
  bereits gesammelten Events trotzdem zu Findings verarbeitet statt komplett verworfen — besser ein
  unvollständiges Bild als gar keins. Schlägt bereits die erste Seite fehl (`events` leer), bleibt
  das Verhalten identisch zu vorher: `[]`.
- **`_continue` statt `continue`**: Python-Client-Konvention, da `continue` ein reserviertes
  Schlüsselwort ist — der Kubernetes-Python-Client bildet den API-Parameter `continue` auf das
  Funktionsargument `_continue` ab.
- **Kein Umbau von `pod_logs.py`**: außerhalb des Scopes dieses Schritts (siehe Kontext) — bewusst
  nicht mitgezogen, um die Änderung fokussiert und review-bar zu halten.

---

## Tests

### `tests/unit/test_k8s_events_plugin.py` — ergänzen

- `test_namespace_findings_follows_continue_token`: `list_namespaced_event` liefert bei erstem
  Aufruf `items=[event_a]` + `metadata._continue="token-1"`, beim zweiten Aufruf (mit
  `_continue="token-1"`) `items=[event_b]` + `metadata._continue=None` → beide Events landen in den
  Findings, `list_namespaced_event` wurde 2× aufgerufen
- `test_namespace_findings_passes_limit_param`: prüft, dass `limit=_PAGE_SIZE` bei jedem Aufruf
  gesetzt ist
- `test_namespace_findings_stops_when_continue_token_empty`: einzelne Seite ohne `_continue` →
  genau 1 Aufruf
- `test_namespace_findings_returns_partial_results_on_mid_pagination_error`: erster Aufruf liefert
  Events + `_continue`-Token, zweiter Aufruf wirft `ApiException(status=500)` → Findings aus der
  ersten Seite werden trotzdem zurückgegeben (nicht `[]`)
- Bestehender Test `test_run_returns_empty_on_403`/`_404`: weiterhin grün, da erste Seite direkt
  fehlschlägt und `events` leer bleibt

---

## Done when

Ein Namespace mit mehr als `_PAGE_SIZE` Warning-Events liefert vollständige Findings über alle
Seiten hinweg, ohne dass eine einzelne API-Antwort mehr als `_PAGE_SIZE` Items enthalten muss.
Bestehendes Fehlerverhalten (401/403/404/generisch → `[]` bzw. Log) bleibt für den Fall erhalten,
dass bereits die erste Seite fehlschlägt.

Alle bestehenden Tests bleiben grün, neue Pagination-Tests kommen hinzu.
