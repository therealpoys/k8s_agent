import logging

from src.config import config
from src.plugins import PLUGIN_REGISTRY
from src.plugins.base import BasePlugin

logger = logging.getLogger(__name__)


def load_plugins() -> list[BasePlugin]:
    plugins: list[BasePlugin] = []

    for name in config.core_plugins:
        cls = PLUGIN_REGISTRY.get(name)
        if cls is None:
            logger.warning("Unbekanntes Core-Plugin '%s' in config — übersprungen", name)
            continue
        plugins.append(cls())
        logger.info("Plugin geladen: %s", name)

    for name, enabled in config.optional_plugins.items():
        if not enabled:
            continue
        cls = PLUGIN_REGISTRY.get(name)
        if cls is None:
            logger.warning("Unbekanntes optionales Plugin '%s' in config — übersprungen", name)
            continue
        plugins.append(cls())
        logger.info("Optionales Plugin geladen: %s", name)

    return plugins
