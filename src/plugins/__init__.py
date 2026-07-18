from src.plugins.pod_logs import PodLogsPlugin
from src.plugins.k8s_events import K8sEventsPlugin
from src.plugins.trivy import TrivyPlugin
from src.plugins.falco import FalcoPlugin
from src.plugins.prometheus import PrometheusPlugin

PLUGIN_REGISTRY: dict[str, type] = {
    "pod_logs": PodLogsPlugin,
    "k8s_events": K8sEventsPlugin,
    "trivy": TrivyPlugin,
    "falco": FalcoPlugin,
    "prometheus": PrometheusPlugin,
}
