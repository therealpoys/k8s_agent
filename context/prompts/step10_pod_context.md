# Prompt — Schritt 10: Pod-Spec, Status & Events als Kontext

## Kontext

Schritt 9 (`agent.py`) ist abgeschlossen. Der Agent läuft und analysiert Pod-Logs. Das LLM bekommt aber nur rohe Log-Zeilen — ohne zu wissen welches Image läuft, ob Limits gesetzt sind, wie oft ein Container schon neu gestartet wurde, oder welche Kubernetes-Events es zu dem Pod gibt.

Dieses Problem lösen wir hier: mehr Kontext pro Pod, bessere Analyse.

## Aufgabe

Erweitere `src/plugins/pod_logs.py` und `src/analyzer.py`.

### 1. `pod_logs.py` — mehr Daten pro Finding

Das `pod`-Objekt (Zeile 48) ist bereits vorhanden. Füge pro Container folgende Felder in das `raw`-Dict ein:

**Aus `pod.spec`:**
```python
"image": container_spec.image,
"resources": {
    "requests": container_spec.resources.requests or {},
    "limits":   container_spec.resources.limits   or {},
},
"liveness_probe":  bool(container_spec.liveness_probe),
"readiness_probe": bool(container_spec.readiness_probe),
```

**Aus `pod.status`:**
```python
"phase": pod.status.phase,          # Running / Pending / Failed / ...
"restart_count": <int>,             # aus container_status.restart_count (0 wenn nicht vorhanden)
"ready": <bool>,                    # aus container_status.ready
"state": <str>,                     # "running" | "waiting:<reason>" | "terminated:<reason>"
```

Für `state` den aktuellen Container-State auflösen:
```python
cs = container_status.state
if cs.running:
    state = "running"
elif cs.waiting:
    state = f"waiting:{cs.waiting.reason}"
elif cs.terminated:
    state = f"terminated:{cs.terminated.reason}"
```

Container-Status aus `pod.status.container_statuses` per Container-Name matchen — Liste kann `None` sein.

**Kubernetes-Events pro Pod** (separater API-Call):
```python
events = self._v1.list_namespaced_event(
    namespace,
    field_selector=f"involvedObject.name={pod_name}",
    timeout_seconds=5,
).items
```

Aus jedem Event nur diese Felder:
```python
{
    "reason": event.reason,
    "message": event.message,
    "count": event.count,
    "type": event.type,   # "Normal" | "Warning"
}
```

Nur Warning-Events oder Events mit `count > 1` ins `raw`-Dict aufnehmen (`"events": [...]`). Bei API-Fehler: leere Liste, nur `logger.warning`.

### 2. `analyzer.py` — Prompt erweitern

Der bestehende Prompt in `_build_prompt()` beschreibt jedes Finding als Log-Eintrag. Erweitere ihn so, dass das LLM die neuen Felder kennt und nutzt:

```
Für jedes Finding stehen folgende Daten zur Verfügung:
- logs: die letzten N Log-Zeilen des Containers
- image: genutztes Container-Image inkl. Tag
- resources.requests / resources.limits: CPU- und Memory-Konfiguration (leer = nicht gesetzt)
- liveness_probe / readiness_probe: ob Probes konfiguriert sind (true/false)
- phase: Kubernetes Pod-Phase
- restart_count: Anzahl Container-Neustarts
- ready: ob der Container als Ready gilt
- state: aktueller Container-State (running / waiting:<reason> / terminated:<reason>)
- events: Kubernetes-Events zum Pod (nur Warnings oder häufige Events)

Nutze diese Informationen aktiv in deiner Analyse:
- Hohe restart_count → möglicher CrashLoop
- state "waiting:CrashLoopBackOff" oder "waiting:OOMKilled" → kritisch
- Fehlende Limits bei hohem Verbrauch → Konfigurationsproblem
- Fehlende Probes → Verfügbarkeitsrisiko
- Warning-Events geben oft den direkten Fehlergrund an
```

Gib die neuen Felder aus `raw` strukturiert in den Prompt — nicht als rohen Dict-Dump, sondern als lesbaren Block pro Finding.

## Coding Standards

- Kein Breaking Change am `Finding`-Datenmodell — alles geht in das bestehende `raw`-Dict
- Events-API-Fehler dürfen den Pod-Lauf nicht abbrechen — immer `try/except`
- Container-Status-Matching per Name, nicht per Index
- Kein `print()` — nur `logger.*`

## Done when

Das LLM bekommt pro Finding einen Block wie diesen:

```
Pod: my-app-7d9f8b-xkj2p / my-app
Image: my-registry/my-app:v1.2.3
Phase: Running | State: waiting:CrashLoopBackOff | Restarts: 5 | Ready: false
Limits: cpu=500m, memory=256Mi | Requests: cpu=100m, memory=128Mi
Probes: liveness=true, readiness=false
Events:
  [Warning] BackOff (x12): Back-off restarting failed container
Logs (last 100 lines):
  ...
```

Und gibt eine Analyse aus, die auf Restarts, State und Events eingeht — nicht nur auf Log-Inhalte.
