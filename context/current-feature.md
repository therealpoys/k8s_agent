# Current Feature: Schritt 3 — Config-Loader (`src/config.py`)

## Status

In Progress

## Feature

Config-Loader, der `config.yaml` einliest und typisierte Konstanten als Singleton-Instanz bereitstellt.

## Goals

- `Config` Dataclass mit allen Feldern aus `config.yaml` (LLM, Kubernetes, Plugins, Outputs, Loop)
- `_load_config()` lädt `config.yaml` relativ zum Projekt-Root via `pathlib.Path`
- Singleton `config: Config = _load_config()` wird beim Import bereitgestellt
- `FileNotFoundError` wenn `config.yaml` fehlt, `KeyError` wenn Pflichtfeld fehlt
- `llm_base_url` ist optional (`None` wenn nicht gesetzt)
- Keine Defaults für Pflichtfelder (`llm_provider`, `namespaces`)

## Done When

```python
from src.config import config
print(config.namespaces)             # ['default']
print(config.loop_interval_seconds)  # 60
print(config.llm_base_url)           # None (oder URL wenn gesetzt)
```

läuft fehlerfrei durch mit einer befüllten `config.yaml`.

## Notes

- Nur erlaubte Imports: `yaml`, `pathlib.Path`, `dataclasses.dataclass`, `logging`
- `pathlib.Path` für alle Pfade — kein `os.path`
- Logging mit `logging.getLogger(__name__)` — kein `print()`
- Specific exceptions — kein bare `except:`
- Keine hardcodierten Pfade oder Namespace-Namen

## History

<!-- Keep this updated. Earliest to latest -->
- **Schritt 1 — Projekt-Setup**: requirements.txt (7 gepinnte Deps), config.yaml, config.yaml.example (inkl. ollama), .env.example, .gitignore
- **Schritt 2 — Datenmodell**: `src/models.py` mit `Finding`- und `Alert`-Dataclasses; vollständige Type Hints, keine Validierungslogik
