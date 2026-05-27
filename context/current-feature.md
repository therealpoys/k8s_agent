# Current Feature: Schritt 1 — Projekt-Setup

## Status

In Progress

## Feature

**Stage 1 — Fundament**

Lauffähiger LangGraph Agent mit erstem Tool: Pod Logs lesen und per LLM analysieren.

## Goals

- `requirements.txt` mit gepinnten Versionen (`==`) für: langgraph, langchain-openai, langchain-anthropic, kubernetes, pyyaml, python-dotenv, pydantic
- `config.yaml` vollständig befüllt und valide YAML (LLM-Provider, Namespaces, Plugins, Outputs, Loop-Interval)
- `config.yaml.example` identisch als Template für neue Nutzer
- `.env.example` mit allen nötigen Keys (OPENAI_API_KEY, ANTHROPIC_API_KEY)
- `.gitignore` schließt `.env` und `config.yaml` aus, deckt Python-Standard-Artefakte ab

## Done When

- `pip install -r requirements.txt` läuft fehlerfrei durch
- `config.yaml` ist befüllt und valide YAML
- `.env.example` zeigt alle nötigen Keys
- `.gitignore` schließt `.env` und `config.yaml` aus

## Notes

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

Coding Standards:
- Keine kommentierten Code-Blöcke
- Keine hardcodierten Secrets
- Dependencies in `requirements.txt` mit `==` gepinnt

## History

<!-- Keep this updated. Earliest to latest -->
