# Prompt — Schritt 3: Config-Loader (`src/config.py`)

## Kontext

Schritt 2 (`src/models.py`) ist abgeschlossen. Jetzt bauen wir den Config-Loader, der `config.yaml` einliest und typisierte Konstanten bereitstellt. Plugins und der Analyzer benötigen diese Werte — daher muss dieser Schritt vor den Plugins fertig sein.

## Aufgabe

Erstelle `src/config.py`.

### Struktur von `config.yaml` (Referenz)

```yaml
llm:
  provider: openai        # "openai" | "anthropic" | "ollama"
  model: gpt-4o-mini
  timeout_seconds: 30
  base_url: null          # Optional — für Ollama: "http://localhost:11434"

kubernetes:
  namespaces:
    - default
  log_lines: 100

plugins:
  core:
    - pod_logs
  optional:
    trivy: false
    falco: false
    prometheus: false

outputs:
  - console

loop_interval_seconds: 60
```

### Was `config.py` exponieren muss

Definiere eine `Config` Dataclass mit folgenden Feldern:

```python
@dataclass
class Config:
    # LLM
    llm_provider: str           # "openai" | "anthropic" | "ollama"
    llm_model: str
    llm_timeout: int            # Sekunden
    llm_base_url: str | None    # Optional — für Ollama oder custom endpoints

    # Kubernetes
    namespaces: list[str]
    log_lines: int

    # Plugins
    core_plugins: list[str]
    optional_plugins: dict[str, bool]

    # Outputs
    outputs: list[str]

    # Loop
    loop_interval_seconds: int
```

Lade die `config.yaml` beim Import und stelle eine Singleton-Instanz bereit:

```python
config: Config = _load_config()
```

### Laderoutine

- Suche `config.yaml` relativ zum Projekt-Root (nicht relativ zum aufrufenden Script)
- Verwende `pathlib.Path` für den Pfad
- Wenn `config.yaml` nicht existiert: `FileNotFoundError` mit klarer Fehlermeldung
- Wenn ein Pflichtfeld fehlt: `KeyError` mit Feldname in der Fehlermeldung
- `llm_base_url` ist optional — `None` wenn nicht gesetzt
- Keine Defaults für Pflichtfelder (`llm_provider`, `namespaces`) — fehlende Werte sollen sofort auffallen

### Erlaubte Imports

```python
import yaml
from pathlib import Path
from dataclasses import dataclass
```

## Coding Standards

- `pathlib.Path` für alle Pfade — kein `os.path`
- Logging mit `logging.getLogger(__name__)` — kein `print()`
- Specific exceptions — kein bare `except:`
- Keine hardcodierten Pfade oder Namespace-Namen

## Done when

```python
from src.config import config
print(config.namespaces)             # ['default']
print(config.loop_interval_seconds)  # 60
print(config.llm_base_url)           # None (oder URL wenn gesetzt)
```

läuft fehlerfrei durch mit einer befüllten `config.yaml`.
