import logging
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from src.dedup import Deduplicator
from src.models import Finding, Alert
from src.plugins.loader import load_plugins
from src import analyzer
from src.outputs import console

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    findings: list[Finding]
    alert: Alert | None


def _collect_findings(state: AgentState) -> dict:
    all_findings: list[Finding] = []
    for plugin in load_plugins():
        try:
            findings = plugin.run()
            all_findings.extend(findings)
            logger.debug("Plugin %s: %d Findings", plugin.name, len(findings))
        except Exception as exc:
            logger.error("Plugin %s fehlgeschlagen: %s", plugin.name, exc)
    return {"findings": all_findings}


def _dedup_findings(state: AgentState) -> dict:
    try:
        dedup = Deduplicator()
        new_findings = dedup.filter_new(state["findings"])
        dedup.cleanup_resolved()
    except Exception as exc:
        logger.error("Dedup fehlgeschlagen (%s) — Findings ungefiltert weitergereicht", exc)
        return {"findings": state["findings"]}
    return {"findings": new_findings}


def _analyze_findings(state: AgentState) -> dict:
    alert = analyzer.analyze(state["findings"])
    return {"alert": alert}


def _persist_recommendations(state: AgentState) -> dict:
    alert = state.get("alert")
    if not alert:
        return {}
    try:
        Deduplicator().update_recommendations(alert.findings)
    except Exception as exc:
        logger.warning("Recommendations konnten nicht in SeenFindings gespeichert werden: %s", exc)
    return {}


def _send_output(state: AgentState) -> dict:
    console.send(state["alert"])
    return {}


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("collect_findings", _collect_findings)
    graph.add_node("dedup_findings", _dedup_findings)
    graph.add_node("analyze_findings", _analyze_findings)
    graph.add_node("persist_recommendations", _persist_recommendations)
    graph.add_node("send_output", _send_output)

    graph.add_edge(START, "collect_findings")
    graph.add_edge("collect_findings", "dedup_findings")
    graph.add_edge("dedup_findings", "analyze_findings")
    graph.add_edge("analyze_findings", "persist_recommendations")
    graph.add_edge("persist_recommendations", "send_output")
    graph.add_edge("send_output", END)

    return graph.compile()
