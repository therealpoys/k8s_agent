import logging
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from src.models import Finding, Alert
from src.plugins.pod_logs import PodLogsPlugin
from src import analyzer
from src.outputs import console

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    findings: list[Finding]
    alert: Alert | None


def _collect_findings(state: AgentState) -> dict:
    try:
        plugin = PodLogsPlugin()
        findings = plugin.run()
        return {"findings": findings}
    except Exception as exc:
        logger.error("collect_findings failed: %s", exc)
        return {"findings": []}


def _analyze_findings(state: AgentState) -> dict:
    alert = analyzer.analyze(state["findings"])
    return {"alert": alert}


def _send_output(state: AgentState) -> dict:
    console.send(state["alert"])
    return {}


def build_graph():
    """Baut und kompiliert den LangGraph Agent."""
    graph = StateGraph(AgentState)

    graph.add_node("collect_findings", _collect_findings)
    graph.add_node("analyze_findings", _analyze_findings)
    graph.add_node("send_output", _send_output)

    graph.add_edge(START, "collect_findings")
    graph.add_edge("collect_findings", "analyze_findings")
    graph.add_edge("analyze_findings", "send_output")
    graph.add_edge("send_output", END)

    return graph.compile()
