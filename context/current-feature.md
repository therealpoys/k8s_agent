# Current Feature: Schritt 7 — Console Output (`src/outputs/console.py`)

## Status

In Progress

## Feature

Strukturierter Console Output-Kanal für Alerts. Erstelle `src/outputs/__init__.py` (leer) und `src/outputs/console.py` mit einer `send(alert: Alert) -> None`-Funktion.

## Goals

- `src/outputs/__init__.py` (leer) und `src/outputs/console.py` existieren
- `send(alert)` gibt den Alert lesbar via `logging.info()` aus (kein `print()`)
- Ausgabeformat: Trennlinie, `[SEVERITY]`-Header, Timestamp als `YYYY-MM-DD HH:MM:SS UTC`, Summary, Recommendation, nummerierte Findings mit source/namespace/resource, Severity und Message (max 200 Zeichen)
- Bei leerem `alert.findings`: Ausgabe mit "No findings" statt der Liste
- Severity in der Überschrift in Großbuchstaben (`[WARNING]`, `[CRITICAL]`, `[INFO]`)
- Nur erlaubte Imports: `logging` und `from src.models import Alert`
- Kein bare `except:`, keine ANSI-Codes, keine hardcodierten Farben

## Done When

```python
from src.outputs.console import send
send(alert)
```
gibt einen lesbaren Alert auf der Konsole aus. Läuft ohne Fehler auch wenn `alert.findings` leer ist.

## Notes

- Datum/Uhrzeit aus `alert.generated_at` formatiert als `YYYY-MM-DD HH:MM:SS UTC`
- Trennlinie: `━` × 50 Zeichen
- Message auf erste 200 Zeichen kürzen
- Einfachster Output-Kanal — kein externer Dienst nötig, erlaubt vollständiges lokales Testen

## History

<!-- Keep this updated. Earliest to latest -->
- **Schritt 1 — Projekt-Setup**: requirements.txt (7 gepinnte Deps), config.yaml, config.yaml.example (inkl. ollama), .env.example, .gitignore
- **Schritt 2 — Datenmodell**: `src/models.py` mit `Finding`- und `Alert`-Dataclasses; vollständige Type Hints, keine Validierungslogik
- **Schritt 3 — Config-Loader**: `src/config.py` mit `Config` Dataclass, `_load_config()` via `pathlib.Path`, Singleton `config`; `FileNotFoundError`/`KeyError` bei fehlenden Feldern, `llm_base_url` optional
- **Schritt 4 — Plugin-Interface**: `src/plugins/__init__.py` (leer) und `src/plugins/base.py` mit `BasePlugin(ABC)`; `run() -> list[Finding]` als `@abstractmethod`, `name` als Klassenattribut
- **Schritt 5 — Erstes Plugin**: `src/plugins/pod_logs.py` mit `PodLogsPlugin`; liest Pod-Logs aus konfigurierten Namespaces via K8s Python Client, In-Cluster/kubeconfig Fallback, dreistufige Fehlerbehandlung (401/403/404/generic); 13 Unit-Tests
- **Schritt 6 — LLM Analyzer**: `src/analyzer.py` mit `analyze(findings) -> Alert`; Provider-Auswahl (openai/anthropic/ollama), strukturierter JSON-Prompt, Severity-Validierung, Degraded Mode bei jedem LLM-Fehler; 18 Unit-Tests
