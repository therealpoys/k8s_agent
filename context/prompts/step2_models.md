# Prompt — Schritt 2: Datenmodell (`src/models.py`)

## Kontext

Schritt 1 (Projekt-Setup) ist abgeschlossen. Jetzt definieren wir das Datenmodell, auf das sich alle anderen Module stützen. Dieses File wird zuerst gebaut, weil Plugins, Analyzer und Outputs alle dieselben Typen importieren müssen.

## Aufgabe

Erstelle `src/models.py` mit zwei Dataclasses: `Finding` und `Alert`.

### `Finding`

Repräsentiert einen Einzelbefund aus einem Plugin-Lauf:

```python
@dataclass
class Finding:
    source: str          # "pod_logs" | "k8s_events" | "trivy" | "falco"
    namespace: str
    resource: str        # Pod-Name, Deployment-Name, etc.
    severity: str        # "info" | "warning" | "critical"
    message: str         # Rohtext aus der Quelle
    timestamp: datetime
    raw: dict | None     # Originaldaten für Debugging
```

### `Alert`

Aggregiert mehrere `Finding`-Objekte und enthält die LLM-Analyse:

```python
@dataclass
class Alert:
    findings: list[Finding]
    severity: str        # Höchster Schweregrad aus findings
    summary: str         # LLM-generierte Zusammenfassung
    recommendation: str  # LLM-generierte Handlungsempfehlung
    generated_at: datetime
```

### Anforderungen

- Beide Klassen als `@dataclass`
- Vollständige Type Hints (kein `Any`)
- `datetime` aus `datetime` importieren
- Keine Validierungslogik in den Dataclasses selbst — nur Datenstruktur
- Severity-Werte `"info"`, `"warning"`, `"critical"` werden **nicht** per Enum erzwungen — das ist Aufgabe des Analyzers

### Erlaubte Imports

```python
from dataclasses import dataclass
from datetime import datetime
```

## Coding Standards

- PEP 8, max. 100 Zeichen pro Zeile
- snake_case für Felder, PascalCase für Klassen
- Kein `print()`, keine Logging-Calls — das ist ein reines Datenmodell
- Keine kommentierten Code-Blöcke

## Done when

`from src.models import Finding, Alert` ist in einer leeren Python-Datei ausführbar ohne ImportError.
