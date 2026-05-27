# Entwicklungsplan — K8s Observability Agent

## Stage 1 — Fundament

Geordnet nach Abhängigkeiten. Jeder Schritt baut auf dem vorherigen auf.

---

### Schritt 1 — Projekt-Setup

**Dateien:** `requirements.txt`, `.env.example`, `.gitignore`, `config.yaml`, `config.yaml.example`

**Ziel:** Lauffähige Python-Umgebung mit allen Dependencies und Konfigurationsvorlagen.

**Done when:** `pip install -r requirements.txt` läuft durch, `config.yaml` ist befüllt.

---

### Schritt 2 — Datenmodell (`src/models.py`)

**Ziel:** `Finding` und `Alert` Dataclasses definieren.

Alles andere hängt davon ab. Zuerst bauen, damit Plugins und Analyzer dieselbe Sprache sprechen.

**Done when:** `Finding` und `Alert` sind als typisierte Dataclasses vorhanden und importierbar.

---

### Schritt 3 — Config-Loader (`src/config.py`)

**Ziel:** `config.yaml` laden und als typisierte Konstanten bereitstellen.

Plugins brauchen Namespace-Listen und Loop-Intervall — daher vor den Plugins.

**Done when:** `from src.config import config` liefert Namespaces, Plugin-Liste und Loop-Intervall.

---

### Schritt 4 — Plugin-Interface (`src/plugins/base.py`)

**Ziel:** `BasePlugin` Abstraktion definieren.

Vor dem ersten konkreten Plugin, damit das Interface klar ist bevor es implementiert wird.

**Done when:** `BasePlugin` ist als abstrakte Klasse vorhanden mit `run() -> list[Finding]` Methode.

---

### Schritt 5 — Erstes Plugin (`src/plugins/pod_logs.py`)

**Ziel:** Pod-Logs via Kubernetes Python Client lesen, `list[Finding]` zurückgeben.

Kernfunktionalität von Stage 1. Lokal testbar mit echtem `kubeconfig`. Unterstützt In-Cluster und lokal.

**Done when:** Plugin liest Logs aller konfigurierten Namespaces und gibt `list[Finding]` zurück.

---

### Schritt 6 — LLM Analyzer (`src/analyzer.py`)

**Ziel:** `list[Finding]` rein → `Alert` raus (Severity + Summary + Recommendation).

LLM-Provider per Config wählbar (OpenAI / Anthropic). Bei LLM-Fehler: Degraded Mode — Alert ohne Summary, kein Absturz.

**Done when:** Analyzer gibt valides `Alert`-Objekt zurück, auch wenn LLM nicht erreichbar ist.

---

### Schritt 7 — Console Output (`src/outputs/console.py`)

**Ziel:** `Alert` strukturiert auf der Konsole ausgeben.

Einfachster Output-Kanal. Macht Testen ohne externe Dienste möglich.

**Done when:** Alert wird lesbar mit Severity, Summary und Recommendation ausgegeben.

---

### Schritt 8 — LangGraph Agent (`src/graph.py`)

**Ziel:** Alles verdrahten — `StateGraph` mit Pod-Logs-Tool → Analyzer → Console Output.

Kann erst gebaut werden wenn alle Teile existieren.

**Done when:** Agent führt einen vollständigen Zyklus durch (Logs lesen → analysieren → ausgeben).

---

### Schritt 9 — Einstiegspunkt (`agent.py`)

**Ziel:** `python agent.py` startet den Agent einmalig.

Loop-Mechanismus kommt in Stage 2.

**Done when:** `python agent.py` läuft durch und gibt Analyse auf der Konsole aus — Stage 1 abgeschlossen.

---

## Dependency-Grafik

```
models.py
    └─► config.py
            └─► plugins/base.py
                    └─► plugins/pod_logs.py
                                └─► analyzer.py ──► outputs/console.py
                                                            └─► graph.py
                                                                    └─► agent.py
```

---

## Roadmap-Übersicht

| Stage | Titel | Status |
|-------|-------|--------|
| 1 | Fundament — Agent liest Pod-Logs und gibt strukturierte Analyse aus | [ ] |
| 2 | Continuous Loop — Agent meldet sich selbstständig bei auffälligen Logs | [ ] |
| 3 | Erste Plugins + Output — Slack, Trivy, K8s Events | [ ] |
| 4 | Erweiterte Plugins — Falco, Prometheus, Korrelation | [ ] |
