# Coding Standards

## Python Style

- Follow **PEP 8** strictly
- Max line length: **100 characters**
- Use **type hints** on all function signatures
- Use **f-strings** for string formatting (no `.format()` or `%`)
- Use `pathlib.Path` for all file paths (no `os.path`)
- Prefer **dataclasses** for structured data (see `src/models.py`)

## Naming

- `snake_case` for variables, functions, modules
- `PascalCase` for classes
- `UPPER_SNAKE_CASE` for constants
- Prefix private functions with `_`

## Functions & Modules

- One responsibility per function
- Module structure: `src/plugins/`, `src/analyzer.py`, `src/outputs/`, `src/config.py`, `src/graph.py`
- No circular imports

## Error Handling

- Always catch specific exceptions — never bare `except:`
- Log errors with context (source, namespace, resource, exception message)
- Plugin-Fehler müssen graceful behandelt werden (Plugin überspringen, Rest läuft weiter)
- K8s API Fehler (401, 403, 404) explizit abfangen und loggen
- Bei LLM-Fehler: Alert ohne LLM-Analyse ausgeben (degraded mode), nicht abbrechen

## Logging

- Use Python's built-in `logging` module — kein `print()` in production code
- Log level convention:
  - `DEBUG` — rohe K8s-Responses, LLM-Prompt/Response
  - `INFO` — normaler Ablauf (Loop-Start, Plugin geladen, X Findings, Alert gesendet)
  - `WARNING` — recoverable issues (Plugin-Timeout, keine Pods im Namespace)
  - `ERROR` — Fehler die den Loop-Zyklus beeinflussen

## LangGraph

- Agent-Definition in `src/graph.py` — kein Agent-Code außerhalb
- Tools als separate Funktionen mit `@tool` Decorator
- State-Schema explizit definieren (TypedDict)
- Loop-Mechanismus über `StateGraph` mit konditionalen Edges

## LLM

- LLM-Client via Config wählbar — nie hardcoden welcher Provider
- LLM-Output validieren: Severity-Wert gültig? Mindestlänge?
- Timeout auf jeden LLM-Call setzen
- Bei LLM-Fehler: Findings ohne Summary weitergeben (degraded mode)

## Kubernetes Client

- Offiziellen Python Client verwenden: `kubernetes` Package
- In-Cluster-Config (`config.incluster_config()`) und lokal (`config.load_kube_config()`) beide unterstützen
- Namespace-Liste aus `config.yaml` — nie hardcoden
- K8s API Calls immer mit Timeout
- Keine echten K8s API-Calls in Unit Tests — immer mocken

## Plugin-System

- Jedes Plugin erbt von `src/plugins/base.py` `BasePlugin`
- Plugins geben immer `list[Finding]` zurück
- Plugin-Aktivierung ausschließlich über `config.yaml` — nie im Code entscheiden ob Plugin läuft
- Plugin-Fehler dürfen den Agent-Loop nicht crashen

## Config & Secrets

- Cluster-Credentials nie im Code oder `config.yaml`
- `config.yaml` liegt im Repo, Secrets in `.env` / K8s Secrets
- `config.py` lädt `config.yaml` und exponiert typisierte Konstanten
- `.env` ist in `.gitignore`, `.env.example` liegt im Repo

## General

- No commented-out code in commits
- No hardcoded Namespace-Namen, URLs oder Tokens
- Dependencies pinned in `requirements.txt`
