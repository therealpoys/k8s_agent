import logging
import yaml
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config.yaml"


@dataclass
class Config:
    llm_provider: str
    llm_model: str
    llm_timeout: int
    llm_base_url: str | None

    namespaces: list[str]
    log_lines: int

    core_plugins: list[str]
    optional_plugins: dict[str, bool]

    outputs: list[str]

    loop_interval_seconds: int

    debug_log_llm_io: bool


def _load_config() -> Config:
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"config.yaml nicht gefunden: {_CONFIG_PATH}. "
            "Bitte config.yaml.example kopieren und anpassen."
        )

    with _CONFIG_PATH.open() as f:
        raw = yaml.safe_load(f)

    logger.debug("config.yaml geladen von %s", _CONFIG_PATH)

    try:
        llm = raw["llm"]
        k8s = raw["kubernetes"]
        plugins = raw["plugins"]
    except KeyError as e:
        raise KeyError(f"Pflichtfeld fehlt in config.yaml: {e}") from e

    return Config(
        llm_provider=llm["provider"],
        llm_model=llm["model"],
        llm_timeout=llm["timeout_seconds"],
        llm_base_url=llm.get("base_url"),
        namespaces=k8s["namespaces"],
        log_lines=k8s["log_lines"],
        core_plugins=plugins["core"],
        optional_plugins=plugins.get("optional", {}),
        outputs=raw["outputs"],
        loop_interval_seconds=raw["loop_interval_seconds"],
        debug_log_llm_io=raw.get("debug", {}).get("log_llm_io", False),
    )


config: Config = _load_config()
