# Prompt — Schritt 7: Console Output (`src/outputs/console.py`)

## Kontext

Schritt 6 (`src/analyzer.py`) ist abgeschlossen. Jetzt bauen wir den einfachsten Output-Kanal: strukturierte Konsolenausgabe. Das erlaubt vollständiges Testen ohne externe Dienste.

## Aufgabe

Erstelle `src/outputs/__init__.py` (leer) und `src/outputs/console.py`.

### Funktion `send`

```python
def send(alert: Alert) -> None:
    """Gibt einen Alert strukturiert auf der Konsole aus."""
```

### Ausgabeformat

Formatiere den Alert lesbar. Beispiel:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[WARNING] K8s Observability Alert
Generated: 2024-01-15 10:30:00 UTC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Summary:
  Two pods in the default namespace are experiencing repeated OOMKilled events.

Recommendation:
  Increase memory limits for affected pods or investigate memory leak.

Findings (2):
  [1] pod_logs / default / my-app-7d9f8b-xkj2p
      Severity: warning
      2024-01-15 10:29:45 | OOMKilled: container exceeded memory limit

  [2] pod_logs / default / my-app-7d9f8b-p8mn3
      Severity: info
      2024-01-15 10:28:12 | Starting container...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Anforderungen

- Severity in Großbuchstaben in der Überschrift (`[WARNING]`, `[CRITICAL]`, `[INFO]`)
- Datum/Uhrzeit aus `alert.generated_at` formatiert als `YYYY-MM-DD HH:MM:SS UTC`
- Findings nummeriert, jedes mit: source / namespace / resource, Severity, Message (erste 200 Zeichen)
- Wenn `alert.findings` leer: trotzdem Ausgabe, aber mit "No findings" anstelle der Liste
- Verwende `logging` für die Ausgabe (`logging.getLogger(__name__).info(...)`) — kein `print()`

### Erlaubte Imports

```python
import logging
from src.models import Alert
```

## Coding Standards

- Kein `print()` — `logging.info()` für die Ausgabe
- Kein bare `except:`
- Keine hardcodierten Farben oder ANSI-Codes (Terminal-Kompatibilität)

## Done when

```python
from src.outputs.console import send
send(alert)
```

gibt einen lesbaren Alert auf der Konsole aus. Läuft ohne Fehler auch wenn `alert.findings` leer ist.
