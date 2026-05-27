# Current Feature: Plugin-Interface (src/plugins/base.py)

## Status

In Progress

## Feature

Abstrakte Basisklasse `BasePlugin` für alle Plugins definieren.

## Goals

- `src/plugins/__init__.py` (leer) erstellen
- `src/plugins/base.py` mit `BasePlugin(ABC)` erstellen
- `run()` mit `@abstractmethod` dekoriert, gibt `list[Finding]` zurück
- `name` als Klassenattribut (kein `__init__`, kein Instanzattribut)
- Keine Implementierungslogik — reines Interface

## Done When

- `from src.plugins.base import BasePlugin` ist ohne ImportError importierbar
- Eine Subklasse ohne `run()`-Implementierung wirft `TypeError` beim Instanziieren

## Notes

- Erlaubte Imports: `from abc import ABC, abstractmethod` und `from src.models import Finding`
- Kein `print()`, keine Logging-Calls
- PEP 8, max. 100 Zeichen pro Zeile

## History

<!-- Keep this updated. Earliest to latest -->
- **Schritt 1 — Projekt-Setup**: requirements.txt (7 gepinnte Deps), config.yaml, config.yaml.example (inkl. ollama), .env.example, .gitignore
- **Schritt 2 — Datenmodell**: `src/models.py` mit `Finding`- und `Alert`-Dataclasses; vollständige Type Hints, keine Validierungslogik
- **Schritt 3 — Config-Loader**: `src/config.py` mit `Config` Dataclass, `_load_config()` via `pathlib.Path`, Singleton `config`; `FileNotFoundError`/`KeyError` bei fehlenden Feldern, `llm_base_url` optional
