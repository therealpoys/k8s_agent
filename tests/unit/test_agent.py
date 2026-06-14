import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def no_dotenv():
    with patch("dotenv.load_dotenv"):
        yield


def _run_main():
    import importlib
    import agent
    importlib.reload(agent)
    agent.main()


def test_main_success():
    mock_graph = MagicMock()
    with patch("src.graph.build_graph", return_value=mock_graph):
        _run_main()
    mock_graph.invoke.assert_called_once_with({})


def test_main_config_not_found(capsys):
    with patch("src.graph.build_graph", side_effect=FileNotFoundError("config.yaml not found")):
        with pytest.raises(SystemExit) as exc_info:
            _run_main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "config.yaml not found" in captured.err


def test_main_graph_invoke_exception(caplog):
    import logging

    mock_graph = MagicMock()
    mock_graph.invoke.side_effect = RuntimeError("boom")

    with patch("src.graph.build_graph", return_value=mock_graph):
        with caplog.at_level(logging.CRITICAL):
            with pytest.raises(SystemExit) as exc_info:
                _run_main()

    assert exc_info.value.code == 1
    assert any("CRITICAL" in r.levelname for r in caplog.records)
