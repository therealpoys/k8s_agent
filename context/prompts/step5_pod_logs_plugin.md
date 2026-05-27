# Prompt — Schritt 5: Erstes Plugin (`src/plugins/pod_logs.py`)

## Kontext

Schritt 4 (`BasePlugin`) ist abgeschlossen. Jetzt bauen wir das erste konkrete Plugin: Pod-Logs via Kubernetes Python Client lesen. Das ist die Kernfunktionalität von Stage 1.

## Aufgabe

Erstelle `src/plugins/pod_logs.py`.

### Klasse `PodLogsPlugin`

Erbt von `BasePlugin`, liest Logs aller Pods in den konfigurierten Namespaces und gibt eine `list[Finding]` zurück.

```python
class PodLogsPlugin(BasePlugin):
    name = "pod_logs"

    def run(self) -> list[Finding]: ...
```

### Kubernetes-Client Setup

- Unterstütze beide Modi automatisch:
  1. **In-Cluster**: `kubernetes.config.load_incluster_config()` (läuft als Pod im Cluster)
  2. **Lokal**: `kubernetes.config.load_kube_config()` (lokaler `~/.kube/config`)
- Versuche zuerst In-Cluster, falle auf lokal zurück
- Client-Initialisierung im Konstruktor (`__init__`)

### `run()` Implementierung

1. Hole alle Namespaces aus `config.namespaces`
2. Liste alle Pods in jedem Namespace (`CoreV1Api.list_namespaced_pod`)
3. Lese Logs jedes Pods (`CoreV1Api.read_namespaced_pod_log`)
   - `tail_lines=config.log_lines`
   - `timeout_seconds=10` (API-Timeout)
4. Erzeuge ein `Finding` pro Pod mit Logs:
   - `source="pod_logs"`
   - `namespace=<namespace>`
   - `resource=<pod-name>`
   - `severity="info"` (Bewertung erfolgt später durch den Analyzer)
   - `message=<rohe Log-Zeilen als String>`
   - `timestamp=datetime.utcnow()`
   - `raw={"pod_name": ..., "namespace": ..., "log_lines": <anzahl>}`
5. Überspringe Pods ohne Logs (leerer String) — kein Finding erstellen

### Fehlerbehandlung

- `kubernetes.client.exceptions.ApiException` mit Status 401/403: logge `ERROR`, wirf nicht weiter
- `kubernetes.client.exceptions.ApiException` mit Status 404 (Pod verschwunden): logge `WARNING`, überspringe Pod
- Jeder andere Fehler pro Pod: logge `WARNING` mit Pod-Name und Exception-Message, überspringe Pod — **der Rest der Pods wird weiter verarbeitet**
- Plugin-Fehler dürfen den Agent-Loop nie crashen

### Erlaubte Imports

```python
import logging
from datetime import datetime
import kubernetes
from kubernetes import client, config as k8s_config
from src.config import config
from src.models import Finding
from src.plugins.base import BasePlugin
```

## Coding Standards

- `logging.getLogger(__name__)` — kein `print()`
- Specific exceptions — kein bare `except:`
- Namespace-Liste aus `config.namespaces` — nie hardcoden
- K8s API Calls immer mit `timeout_seconds`

## Done when

Das Plugin lässt sich instanziieren und `run()` aufrufen gegen einen echten Cluster (lokal via kubeconfig). Es gibt eine `list[Finding]` zurück — auch wenn der Cluster leer ist (dann leere Liste).
