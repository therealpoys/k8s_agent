# Prompt — Schritt 9: Einstiegspunkt (`agent.py`)

## Kontext

Schritt 8 (`src/graph.py`) ist abgeschlossen. Alle Teile sind vorhanden. Jetzt bauen wir den minimalen Einstiegspunkt, der alles zusammensetzt und `python agent.py` lauffähig macht.

Stage 1 ist nach diesem Schritt abgeschlossen. Loop-Mechanismus und weiteres kommen in Stage 2.

## Aufgabe

Erstelle `agent.py` im Projekt-Root.

### Was `agent.py` tut

1. Logging konfigurieren (Level aus Umgebungsvariable `LOG_LEVEL`, Default `INFO`)
2. `.env` laden via `python-dotenv`
3. `build_graph()` aufrufen
4. Den Graph einmalig mit `graph.invoke({})` starten
5. Sauber beenden

### Logging-Setup

```python
import logging
import os

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
```

### Fehlerbehandlung

- Wenn `config.yaml` nicht existiert: Fehlermeldung ausgeben und mit Exit-Code 1 beenden
- Alle anderen unerwarteten Exceptions: logge `CRITICAL` mit Traceback, Exit-Code 1
- **Kein** `try/except Exception` um die gesamte Logik — nur um den `graph.invoke()` Aufruf

### Erlaubte Imports

```python
import logging
import os
import sys
from dotenv import load_dotenv
from src.graph import build_graph
```

### Struktur

```python
def main() -> None:
    ...

if __name__ == "__main__":
    main()
```

## Coding Standards

- `logging.getLogger(__name__)` — kein `print()` nach dem Logging-Setup
- Kein Agent-Code in `agent.py` — nur Initialisierung und Aufruf
- `if __name__ == "__main__":` Guard zwingend

## Done when

```bash
python agent.py
```

läuft durch, gibt strukturierte Analyse auf der Konsole aus, und beendet sich sauber. Stage 1 ist abgeschlossen.
