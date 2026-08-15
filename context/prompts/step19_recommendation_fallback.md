# Prompt — Schritt 19: Fallback-Recommendation bei unvollständiger LLM-Antwort

## Kontext

Beim Live-Test von Schritt 17 im Cluster fiel auf, dass viele `SeenFinding`-CRs Einträge mit
leerer `recommendation` enthalten (`kubectl get sf -o yaml` → `recommendation: ""`). Ursache
gefunden und live verifiziert (2026-08-15, gleicher Cluster):

- `src/analyzer.py::analyze()` erwartet laut Prompt-Regel ("findings array must have exactly one
  entry per input finding") ein `findings[]`-Element pro Input-Finding, inkl. `recommendation`.
- Ein Run mit **6 Findings** in einem LLM-Call: alle 6 bekamen eine Recommendation.
- Ein Run mit **52 Findings** in einem LLM-Call (Debug-Session): deutlich sichtbare Lücken —
  das lokale Ollama-Modell (`qwen3.6:35b-a3b-q4_K_M`) hält die "ein Eintrag pro Finding"-Regel bei
  großen Batches nicht zuverlässig ein.
- Für Indizes, die im `findings[]`-Array der LLM-Antwort fehlen (oder dort ohne/mit leerem
  `recommendation`-Feld auftauchen), bleibt `Finding.recommendation` dauerhaft `None`/`""` —
  `Deduplicator.update_recommendations()` patcht so ein Finding nie (filtert via
  `if f.recommendation:`), die CR behält also für immer eine leere Recommendation, bis (falls
  überhaupt) ein späterer Run zufällig doch einen Treffer liefert.

Das ist kein Bug aus Schritt 17 selbst — der Enrichment-Mechanismus ist seit der letzten
Bugfix-Runde unverändert. Schritt 17 verschärft das Problem aber tendenziell: der Full-Context-
Resend (siehe `context/prompts/step17_seenfinding_aggregation.md`) bündelt bei jeder Änderung
alle Findings einer Resource (alt+neu) erneut in einen Prompt, was die Batch-Größe pro LLM-Call
erhöht — größere Batches erhöhen die Wahrscheinlichkeit unvollständiger LLM-Antworten.

---

## Aufgabe

### `src/analyzer.py` — Fallback nach dem Enrichment-Loop

Nach der bestehenden Schleife, die `per_finding`-Einträge auf `enriched` anwendet (`analyze()`,
aktuell endend bei `enriched[idx] = Finding(...)`), einen zweiten Pass ergänzen: jedes Finding in
`enriched`, dessen `recommendation` weiterhin falsy ist (weder von der LLM explizit gesetzt noch
mit einem nicht-leeren String versehen), bekommt eine Fallback-Recommendation, die auf der
Alert-weiten `recommendation` (`data["recommendation"]`) basiert — mit einer kurzen Kennzeichnung,
damit im `SeenFinding`-CR bzw. in der Konsolen-Ausgabe erkennbar bleibt, dass es sich nicht um
eine finding-spezifische LLM-Aussage handelt:

```python
_FALLBACK_PREFIX = "No specific guidance from the LLM for this finding — see overall recommendation: "

...

per_finding = data.get("findings", [])
enriched = list(findings)
for finding_data in per_finding:
    idx = finding_data.get("index", 0) - 1
    if idx < 0 or idx >= len(enriched):
        continue
    f = enriched[idx]
    f_severity = finding_data.get("severity", f.severity)
    enriched[idx] = Finding(
        source=f.source,
        namespace=f.namespace,
        resource=f.resource,
        severity=f_severity if f_severity in _VALID_SEVERITIES else f.severity,
        message=f.message,
        timestamp=f.timestamp,
        raw=f.raw,
        fingerprint=f.fingerprint,
        identity=f.identity,
        recommendation=finding_data.get("recommendation"),
    )

overall_recommendation = data["recommendation"]
for idx, f in enumerate(enriched):
    if not f.recommendation:
        enriched[idx] = Finding(
            source=f.source,
            namespace=f.namespace,
            resource=f.resource,
            severity=f.severity,
            message=f.message,
            timestamp=f.timestamp,
            raw=f.raw,
            fingerprint=f.fingerprint,
            identity=f.identity,
            recommendation=_FALLBACK_PREFIX + overall_recommendation,
        )
```

Wichtig: Dieser zweite Pass läuft **nur im Happy Path** (innerhalb des bestehenden `try`-Blocks,
nach erfolgreichem `json.loads` und vorhandenem `data["recommendation"]`) — **nicht** in
`_degraded_alert()`. Bei einem kompletten LLM-Ausfall ist die gesamte Analyse fehlgeschlagen
("LLM analysis unavailable"); jedem einzelnen Finding dort zusätzlich denselben generischen
Fallback-Text aufzudrücken würde fälschlich suggerieren, die LLM hätte sich mit dem jeweiligen
Finding befasst.

Keine Änderung nötig an `src/dedup.py` (`update_recommendations()` patcht weiterhin jedes Finding
mit truthy `recommendation` — nach diesem Fix ist das im Happy Path jedes Finding) oder an
`src/graph.py`.

---

## Designentscheidungen

- **Fallback = Alert-weite Recommendation statt generischem Static-String** ("Findings manuell
  prüfen" o.ä.): Die Alert-weite Recommendation ist selbst LLM-generiert und trägt echten Kontext
  zum aktuellen Run — informativer als ein hartkodierter Platzhaltersatz, ohne einen zweiten
  statischen String pflegen zu müssen.
- **Kennzeichnungs-Präfix statt stillem Reuse**: Ohne Präfix sähe die Fallback-Recommendation im
  `SeenFinding`-CR wie eine finding-spezifische LLM-Aussage aus. Der Präfix macht für
  `kubectl get sf -o yaml` und die Konsolen-Ausgabe sofort erkennbar, dass hier keine gezielte
  Analyse dieses einzelnen Findings stattgefunden hat.
- **Nur im Happy Path, nicht im Degraded Mode**: Degraded Mode kommuniziert den kompletten
  LLM-Ausfall bereits klar auf Alert-Ebene (`summary="LLM analysis unavailable"`). Denselben
  Fallback-Text zusätzlich in jedes Finding zu schreiben würde keinen Mehrwert bringen und die
  Unterscheidung zwischen "LLM hat teilweise geantwortet" und "LLM ist komplett ausgefallen"
  verwischen.
- **Fix in `analyzer.py`, nicht in `dedup.py`**: Hält die Garantie "ein `Finding`, das den
  Analyzer erfolgreich durchlaufen hat, hat immer eine `recommendation`" an einer einzigen Stelle
  — `dedup.py` und `console.py` brauchen dadurch weiterhin keine Sonderbehandlung für leere
  Recommendations.

---

## Tests

### `tests/unit/test_analyzer.py`

- `test_finding_without_llm_entry_gets_fallback_recommendation` — LLM-Antwort enthält im
  `findings[]`-Array keinen Eintrag für Index 2 von 2 Findings; `enriched[1].recommendation`
  beginnt mit dem Fallback-Präfix und enthält die Alert-weite Recommendation.
- `test_finding_with_empty_recommendation_string_gets_fallback` — LLM liefert einen Eintrag für
  den Index, aber mit `"recommendation": ""`; gleiche Fallback-Erwartung.
- `test_finding_with_explicit_recommendation_keeps_it` — Regressionstest: ein Finding mit
  vorhandener, nicht-leerer LLM-Recommendation bleibt unverändert (kein Fallback-Präfix).
- `test_degraded_mode_does_not_apply_fallback_text` — bei einem LLM-Fehler (Exception oder
  invalides JSON) bleibt `recommendation` alle Findings weiterhin `None`, kein Fallback-Text.

---

## Done when

Kein Finding, dessen Run erfolgreich (Happy Path, kein Degraded Mode) durch den Analyzer lief,
landet mit leerer `recommendation` in einem `SeenFinding`-CR oder in der Konsolen-Ausgabe — es
gibt entweder eine finding-spezifische LLM-Recommendation oder den gekennzeichneten Fallback auf
die Alert-weite Recommendation. Bestehende Tests bleiben grün, neue Fallback-Tests kommen hinzu.
