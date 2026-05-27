# Prompt — Schritt 6: LLM Analyzer (`src/analyzer.py`)

## Kontext

Schritt 5 (`PodLogsPlugin`) ist abgeschlossen. Jetzt bauen wir den Analyzer, der `list[Finding]` vom Plugin entgegennimmt, per LLM analysiert und ein `Alert`-Objekt zurückgibt.

## Aufgabe

Erstelle `src/analyzer.py`.

### Funktion `analyze`

```python
def analyze(findings: list[Finding]) -> Alert:
    """Analysiert Findings via LLM und gibt einen Alert zurück."""
```

### LLM-Provider-Auswahl

Der Provider wird aus `config.llm_provider` gelesen:

| `config.llm_provider` | Zu verwendender LangChain-Client |
|---|---|
| `"openai"` | `langchain_openai.ChatOpenAI` |
| `"anthropic"` | `langchain_anthropic.ChatAnthropic` |
| `"ollama"` | `langchain_openai.ChatOpenAI` mit `base_url=config.llm_base_url` und `api_key="ollama"` |

- Modell: `config.llm_model`
- Timeout: `config.llm_timeout` Sekunden
- API-Keys aus Umgebungsvariablen (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`) — nie aus `config.yaml`

### Prompt-Design

Baue einen strukturierten Prompt der das LLM anweist:
1. Die übergebenen Findings zu bewerten
2. Den Schweregrad einzustufen: `"info"` | `"warning"` | `"critical"`
3. Eine kurze Zusammenfassung (2-3 Sätze) zu geben
4. Eine konkrete Handlungsempfehlung zu geben

Erwarte die Antwort als JSON:
```json
{
  "severity": "warning",
  "summary": "...",
  "recommendation": "..."
}
```

### Rückgabe

- Parse die LLM-Antwort als JSON
- Validiere: `severity` muss `"info"`, `"warning"` oder `"critical"` sein
- Wenn Severity ungültig: default auf `"warning"`, logge `WARNING`
- Gib `Alert(findings=findings, severity=..., summary=..., recommendation=..., generated_at=datetime.utcnow())` zurück

### Degraded Mode (LLM-Fehler)

Bei **jedem** LLM-Fehler (Timeout, API-Fehler, ungültiges JSON):
- Logge `ERROR` mit Fehlermeldung
- Gib `Alert` zurück mit:
  - `severity` = höchster Severity-Wert aus den Findings (`"critical"` > `"warning"` > `"info"`)
  - `summary = "LLM analysis unavailable"`
  - `recommendation = "Check logs manually"`
- **Niemals** Exception propagieren — der Agent-Loop darf nicht crashen

### Hilfsfunktion

```python
def _highest_severity(findings: list[Finding]) -> str:
    """Gibt den höchsten Severity-Wert aus einer Liste von Findings zurück."""
```

### Erlaubte Imports

```python
import json
import logging
from datetime import datetime
from src.config import config
from src.models import Alert, Finding
```

LangChain-Imports je nach Provider — alle drei müssen unterstützt werden.

## Coding Standards

- `logging.getLogger(__name__)` — kein `print()`
- Specific exceptions — kein bare `except:`
- Timeout auf jeden LLM-Call setzen
- LLM-Output validieren bevor er weiterverwendet wird

## Done when

`analyze([])` gibt ein valides `Alert`-Objekt zurück. Bei fehlender `OPENAI_API_KEY`-Umgebungsvariable läuft der Analyzer im Degraded Mode durch ohne Exception.
