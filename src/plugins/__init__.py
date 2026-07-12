from src.plugins.pod_logs import PodLogsPlugin
from src.plugins.trivy import TrivyPlugin
from src.plugins.falco import FalcoPlugin
from src.plugins.prometheus import PrometheusPlugin

PLUGIN_REGISTRY: dict[str, type] = {
    "pod_logs": PodLogsPlugin,
    "trivy": TrivyPlugin,
    "falco": FalcoPlugin,
    "prometheus": PrometheusPlugin,
}
