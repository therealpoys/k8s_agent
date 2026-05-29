import logging
import os
import yaml
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
# Im Cluster wird config.yaml per ConfigMap unter /app/config.yaml gemountet;
# lokal liegt sie im Projektverzeichnis. CONFIG_PATH überschreibt beides.
_CONFIG_PATH = Path(os.getenv("CONFIG_PATH", str(_PROJECT_ROOT / "config.yaml")))


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

    # Env-Vars überschreiben config.yaml — sinnvoll für K8s Secrets/ConfigMaps
    llm_base_url = os.getenv("LLM_BASE_URL") or llm.get("base_url")
    llm_model = os.getenv("LLM_MODEL") or llm["model"]
    llm_provider = os.getenv("LLM_PROVIDER") or llm["provider"]

    return Config(
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_timeout=llm["timeout_seconds"],
        llm_base_url=llm_base_url,
        namespaces=k8s["namespaces"],
        log_lines=k8s["log_lines"],
        core_plugins=plugins["core"],
        optional_plugins=plugins.get("optional", {}),
        outputs=raw["outputs"],
        loop_interval_seconds=int(os.getenv("LOOP_INTERVAL_SECONDS", raw["loop_interval_seconds"])),
        debug_log_llm_io=raw.get("debug", {}).get("log_llm_io", False),
    )


config: Config = _load_config()
