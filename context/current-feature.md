# Current Feature: Schritt 10 — Pod-Spec, Status & Events als Kontext

## Status

In Progress

## Feature

Extend `pod_logs.py` to collect per-container pod spec, status fields, and Kubernetes events alongside log lines. Extend `analyzer.py` to include these new fields in the LLM prompt as a structured, readable block per finding.

## Goals

- `pod_logs.py` enriches each Finding's `raw` dict with: `image`, `resources` (requests/limits), `liveness_probe`, `readiness_probe`, `phase`, `restart_count`, `ready`, `state`, and `events`
- Container status is matched by name (not index); missing status fields default to safe values (0 / False / "unknown")
- Kubernetes events are fetched per pod via `list_namespaced_event` with `field_selector`; only Warning events or those with `count > 1` are included; API errors result in an empty list (logged as warning, never a crash)
- `analyzer.py` renders each Finding as a structured block in the prompt (image, phase, state, restarts, probes, limits, events, then logs) — not a raw dict dump
- LLM output references restarts, state, and events — not just log content

## Done When

The LLM receives a prompt block per finding resembling:
```
Pod: my-app-7d9f8b-xkj2p / my-app
Image: my-registry/my-app:v1.2.3
Phase: Running | State: waiting:CrashLoopBackOff | Restarts: 5 | Ready: false
Limits: cpu=500m, memory=256Mi | Requests: cpu=100m, memory=128Mi
Probes: liveness=true, readiness=false
Events:
  [Warning] BackOff (x12): Back-off restarting failed container
Logs (last 100 lines):
  ...
```

## Notes

- No breaking change to the `Finding` data model — all new data goes into the existing `raw` dict
- Events API failures must not abort the pod run — always `try/except`, empty list on error, `logger.warning`
- Container status matching by container name, not list index
- No `print()` — only `logger.*`
- `container_statuses` list on `pod.status` can be `None`



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
