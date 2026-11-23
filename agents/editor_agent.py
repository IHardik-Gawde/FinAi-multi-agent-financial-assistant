"""
Deterministic Editor Agent.

The Supervisor and specialist agents have already done the reasoning and retrieval.
This component formats and consolidates their returned results. It makes no LLM calls,
does no retrieval, and performs no calculations.
"""

import re
from collections.abc import Mapping


def _humanize_key(key) -> str:
    """Turn internal field names into readable labels."""
    return re.sub(r"[_\-]+", " ", str(key)).strip().capitalize()


def _plain_value(value):
    """Convert common agent/document objects into printable Python values."""
    if hasattr(value, "page_content"):
        return {
            "page_content": value.page_content,
            "metadata": getattr(value, "metadata", {}) or {},
        }

    if isinstance(value, Mapping):
        return {str(k): _plain_value(v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [_plain_value(item) for item in value]

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    return str(value)


def _format_mapping(data: Mapping, indent: int = 0) -> list[str]:
    lines = []
    prefix = " " * indent

    for key, value in data.items():
        key_lower = str(key).lower()
        if key_lower in {"embedding", "embeddings", "vector", "vectors", "id"}:
            continue

        label = _humanize_key(key)
        if isinstance(value, Mapping):
            lines.append(f"{prefix}{label}:")
            lines.extend(_format_mapping(value, indent + 2))
        elif isinstance(value, list):
            if not value:
                lines.append(f"{prefix}{label}: none returned")
                continue
            lines.append(f"{prefix}{label}:")
            for item in value:
                if isinstance(item, Mapping):
                    lines.extend(_format_mapping(item, indent + 2))
                else:
                    lines.append(f"{' ' * (indent + 2)}- {item}")
        else:
            lines.append(f"{prefix}{label}: {value}")

    return lines


def _format_document(document, index: int) -> str:
    """Format a retrieved document/chunk while retaining its source metadata."""
    document = _plain_value(document)

    if isinstance(document, Mapping):
        metadata = document.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            metadata = {"details": metadata}

        source = (
            metadata.get("source")
            or metadata.get("file_path")
            or metadata.get("filename")
            or document.get("source")
            or f"Research result {index}"
        )
        page = metadata.get("page")
        heading = f"- {source}"
        if page is not None:
            heading += f" (page {page})"

        content = (
            document.get("page_content")
            or document.get("content")
            or document.get("text")
        )
        if content is not None:
            return f"{heading}:\n{str(content).strip()}"

        details = {
            key: value
            for key, value in document.items()
            if key not in {"metadata", "id", "embedding", "embeddings"}
        }
        detail_lines = _format_mapping(details, 2)
        return heading + (("\n" + "\n".join(detail_lines)) if detail_lines else "")

    return f"- Research result {index}:\n{str(document).strip()}"


def _format_finance_result(result) -> str:
    result = _plain_value(result)
    if result is None:
        return ""
    if isinstance(result, Mapping):
        lines = _format_mapping(result)
        return "\n".join(lines) if lines else ""
    if isinstance(result, list):
        return "\n".join(f"- {item}" for item in result)
    text = str(result).strip()
    # Finance may return Markdown with newline escape sequences as literal text.
    # Restore those sequences so headings, paragraphs, and tables render correctly.
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    return text


def _get_research_documents(research_result):
    """Support the common Research Agent response wrappers."""
    if research_result is None:
        return []

    result = _plain_value(research_result)
    if isinstance(result, Mapping):
        nested = result.get("research_result")
        if isinstance(nested, Mapping):
            documents = nested.get("documents")
            if isinstance(documents, list):
                return documents

        documents = result.get("documents")
        if isinstance(documents, list):
            return documents

        if nested is not None:
            return [nested]

        evidence = result.get("research_evidence")
        if evidence is not None:
            return evidence if isinstance(evidence, list) else [evidence]

        return [result]

    return result if isinstance(result, list) else [result]


def _split_research_sentences(text: str) -> list[str]:
    """Convert unstructured prose into readable points without changing wording.

    Existing Markdown structure is retained. Plain paragraphs are split at
    sentence boundaries and presented as separate bullets.
    """
    raw_text = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw_text:
        return []

    # Preserve headings, bullets, numbered lists, and paragraph boundaries.
    lines = [line.rstrip() for line in raw_text.split("\n")]
    has_markdown_structure = any(
        re.match(r"^\s*(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|>\s)", line) for line in lines
    )
    if has_markdown_structure:
        formatted = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if formatted and formatted[-1] != "":
                    formatted.append("")
                continue
            # Keep existing Markdown markers and indentation intact.
            formatted.append(line.rstrip())
        while formatted and not formatted[-1]:
            formatted.pop()
        return formatted

    # Treat each source paragraph independently, then split prose into points.
    paragraphs = [
        re.sub(r"\s+", " ", paragraph).strip()
        for paragraph in re.split(r"\n\s*\n", raw_text)
        if paragraph.strip()
    ]
    points = []
    for paragraph in paragraphs:
        protected = re.sub(
            r"\b(Pvt|Ltd|Inc|Corp|Co|Dr|Mr|Mrs|Ms|Prof)\.",
            lambda match: match.group(0).replace(".", "<DOT>"),
            paragraph,
            flags=re.IGNORECASE,
        )
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z₹0-9*])", protected)
        points.extend(
            sentence.replace("<DOT>", ".").strip()
            for sentence in sentences
            if sentence.strip()
        )
    return points


def _format_research_result(research_result, research_evidence=None) -> str:
    """Present research as scannable findings and list the retrieved sources."""
    documents = _get_research_documents(research_result)
    if not documents:
        return ""

    # The Research Agent currently returns a narrative string. Avoid displaying
    # the artificial "Research result 1" wrapper as if it were a document.
    if len(documents) == 1 and isinstance(documents[0], str):
        findings = _split_research_sentences(documents[0])
        if not findings:
            return ""
        has_own_heading = bool(findings and findings[0].lstrip().startswith("#"))
        lines = [] if has_own_heading else ["### Research Findings"]
        for line in findings:
            if not line:
                if lines[-1] != "":
                    lines.append("")
            elif line.startswith(("#", "- ", "* ", "+ ", "> ")) or re.match(
                r"^\d+[.)]\s", line
            ):
                lines.append(line)
            else:
                lines.append(f"- {line}")
        while lines and not lines[-1]:
            lines.pop()

        sources = []
        seen = set()
        for item in research_evidence or []:
            if isinstance(item, Mapping):
                source = item.get("source")
                if source and source not in seen:
                    seen.add(source)
                    sources.append(str(source))
        if sources:
            lines.extend(["", "### Sources"])
            lines.extend(f"- {source}" for source in sources)
        return "\n".join(lines)

    return "\n\n".join(
        _format_document(document, index)
        for index, document in enumerate(documents, start=1)
    ).strip()


def _normalize_line(line: str) -> str:
    """Normalize a line for conservative duplicate detection."""
    line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
    line = re.sub(r"^\s*[-*]\s*", "", line)
    return re.sub(r"\s+", " ", line).strip(" :\t").casefold()


def _is_repeated_financial_fact(line: str, finance_text: str) -> bool:
    """Detect research lines that restate facts already reported by Finance."""
    normalized = _normalize_line(line)
    finance_normalized = _normalize_line(finance_text)
    if not normalized:
        return True
    if normalized.startswith("research result "):
        return True
    if normalized in {"uploaded financial report figures", "financial report figures"}:
        return True
    if normalized in finance_normalized:
        return True

    # If a research sentence repeats a transaction/invoice identifier already
    # covered by Finance, it is a duplicate even when the surrounding wording
    # differs (for example, "The report lists invoice INV-001 as overdue").
    identifiers = set(
        re.findall(r"\b[A-Z]{2,}[A-Z0-9]*-\d{3,}(?:-\d+)?\b", line, re.IGNORECASE)
    )
    finance_identifiers = set(
        re.findall(
            r"\b[A-Z]{2,}[A-Z0-9]*-\d{3,}(?:-\d+)?\b",
            finance_text,
            re.IGNORECASE,
        )
    )
    if identifiers and identifiers.issubset(finance_identifiers):
        return True

    # Search anywhere in the sentence, not only at its beginning. This catches
    # narrative restatements such as "The report records revenue of ₹860,000".
    metric_pattern = (
        r"\b(revenue|operating expenses?|net operating difference)\b"
        r"[^\d₹]{0,40}(?:₹|inr|rs\.?|■)?\s*([\d,]+(?:\.\d+)?)"
    )
    metric_matches = re.finditer(metric_pattern, line, flags=re.IGNORECASE)
    finance_metrics = {}
    for candidate in re.finditer(metric_pattern, finance_text, flags=re.IGNORECASE):
        metric = re.sub(r"\s+", " ", candidate.group(1).casefold())
        finance_metrics.setdefault(metric, set()).add(
            candidate.group(2).replace(",", "")
        )
    for match in metric_matches:
        metric = re.sub(r"\s+", " ", match.group(1).casefold())
        value = match.group(2).replace(",", "")
        if value in finance_metrics.get(metric, set()):
            return True

    # Company headings are redundant when Finance already names the company.
    heading = re.sub(r"\s*[—–-]\s*.*$", "", normalized)
    heading = re.sub(r"\s*\(.*?\)\s*$", "", heading)
    if len(heading) >= 8 and not re.search(r"\d", heading):
        if heading in finance_normalized:
            return True

    return False


def _consolidate_results(finance_text: str, research_text: str) -> str:
    """Keep Finance as the numeric/comparison source and add distinct research."""
    if not finance_text:
        return research_text
    if not research_text:
        return finance_text

    remaining_lines = [
        line
        for line in research_text.splitlines()
        if not _is_repeated_financial_fact(line, finance_text)
    ]
    distinct_research = "\n".join(remaining_lines).strip()
    distinct_research = re.sub(r"\n{3,}", "\n\n", distinct_research)

    if not distinct_research:
        return finance_text

    return finance_text + "\n\nAdditional Research Findings:\n" + distinct_research


def editor_agent(state: dict):
    """Consolidate specialist results without redoing their reasoning."""
    selected_agents = state.get("next_agent") or []
    sections = []

    finance_text = ""
    research_text = ""

    if "finance" in selected_agents:
        finance_text = _format_finance_result(state.get("finance_result"))
        if not finance_text:
            finance_text = "The Finance Agent did not return any usable results."

    if "research" in selected_agents:
        research_text = _format_research_result(
            state.get("research_result"), state.get("research_evidence")
        )
        if not research_text:
            research_text = "The Research Agent did not return any usable results."

    if "finance" in selected_agents and "research" in selected_agents:
        consolidated = _consolidate_results(finance_text, research_text)
        if consolidated:
            sections.append(consolidated)
    else:
        if "finance" in selected_agents:
            sections.append("Finance Agent Results:\n" + finance_text)
        if "research" in selected_agents:
            sections.append("Research Agent Results:\n" + research_text)

    if not sections:
        final_response = (
            "I could not retrieve any results from the Finance or Research Agent."
        )
    else:
        final_response = "\n\n".join(sections)

    user_query = str(state.get("user_query", "")).lower()
    asks_for_period_comparison = (
        any(
            term in user_query
            for term in (
                "previous period",
                "prior period",
                "prior-period",
                "period-over-period",
                "period over period",
            )
        )
        or "percentage change" in user_query
    )
    if (
        asks_for_period_comparison
        and "finance" in selected_agents
        and "research" not in selected_agents
    ):
        final_response += (
            "\n\nPeriod comparison limitation: the current Finance Agent "
            "tool returns an aggregate summary and does not retrieve separate "
            "current- and previous-period values. Previous-period figures and "
            "percentage changes therefore cannot be established from the "
            "available internal data."
        )

    return {
        "editor_result": final_response,
        "final_response": final_response,
    }
