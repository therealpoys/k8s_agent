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

                pod_events = self._get_pod_events(namespace, pod_name)
                container_statuses = pod.status.container_statuses or []
                init_container_statuses = pod.status.init_container_statuses or []
                phase = pod.status.phase or "unknown"

                all_containers = [
                    (c, False) for c in (pod.spec.containers or [])
                ] + [
                    (c, True) for c in (pod.spec.init_containers or [])
                ]

                for container_spec, is_init in all_containers:
                    container = container_spec.name
                    statuses = init_container_statuses if is_init else container_statuses
                    cs = next((s for s in statuses if s.name == container), None)

                    image = container_spec.image or "unknown"
                    resources = container_spec.resources
                    requests = (resources.requests if resources else None) or {}
                    limits = (resources.limits if resources else None) or {}
                    liveness_probe = bool(container_spec.liveness_probe) if not is_init else False
                    readiness_probe = bool(container_spec.readiness_probe) if not is_init else False
                    command = (container_spec.command or []) + (container_spec.args or [])

                    restart_count = cs.restart_count if cs else 0
                    ready = cs.ready if cs else False
                    state = _container_state_str(cs.state if cs else None)
                    last_exit_code = None
                    if cs is not None:
                        if cs.state and cs.state.terminated:
                            last_exit_code = cs.state.terminated.exit_code
                        elif cs.last_state and cs.last_state.terminated:
                            last_exit_code = cs.last_state.terminated.exit_code

                    waiting_reason = (
                        cs.state.waiting.reason
                        if cs is not None and cs.state is not None and cs.state.waiting is not None
                        else None
                    )
                    is_waiting = waiting_reason is not None
                    use_previous = waiting_reason == "CrashLoopBackOff"

                    logs = ""
                    if not is_waiting or use_previous:
                        try:
                            logs = self._v1.read_namespaced_pod_log(
                                name=pod_name,
                                namespace=namespace,
                                container=container,
                                tail_lines=config.log_lines,
                                previous=use_previous,
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

                    if not logs and not is_waiting:
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
                                "is_init_container": is_init,
                                "namespace": namespace,
                                "command": command,
                                "last_exit_code": last_exit_code,
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
