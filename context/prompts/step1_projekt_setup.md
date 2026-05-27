# Prompt — Schritt 1: Projekt-Setup

## Kontext

Wir bauen einen K8s Observability Agent mit LangGraph. Dieses ist der allererste Schritt — noch kein Code existiert. Das Ziel ist eine lauffähige Python-Umgebung mit allen nötigen Dateien.

Projektstruktur (geplant):
```
k8s_agent/
├── config.yaml
├── config.yaml.example
├── requirements.txt
├── .env.example
├── .gitignore
├── agent.py
└── src/
    ├── config.py
    ├── models.py
    ├── graph.py
    ├── analyzer.py
    ├── plugins/
    │   ├── __init__.py
    │   ├── base.py
    │   ├── pod_logs.py
    │   └── k8s_events.py
    └── outputs/
        ├── __init__.py
        └── console.py
```

## Aufgabe

Erstelle folgende Dateien:

### `requirements.txt`
Pinne alle Dependencies mit exakten Versionen (`==`). Benötigte Pakete:
- `langgraph`
- `langchain-openai`
- `langchain-anthropic`
- `kubernetes`
- `pyyaml`
- `python-dotenv`
- `pydantic`

### `config.yaml`
Vollständige, befüllte Konfiguration (kein Platzhalter-Text):
```yaml
llm:
  provider: openai        # "openai" | "anthropic"
  model: gpt-4o-mini
  timeout_seconds: 30

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

### `config.yaml.example`
Identisch mit `config.yaml`, aber alle Werte sind aussagekräftige Beispiele/Platzhalter. Dient als Template für neue Nutzer.

### `.env.example`
Enthält alle nötigen Umgebungsvariablen als Beispiel:
```
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

### `.gitignore`
Sinnvolle `.gitignore` für ein Python-Projekt. Muss zwingend enthalten:
- `.env`
- `config.yaml` (nur `.example` ins Repo)
- `__pycache__/`, `*.pyc`, `.venv/`, `*.egg-info/`

## Coding Standards

- Keine kommentierten Code-Blöcke
- Keine hardcodierten Secrets
- Dependencies in `requirements.txt` mit `==` gepinnt

## Done when

- `pip install -r requirements.txt` läuft fehlerfrei durch
- `config.yaml` ist befüllt und valide YAML
- `.env.example` zeigt alle nötigen Keys
- `.gitignore` schließt `.env` und `config.yaml` aus
