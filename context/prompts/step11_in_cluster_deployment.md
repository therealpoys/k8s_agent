# Prompt — Schritt 11: In-Cluster Deployment mit Helm

## Kontext

Schritt 10 ist abgeschlossen. Der Agent läuft lokal mit `python agent.py` und analysiert Pod-Logs mit vollem Kontext (Image, Restarts, Events). Jetzt soll er selbst als Pod im Kubernetes-Cluster laufen — mit In-Cluster-Auth, RBAC und Helm-basierter Konfiguration.

Die Kubernetes-Auth ist bereits vorbereitet: `pod_logs.py` versucht zuerst `load_incluster_config()`, fällt erst dann auf kubeconfig zurück.

## Aufgabe

Erstelle folgende Dateien:

```
k8s_agent/
├── Dockerfile
└── deploy/
    └── helm/
        └── k8s-agent/
            ├── Chart.yaml
            ├── values.yaml
            └── templates/
                ├── serviceaccount.yaml
                ├── clusterrole.yaml
                ├── clusterrolebinding.yaml
                ├── configmap.yaml
                └── deployment.yaml
```

---

### 1. `Dockerfile`

```dockerfile
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent.py .
COPY src/ ./src/

CMD ["python", "agent.py"]
```

- Kein `COPY config.yaml` — kommt via Helm-ConfigMap als Volume
- Kein `COPY .env` — Secrets kommen als Env-Vars
- `python:3.13-slim`, kein Alpine (C-Extensions in einigen Deps)

---

### 2. `deploy/helm/k8s-agent/Chart.yaml`

```yaml
apiVersion: v2
name: k8s-agent
description: Kubernetes Observability Agent
version: 0.1.0
appVersion: "0.1.0"
```

---

### 3. `deploy/helm/k8s-agent/values.yaml`

Hier lebt die gesamte Agent-Konfiguration. Das `agentConfig`-Block wird 1:1 als `config.yaml` in den Pod gemountet.

```yaml
image:
  repository: k8s-agent
  tag: latest
  pullPolicy: IfNotPresent

# Wird als config.yaml in den Container gemountet
agentConfig:
  llm:
    provider: anthropic          # anthropic | openai | ollama
    model: claude-haiku-4-5-20251001
    timeout_seconds: 60
    # base_url nur für Ollama nötig:
    # base_url: http://ollama.ollama.svc.cluster.local:11434

  kubernetes:
    namespaces:
      - default
    log_lines: 100

  plugins:
    core:
      - pod_logs
    optional:
      trivy: false
      falco: false
      prometheus: false

  outputs:
    - console

  loop_interval_seconds: 60

# Name eines bereits existierenden Secrets mit LLM API-Keys
# Das Secret muss ANTHROPIC_API_KEY oder OPENAI_API_KEY enthalten
existingSecret: k8s-agent-secrets

resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 256Mi
```

**Hinweis:** Kein `secret.yaml`-Template im Chart — Secrets werden außerhalb von Helm verwaltet (`kubectl create secret generic …`) und per `existingSecret` referenziert. So landen keine API-Keys im Helm-Release-State.

**Ollama vs. Cloud-LLM:** Ollama unter `localhost:11434` ist im Cluster nicht erreichbar. Für Ollama muss ein Ollama-Deployment im Cluster laufen und `base_url` auf den internen Service-DNS zeigen. Standard-Provider im Chart ist `anthropic`.

---

### 4. `deploy/helm/k8s-agent/templates/configmap.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "k8s-agent.fullname" . }}-config
  namespace: {{ .Release.Namespace }}
data:
  config.yaml: |
{{ .Values.agentConfig | toYaml | indent 4 }}
```

Der `agentConfig`-Block aus `values.yaml` wird direkt als `config.yaml` gerendert — kein Zwischenformat, kein manuelles Synchronisieren.

---

### 5. `deploy/helm/k8s-agent/templates/serviceaccount.yaml`

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "k8s-agent.fullname" . }}
  namespace: {{ .Release.Namespace }}
```

---

### 6. `deploy/helm/k8s-agent/templates/clusterrole.yaml`

Read-only Zugriff auf Pods, Logs und Events — cluster-weit, weil der Agent mehrere Namespaces aus der Config überwacht.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: {{ include "k8s-agent.fullname" . }}
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["list", "get"]
  - apiGroups: [""]
    resources: ["pods/log"]
    verbs: ["get"]
  - apiGroups: [""]
    resources: ["events"]
    verbs: ["list", "get"]
```

---

### 7. `deploy/helm/k8s-agent/templates/clusterrolebinding.yaml`

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: {{ include "k8s-agent.fullname" . }}
subjects:
  - kind: ServiceAccount
    name: {{ include "k8s-agent.fullname" . }}
    namespace: {{ .Release.Namespace }}
roleRef:
  kind: ClusterRole
  name: {{ include "k8s-agent.fullname" . }}
  apiGroup: rbac.authorization.k8s.io
```

---

### 8. `deploy/helm/k8s-agent/templates/deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "k8s-agent.fullname" . }}
  namespace: {{ .Release.Namespace }}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {{ include "k8s-agent.fullname" . }}
  template:
    metadata:
      labels:
        app: {{ include "k8s-agent.fullname" . }}
    spec:
      serviceAccountName: {{ include "k8s-agent.fullname" . }}

      containers:
        - name: k8s-agent
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}

          envFrom:
            - secretRef:
                name: {{ .Values.existingSecret }}

          volumeMounts:
            - name: config
              mountPath: /app/config.yaml
              subPath: config.yaml
              readOnly: true

          resources:
            {{- toYaml .Values.resources | nindent 12 }}

      volumes:
        - name: config
          configMap:
            name: {{ include "k8s-agent.fullname" . }}-config
```

**Replicas: 1** — mehrere Instanzen würden denselben Cluster parallel analysieren und doppelte Alerts erzeugen.

**Hinweis Loop:** Der Agent endet nach einem Lauf (Stage 1). Das Deployment startet ihn automatisch neu (`restartPolicy: Always` ist Default). Das ist ein akzeptabler Workaround bis Stage 2 den Loop-Mechanismus implementiert.

---

### 9. `deploy/helm/k8s-agent/templates/_helpers.tpl`

```yaml
{{- define "k8s-agent.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
```

---

## Deploy-Ablauf

```bash
# 1. Image bauen
docker build -t k8s-agent:latest .

# 2. Secret anlegen (einmalig, außerhalb von Helm)
kubectl create secret generic k8s-agent-secrets \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-...

# 3. Helm installieren (Config kommt aus values.yaml)
helm install k8s-agent deploy/helm/k8s-agent/

# 4. Config ändern → einfach upgrade
helm upgrade k8s-agent deploy/helm/k8s-agent/ \
  --set agentConfig.kubernetes.namespaces[0]=production

# 5. Logs prüfen
kubectl logs -f deployment/k8s-agent-k8s-agent
```

---

## Coding Standards

- Kein `secret.yaml`-Template — Secrets gehören nicht in den Helm-Release-State
- `values.yaml` ist Source of Truth für die Agent-Config — kein separates Synchronisieren mit `config.yaml`
- Alle Helm-Templates nutzen `{{ include "k8s-agent.fullname" . }}` — keine hartkodtierten Namen
- `deploy/` in `.gitignore` nur für generierte Dateien, nicht für das Chart selbst

## Done when

```bash
helm install k8s-agent deploy/helm/k8s-agent/
kubectl logs -f deployment/k8s-agent-k8s-agent
```

gibt die Analyse-Ausgabe aus — identisch zu `python agent.py` lokal, aber mit In-Cluster-Auth und Helm-verwalteter Config.
