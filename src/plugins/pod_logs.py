import logging
from datetime import datetime

import kubernetes
from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException

from src.config import config
from src.models import Finding
from src.plugins.base import BasePlugin

logger = logging.getLogger(__name__)


def _container_state_str(state) -> str:
    if state is None:
        return "unknown"
    if state.running:
        return "running"
    if state.waiting:
        return f"waiting:{state.waiting.reason or 'unknown'}"
    if state.terminated:
        return f"terminated:{state.terminated.reason or 'unknown'}"
    return "unknown"


class PodLogsPlugin(BasePlugin):
    name = "pod_logs"

    def __init__(self) -> None:
        try:
            k8s_config.load_incluster_config()
            logger.debug("Kubernetes In-Cluster-Config geladen")
        except kubernetes.config.ConfigException:
            k8s_config.load_kube_config()
            logger.debug("Kubernetes kubeconfig geladen")
        self._v1 = client.CoreV1Api()

    def _get_pod_events(self, namespace: str, pod_name: str) -> list[dict]:
        try:
            events = self._v1.list_namespaced_event(
                namespace,
                field_selector=f"involvedObject.name={pod_name}",
                timeout_seconds=5,
            ).items
            return [
                {
                    "reason": e.reason,
                    "message": e.message,
                    "count": e.count,
                    "type": e.type,
                }
                for e in events
                if e.type == "Warning" or (e.count or 0) > 1
            ]
        except Exception as e:
            logger.warning(
                "Fehler beim Abrufen von Events für Pod '%s/%s': %s",
                namespace, pod_name, e,
            )
            return []

    def run(self) -> list[Finding]:
        findings: list[Finding] = []

        for namespace in config.namespaces:
            try:
                pods = self._v1.list_namespaced_pod(
                    namespace, timeout_seconds=10
                )
            except ApiException as e:
                if e.status in (401, 403):
                    logger.error(
                        "Zugriff verweigert beim Abrufen von Pods in Namespace '%s': %s",
                        namespace, e,
                    )
                    return findings
                logger.warning(
                    "Fehler beim Abrufen von Pods in Namespace '%s': %s",
                    namespace, e,
                )
                continue

            for pod in pods.items:
                pod_name = pod.metadata.name
                containers = [c.name for c in (pod.spec.containers or [])]

                pod_events = self._get_pod_events(namespace, pod_name)
                container_statuses = pod.status.container_statuses or []
                phase = pod.status.phase or "unknown"

                for container in containers:
                    container_spec = next(
                        (c for c in (pod.spec.containers or []) if c.name == container),
                        None,
                    )
                    cs = next((s for s in container_statuses if s.name == container), None)

                    image = container_spec.image if container_spec else "unknown"
                    resources = container_spec.resources if container_spec else None
                    requests = (resources.requests if resources else None) or {}
                    limits = (resources.limits if resources else None) or {}
                    liveness_probe = bool(container_spec.liveness_probe) if container_spec else False
                    readiness_probe = bool(container_spec.readiness_probe) if container_spec else False

                    restart_count = cs.restart_count if cs else 0
                    ready = cs.ready if cs else False
                    state = _container_state_str(cs.state if cs else None)

                    try:
                        logs = self._v1.read_namespaced_pod_log(
                            name=pod_name,
                            namespace=namespace,
                            container=container,
                            tail_lines=config.log_lines,
                        )
                    except ApiException as e:
                        if e.status in (401, 403):
                            logger.error(
                                "Zugriff verweigert beim Lesen von Logs für Pod '%s/%s' container '%s': %s",
                                namespace, pod_name, container, e,
                            )
                            return findings
                        if e.status == 404:
                            logger.warning(
                                "Pod '%s/%s' nicht mehr vorhanden, wird übersprungen",
                                namespace, pod_name,
                            )
                            break
                        logger.warning(
                            "Fehler beim Lesen von Logs für Pod '%s/%s' container '%s': %s",
                            namespace, pod_name, container, e,
                        )
                        continue
                    except Exception as e:
                        logger.warning(
                            "Unerwarteter Fehler bei Pod '%s/%s' container '%s': %s",
                            namespace, pod_name, container, e,
                        )
                        continue

                    if not logs:
                        continue

                    findings.append(
                        Finding(
                            source="pod_logs",
                            namespace=namespace,
                            resource=f"{pod_name}/{container}",
                            severity="info",
                            message=logs,
                            timestamp=datetime.utcnow(),
                            raw={
                                "pod_name": pod_name,
                                "container": container,
                                "namespace": namespace,
                                "log_lines": logs.count("\n") + 1,
                                "image": image,
                                "resources": {
                                    "requests": requests,
                                    "limits": limits,
                                },
                                "liveness_probe": liveness_probe,
                                "readiness_probe": readiness_probe,
                                "phase": phase,
                                "restart_count": restart_count,
                                "ready": ready,
                                "state": state,
                                "events": pod_events,
                            },
                        )
                    )

        return findings
