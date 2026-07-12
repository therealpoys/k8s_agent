# Prompt — Schritt 14: PrometheusPlugin

## Kontext

Schritt 13 ist abgeschlossen. `FalcoPlugin` läuft als drittes Plugin. `config.yaml.example` listet
`prometheus: false` als optionales Plugin — bisher Platzhalter ohne Implementierung.

Anders als Falco (Pod-Logs parsen) und Trivy (CRD lesen) bietet Prometheus eine eigene HTTP-API.
Der eingebaute Endpunkt `GET /api/v1/alerts` liefert alle aktiven Alerts (aus `PrometheusRule`
bzw. klassischen Alerting-Rules) inklusive Labels (`severity`, `namespace`, `pod`, `alertname`, …)
und Annotations (`summary`, `description`). Das deckt sich exakt mit dem, was der Agent als
Finding braucht — kein Umweg über Kubernetes-Objekte nötig.

**Voraussetzung:** Ein laufender Prometheus-Server, erreichbar per HTTP unter einer konfigurierbaren
URL (typischerweise der In-Cluster-Service, z. B. `http://prometheus-operated.monitoring.svc.cluster.local:9090`
bei kube-prometheus-stack).

Auch anpassen: In `config.yaml.example` trägt `falco: false` noch den Kommentar
`# noch nicht implementiert` — das stimmt seit Schritt 13 nicht mehr. Zusammen mit diesem Schritt
beide Kommentare korrigieren.

---

## Aufgabe

### 1. `src/config.py` — `prometheus_url` ergänzen

Eigener Top-Level-Block `prometheus:` in der YAML, da die URL kein Kubernetes-Konzept ist (anders
als `falco_namespace`, das eine Namespace-Discovery im Cluster ist).

```python
@dataclass
class Config:
    # ... bestehende Felder ...
    prometheus_url: str  # neu
```

In `_load_config()`:

```python
prometheus = raw.get("prometheus", {})
```

```python
prometheus_url=prometheus.get(
    "url", "http://prometheus-operated.monitoring.svc.cluster.local:9090"
),
```

Kein `KeyError` bei fehlendem Block — Default greift, analog zu `falco_namespace`.

---

### 2. `config.yaml.example` — `prometheus:` dokumentieren, veralteten Kommentar fixen

```yaml
kubernetes:
  namespaces:
    - default             # add more namespaces as needed
  log_lines: 100
  falco_namespace: falco  # Namespace in dem Falco läuft (für FalcoPlugin)

prometheus:
  url: http://prometheus-operated.monitoring.svc.cluster.local:9090  # Prometheus-Service-URL (für PrometheusPlugin)

plugins:
  core:
    - pod_logs        # immer aktiv
  optional:
    trivy: false      # Trivy Operator muss im Cluster installiert sein
    falco: false      # Falco DaemonSet muss im Cluster laufen (json_output: true)
    prometheus: false # Prometheus muss unter prometheus.url erreichbar sein
```

---

### 3. `requirements.txt` — `requests` ergänzen

Für den HTTP-Call gegen die Prometheus-API. `kubernetes`-Paket bringt es transitiv mit, aber als
direkte Dependency explizit pinnen:

```
requests==2.34.2
```

---

### 4. `src/plugins/prometheus.py` — PrometheusPlugin (neue Datei)

```python
import logging
from datetime import datetime, timezone

import requests

from src.config import config
from src.models import Finding
from src.plugins.base import BasePlugin

logger = logging.getLogger(__name__)

# Prometheus-Alert-Severity-Label-Konvention (kube-prometheus-stack Default-Regeln)
_SEVERITY_MAP: dict[str, str] = {
    "critical": "CRITICAL",
    "warning": "HIGH",
    "info": "info",
}

_REQUEST_TIMEOUT_SECONDS = 10


class PrometheusPlugin(BasePlugin):
    name = "prometheus"

    def run(self) -> list[Finding]:
        try:
            response = requests.get(
                f"{config.prometheus_url}/api/v1/alerts",
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning(
                "Prometheus unter %s nicht erreichbar: %s", config.prometheus_url, exc
            )
            return []

        try:
            data = response.json()
        except ValueError:
            logger.warning("Prometheus-Antwort von %s ist kein valides JSON", config.prometheus_url)
            return []

        alerts = data.get("data", {}).get("alerts", [])
        return self._alerts_to_findings(alerts)

    def _alerts_to_findings(self, alerts: list[dict]) -> list[Finding]:
        findings: list[Finding] = []
        for alert in alerts:
            if alert.get("state") != "firing":
                continue  # "pending" hat die for:-Dauer noch nicht überschritten

            labels = alert.get("labels", {})
            annotations = alert.get("annotations", {})

            severity_label = labels.get("severity", "").lower()
            severity = _SEVERITY_MAP.get(severity_label, "HIGH")

            alertname = labels.get("alertname", "unknown")
            namespace = labels.get("namespace", "")
            pod = labels.get("pod", "")

            resource = f"pod/{pod}" if pod else labels.get("instance", "unknown")
            message = annotations.get("summary") or annotations.get("description") or alertname

            try:
                timestamp = datetime.fromisoformat(alert["activeAt"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                timestamp = datetime.now(timezone.utc)

            findings.append(
                Finding(
                    source=self.name,
                    namespace=namespace,
                    resource=resource,
                    severity=severity,
                    message=f"{alertname}: {message}",
                    timestamp=timestamp,
                    raw={
                        "alertname": alertname,
                        "labels": labels,
                        "annotations": annotations,
                        "state": alert.get("state"),
                    },
                )
            )

        return findings
```

**Designentscheidungen:**
- Direkter HTTP-Call gegen die eingebaute Prometheus-API (`/api/v1/alerts`) statt Kubernetes-Objekt-
  Discovery — kein Pod-Label-Selector wie bei Falco nötig, Prometheus ist über eine feste URL erreichbar
- Nur `state: firing` → `pending`-Alerts (Schwellwert noch nicht über `for:`-Dauer) erzeugen keine Findings,
  sonst Flooding durch Alerts die gleich wieder verschwinden
- `labels.severity` folgt der kube-prometheus-stack-Konvention (`critical`/`warning`/`info`); unbekanntes
  oder fehlendes Label fällt auf `HIGH` zurück statt still zu verschwinden
- Verbindungsfehler/Timeout/ungültiges JSON: `warning`-Log, `[]`, kein Crash — konsistent mit
  Falco- und Trivy-Plugin
- Kein `__init__` mit Kubernetes-Client nötig (anders als Falco/Trivy/PodLogs) — das Plugin braucht nur `requests`

---

### 5. `src/plugins/__init__.py` — PrometheusPlugin registrieren

```python
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
```

---

### 6. `deploy/helm/k8s-agent/values.yaml` — Prometheus-URL ergänzen

Kein RBAC nötig (kein Kubernetes-API-Zugriff, nur HTTP) — im Gegensatz zu Falco/Trivy also kein
ClusterRole-Eintrag.

```yaml
agentConfig:
  kubernetes:
    namespaces:
      - default
    log_lines: 100
    falco_namespace: falco

  prometheus:
    url: http://prometheus-operated.monitoring.svc.cluster.local:9090   # neu

  plugins:
    core:
      - pod_logs
    optional:
      trivy: false
      falco: false
      prometheus: false
```

Falls ein `kube-prometheus-stack` Sub-Chart wie bei Trivy/Falco gewünscht ist, kann das in einem
späteren Schritt ergänzt werden — vorerst wird ein bereits im Cluster laufendes Prometheus vorausgesetzt.

---

## Tests

### `tests/unit/test_prometheus_plugin.py` (neue Datei)

Alle Tests mocken `requests.get` (`patch("src.plugins.prometheus.requests.get")`) und
`src.plugins.prometheus.config`.

- `test_run_returns_empty_on_connection_error`: `requests.get` wirft `requests.ConnectionError` → `[]`, warning-Log
- `test_run_returns_empty_on_timeout`: `requests.get` wirft `requests.Timeout` → `[]`
- `test_run_returns_empty_on_http_error`: Response mit `raise_for_status()` → `requests.HTTPError` → `[]`
- `test_run_returns_empty_on_invalid_json`: `response.json()` wirft `ValueError` → `[]`
- `test_run_returns_empty_when_no_alerts`: `data.alerts == []` → `[]`
- `test_alerts_to_findings_skips_pending`: Alert mit `state: pending` → kein Finding
- `test_alerts_to_findings_maps_critical`: `labels.severity: critical` → `severity="CRITICAL"`
- `test_alerts_to_findings_maps_warning`: `labels.severity: warning` → `severity="HIGH"`
- `test_alerts_to_findings_unknown_severity_defaults_high`: `labels.severity` fehlt/unbekannt → `severity="HIGH"`
- `test_alerts_to_findings_multiple_firing`: 2 firing Alerts → 2 Findings
- `test_finding_message_includes_alertname_and_summary`: `alertname` + `annotations.summary` im `message`-String
- `test_finding_resource_uses_pod_label`: `labels.pod` gesetzt → `resource == "pod/<name>"`
- `test_finding_resource_falls_back_to_instance`: kein `pod`-Label → `resource == labels.instance`
- `test_finding_raw_contains_labels_and_annotations`: `raw["labels"]` und `raw["annotations"]` vollständig

### `tests/unit/test_config.py` — bestehende Tests anpassen

`prometheus_url` zum Config-Fixture hinzufügen (Default, wenn `prometheus:`-Block fehlt) und einen
Test für explizit gesetzte URL ergänzen.

---

## Done when

```yaml
# config.yaml
prometheus:
  url: http://localhost:9090

plugins:
  optional:
    prometheus: true
```

```bash
python agent.py
```

gibt Prometheus-Findings aus wenn unter der konfigurierten URL aktive `firing`-Alerts existieren.
Bei nicht erreichbarem Prometheus: stiller `warning`-Log, kein Crash.

Und:

```bash
helm upgrade k8s-agent deploy/helm/k8s-agent/ --set agentConfig.plugins.optional.prometheus=true
kubectl logs -f deployment/k8s-agent-k8s-agent
```

zeigt `[CRITICAL]`/`[HIGH]` Findings für aktive Prometheus-Alerts mit Alertname und Summary im
`message`-Feld für das LLM.

Alle bestehenden Tests bleiben grün, neue Tests für PrometheusPlugin kommen hinzu.
