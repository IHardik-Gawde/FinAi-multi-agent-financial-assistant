import json
import os
import re
import time
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_ollama import ChatOllama

from rag.document_manager import get_vector_store


def _env_flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() not in {"0", "false", "no", "off"}


# Latency / hallucination settings for a small local model:
# - reasoning off: hidden "thinking" tokens were most of the 9s + 32s LLM time
# - low temperature: a 1.7B model drifts and invents things at 0.6
# - num_ctx: Ollama's default (~4k) silently TRUNCATES long prompts, which can
#   cut off the system prompt and leaves the model guessing
# - num_predict: hard cap so a rambling answer cannot run for 30+ seconds
# - keep_alive: keep the model loaded between requests (no reload cost)
llm = ChatOllama(
    model="qwen3:1.7b",
    temperature=0.1,
    reasoning=_env_flag("RESEARCH_REASONING", "0"),
    num_ctx=8192,
    num_predict=900,
    keep_alive="30m",
)
# The second "verify everything" LLM pass cost ~32s and made answers worse
# (it re-wrote the first draft). Off by default; set RESEARCH_FINAL_PASS=1 to enable.
USE_FINAL_PASS = _env_flag("RESEARCH_FINAL_PASS", "0")
INITIAL_TOP_K = 6
EVIDENCE_TEXT_CHARS = 900
MAX_TOOL_CALLS = 8
DEFAULT_TOP_K = 5
MAX_TOP_K = 12
MAX_TOOL_RESULT_CHARS = 9000
DEBUG_RESEARCH = os.getenv("RESEARCH_DEBUG", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}


def _debug(message: str, **details) -> None:
    """Print a debug event and optional structured details.

    Accepting keyword details keeps instrumentation calls from interrupting
    the research workflow when a caller adds structured diagnostic fields.
    """
    if not DEBUG_RESEARCH:
        return
    if details:
        payload = json.dumps(details, ensure_ascii=False, default=str, sort_keys=True)
        print(f"[RESEARCH_DEBUG] {message} {payload}", flush=True)
    else:
        print(f"[RESEARCH_DEBUG] {message}", flush=True)


def _timed_invoke(label: str, model, messages):
    started = time.perf_counter()
    try:
        return model.invoke(messages)
    finally:
        elapsed = time.perf_counter() - started
        _debug(f"TIMING {label}_seconds={elapsed:.3f}")


def _build_response(
    result: str,
    evidence: Optional[list] = None,
    entities: Optional[list] = None,
    needs_finance_agent: bool = False,
    needs_clarification: bool = False,
) -> dict:
    evidence = evidence or []
    sources, seen = [], set()
    for item in evidence:
        key = (item.get("source", "Unknown"), item.get("entity"))
        if key not in seen:
            seen.add(key)
            sources.append({"source": key[0], "entity": key[1]})
    return {
        "research_result": result,
        "research_evidence": evidence,
        "research_sources": sources,
        "research_entities": entities or [],
        "needs_finance_agent": needs_finance_agent,
        "needs_clarification": needs_clarification,
    }


def _source_catalog(vector_store) -> list[dict]:
    """Expose indexed source metadata; do not infer which source the user means."""
    catalog = {}
    documents = getattr(vector_store, "documents", [])
    document_ids = getattr(vector_store, "document_ids", [])
    chunk_metadata = getattr(vector_store, "chunk_metadata", [])

    for index, document_id in enumerate(document_ids):
        if not isinstance(document_id, (tuple, list)) or len(document_id) < 2:
            continue
        source = str(document_id[1])
        item = catalog.setdefault(
            source, {"source": source, "chunks": 0, "companies": []}
        )
        item["chunks"] += 1
        if index < len(chunk_metadata):
            metadata = chunk_metadata[index]
            company = metadata.get("company") if isinstance(metadata, dict) else None
            if (
                isinstance(company, str)
                and company.strip()
                and company.strip() not in item["companies"]
            ):
                item["companies"].append(company.strip())

    return list(catalog.values())


def _normalize_match_text(value: str) -> str:
    """Normalize names so punctuation, spaces, and casing do not affect matching."""
    return "".join(char.lower() for char in str(value) if char.isalnum())


def _match_sources_mentioned_in_query(
    user_query: str, source_catalog: list[dict]
) -> list[str]:
    """
    Match explicitly mentioned indexed source/company names.
    This is lexical entity resolution, not semantic retrieval.
    """
    normalized_query = _normalize_match_text(user_query)
    matches = []

    for item in source_catalog:
        source = str(item.get("source", ""))
        aliases = [os.path.splitext(os.path.basename(source))[0]]
        aliases.extend(
            company for company in item.get("companies", []) if isinstance(company, str)
        )

        matched_aliases = [
            _normalize_match_text(alias)
            for alias in aliases
            if len(_normalize_match_text(alias)) >= 4
            and _normalize_match_text(alias) in normalized_query
        ]
        if matched_aliases:
            matches.append((max(map(len, matched_aliases)), source))

    # Prefer more specific aliases and preserve catalog order for ties.
    matches.sort(key=lambda item: item[0], reverse=True)
    result, seen = [], set()
    for _, source in matches:
        if source not in seen:
            seen.add(source)
            result.append(source)
    return result or _match_sources_by_tokens(user_query, source_catalog)


# ---------------------------------------------------------------------------
# Deterministic "what is in the vector store?" path (no LLM, ~0 ms)
# ---------------------------------------------------------------------------
_INVENTORY_VERB = re.compile(
    r"\b(list|show|names?|which|enumerate|display|how many|what (?:pdfs?|documents?|docs?|files?|invoices?))\b",
    re.I,
)
_INVENTORY_NOUN = re.compile(
    r"\b(pdfs?|documents?|docs?|files?|invoices?|sources?|uploads?|uploaded)\b", re.I
)
_INVENTORY_SCOPE = re.compile(
    r"(vector\s*(store|db|database)|\bindex(ed)?\b|uploaded|knowledge\s*base|"
    r"\bavailable\b|\bpresent\b|\bstored\b|\ball\b|\bsystem\b|\bhave\b)",
    re.I,
)
# Words that mean the user wants document CONTENT, not an inventory.
_CONTENT_WORDS = re.compile(
    r"(amount|total|due\b|overdue|pending|paid|status|revenue|expense|profit|balance|"
    r"customer|summar|compare|calculat|how much|why\b|detail|contain|mention|"
    r"include|says?\b|inside|about\b|explain|risk|trend)",
    re.I,
)
_INVOICE_ID_RE = re.compile(r"(?<![\w-])[A-Z]{1,4}-\d{2,4}-\d{2,4}(?![\w-])")


def _is_inventory_query(user_query: str) -> bool:
    """True when the user only wants to know WHICH documents exist."""
    q = user_query or ""
    return bool(
        _INVENTORY_VERB.search(q)
        and _INVENTORY_NOUN.search(q)
        and _INVENTORY_SCOPE.search(q)
        and not _CONTENT_WORDS.search(q)
        and not _INTERPRETIVE_RE.search(q)
    )


def _chunk_texts_by_source(vector_store) -> dict:
    texts: dict = {}
    documents = getattr(vector_store, "documents", [])
    document_ids = getattr(vector_store, "document_ids", [])
    for index, document_id in enumerate(document_ids):
        if not isinstance(document_id, (tuple, list)) or len(document_id) < 2:
            continue
        if index >= len(documents):
            break
        doc = documents[index]
        text = doc.get("text", "") if isinstance(doc, dict) else str(doc)
        texts.setdefault(str(document_id[1]), []).append(text)
    return texts


def _describe_source(chunks: list) -> tuple:
    """Return (document_type, invoice_ids) using plain pattern matching."""
    joined = "\n".join(chunks)
    is_invoice = bool(
        re.search(r"invoice\s*(no|number)\b", joined, re.I)
        and re.search(r"bill\s*to", joined, re.I)
    )
    ids = []
    for match in _INVOICE_ID_RE.findall(joined):
        if match not in ids:
            ids.append(match)
    if is_invoice:
        return "Invoice", ids
    if re.search(r"accounts receivable|operating expense", joined, re.I):
        return "Financial report", ids
    return "Document", ids


def _inventory_answer(vector_store, source_catalog: list) -> dict:
    """Build the document list straight from the index. No model involved."""
    chunk_texts = _chunk_texts_by_source(vector_store)
    rows, invoices, reports = [], [], []
    for number, item in enumerate(source_catalog, start=1):
        source = item["source"]
        doc_type, ids = _describe_source(chunk_texts.get(source, []))
        company = ", ".join(item.get("companies", [])) or "-"
        rows.append(
            f"| {number} | {source} | {doc_type} | {company} | "
            f"{', '.join(ids) if ids else '-'} |"
        )
        (invoices if doc_type == "Invoice" else reports).append(source)

    lines = [
        f"## Documents in the vector store ({len(source_catalog)} PDFs)",
        "",
        "| # | File | Type | Company | Invoice IDs found in indexed text |",
        "|---|------|------|---------|------------------------------------|",
        *rows,
        "",
    ]
    if invoices:
        lines.append("**Standalone invoices:** " + ", ".join(invoices))
    else:
        lines.append("**Standalone invoices:** none detected")
    lines.append(
        "**Other documents (financial reports; their receivable invoice IDs are listed above):** "
        + (", ".join(reports) if reports else "none")
    )
    lines.append("")
    lines.append(
        "_This list comes from the index metadata and indexed text, not from a model summary._"
    )
    answer = "\n".join(lines)

    response = _build_response(answer)
    response["research_sources"] = [
        {"source": item["source"], "entity": (item.get("companies") or [None])[0]}
        for item in source_catalog
    ]
    return response


def _compact_evidence(evidence: list, limit: int = EVIDENCE_TEXT_CHARS) -> list:
    """Shorter evidence for the prompt: fewer tokens, faster generation."""
    compact = []
    for item in evidence:
        entry = {
            "source": item.get("source"),
            "text": str(item.get("text", ""))[:limit],
        }
        if item.get("company"):
            entry["company"] = item["company"]
        compact.append(entry)
    return compact


def _make_retrieval_tools(vector_store, evidence_store: list, source_catalog: list):
    """Create request-scoped tools. Qwen selects tools and supplies their arguments."""

    @tool
    def list_uploaded_sources() -> str:
        """List the documents currently indexed in the user's uploaded-document store, including source names and available company metadata. Use this when you need to discover which documents or companies are available."""
        return json.dumps(source_catalog, ensure_ascii=False)

    @tool
    def search_uploaded_documents(
        query: str, top_k: int = DEFAULT_TOP_K, source: Optional[str] = None
    ) -> str:
        """Search uploaded-document chunks using a semantic query. Choose the query to retrieve the evidence needed for the user's request. Optionally restrict the search to one exact source filename returned by list_uploaded_sources. Use top_k from 1 to 12."""
        if not isinstance(query, str) or not query.strip():
            return "Search not run: query must be a non-empty string."
        try:
            count = max(1, min(int(top_k), MAX_TOP_K))
        except (TypeError, ValueError):
            count = DEFAULT_TOP_K

        kwargs = {"top_k": count}
        if source:
            known_sources = {item["source"] for item in source_catalog}
            if source not in known_sources:
                return json.dumps(
                    {
                        "error": "Unknown source. Call list_uploaded_sources to see exact source names."
                    }
                )
            kwargs["allowed_sources"] = [source]

        _debug(
            f"TOOL_CALL search_uploaded_documents query={query!r} top_k={count} source={source!r}"
        )
        try:
            search_started = time.perf_counter()
            try:
                results = vector_store.search(query.strip(), **kwargs)
            finally:
                _debug(
                    f"TIMING vector_search_seconds="
                    f"{time.perf_counter() - search_started:.3f}"
                )
        except Exception as exc:
            _debug(f"TOOL_ERROR search_uploaded_documents {type(exc).__name__}: {exc}")
            return json.dumps(
                {"error": f"Document search failed: {type(exc).__name__}: {exc}"}
            )

        returned = []
        company_by_source = {
            item["source"]: item["companies"][0]
            for item in source_catalog
            if len(item.get("companies", [])) == 1
        }
        for result in results or []:
            if not isinstance(result, dict):
                continue
            text = str(result.get("text", "")).strip()
            if not text:
                continue
            source_name = str(result.get("source", "Unknown"))
            item = {
                "source": source_name,
                "text": text,
            }
            if source_name in company_by_source:
                item["company"] = company_by_source[source_name]
            # Preserve other retrieval metadata (e.g. score/page) when present.
            for key, value in result.items():
                if key not in {"source", "text"} and isinstance(
                    value, (str, int, float, bool, type(None))
                ):
                    item[key] = value
            identity = (item["source"], item["text"])
            if not any(
                (old.get("source"), old.get("text")) == identity
                for old in evidence_store
            ):
                evidence_store.append(item)
            returned.append(item)

        payload = {"query": query, "results": returned}
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
        if len(serialized) > MAX_TOOL_RESULT_CHARS:
            serialized = (
                serialized[:MAX_TOOL_RESULT_CHARS] + " ...[tool result truncated]"
            )
        _debug(f"TOOL_RESULT search_uploaded_documents returned={len(returned)}")
        return serialized

    @tool
    def get_uploaded_source_details(source: str) -> str:
        """Get indexed metadata for one exact uploaded source filename. Use a filename returned by list_uploaded_sources."""
        for item in source_catalog:
            if item["source"] == source:
                return json.dumps(item, ensure_ascii=False)
        return json.dumps(
            {
                "error": "Unknown source. Call list_uploaded_sources to see exact source names."
            }
        )

    return [
        list_uploaded_sources,
        search_uploaded_documents,
        get_uploaded_source_details,
    ]


SYSTEM_PROMPT = """You are the Research Agent of a finance assistant. You answer questions about the user's uploaded documents.

TASK
Answer ONLY the user's question, using ONLY the document passages you were given or retrieved. Nothing else.

HOW TO WORK
1. Read the user's question. Decide exactly what they want (a list, a value, a status, an explanation).
2. If you need document text, call search_uploaded_documents. If you need to know which files exist, call list_uploaded_sources.
3. If passages were already provided, use them. Do not repeat the same search.
4. Write the answer, then stop.

RULES
- Do not answer a question the user did not ask. No commentary about the documents, the data, or the system.
- Copy names, amounts, dates, IDs and statuses exactly as written. Keep each row's values together.
- Do not calculate (calculations belong to the Finance Agent). Do not use outside knowledge.
- Never infer causes, risks, challenges or business conditions. A status such as Pending or Overdue is only a status.
- If asked whether the documents say something and they do not, answer: "The documents do not state this."
- If the passages do not contain the answer, say: "I could not find this in the retrieved documents."
- Be short. Use a list or table only if the user asked for a list.
"""

FINAL_SYSTEM_PROMPT = """You write the final answer for a finance assistant.
Use ONLY the PASSAGES provided. Answer ONLY the USER QUESTION. Do not add commentary.
Copy names, amounts, dates, IDs and statuses exactly. Keep each table row's values together.
Do not calculate, guess, or use outside knowledge.
If the passages do not contain the answer, say: "I could not find this in the retrieved documents."
Be short."""


def _normalize_tool_args(
    name: str,
    raw_args,
    source_catalog: list[dict],
    fallback_query: Optional[str] = None,
) -> dict:
    """Normalize common model-generated argument-shape errors before validation."""
    args = dict(raw_args) if isinstance(raw_args, dict) else {}
    if not isinstance(raw_args, dict):
        _debug(f"TOOL_ARGS_NORMALIZED name={name!r} reason=non_object_arguments")

    if name == "list_uploaded_sources":
        # This tool takes no arguments. Small models sometimes attach irrelevant
        # fields copied from another tool's schema.
        if args:
            _debug(
                f"TOOL_ARGS_NORMALIZED name={name!r} reason=removed_unexpected_arguments"
            )
        return {}

    if name == "search_uploaded_documents":
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            args["query"] = fallback_query or ""
            _debug(
                f"TOOL_ARGS_NORMALIZED name={name!r} field=query "
                "action=use_original_user_query"
            )

        source = args.get("source")
        if source is None or source == "" or source == [] or source == {}:
            if "source" in args and source is not None:
                _debug(
                    f"TOOL_ARGS_NORMALIZED name={name!r} field=source "
                    f"invalid_empty_value={source!r} action=unrestricted_search"
                )
            args["source"] = None
        elif isinstance(source, str):
            known_sources = {item.get("source") for item in source_catalog}
            if source not in known_sources:
                # A guessed or combined source label should not block retrieval.
                # Fall back to global semantic search; evidence still identifies
                # the actual source for the model.
                _debug(
                    f"TOOL_ARGS_NORMALIZED name={name!r} field=source "
                    f"unknown_value={source!r} action=unrestricted_search"
                )
                args["source"] = None
        elif (
            isinstance(source, list) and len(source) == 1 and isinstance(source[0], str)
        ):
            known_sources = {item.get("source") for item in source_catalog}
            args["source"] = source[0] if source[0] in known_sources else None
            _debug(
                f"TOOL_ARGS_NORMALIZED name={name!r} field=source action=single_item_list"
            )
        else:
            _debug(
                f"TOOL_ARGS_NORMALIZED name={name!r} field=source "
                f"invalid_type={type(source).__name__} action=unrestricted_search"
            )
            args["source"] = None

        top_k = args.get("top_k", DEFAULT_TOP_K)
        try:
            args["top_k"] = max(DEFAULT_TOP_K, min(int(top_k), MAX_TOP_K))
        except (TypeError, ValueError):
            args["top_k"] = DEFAULT_TOP_K
            _debug(f"TOOL_ARGS_NORMALIZED name={name!r} field=top_k action=default")

    if name == "get_uploaded_source_details":
        source = args.get("source")
        if not isinstance(source, str):
            args["source"] = ""
            _debug(
                f"TOOL_ARGS_NORMALIZED name={name!r} field=source "
                f"invalid_type={type(source).__name__}"
            )

    return args


def _tool_result_is_error(result: str) -> bool:
    """Identify tool errors so the model receives explicit recovery guidance."""
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        return isinstance(result, str) and (
            result.startswith("Search not run:")
            or result.startswith("Tool execution failed:")
        )
    return isinstance(payload, dict) and bool(payload.get("error"))


def _execute_tool_call(
    call: dict,
    tool_map: dict,
    source_catalog: list[dict],
    normalized_args: Optional[dict] = None,
) -> str:
    """Execute a model-selected tool after normalizing common argument errors."""
    name = call.get("name")
    args = (
        normalized_args
        if isinstance(normalized_args, dict)
        else _normalize_tool_args(name, call.get("args", {}), source_catalog)
    )

    _debug(f"TOOL_SELECTED name={name!r} args={args!r}")

    selected_tool = tool_map.get(name)
    if selected_tool is None:
        result = json.dumps({"error": f"Unknown tool: {name}"})
    else:
        try:
            result = selected_tool.invoke(args)
        except Exception as exc:
            _debug(f"TOOL_EXECUTION_ERROR name={name} {type(exc).__name__}: {exc}")
            result = json.dumps(
                {
                    "error": f"Tool execution failed: {type(exc).__name__}: {exc}",
                    "recoverable": True,
                }
            )

    result_text = str(result)
    preview_limit = 4000
    preview = result_text[:preview_limit]
    if len(result_text) > preview_limit:
        preview += " ...[debug preview truncated]"
    _debug(f"TOOL_RESPONSE name={name!r} result={preview!r}")
    return result_text


# ---------------------------------------------------------------------------
# Evidence-first path: qualitative / receivable / lookup questions
# The model is NOT trusted to decide "does the document say X?". Code scans the
# document text; the model is only used for simple value lookups, and its
# output is checked against the document text before it is returned.
# ---------------------------------------------------------------------------
_RECEIVABLE_RE = re.compile(
    r"(invoice|pending|overdue|unpaid|outstanding|receivable|collection)", re.I
)
_INTERPRETIVE_RE = re.compile(
    r"(struggl|operational|challenge|problem|issue|concern|risk|difficult|weak|"
    r"inefficien|\bwhy\b|\breasons?\b|explain|explanation|relationship|biggest|identified|"
    r"mention|cause|behind|performance|\bsuggest|\bindicat|\bassum|"
    r"\bdeal with\b|\bhandl|\btreat|\bsays? about)",
    re.I,
)
_LOOKUP_RE = re.compile(
    r"(how much|revenue|expenses?\b|profit|income|salar|cost|total|amount|balance)",
    re.I,
)
_CALC_RE = re.compile(
    r"(\bcalculat|\bcomput|\bsum\b|\bdifferences?\b|\bratios?\b|\breconcil|\bcompar|\bagree|\bmatch)",
    re.I,
)
_FINANCE_RECORDS_RE = re.compile(
    r"(finance records|our records|our finance|ledger|our books|accounting system)",
    re.I,
)
_EXPLANATORY_RE = re.compile(
    r"\b(?:challeng|risk|concern|problem|difficult|delay|pressure|strain|declin|"
    r"decreas|increas|because|due to|driven|owing to|attribut|reasons?\b|impact|struggl|"
    r"shortfall|default|disput|liquidity|cash.?flow|inefficien|weak)"
    r"|\b(?:issues?|collections?)\b",
    re.I,
)
_ROW_RE = re.compile(
    r"(?<![\w-])([A-Z]{1,4}-\d{2,4}-\d{2,4})\s+(.{3,80}?)\s+(Pending|Paid|Overdue)\b"
)
_GENERIC_TOKENS = {
    "pdf",
    "pvt",
    "ltd",
    "limited",
    "private",
    "services",
    "service",
    "solutions",
    "systems",
    "system",
    "group",
    "company",
    "inc",
    "the",
    "and",
    "technologies",
    "technology",
    "business",
    "digital",
    "learning",
    "logistics",
    "mobility",
    "analytics",
    "manufacturing",
    "energy",
    "renewable",
}


def _match_sources_by_tokens(user_query: str, source_catalog: list) -> list:
    """Typo/partial-name matching: 'ABC Technology', 'the Redwood report'."""
    from collections import Counter

    def tokens_of(item):
        names = [os.path.splitext(os.path.basename(item["source"]))[0]]
        names += [c for c in item.get("companies", []) if isinstance(c, str)]
        found = set()
        for name in names:
            # split CamelCase and non-alphanumerics
            spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
            for tok in re.findall(r"[A-Za-z0-9]+", spaced):
                tok = tok.lower()
                if tok not in _GENERIC_TOKENS and len(tok) >= 3:
                    found.add(tok)
            glued = _normalize_match_text(name)
            if len(glued) >= 6:
                found.add(glued)
        return found

    per_source = {item["source"]: tokens_of(item) for item in source_catalog}
    frequency = Counter(tok for toks in per_source.values() for tok in toks)
    query_norm = _normalize_match_text(user_query)
    query_tokens = set(re.findall(r"[a-z0-9]+", user_query.lower()))

    matches = []
    for source, toks in per_source.items():
        for tok in toks:
            if frequency[tok] != 1:
                continue  # shared by several documents: not distinctive
            if (len(tok) >= 6 and tok in query_norm) or tok in query_tokens:
                matches.append(source)
                break
    return matches


def _source_full_text(chunks: list) -> str:
    text = " ".join(chunks).replace("\x7f", " - ")
    return re.sub(r"\s+", " ", text).strip()


def _extract_receivable_rows(text: str) -> list:
    rows, seen = [], set()
    for invoice_id, detail, status in _ROW_RE.findall(text):
        if invoice_id in seen:
            continue
        seen.add(invoice_id)
        rows.append((invoice_id, detail.strip(), status))
    return rows


def _invoice_key_lines(text: str) -> list:
    """Verbatim key fields of a standalone invoice (no model, no arithmetic)."""
    out = []
    spec = [
        ("Invoice No", r"Invoice No:?\s*(\S+)"),
        ("Invoice Date", r"Invoice Date:?\s*(\d{1,2}\s+\w+\s+\d{4})"),
        ("Due Date", r"Due Date:?\s*(\d{1,2}\s+\w+\s+\d{4})"),
        ("Grand Total", r"Grand Total\s*([^\s\d]?\s?[\d,]+\.\d{2})"),
        ("Amount Paid", r"Amount Paid\s*([^\s\d]?\s?[\d,]+\.\d{2})"),
        ("Balance Due", r"Balance Due\s*([^\s\d]?\s?[\d,]+\.\d{2})"),
    ]
    for label, pattern in spec:
        match = re.search(pattern, text)
        if match:
            out.append((label, match.group(1).strip()))
    return out


def _explanatory_sentences(text: str) -> list:
    sentences = re.split(r"(?<=[.;!?])\s+| - ", text)
    hits = []
    for sentence in sentences:
        sentence = sentence.strip()
        if 15 <= len(sentence) <= 400 and _EXPLANATORY_RE.search(sentence):
            if sentence not in hits:
                hits.append(sentence)
    return hits


def _section_for_topic(text: str, query: str) -> str:
    q = query.lower()
    if re.search(r"expens|cost", q):
        start, end = r"operating expense", r"(?:\d\.\s*)?accounts receivable"
    elif re.search(r"customer|relationship|receivable|collection", q):
        start, end = (
            r"accounts receivable",
            r"\d\.\s*(?:management|accounting|financial)",
        )
    elif re.search(r"revenue|income|performance", q):
        start, end = r"revenue", r"(?:\d\.\s*)?operating expense"
    else:
        start, end = r"(?:management|accounting|financial) (?:notes|and policies)", None
    m = re.search(start, text, re.I)
    if not m:
        return ""
    stop = len(text)
    if end:
        e = re.search(end, text[m.end() :], re.I)
        if e:
            stop = m.end() + e.start()
    return text[m.start() : min(stop, m.start() + 700)].strip()


def _numbers_in(text: str) -> set:
    return {
        n.replace(",", "").rstrip(".")
        for n in re.findall(r"\d[\d,]*\.?\d*", text)
        if len(n.replace(",", "").rstrip(".")) >= 3
    }


def _ungrounded_numbers(answer: str, evidence_text: str) -> list:
    allowed = _numbers_in(evidence_text)
    return sorted(n for n in _numbers_in(answer) if n not in allowed)


def _apply_grounding_guard(answer: str, evidence: list) -> str:
    """Discard a model answer that contains values not present in the documents."""
    evidence_text = " ".join(str(item.get("text", "")) for item in evidence)
    bad = _ungrounded_numbers(answer, evidence_text)
    if not bad:
        return answer
    _debug(f"GROUNDING_GUARD_TRIGGERED ungrounded={bad!r}")
    lines = [
        "I could not produce a verified answer: the model's draft contained values "
        f"that do not appear in the retrieved documents ({', '.join(bad[:6])}), so it was discarded.",
        "",
        "Retrieved passages:",
    ]
    for item in evidence[:4]:
        lines.append(f"- **{item.get('source')}**: {str(item.get('text', ''))[:300]}")
    return "\n".join(lines)


def _lookup_with_model(user_query: str, source: str, text: str) -> str:
    """Single small, constrained model call for a value lookup; output is verified."""
    response = _timed_invoke(
        "lookup_llm",
        llm,
        [
            SystemMessage(
                content=(
                    "Answer using ONLY the DOCUMENT TEXT. Copy numbers exactly as written. "
                    "Do not calculate. Answer only the factual / number part of the question; "
                    "ignore any request for reasons or explanations. "
                    "If the value is not in the text, reply: Not stated in the document. "
                    "Maximum 3 sentences."
                )
            ),
            HumanMessage(
                content=f"DOCUMENT ({source}):\n{text[:3500]}\n\nQUESTION: {user_query}"
            ),
        ],
    )
    answer = re.sub(
        r"<think>.*?</think>", "", str(response.content), flags=re.S
    ).strip()
    bad = _ungrounded_numbers(answer, text)
    if bad:
        _debug(f"LOOKUP_GUARD_TRIGGERED source={source!r} ungrounded={bad!r}")
        return (
            "_The model's answer contained values not found in the document "
            f"({', '.join(bad[:5])}) and was discarded._ Relevant text from the document:\n> "
            + (_section_for_topic(text, user_query) or text[:500])
        )
    return answer or "Not stated in the document."


def _structured_answer(user_query: str, vector_store, source_catalog: list):
    receivable = bool(_RECEIVABLE_RE.search(user_query))
    interpretive = bool(_INTERPRETIVE_RE.search(user_query))
    calc = bool(_CALC_RE.search(user_query))
    finance_records = bool(_FINANCE_RECORDS_RE.search(user_query))
    matched = _match_sources_mentioned_in_query(user_query, source_catalog)
    lookup = bool(_LOOKUP_RE.search(user_query)) and bool(matched) and not receivable

    if not (receivable or interpretive or lookup):
        return None

    chunk_texts = _chunk_texts_by_source(vector_store)
    targets = matched or [item["source"] for item in source_catalog]
    full = {s: _source_full_text(chunk_texts.get(s, [])) for s in targets}
    kind = {s: _describe_source(chunk_texts.get(s, []))[0] for s in targets}
    _debug(
        f"STRUCTURED_PATH receivable={receivable} interpretive={interpretive} "
        f"lookup={lookup} calc={calc} finance_records={finance_records} targets={targets!r}"
    )

    parts = []

    # --- receivable / invoice facts (verbatim, no model) -------------------
    if receivable:
        q = user_query.lower()
        wanted = None
        if re.search(r"unpaid|outstanding", q):
            wanted = {"Pending", "Overdue"}
        elif "overdue" in q:
            wanted = {"Overdue"}
        elif "pending" in q:
            wanted = {"Pending"}
        elif re.search(r"\bpaid\b", q):
            wanted = {"Paid"}
        lines = []
        for s in targets:
            if kind[s] == "Invoice":
                keys = _invoice_key_lines(full[s])
                if keys and (matched or wanted is None):
                    lines.append(f"**{s}** (standalone invoice, fields as written):")
                    lines.extend(f"- {label}: {value}" for label, value in keys)
                    lines.append(
                        "- The document has no payment-status label such as Pending/Overdue."
                    )
                continue
            rows = [
                r
                for r in _extract_receivable_rows(full[s])
                if not wanted or r[2] in wanted
            ]
            if rows:
                lines.append(f"**{s}** (accounts receivable rows as written):")
                lines.extend(f"- {i} | {d} | {st}" for i, d, st in rows)
        label = "/".join(sorted(wanted)) if wanted else "all"
        parts.append(
            f"### Invoices in the documents ({label})\n"
            + (
                "\n".join(lines)
                if lines
                else "No matching invoice rows were found in the indexed text."
            )
        )

    # --- factual lookup (small constrained model call + verification) ------
    if lookup:
        lookup_lines = []
        for s in matched[:3]:
            lookup_lines.append(
                f"**{s}:** {_lookup_with_model(user_query, s, full[s])}"
            )
        parts.append("### Figures stated in the document\n" + "\n".join(lookup_lines))

    # --- qualitative questions: scan the text, never guess -----------------
    if interpretive:
        found, empty = [], []
        for s in targets:
            hits = _explanatory_sentences(full[s])
            (found if hits else empty).append((s, hits))
        out = []
        for s, hits in found:
            out.append(
                f"**{s}** - sentences using explanatory/problem wording (verbatim):"
            )
            out.extend(f"> {h}" for h in hits[:5])
        if matched:
            for s, _ in empty:
                msg = f"**{s}** - the document does not state any challenge, problem, cause or explanation"
                if kind[s] == "Invoice":
                    msg += "; it is an invoice and contains no management commentary."
                else:
                    msg += "; it only reports figures and standard notes."
                    if re.search(r"overdue", full[s], re.I):
                        msg += " An 'Overdue' status is a status, not an explanation."
                out.append(msg)
                section = _section_for_topic(full[s], user_query)
                if section:
                    out.append(f"What it does document:\n> {section}")
        elif empty:
            names = ", ".join(s for s, _ in empty)
            if not found:
                out.append(
                    f"None of the {len(empty)} uploaded documents states a challenge, problem, "
                    "cause, explanation or customer-relationship detail. They report figures and "
                    "standard notes only."
                )
            out.append(f"Documents scanned with no such wording: {names}.")
            out.append(
                "Name a specific report if you want the relevant sections quoted."
            )
        parts.append("### What the documents say\n" + "\n".join(out))

    notes = []
    if calc or re.search(r"calculat|outstanding amount", user_query, re.I):
        notes.append(
            "Calculations (totals, differences, outstanding amounts) are not done by the Research Agent; figures above are as written in the documents."
        )
    if finance_records:
        notes.append(
            "Comparison with the finance records needs the Finance Agent; only the document side is shown here."
        )
    if notes:
        parts.append(
            "### Handled by the Finance Agent\n" + "\n".join(f"- {n}" for n in notes)
        )

    response = _build_response(
        "\n\n".join(parts),
        needs_finance_agent=bool(notes),
    )
    response["research_sources"] = [{"source": s, "entity": None} for s in targets]
    return response


def research_agent(state: dict):
    """
    Research with a lightweight deterministic execution controller:
    - retrieves before generation,
    - searches explicitly named indexed sources separately,
    - prevents repeated identical searches,
    - verifies coverage of explicitly matched sources before finalizing.
    """
    user_query = state.get("user_query", "")
    research_task = state.get("research_task", "")
    if not isinstance(research_task, str):
        research_task = ""
    research_task = research_task.strip()
    if not isinstance(user_query, str) or not user_query.strip():
        return _build_response(
            "## Research Request Missing\nPlease provide a research question.",
            needs_clarification=True,
        )

    user_query = user_query.strip()
    request_started = time.perf_counter()
    _debug(f"REQUEST_START query={user_query!r}")

    try:
        vector_store = get_vector_store()
        source_catalog = _source_catalog(vector_store)
        _debug(
            f"INDEX_READY documents={len(source_catalog)} "
            f"chunks={len(getattr(vector_store, 'documents', []))} "
            f"sources={[item['source'] for item in source_catalog]!r}"
        )
    except Exception as exc:
        _debug(f"VECTOR_STORE_ERROR {type(exc).__name__}: {exc}")
        return _build_response(
            "## Research Temporarily Unavailable\nThe uploaded-document index could not be accessed. Please try again."
        )

    if (
        source_catalog
        and _is_inventory_query(user_query)
        and not _match_sources_mentioned_in_query(user_query, source_catalog)
    ):
        _debug(f"INVENTORY_FAST_PATH documents={len(source_catalog)} llm_calls=0")
        _debug(
            f"TIMING total_request_seconds={time.perf_counter() - request_started:.3f}"
        )
        return _inventory_answer(vector_store, source_catalog)

    structured = _structured_answer(user_query, vector_store, source_catalog)
    if structured is not None:
        _debug(
            f"TIMING total_request_seconds={time.perf_counter() - request_started:.3f}"
        )
        return structured

    evidence = []
    tools = _make_retrieval_tools(vector_store, evidence, source_catalog)
    tool_map = {item.name: item for item in tools}
    model = llm.bind_tools(tools)
    initial_request = (
        f"ORIGINAL USER REQUEST:\n{user_query}"
        + (
            f"\n\nSUPERVISOR RESEARCH ASSIGNMENT:\n{research_task}"
            if research_task
            else ""
        )
        + "\n\nTreat the original user request as authoritative. "
        "Use the assignment only to clarify the research contribution and scope. "
        "Do not let examples in the assignment become assumed facts or force "
        "the answer toward a predetermined conclusion."
    )
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=initial_request),
    ]

    total_tool_calls = 0
    failed_call_signatures = set()
    successful_call_signatures = set()
    tool_errors = 0
    source_search_attempted = set()
    source_search_retried = set()
    research_phase_output = ""

    def _signature(name: str, args: dict) -> str:
        return json.dumps(
            {"name": name, "args": args},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )

    def _run_search(query: str, source: Optional[str], top_k: int) -> str:
        nonlocal total_tool_calls, tool_errors
        args = _normalize_tool_args(
            "search_uploaded_documents",
            {"query": query, "source": source, "top_k": top_k},
            source_catalog,
            fallback_query=user_query,
        )
        signature = _signature("search_uploaded_documents", args)
        if signature in successful_call_signatures:
            _debug(
                f"CONTROLLER_DUPLICATE_SEARCH_SKIPPED source={source!r} query={query!r}"
            )
            return ""
        if signature in failed_call_signatures:
            _debug(
                f"CONTROLLER_PREVIOUS_FAILURE_SKIPPED source={source!r} query={query!r}"
            )
            return ""

        if total_tool_calls >= MAX_TOOL_CALLS:
            return ""

        total_tool_calls += 1
        result = _execute_tool_call(
            {"name": "search_uploaded_documents", "args": args},
            tool_map,
            source_catalog,
            normalized_args=args,
        )
        if _tool_result_is_error(result):
            tool_errors += 1
            failed_call_signatures.add(signature)
        else:
            successful_call_signatures.add(signature)
            if source:
                source_search_attempted.add(source)
        return result

    try:
        # Deterministic first retrieval prevents the small model from ending
        # after metadata inspection or from choosing a dangerously small top_k.
        matched_sources = _match_sources_mentioned_in_query(user_query, source_catalog)
        _debug(f"CONTROLLER_MATCHED_SOURCES sources={matched_sources!r}")

        initial_results = []
        if matched_sources:
            # Search every explicitly named source independently. Keep some
            # tool-call budget for Qwen to refine the research afterward.
            initial_sources = matched_sources[:4]
            for source in initial_sources:
                _debug(
                    f"CONTROLLER_INITIAL_RETRIEVAL source={source!r} "
                    f"query={user_query!r} top_k={DEFAULT_TOP_K}"
                )
                result = _run_search(user_query, source, DEFAULT_TOP_K)
                if result:
                    initial_results.append({"source": source, "tool_result": result})
        else:
            # For requests without a literal company/file mention, start with
            # a broad retrieval pass; Qwen can refine it with further searches.
            _debug(
                f"CONTROLLER_INITIAL_RETRIEVAL source=None "
                f"query={user_query!r} top_k={INITIAL_TOP_K}"
            )
            result = _run_search(user_query, None, INITIAL_TOP_K)
            if result:
                initial_results.append({"source": None, "tool_result": result})

        if initial_results:
            messages.append(
                HumanMessage(
                    content=(
                        "The execution controller has already performed the initial "
                        "document search. Inspect these retrieved results before making "
                        "another tool call. Do not repeat an identical search. Continue "
                        "research only if additional evidence is needed.\n\n"
                        + json.dumps(initial_results, ensure_ascii=False, default=str)
                    )
                )
            )

        while total_tool_calls < MAX_TOOL_CALLS:
            response = _timed_invoke("research_llm", model, messages)
            messages.append(response)
            calls = getattr(response, "tool_calls", None) or []

            if not calls:
                # Preserve the synthesis produced after the model inspected the
                # retrieved evidence. The final-answer pass must refine this work,
                # not start reasoning from scratch with only the raw passages.
                research_phase_output = str(response.content or "").strip()
                _debug(
                    "RESEARCH_SYNTHESIS_CAPTURED",
                    characters=len(research_phase_output),
                    synthesis_preview=research_phase_output[:5000],
                )
                # If the user explicitly named indexed sources, ensure each
                # one has at least been searched before allowing a final answer.
                evidence_sources = {
                    item.get("source") for item in evidence if item.get("source")
                }
                missing_sources = [
                    source
                    for source in matched_sources
                    if source not in evidence_sources
                ]

                retry_source = next(
                    (
                        source
                        for source in missing_sources
                        if source not in source_search_retried
                        and total_tool_calls < MAX_TOOL_CALLS
                    ),
                    None,
                )
                if retry_source:
                    source_search_retried.add(retry_source)
                    catalog_item = next(
                        item
                        for item in source_catalog
                        if item.get("source") == retry_source
                    )
                    company_names = catalog_item.get("companies", [])
                    company_hint = (
                        company_names[0]
                        if company_names
                        else os.path.splitext(os.path.basename(retry_source))[0]
                    )
                    retry_query = f"{user_query} {company_hint}"
                    _debug(
                        f"CONTROLLER_COVERAGE_RETRY source={retry_source!r} "
                        f"query={retry_query!r}"
                    )
                    retry_result = _run_search(retry_query, retry_source, INITIAL_TOP_K)
                    messages.append(
                        HumanMessage(
                            content=(
                                "The execution controller performed an additional "
                                f"source-restricted search for {retry_source!r}. "
                                "Inspect this result and continue the original task. "
                                "Do not claim the source lacks information unless the "
                                "retrieved passages support that conclusion.\n\n"
                                f"{retry_result}"
                            )
                        )
                    )
                    continue

                if not evidence:
                    messages.append(
                        HumanMessage(
                            content=(
                                "No document-content evidence has been retrieved. "
                                "Metadata is not evidence. Choose a new, useful "
                                "search_uploaded_documents query. Do not repeat a "
                                "previously failed or identical search, and do not "
                                "answer from prior knowledge."
                            )
                        )
                    )
                    retry_response = _timed_invoke("retry_llm", model, messages)
                    messages.append(retry_response)
                    retry_calls = getattr(retry_response, "tool_calls", None) or []
                    if retry_calls:
                        calls = retry_calls
                    else:
                        _debug(
                            f"RESEARCH_INCOMPLETE reason=no_evidence "
                            f"tool_calls={total_tool_calls} tool_errors={tool_errors}"
                        )
                        return _build_response(
                            "## No Document Evidence Retrieved\n"
                            "No document passages were successfully retrieved, so I cannot provide a source-grounded answer.",
                            needs_clarification=True,
                        )
                else:
                    evidence_sources = sorted(
                        {
                            item.get("source", "Unknown")
                            for item in evidence
                            if item.get("source")
                        }
                    )
                    missing_sources = [
                        source
                        for source in matched_sources
                        if source not in evidence_sources
                    ]

                    if not USE_FINAL_PASS and research_phase_output:
                        # The research pass already saw the evidence. Re-generating
                        # the answer cost ~30s and re-introduced hallucinations.
                        answer = research_phase_output
                    else:
                        final_response = _timed_invoke(
                            "final_answer_llm",
                            llm,
                            [
                                SystemMessage(content=FINAL_SYSTEM_PROMPT),
                                HumanMessage(
                                    content=(
                                        f"USER QUESTION:\n{user_query}\n\n"
                                        f"PASSAGES:\n"
                                        f"{json.dumps(_compact_evidence(evidence), ensure_ascii=False)}\n\n"
                                        f"Sources with no passages: {json.dumps(missing_sources)}\n\n"
                                        "Answer the USER QUESTION only."
                                    )
                                ),
                            ],
                        )
                        answer = str(final_response.content).strip()
                    answer = _apply_grounding_guard(answer, evidence)
                    if not answer:
                        answer = (
                            "## Research Incomplete\n"
                            "Retrieved evidence was available, but the model did not produce a final answer."
                        )

                    entities = []
                    for item in evidence:
                        entity = item.get("company") or item.get("entity")
                        if entity and entity not in entities:
                            entities.append(entity)

                    _debug(
                        f"TIMING total_request_seconds="
                        f"{time.perf_counter() - request_started:.3f}"
                    )
                    _debug(
                        f"RESEARCH_COMPLETE tool_calls={total_tool_calls} "
                        f"tool_errors={tool_errors} evidence_chunks={len(evidence)} "
                        f"sources={evidence_sources!r} "
                        f"uncovered_sources={missing_sources!r}"
                    )
                    return _build_response(
                        answer,
                        evidence=evidence,
                        entities=entities,
                    )

            batch_had_error = False
            for call in calls:
                if total_tool_calls >= MAX_TOOL_CALLS:
                    break

                total_tool_calls += 1
                name = call.get("name")
                normalized_args = _normalize_tool_args(
                    name,
                    call.get("args", {}),
                    source_catalog,
                    fallback_query=user_query,
                )
                signature = _signature(name, normalized_args)

                if signature in failed_call_signatures:
                    tool_result = json.dumps(
                        {
                            "error": (
                                "This exact tool call already failed. Do not repeat it. "
                                "Correct the arguments or choose a different retrieval action."
                            ),
                            "recoverable": True,
                        }
                    )
                    _debug(
                        f"TOOL_REPEAT_BLOCKED name={name!r} args={normalized_args!r}"
                    )
                    batch_had_error = True
                elif signature in successful_call_signatures:
                    tool_result = json.dumps(
                        {
                            "status": "already_executed",
                            "message": (
                                "This exact tool call has already completed successfully. "
                                "Its result is already present in the conversation. "
                                "Do not repeat it; continue with a different useful search "
                                "or provide the answer from the evidence."
                            ),
                        }
                    )
                    _debug(
                        f"TOOL_DUPLICATE_BLOCKED name={name!r} args={normalized_args!r}"
                    )
                else:
                    tool_result = _execute_tool_call(
                        {"name": name, "args": normalized_args},
                        tool_map,
                        source_catalog,
                        normalized_args=normalized_args,
                    )
                    if _tool_result_is_error(tool_result):
                        tool_errors += 1
                        failed_call_signatures.add(signature)
                        batch_had_error = True
                    else:
                        successful_call_signatures.add(signature)
                        if name == "search_uploaded_documents" and normalized_args.get(
                            "source"
                        ):
                            source_search_attempted.add(normalized_args["source"])

                messages.append(
                    ToolMessage(
                        content=tool_result,
                        tool_call_id=call.get("id"),
                    )
                )

            if batch_had_error:
                messages.append(
                    HumanMessage(
                        content=(
                            "A tool call failed. Read the error and correct the "
                            "arguments or choose another valid action. Do not repeat "
                            "the failed call and do not answer from an error. Continue "
                            "the original research task."
                        )
                    )
                )

        # Tool-call budget exhausted. Be explicit about incomplete coverage.
        if not evidence:
            answer = (
                "## Research Incomplete\n"
                "The tool-call limit was reached before any document evidence was retrieved."
            )
        else:
            evidence_payload = json.dumps(
                _compact_evidence(evidence), ensure_ascii=False, default=str
            )
            final_response = _timed_invoke(
                "fallback_final_answer_llm",
                llm,
                [
                    SystemMessage(content=FINAL_SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"Original request:\n{user_query}\n\n"
                            f"Supervisor research assignment (scope only; not evidence):\n"
                            f"{research_task or 'No separate assignment provided.'}\n\n"
                            f"Research-phase synthesis:\n"
                            f"{research_phase_output or 'No synthesis was captured.'}\n\n"
                            f"Matched sources:\n{json.dumps(matched_sources, ensure_ascii=False)}\n\n"
                            f"Retrieved evidence:\n{evidence_payload}"
                        )
                    ),
                ],
            )
            answer = str(final_response.content).strip() or (
                "## Research Incomplete\n"
                "The tool-call limit was reached before a complete answer was produced."
            )

        _debug(
            f"TIMING total_request_seconds={time.perf_counter() - request_started:.3f}"
        )
        _debug(
            f"RESEARCH_INCOMPLETE tool_calls={total_tool_calls} "
            f"tool_errors={tool_errors} evidence_chunks={len(evidence)}"
        )
        return _build_response(answer, evidence=evidence)

    except Exception as exc:
        _debug(f"RESEARCH_ERROR {type(exc).__name__}: {exc}")
        return _build_response(
            "## Research Temporarily Unavailable\n"
            "The document retrieval or language-model step failed. Please try again.",
            evidence=evidence,
        )
