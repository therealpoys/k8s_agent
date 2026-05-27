import json
import logging
from datetime import datetime

from src.config import config
from src.models import Alert, Finding

logger = logging.getLogger(__name__)

_VALID_SEVERITIES = {"info", "warning", "critical"}
_SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}

_PROMPT_TEMPLATE = """You are a Kubernetes observability agent. Analyze the following findings from a cluster and respond with a JSON object only — no markdown, no explanation.

Findings:
{findings}

Respond with exactly this JSON structure:
{{
  "severity": "<info|warning|critical>",
  "summary": "<2-3 sentence summary of the situation>",
  "recommendation": "<concrete action to take>"
}}

Rules:
- severity must be one of: info, warning, critical
- summary must be 2-3 sentences
- recommendation must be a concrete, actionable step"""


def _highest_severity(findings: list[Finding]) -> str:
    """Gibt den höchsten Severity-Wert aus einer Liste von Findings zurück."""
    if not findings:
        return "info"
    return max(
        (f.severity for f in findings if f.severity in _SEVERITY_ORDER),
        key=lambda s: _SEVERITY_ORDER.get(s, 0),
        default="info",
    )


def _build_llm():
    provider = config.llm_provider
    model = config.llm_model
    timeout = config.llm_timeout

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model, timeout=timeout)

    if provider == "ollama":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            timeout=timeout,
            base_url=config.llm_base_url,
            api_key="ollama",
        )

    # default: openai
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=model, timeout=timeout)


def _degraded_alert(findings: list[Finding]) -> Alert:
    return Alert(
        findings=findings,
        severity=_highest_severity(findings),
        summary="LLM analysis unavailable",
        recommendation="Check logs manually",
        generated_at=datetime.utcnow(),
    )


def analyze(findings: list[Finding]) -> Alert:
    """Analysiert Findings via LLM und gibt einen Alert zurück."""
    findings_text = "\n".join(
        f"- [{f.severity.upper()}] {f.source}/{f.namespace}/{f.resource}: {f.message}"
        for f in findings
    ) or "(no findings)"

    prompt = _PROMPT_TEMPLATE.format(findings=findings_text)

    try:
        llm = _build_llm()
        response = llm.invoke(prompt)
        raw_content = response.content if hasattr(response, "content") else str(response)

        data = json.loads(raw_content)

        severity = data.get("severity", "warning")
        if severity not in _VALID_SEVERITIES:
            logger.warning("LLM returned invalid severity %r, defaulting to 'warning'", severity)
            severity = "warning"

        return Alert(
            findings=findings,
            severity=severity,
            summary=data["summary"],
            recommendation=data["recommendation"],
            generated_at=datetime.utcnow(),
        )

    except json.JSONDecodeError as e:
        logger.error("LLM returned invalid JSON: %s", e)
        return _degraded_alert(findings)
    except Exception as e:
        logger.error("LLM analysis failed: %s", e)
        return _degraded_alert(findings)
