from src.plugins.pod_logs import PodLogsPlugin
from src.plugins.trivy import TrivyPlugin

PLUGIN_REGISTRY: dict[str, type] = {
    "pod_logs": PodLogsPlugin,
    "trivy": TrivyPlugin,
}
