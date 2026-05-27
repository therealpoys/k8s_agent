# Prompt — Schritt 4: Plugin-Interface (`src/plugins/base.py`)

## Kontext

Schritt 3 (`src/config.py`) ist abgeschlossen. Jetzt definieren wir das abstrakte Interface, das alle Plugins implementieren müssen. Das Interface wird zuerst gebaut, damit spätere Plugin-Implementierungen dieselbe Signatur erzwingen.

## Aufgabe

Erstelle `src/plugins/__init__.py` (leer) und `src/plugins/base.py`.

### `BasePlugin`

Abstrakte Basisklasse für alle Plugins:

```python
from abc import ABC, abstractmethod
from src.models import Finding

class BasePlugin(ABC):
    name: str  # Klassenattribut — wird von Subklassen überschrieben

    @abstractmethod
    def run(self) -> list[Finding]:
        """Führt den Plugin-Lauf durch und gibt Findings zurück."""
        ...
```

### Anforderungen

- `BasePlugin` erbt von `ABC`
- `run()` ist mit `@abstractmethod` dekoriert
- `name` ist ein Klassenattribut (kein Instanzattribut, kein `__init__`-Parameter)
- Keine Implementierungslogik in `base.py` — nur das Interface
- Kein `__init__` nötig, solange Plugins keinen gemeinsamen Konstruktor brauchen

### Erlaubte Imports

```python
from abc import ABC, abstractmethod
from src.models import Finding
```

## Coding Standards

- PEP 8, max. 100 Zeichen pro Zeile
- Kein `print()`, keine Logging-Calls — reines Interface
- Keine kommentierten Code-Blöcke

## Done when

```python
from src.plugins.base import BasePlugin
```

ist ohne ImportError importierbar, und eine Klasse die `BasePlugin` erbt aber `run()` nicht implementiert wirft `TypeError` beim Instanziieren.
