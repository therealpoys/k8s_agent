import logging
from datetime import datetime, timezone

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException

from src.config import config
from src.models import Finding
from src.plugins.base import BasePlugin

logger = logging.getLogger(__name__)

_GROUP = "aquasecurity.github.io"
_VERSION = "v1alpha1"
_PLURAL = "vulnerabilityreports"


class TrivyPlugin(BasePlugin):
    name = "trivy"

    def __init__(self):
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()
        self._api = client.CustomObjectsApi()

    def run(self) -> list[Finding]:
        findings: list[Finding] = []
        for namespace in config.namespaces:
            findings.extend(self._scan_namespace(namespace))
        return findings

    def _scan_namespace(self, namespace: str) -> list[Finding]:
        try:
            response = self._api.list_namespaced_custom_object(
                group=_GROUP,
                version=_VERSION,
                namespace=namespace,
                plural=_PLURAL,
            )
        except ApiException as exc:
            if exc.status == 404:
                logger.debug(
                    "Trivy CRDs nicht gefunden in Namespace %s — Trivy Operator installiert?",
                    namespace,
                )
            elif exc.status in (401, 403):
                logger.warning(
                    "Kein Zugriff auf VulnerabilityReports in %s (HTTP %s)", namespace, exc.status
                )
            else:
                logger.error("Fehler beim Lesen von VulnerabilityReports in %s: %s", namespace, exc)
            return []

        findings: list[Finding] = []
        for report in response.get("items", []):
            finding = self._report_to_finding(report, namespace)
            if finding:
                findings.append(finding)
        return findings

    def _report_to_finding(self, report: dict, namespace: str) -> Finding | None:
        summary = report.get("report", {}).get("summary", {})
        critical = summary.get("criticalCount", 0)
        high = summary.get("highCount", 0)

        if critical == 0 and high == 0:
            return None

        meta = report.get("metadata", {})
        labels = meta.get("labels", {})
        container = labels.get("trivy-operator.container.name", "unknown")
        kind = labels.get("trivy-operator.resource.kind", "")
        resource_name = labels.get("trivy-operator.resource.name", meta.get("name", "unknown"))

        artifact = report.get("report", {}).get("artifact", {})
        image = f"{artifact.get('repository', '')}:{artifact.get('tag', 'unknown')}"

        severity = "CRITICAL" if critical > 0 else "HIGH"
        message = (
            f"{critical} kritische, {high} hohe CVEs in {image} "
            f"({kind}/{resource_name}, Container: {container})"
        )

        top_vulns = [
            v for v in report.get("report", {}).get("vulnerabilities", [])
            if v.get("severity") in ("CRITICAL", "HIGH")
        ][:5]

        return Finding(
            source=self.name,
            namespace=namespace,
            resource=f"{kind}/{resource_name}:{container}",
            severity=severity,
            message=message,
            timestamp=datetime.now(timezone.utc),
            raw={
                "summary": summary,
                "image": image,
                "top_vulnerabilities": [
                    {
                        "id": v.get("vulnerabilityID"),
                        "title": v.get("title"),
                        "severity": v.get("severity"),
                        "resource": v.get("resource"),
                        "installedVersion": v.get("installedVersion"),
                        "fixedVersion": v.get("fixedVersion"),
                    }
                    for v in top_vulns
                ],
            },
        )
