# Current Feature: Schritt 2 — Datenmodell (`src/models.py`)

## Status

In Progress

## Feature

Erstelle `src/models.py` mit den Dataclasses `Finding` und `Alert`, die als gemeinsame Typen für Plugins, Analyzer und Outputs dienen.

## Goals

- `Finding`-Dataclass mit Feldern: `source`, `namespace`, `resource`, `severity`, `message`, `timestamp`, `raw`
- `Alert`-Dataclass mit Feldern: `findings`, `severity`, `summary`, `recommendation`, `generated_at`
- Vollständige Type Hints, keine `Any`-Typen
- Nur erlaubte Imports: `from dataclasses import dataclass` und `from datetime import datetime`
- Keine Validierungslogik in den Dataclasses — nur Datenstruktur
- `from src.models import Finding, Alert` läuft ohne ImportError

## Done When

`from src.models import Finding, Alert` ist in einer leeren Python-Datei ausführbar ohne ImportError.

## Notes

- Severity-Werte (`"info"`, `"warning"`, `"critical"`) werden **nicht** per Enum erzwungen — das ist Aufgabe des Analyzers
- Kein `print()`, keine Logging-Calls
- PEP 8, max. 100 Zeichen pro Zeile, snake_case für Felder, PascalCase für Klassen
- Keine kommentierten Code-Blöcke

## History

<!-- Keep this updated. Earliest to latest -->
- **Schritt 1 — Projekt-Setup**: requirements.txt (7 gepinnte Deps), config.yaml, config.yaml.example (inkl. ollama), .env.example, .gitignore
