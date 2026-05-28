import logging
from datetime import datetime

import kubernetes
from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException

from src.config import config
from src.models import Finding
from src.plugins.base import BasePlugin

logger = logging.getLogger(__name__)


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

                for container in containers:
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
                            },
                        )
                    )

        return findings
