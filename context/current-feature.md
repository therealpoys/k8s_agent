# Current Feature

## Status

Not Started

## Feature

**Stage 1 — Fundament**

Lauffähiger LangGraph Agent mit erstem Tool: Pod Logs lesen und per LLM analysieren.

## Goals

- LangGraph Agent Skeleton aufsetzen (`src/graph.py`)
- Tool implementieren: Pod Logs lesen via Kubernetes Python Client (`src/plugins/pod_logs.py`)
- LLM analysiert Logs und gibt strukturierte Einschätzung zurück (`src/analyzer.py`)
- Output: Konsolenausgabe

## Done When

Agent liest Logs eines Pods und gibt strukturierte Analyse aus (Severity + Zusammenfassung + Empfehlung).

## Notes

<!-- Add notes here -->

## History

<!-- Keep this updated. Earliest to latest -->
