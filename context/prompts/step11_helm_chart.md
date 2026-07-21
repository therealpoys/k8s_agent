# Prompt — Schritt 11: Helm Chart

## Kontext

Die Kubernetes-Manifeste unter `k8s/` (deployment.yaml, configmap.yaml, rbac.yaml) sind funktionsfähig, aber statisch. Alle Werte wie Image-Tag, Namespace, LLM-URL oder Config-Parameter sind hardcoded. Für verschiedene Umgebungen (dev, staging, prod) oder Community-Nutzung brauchen wir ein parametrisierbares Helm Chart.

## Aufgabe

Erstelle ein vollständiges Helm Chart unter `helm/k8s-agent/`, das die drei bestehenden Manifeste abbildet.

### Zielstruktur

```
helm/k8s-agent/
├── Chart.yaml
├── values.yaml
├── .helmignore
├── templates/
│   ├── _helpers.tpl
│   ├── deployment.yaml
│   ├── configmap.yaml
│   ├── rbac.yaml
│   └── NOTES.txt
```

### Chart.yaml

```yaml
apiVersion: v2
name: k8s-agent
description: Kubernetes Observability Agent powered by LLM
type: application
version: 0.1.0
appVersion: "latest"
```

### values.yaml

Ziehe alle konfigurierbaren Werte heraus:

```yaml
replicaCount: 1

image:
  repository: k8s-agent
  tag: latest
  pullPolicy: IfNotPresent

nameOverride: ""
fullnameOverride: ""

serviceAccount:
  create: true
  name: ""

rbac:
  create: true

resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi

env:
  llmBaseUrl: "http://ollama.default.svc.cluster.local:11434/v1"
  logLevel: INFO

config:
  llm:
    provider: ollama
    model: qwen3:8b
    timeoutSeconds: 60
  kubernetes:
    namespaces:
      - default
    logLines: 100
  plugins:
    core:
      - pod_logs
    optional:
      trivy: false
      falco: false
      prometheus: false
  outputs:
    - console
  loopIntervalSeconds: 60
  debug:
    logLlmIo: false
```

### templates/_helpers.tpl

Standard-Helpers:
- `k8s-agent.name` — Chart-Name mit nameOverride
- `k8s-agent.fullname` — Release + Name, max. 63 Zeichen
- `k8s-agent.chart` — `name-version` für `helm.sh/chart` Label
- `k8s-agent.labels` — alle Standard `app.kubernetes.io/*` Labels
- `k8s-agent.selectorLabels` — nur `app.kubernetes.io/name` + `instance`
- `k8s-agent.serviceAccountName` — Name aus values oder fullname

### templates/deployment.yaml

Das bestehende `k8s/deployment.yaml` 1:1 übertragen, alle Hardcoded-Werte durch Values ersetzen:
- `name`, `namespace` über fullname-Helper
- `labels` und `selector` über selectorLabels-Helper
- `image` aus `image.repository:image.tag`
- `imagePullPolicy` aus `image.pullPolicy`
- `serviceAccountName` über serviceAccountName-Helper
- `env`-Einträge aus `env.llmBaseUrl` und `env.logLevel`
- `resources` aus `resources.*`
- ConfigMap-Name über fullname-Helper

### templates/configmap.yaml

Den `config.yaml`-Inhalt dynamisch aus `values.config` rendern.
Die verschachtelten Values über `toYaml` und `indent` in das ConfigMap-Data-Feld einbetten — kein manuelles Stringbuilding.

### templates/rbac.yaml

ServiceAccount, ClusterRole und ClusterRoleBinding aus `k8s/rbac.yaml` übertragen.
Jede Ressource mit `{{- if .Values.rbac.create }}` bzw. `{{- if .Values.serviceAccount.create }}` absichern.
Namespace im ClusterRoleBinding-Subject dynamisch über `.Release.Namespace`.

### templates/NOTES.txt

Kurze Ausgabe nach `helm install`:
- Release-Name und Namespace
- Hinweis wie man Logs liest (`kubectl logs -l app.kubernetes.io/name=k8s-agent`)
- Hinweis zum Überschreiben des LLM-Endpunkts via `--set env.llmBaseUrl=...`

## Coding Standards

- Alle Ressource-Namen ausschließlich über `k8s-agent.fullname` — kein Hardcoding
- `app.kubernetes.io/*` Labels auf allen Ressourcen
- `helm.sh/chart` Label im `labels`-Helper einschließen
- `.helmignore` mit `*.md`, `*.txt` (außer templates/), `.git/`
- Kein `namespace:` in den Templates hardcoden — immer `.Release.Namespace`

## Done when

```bash
helm lint helm/k8s-agent
helm template k8s-agent helm/k8s-agent | kubectl apply --dry-run=client -f -
```

Beide Befehle laufen fehlerfrei durch. Ein `helm install` in einen leeren Namespace deployt Deployment, ConfigMap, ServiceAccount, ClusterRole und ClusterRoleBinding korrekt.
