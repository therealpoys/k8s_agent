# Current Feature

## Status

Not Started

## Feature

<!-- Add feature here -->

## Goals

<!-- Add goals here -->

## Done When

<!-- Add done criteria here -->

## Notes

<!-- Add notes here -->



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
- **Schritt 9 — Einstiegspunkt**: `agent.py` im Projekt-Root; Logging via `LOG_LEVEL`, `load_dotenv()`, `build_graph()` + einmaliges `graph.invoke({})`; `FileNotFoundError` → stderr + exit 1; unerwartete Exceptions um `graph.invoke()` → `CRITICAL` + exit 1; `__main__` Guard; 3 Unit-Tests; Stage 1 abgeschlossen
- **Bugfixes & Ollama-Testlauf**: Multi-Container-Support in `pod_logs.py` (400 Bad Request Fix); per-Finding LLM-Empfehlungen mit index-basiertem Matching; `b'...'` Bytes-Repr bereinigt; `debug.log_llm_io` Flag in config.yaml für LLM Request/Response Logging
- **Ollama-Fix & Schritt-10-Prompt**: `/v1`-Suffix für Ollama-Endpoint in `analyzer.py`; korrekter Modellname `qwen3.6:35b-a3b-q4_K_M`; `context/prompts/step10_pod_context.md` — Spec für Pod-Spec/Status/Events-Kontext im LLM-Prompt
- **Schritt 10 — Pod-Spec, Status & Events als Kontext**: `pod_logs.py` erweitert um Image, Ressourcen (requests/limits), Probes, Phase, Restart-Count, Ready und Container-State (inkl. CrashLoop-Erkennung); Events per Pod via `list_namespaced_event` (nur Warning oder count>1, API-Fehler → leere Liste); `analyzer.py` rendert pro Finding einen strukturierten Block im LLM-Prompt; `_format_finding_block()` + aktualisiertes Prompt-Template; Tests repariert (Multi-Container-Regression) und erweitert; 75 Tests grün
- **Bugfixes — Init-Container, CrashLoop-Logs & Command-Kontext**: Init-Container-Support in `pod_logs.py` (spec.init_containers + status.init_container_statuses); 400-Fehler-Fix für wartende Container (ImagePullBackOff etc.) durch bedingten Log-Abruf; `previous=True` für CrashLoopBackOff um letzte Crash-Logs zu lesen; `command`/`args` und `last_exit_code` als Kontext im Finding + LLM-Prompt damit das LLM fehlerhafte Entrypoints direkt erkennt
