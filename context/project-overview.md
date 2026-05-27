# K8s Observability Agent — Project Overview

> **Ein selbst gebauter, proaktiver Kubernetes Observability Agent mit LangGraph. Modular aufgebaut, läuft im Cluster, analysiert Logs und gibt Warnungen und Handlungsempfehlungen aus.**

---

## Das Problem

Kubernetes-Cluster erzeugen kontinuierlich Logs, Events und Security-Alerts aus verschiedenen Quellen:

| Was | Wo es passiert |
|-----|---------------|
| Pod-Fehler & Abstürze | `kubectl logs` |
| Cluster-Events | `kubectl get events` |
| CVE-Funde | Trivy Scan Results |
| Security-Events | Falco Alerts |
| Performance-Metriken | Prometheus |

Alles manuell zu überwachen ist nicht skalierbar. Dieser Agent korreliert alle Quellen automatisch und gibt strukturierte Warnungen aus.

---

## Tech Stack

| Layer | Technologie |
|-------|------------|
| **Agent Framework** | [LangGraph](https://langchain-ai.github.io/langgraph/) (LangChain) |
| **Sprache** | Python |
| **K8s Client** | [kubernetes](https://github.com/kubernetes-client/python) (offizieller Python-Client) |
| **LLM** | Offen — OpenAI / Anthropic / lokal via Ollama |
| **Deployment** | Kubernetes lokal (minikube / kind / k3d) |
| **Config** | `config.yaml` — Plugin-Aktivierung ohne Code-Änderung |
| **Output** | Slack, E-Mail, Webhook, Konsole |

---

## Architektur

```
LangGraph Agent Loop (kontinuierlich)
    │
    ├─► Core Plugins (immer aktiv)
    │   ├── pod_logs         → kubectl logs via K8s Python Client
    │   └── k8s_events       → kubectl get events
    │
    ├─► Optional Plugins (via config.yaml)
    │   ├── trivy            → Scan Results lesen
    │   ├── falco            → Security Alerts
    │   └── prometheus       → Metriken
    │
    └─► LLM Analyse
        ├── Anomalie-Erkennung
        ├── Schweregrad-Bewertung (Info / Warning / Critical)
        └── Handlungsempfehlung
              │
              ▼
        Output-Kanäle (via config.yaml)
        ├── Konsole
        ├── Slack Webhook
        ├── E-Mail
        └── Webhook
```

---

## Plugin-Konzept (`config.yaml`)

Plugins werden per `
plugins:
  core:
    - pod_logs
    - k8s_events
  optional:
    trivy: true
    falco: true
    prometheus: false

outputs:
  - slack

loop_interval_seconds: 60

namespaces:
  - default
  - production
```

---

## Roadmap

### Stage 1 — Fundament *(aktuell)*
**Ziel:** Lauffähiger LangGraph Agent mit erstem Tool

| Task | Status |
|------|--------|
| LangGraph Agent Skeleton aufsetzen | [ ] |
| Tool: Pod Logs lesen (kubectl logs via Python K8s Client) | [ ] |
| LLM analysiert Logs und gibt Einschätzung | [ ] |
| Output: Konsolenausgabe | [ ] |

**Done when:** Agent liest Logs eines Pods und gibt strukturierte Analyse aus

---

### Stage 2 — Continuous Loop
**Ziel:** Agent läuft proaktiv und dauerhaft

| Task | Status |
|------|--------|
| Loop-Mechanismus in LangGraph implementieren | [ ] |
| Intervall-basierte Log-Prüfung (z.B. alle 60s) | [ ] |
| Anomalie-Erkennung via LLM | [ ] |
| Schweregrad-Bewertung (Info / Warning / Critical) | [ ] |

**Done when:** Agent meldet sich selbstständig bei auffälligen Logs

---

### Stage 3 — Erste Plugins + Output
**Ziel:** Modulares Plugin-System + erster externer Output-Kanal

| Task | Status |
|------|--------|
| `config.yaml` für Plugin-Aktivierung einführen | [ ] |
| Plugin: Trivy Scan Results lesen | [ ] |
| Plugin: K8s Events (`kubectl get events`) | [ ] |
| Output: Slack Webhook Integration | [ ] |

**Done when:** Agent schickt strukturierte Warnungen nach Slack, Trivy-Ergebnisse werden korreliert

---

### Stage 4 — Erweiterte Plugins
**Ziel:** Vollständiges Observability-Bild

| Task | Status |
|------|--------|
| Plugin: Falco Alerts | [ ] |
| Plugin: Prometheus Metriken | [ ] |
| Korrelation über mehrere Quellen (Log + Trivy + Falco) | [ ] |
| Weitere Output-Kanäle (E-Mail, Webhook) | [ ] |

**Done when:** Agent korreliert Logs, CVEs und Security-Events zu einem einheitlichen Bericht

---

## Ordnerstruktur (geplant)

```
k8s_agent/
├── config.yaml                 # Plugin-Aktivierung, Outputs, Intervall
├── config.yaml.example         # Template
├── requirements.txt
├── agent.py                    # Haupteinstiegspunkt
├── context/                    # Claude-Kontext-Dateien
└── src/
    ├── config.py               # config.yaml laden + validieren
    ├── models.py               # Alert, Finding Dataclasses
    ├── graph.py                # LangGraph Agent Definition
    ├── plugins/
    │   ├── __init__.py
    │   ├── base.py             # Plugin-Interface
    │   ├── pod_logs.py         # Core: Pod Logs
    │   ├── k8s_events.py       # Core: K8s Events
    │   ├── trivy.py            # Optional: Trivy
    │   ├── falco.py            # Optional: Falco
    │   └── prometheus.py       # Optional: Prometheus
    ├── analyzer.py             # LLM Analyse + Schweregrad-Bewertung
    └── outputs/
        ├── __init__.py
        ├── console.py
        ├── slack.py
        ├── email.py
        └── webhook.py
```

---

## Datenmodell

```python
@dataclass
class Finding:
    source: str          # "pod_logs" | "k8s_events" | "trivy" | "falco"
    namespace: str
    resource: str        # Pod-Name, Deployment-Name, etc.
    severity: str        # "info" | "warning" | "critical"
    message: str         # Rohtext aus der Quelle
    timestamp: datetime
    raw: dict | None     # Originaldaten

@dataclass
class Alert:
    findings: list[Finding]
    severity: str        # Höchster Schweregrad aus findings
    summary: str         # LLM-generierte Zusammenfassung
    recommendation: str  # LLM-generierte Handlungsempfehlung
    generated_at: datetime
```
