import pytest
from pathlib import Path
from unittest.mock import patch


MINIMAL_YAML = """\
llm:
  provider: openai
  model: gpt-4o-mini
  timeout_seconds: 30

kubernetes:
  namespaces:
    - default
  log_lines: 100

plugins:
  core:
    - pod_logs
  optional:
    trivy: false

outputs:
  - console
"""

YAML_WITH_BASE_URL = MINIMAL_YAML.replace(
    "  timeout_seconds: 30",
    "  timeout_seconds: 30\n  base_url: http://localhost:11434",
)


def _load(yaml_content: str):
    """Import _load_config fresh with a tmp config.yaml."""
    from src.config import _load_config
    import importlib, sys

    tmp = pytest.importorskip("pathlib")  # always available, just triggers import check
    return _load_config


def _call_load(tmp_path: Path, yaml_content: str):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml_content)

    with patch("src.config._CONFIG_PATH", config_file):
        from src.config import _load_config
        return _load_config()


class TestLoadConfigHappyPath:
    def test_llm_fields(self, tmp_path):
        cfg = _call_load(tmp_path, MINIMAL_YAML)
        assert cfg.llm_provider == "openai"
        assert cfg.llm_model == "gpt-4o-mini"
        assert cfg.llm_timeout == 30
        assert cfg.llm_base_url is None

    def test_base_url_parsed(self, tmp_path):
        cfg = _call_load(tmp_path, YAML_WITH_BASE_URL)
        assert cfg.llm_base_url == "http://localhost:11434"

    def test_kubernetes_fields(self, tmp_path):
        cfg = _call_load(tmp_path, MINIMAL_YAML)
        assert cfg.namespaces == ["default"]
        assert cfg.log_lines == 100

    def test_plugins_fields(self, tmp_path):
        cfg = _call_load(tmp_path, MINIMAL_YAML)
        assert cfg.core_plugins == ["pod_logs"]
        assert cfg.optional_plugins == {"trivy": False}

    def test_outputs(self, tmp_path):
        cfg = _call_load(tmp_path, MINIMAL_YAML)
        assert cfg.outputs == ["console"]

    def test_multiple_namespaces(self, tmp_path):
        yaml = MINIMAL_YAML.replace("    - default", "    - default\n    - kube-system")
        cfg = _call_load(tmp_path, yaml)
        assert cfg.namespaces == ["default", "kube-system"]


class TestLoadConfigErrors:
    def test_file_not_found(self, tmp_path):
        missing = tmp_path / "config.yaml"
        with patch("src.config._CONFIG_PATH", missing):
            from src.config import _load_config
            with pytest.raises(FileNotFoundError, match="config.yaml"):
                _load_config()

    def test_missing_llm_section(self, tmp_path):
        yaml = "\n".join(
            line for line in MINIMAL_YAML.splitlines()
            if not line.startswith("llm") and not line.startswith("  provider")
            and not line.startswith("  model") and not line.startswith("  timeout")
        )
        with patch("src.config._CONFIG_PATH", tmp_path / "config.yaml"):
            (tmp_path / "config.yaml").write_text(yaml)
            from src.config import _load_config
            with pytest.raises(KeyError):
                _load_config()

    def test_missing_kubernetes_section(self, tmp_path):
        yaml = "\n".join(
            line for line in MINIMAL_YAML.splitlines()
            if not line.startswith("kubernetes") and "namespaces" not in line
            and "log_lines" not in line and "    - default" not in line
        )
        (tmp_path / "config.yaml").write_text(yaml)
        with patch("src.config._CONFIG_PATH", tmp_path / "config.yaml"):
            from src.config import _load_config
            with pytest.raises(KeyError):
                _load_config()
