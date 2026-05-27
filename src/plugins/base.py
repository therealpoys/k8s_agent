from abc import ABC, abstractmethod

from src.models import Finding


class BasePlugin(ABC):
    name: str

    @abstractmethod
    def run(self) -> list[Finding]:
        """Führt den Plugin-Lauf durch und gibt Findings zurück."""
        ...
