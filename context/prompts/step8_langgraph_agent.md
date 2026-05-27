# Prompt — Schritt 8: LangGraph Agent (`src/graph.py`)

## Kontext

Alle Bausteine sind fertig: `models.py`, `config.py`, `plugins/pod_logs.py`, `analyzer.py`, `outputs/console.py`. Jetzt verdrahten wir alles in einem LangGraph `StateGraph`.

## Aufgabe

Erstelle `src/graph.py`.

### State-Schema

Definiere ein explizites `TypedDict` für den Agent-State:

```python
from typing import TypedDict
from src.models import Finding, Alert

class AgentState(TypedDict):
    findings: list[Finding]
    alert: Alert | None
```

### Graph-Aufbau

Der Agent führt einen einzelnen Zyklus durch (kein Loop — der kommt in Stage 2):

```
START → collect_findings → analyze_findings → send_output → END
```

**Node: `collect_findings`**
- Instanziiert `PodLogsPlugin` und ruft `run()` auf
- Gibt `{"findings": findings}` zurück
- Bei Plugin-Fehler: logge `ERROR`, gib leere Liste zurück — nie crashen

**Node: `analyze_findings`**
- Ruft `analyzer.analyze(state["findings"])` auf
- Gibt `{"alert": alert}` zurück

**Node: `send_output`**
- Ruft `console.send(state["alert"])` auf
- Gibt State unverändert zurück

### Kompilierter Graph

Exportiere eine Funktion:

```python
def build_graph() -> CompiledGraph:
    """Baut und kompiliert den LangGraph Agent."""
```

### Erlaubte Imports

```python
import logging
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from src.models import Finding, Alert
from src.plugins.pod_logs import PodLogsPlugin
from src import analyzer
from src.outputs import console
```

## Coding Standards

- Agent-Definition ausschließlich in `graph.py` — kein Agent-Code in anderen Modulen
- State-Schema explizit als `TypedDict` — kein `dict`
- Nodes als private Funktionen mit Prefix `_` (`_collect_findings`, `_analyze_findings`, `_send_output`)
- Logging mit `logging.getLogger(__name__)`

## Done when

```python
from src.graph import build_graph
graph = build_graph()
graph.invoke({})
```

führt einen vollständigen Zyklus durch: Logs lesen → analysieren → auf Konsole ausgeben, ohne Exception.
