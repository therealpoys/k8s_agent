# Current Feature: Schritt 6 — LLM Analyzer (`src/analyzer.py`)

## Status

In Progress

## Feature

Analyzer-Modul, das `list[Finding]` von Plugins entgegennimmt, per LLM analysiert und ein `Alert`-Objekt zurückgibt.

## Goals

- `analyze(findings)` wählt den LLM-Provider aus `config.llm_provider` (`openai`, `anthropic`, `ollama`)
- Strukturierter Prompt fordert Severity-Einstufung, Summary und Recommendation als JSON
- LLM-Antwort wird validiert: `severity` muss `"info"` | `"warning"` | `"critical"` sein (Fallback: `"warning"`)
- Gibt ein vollständiges `Alert`-Objekt zurück
- Degraded Mode bei jedem LLM-Fehler: kein Exception-Propagation, Alert mit höchstem Severity aus Findings

## Done When

`analyze([])` gibt ein valides `Alert`-Objekt zurück. Bei fehlender `OPENAI_API_KEY`-Umgebungsvariable läuft der Analyzer im Degraded Mode durch ohne Exception.

## Notes

- Provider-Mapping: `openai` → `ChatOpenAI`, `anthropic` → `ChatAnthropic`, `ollama` → `ChatOpenAI` mit `base_url` + `api_key="ollama"`
- Modell: `config.llm_model`, Timeout: `config.llm_timeout`
- API-Keys nur aus Umgebungsvariablen, nie aus `config.yaml`
- Hilfsfunktion `_highest_severity(findings)` für Degraded Mode
- `logging.getLogger(__name__)` — kein `print()`
- Erlaubte Imports: `json`, `logging`, `datetime`, `src.config`, `src.models` + LangChain je Provider

## History

<!-- Keep this updated. Earliest to latest -->
- **Schritt 1 — Projekt-Setup**: requirements.txt (7 gepinnte Deps), config.yaml, config.yaml.example (inkl. ollama), .env.example, .gitignore
- **Schritt 2 — Datenmodell**: `src/models.py` mit `Finding`- und `Alert`-Dataclasses; vollständige Type Hints, keine Validierungslogik
- **Schritt 3 — Config-Loader**: `src/config.py` mit `Config` Dataclass, `_load_config()` via `pathlib.Path`, Singleton `config`; `FileNotFoundError`/`KeyError` bei fehlenden Feldern, `llm_base_url` optional
- **Schritt 4 — Plugin-Interface**: `src/plugins/__init__.py` (leer) und `src/plugins/base.py` mit `BasePlugin(ABC)`; `run() -> list[Finding]` als `@abstractmethod`, `name` als Klassenattribut
- **Schritt 5 — Erstes Plugin**: `src/plugins/pod_logs.py` mit `PodLogsPlugin`; liest Pod-Logs aus konfigurierten Namespaces via K8s Python Client, In-Cluster/kubeconfig Fallback, dreistufige Fehlerbehandlung (401/403/404/generic); 13 Unit-Tests
