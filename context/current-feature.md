# Current Feature: Schritt 9 — Einstiegspunkt (`agent.py`)

## Status

In Progress

## Feature

Minimaler Einstiegspunkt `agent.py` im Projekt-Root, der Logging konfiguriert, `.env` lädt, den LangGraph-Graphen baut und einmalig ausführt. Schließt Stage 1 ab.

## Goals

- `agent.py` im Projekt-Root erstellen
- Logging via `LOG_LEVEL` Env-Variable konfigurieren (Default `INFO`)
- `.env` via `python-dotenv` laden
- `build_graph()` aufrufen und Graph einmalig mit `graph.invoke({})` starten
- Fehlerbehandlung: `FileNotFoundError` für fehlende `config.yaml` → Exit-Code 1; unerwartete Exceptions um `graph.invoke()` → `CRITICAL`-Log + Exit-Code 1
- `if __name__ == "__main__":` Guard

## Done When

`python agent.py` läuft durch, gibt strukturierte Analyse auf der Konsole aus und beendet sich sauber. Stage 1 ist abgeschlossen.

## Notes

- Erlaubte Imports: `logging`, `os`, `sys`, `dotenv.load_dotenv`, `src.graph.build_graph`
- Kein `print()` nach dem Logging-Setup — nur `logging.getLogger(__name__)`
- Kein Agent-Code in `agent.py` — nur Initialisierung und Aufruf
- `try/except Exception` nur um `graph.invoke()`, nicht um die gesamte Logik
- Logging-Format: `"%(asctime)s [%(levelname)s] %(name)s: %(message)s"`, datefmt `"%Y-%m-%d %H:%M:%S"`

## History

<!-- Keep this updated. Earliest to latest -->
- **Schritt 1 — Projekt-Setup**: requirements.txt (7 gepinnte Deps), config.yaml, config.yaml.example (inkl. ollama), .env.example, .gitignore
- **Schritt 2 — Datenmodell**: `src/models.py` mit `Finding`- und `Alert`-Dataclasses; vollständige Type Hints, keine Validierungslogik
- **Schritt 3 — Config-Loader**: `src/config.py` mit `Config` Dataclass, `_load_config()` via `pathlib.Path`, Singleton `config`; `FileNotFoundError`/`KeyError` bei fehlenden Feldern, `llm_base_url` optional
- **Schritt 4 — Plugin-Interface**: `src/plugins/__init__.py` (leer) und `src/plugins/base.py` mit `BasePlugin(ABC)`; `run() -> list[Finding]` als `@abstractmethod`, `name` als Klassenattribut
- **Schritt 5 — Erstes Plugin**: `src/plugins/pod_logs.py` mit `PodLogsPlugin`; liest Pod-Logs aus konfigurierten Namespaces via K8s Python Client, In-Cluster/kubeconfig Fallback, dreistufige Fehlerbehandlung (401/403/404/generic); 13 Unit-Tests
- **Schritt 6 — LLM Analyzer**: `src/analyzer.py` mit `analyze(findings) -> Alert`; Provider-Auswahl (openai/anthropic/ollama), strukturierter JSON-Prompt, Severity-Validierung, Degraded Mode bei jedem LLM-Fehler; 18 Unit-Tests
- **Schritt 7 — Console Output**: `src/outputs/__init__.py` (leer) und `src/outputs/console.py` mit `send(alert) -> None`; strukturierte Ausgabe via `logging.info()`, Trennlinien, `[SEVERITY]`-Header, Timestamp als UTC, nummerierte Findings mit Message-Kürzung auf 200 Zeichen, "No findings" bei leerer Liste; 12 Unit-Tests
- **Schritt 8 — LangGraph Agent**: `src/graph.py` mit `AgentState` TypedDict, `build_graph() -> CompiledGraph`; drei private Nodes (`_collect_findings`, `_analyze_findings`, `_send_output`); Graph-Fluss START→collect→analyze→send→END; Fehlerbehandlung in collect (Exception → leere Liste, nie crashen); 10 Unit-Tests
