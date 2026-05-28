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
  "summary": "<2-3 sentence summary of the overall situation>",
  "recommendation": "<overall action to take>",
  "findings": [
    {{
      "index": 1,
      "severity": "<info|warning|critical>",
      "recommendation": "<concrete, actionable step specific to this finding>"
    }}
  ]
}}

Rules:
- severity must be one of: info, warning, critical
- summary must be 2-3 sentences
- findings array must have exactly one entry per input finding, with index matching the Finding # number
- each recommendation must directly address that specific finding's log content — do not mix up findings"""


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


def _clean_log(message: str, max_chars: int = 400) -> str:
    if message.startswith("b'") or message.startswith('b"'):
        message = message[2:-1].replace("\\n", "\n").replace("\\'", "'")
    return message[:max_chars].strip()


def analyze(findings: list[Finding]) -> Alert:
    """Analysiert Findings via LLM und gibt einen Alert zurück."""
    findings_text = "\n\n".join(
        f"Finding #{i} [{f.severity.upper()}] {f.namespace}/{f.resource}:\n{_clean_log(f.message)}"
        for i, f in enumerate(findings, start=1)
    ) or "(no findings)"

    prompt = _PROMPT_TEMPLATE.format(findings=findings_text)

    try:
        llm = _build_llm()
        if config.debug_log_llm_io:
            logger.info("LLM REQUEST:\n%s", prompt)
        response = llm.invoke(prompt)
        raw_content = response.content if hasattr(response, "content") else str(response)
        if config.debug_log_llm_io:
            logger.info("LLM RESPONSE:\n%s", raw_content)

        data = json.loads(raw_content)

        severity = data.get("severity", "warning")
        if severity not in _VALID_SEVERITIES:
            logger.warning("LLM returned invalid severity %r, defaulting to 'warning'", severity)
            severity = "warning"

        per_finding = data.get("findings", [])
        enriched = list(findings)
        for finding_data in per_finding:
            idx = finding_data.get("index", 0) - 1
            if idx < 0 or idx >= len(enriched):
                continue
            f = enriched[idx]
            f_severity = finding_data.get("severity", f.severity)
            enriched[idx] = Finding(
                source=f.source,
                namespace=f.namespace,
                resource=f.resource,
                severity=f_severity if f_severity in _VALID_SEVERITIES else f.severity,
                message=f.message,
                timestamp=f.timestamp,
                raw=f.raw,
                recommendation=finding_data.get("recommendation"),
            )

        return Alert(
            findings=enriched,
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
