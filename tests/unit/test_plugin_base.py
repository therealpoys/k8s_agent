import pytest

from src.models import Finding
from src.plugins.base import BasePlugin


class ConcretePlugin(BasePlugin):
    name = "concrete"

    def run(self) -> list[Finding]:
        return []


def test_concrete_plugin_instantiates():
    plugin = ConcretePlugin()
    assert plugin.run() == []


def test_incomplete_plugin_raises_type_error():
    class IncompletePlugin(BasePlugin):
        name = "incomplete"

    with pytest.raises(TypeError):
        IncompletePlugin()


def test_name_is_class_attribute():
    assert ConcretePlugin.name == "concrete"
