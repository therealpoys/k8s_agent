# Current Feature: Schritt 8 — LangGraph Agent

## Status

In Progress

## Feature

Erstelle `src/graph.py` — verdrahtet alle Bausteine (plugins, analyzer, console output) in einem LangGraph `StateGraph` mit drei Nodes: collect → analyze → send.

## Goals

- `AgentState` TypedDict mit `findings: list[Finding]` und `alert: Alert | None`
- Graph-Fluss: `START → collect_findings → analyze_findings → send_output → END`
- `_collect_findings`: instanziiert `PodLogsPlugin`, ruft `run()` auf; bei Fehler leere Liste zurückgeben, nie crashen
- `_analyze_findings`: ruft `analyzer.analyze()` auf, gibt `{"alert": alert}` zurück
- `_send_output`: ruft `console.send()` auf, gibt State unverändert zurück
- `build_graph() -> CompiledGraph` als exportierte Funktion
- Nodes als private Funktionen (`_`-Prefix), Logging via `logging.getLogger(__name__)`

## Done When

```python
from src.graph import build_graph
graph = build_graph()
graph.invoke({})
```

führt einen vollständigen Zyklus durch (Logs lesen → analysieren → Konsolenausgabe) ohne Exception.

## Notes

- Erlaubte Imports: `logging`, `typing.TypedDict`, `langgraph.graph` (StateGraph/START/END), `src.models`, `src.plugins.pod_logs`, `src.analyzer`, `src.outputs.console`
- Kein Agent-Code außerhalb von `graph.py`
- State-Schema explizit als TypedDict, kein generisches `dict`
- Kein Loop in Stage 1 — single cycle only

## History

<!-- Keep this updated. Earliest to latest -->
- **Schritt 1 — Projekt-Setup**: requirements.txt (7 gepinnte Deps), config.yaml, config.yaml.example (inkl. ollama), .env.example, .gitignore
- **Schritt 2 — Datenmodell**: `src/models.py` mit `Finding`- und `Alert`-Dataclasses; vollständige Type Hints, keine Validierungslogik
- **Schritt 3 — Config-Loader**: `src/config.py` mit `Config` Dataclass, `_load_config()` via `pathlib.Path`, Singleton `config`; `FileNotFoundError`/`KeyError` bei fehlenden Feldern, `llm_base_url` optional
- **Schritt 4 — Plugin-Interface**: `src/plugins/__init__.py` (leer) und `src/plugins/base.py` mit `BasePlugin(ABC)`; `run() -> list[Finding]` als `@abstractmethod`, `name` als Klassenattribut
- **Schritt 5 — Erstes Plugin**: `src/plugins/pod_logs.py` mit `PodLogsPlugin`; liest Pod-Logs aus konfigurierten Namespaces via K8s Python Client, In-Cluster/kubeconfig Fallback, dreistufige Fehlerbehandlung (401/403/404/generic); 13 Unit-Tests
- **Schritt 6 — LLM Analyzer**: `src/analyzer.py` mit `analyze(findings) -> Alert`; Provider-Auswahl (openai/anthropic/ollama), strukturierter JSON-Prompt, Severity-Validierung, Degraded Mode bei jedem LLM-Fehler; 18 Unit-Tests
- **Schritt 7 — Console Output**: `src/outputs/__init__.py` (leer) und `src/outputs/console.py` mit `send(alert) -> None`; strukturierte Ausgabe via `logging.info()`, Trennlinien, `[SEVERITY]`-Header, Timestamp als UTC, nummerierte Findings mit Message-Kürzung auf 200 Zeichen, "No findings" bei leerer Liste; 12 Unit-Tests
