import json
import re
from decimal import Decimal, InvalidOperation

from langchain_ollama import ChatOllama
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, SystemMessage
from database.db import SessionLocal
from database.models import DocumentRecord, FinancialDataPoint


def _finance_debug(event: str, **details) -> None:
    """Print structured diagnostics for deterministic Finance Agent responses."""
    payload = json.dumps(details, ensure_ascii=False, default=str, sort_keys=True)
    print(f"[FINANCE_DEBUG] {event} {payload}", flush=True)


def _log_agent_tool_trace(messages) -> None:
    """Log model-generated tool arguments and tool results for debugging."""
    for message_index, message in enumerate(messages or []):
        tool_calls = getattr(message, "tool_calls", None) or []
        for call in tool_calls:
            _finance_debug(
                "LLM_TOOL_CALL",
                message_index=message_index,
                tool_call_id=call.get("id"),
                tool_name=call.get("name"),
                arguments=call.get("args", {}),
            )

        if getattr(message, "tool_call_id", None):
            content = getattr(message, "content", "")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False, default=str)
            max_logged_chars = 8000
            _finance_debug(
                "LLM_TOOL_RESULT",
                message_index=message_index,
                tool_call_id=message.tool_call_id,
                tool_name=getattr(message, "name", None),
                content=content[:max_logged_chars],
                truncated=len(content) > max_logged_chars,
                original_length=len(content),
            )


# Initialize local LLM.
# num_ctx matters: Ollama's default window is small and silently truncates the
# system prompt / tool schemas / tool results, which causes flaky tool use.
llm = ChatOllama(model="qwen3:1.7b", temperature=0, num_ctx=8192)


def _strip_think(text) -> str:
    """Remove any leftover <think>...</think> block from model output."""
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False, default=str)
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


# Unified document-backed finance tools


def _resolve_company_names(
    company_name: str = "", company_names: str = ""
) -> list[str]:
    """Accept both singular and plural argument keys from tool-calling models."""
    raw = company_name or company_names or ""
    return list(
        dict.fromkeys(part.strip() for part in str(raw).split(",") if part.strip())
    )


@tool
def saved_document_records(
    document_type: str = "",
    company_name: str = "",
    company_names: str = "",
):
    """Retrieve confirmed uploaded-document records. When a company is supplied, filter to that company before returning records; company_name and comma-separated company_names are accepted. Use without a company only for an explicitly broad document listing."""
    requested_companies = _resolve_company_names(company_name, company_names)
    normalized_companies = [
        _normalize_lookup_text(name) for name in requested_companies
    ]

    db = SessionLocal()
    try:
        query = db.query(DocumentRecord).filter(DocumentRecord.status == "confirmed")
        if document_type:
            query = query.filter(DocumentRecord.document_type == document_type)

        # Company-scoped retrieval is performed BEFORE limiting results. Upload
        # recency must not decide which company's records enter the model context.
        if normalized_companies:
            rows = query.order_by(DocumentRecord.id.asc()).all()
            matches = []
            for record in rows:
                fields = record.extracted_data or {}
                sections = fields.get("sections") or {}
                extracted_text = (
                    sections.get("extracted_text", "")
                    if isinstance(sections, dict)
                    else ""
                )
                matched_company = False
                for company_key in normalized_companies:
                    if not company_key:
                        continue
                    if record.document_type == "financial_report":
                        matched_company = _report_matches_company(
                            company_key, fields, record.filename, extracted_text
                        )
                    else:
                        searchable = " ".join(
                            [record.filename, *_collect_document_strings(fields)]
                        )
                        matched_company = company_key in _normalize_lookup_text(
                            searchable
                        )
                    if matched_company:
                        break
                if matched_company:
                    matches.append(record)
            rows = matches[:50]
        else:
            # Preserve the existing recent-first behavior only for deliberately
            # broad requests that do not specify a company.
            rows = (
                query.order_by(
                    DocumentRecord.created_at.desc(), DocumentRecord.id.desc()
                )
                .limit(50)
                .all()
            )

        _finance_debug(
            "SAVED_DOCUMENT_RECORDS",
            document_type=document_type or None,
            requested_companies=requested_companies,
            result_count=len(rows),
            filenames=[r.filename for r in rows],
        )
        return json.dumps(
            [
                {
                    "filename": r.filename,
                    "document_type": r.document_type,
                    "fields": r.extracted_data,
                }
                for r in rows
            ],
            ensure_ascii=False,
            default=str,
        )
    finally:
        db.close()


@tool("company_financial_records")
def company_financial_records(company_name: str = "", company_names: str = ""):
    """Retrieve standard financial figures for one or more named companies. Accepts company_name or the company_names alias; multiple names may be comma-separated. For report-body details use search_financial_records."""
    requested = _resolve_company_names(company_name, company_names)
    if not requested:
        return json.dumps({"error": "Provide company_name or company_names."})
    results = []
    for name in requested:
        records = _get_company_financial_records(name)
        results.append(
            {
                "company": name,
                "matches": records,
                "message": None
                if records
                else "No confirmed financial record matched this company.",
            }
        )
    if len(results) == 1:
        return json.dumps(results[0], ensure_ascii=False, default=str)
    return json.dumps({"results": results}, ensure_ascii=False, default=str)


@tool("search_confirmed_documents")
def search_confirmed_documents(
    search_query: str = "",
    document_type: str = "",
    company_name: str = "",
    company_names: str = "",
):
    """Search confirmed uploaded documents. When company_name/company_names is supplied, invoice/company identity must match the vendor, customer, or report company fields; never match a company merely because its name appears in unrelated document text. search_query may be an invoice number or additional search term."""
    requested_companies = _resolve_company_names(company_name, company_names)
    # Older Qwen tool calls often pass a company only as search_query. For invoice
    # searches, interpret a non-ID phrase as the company identity, never as a
    # full-text search across unrelated invoice descriptions.
    if (
        not requested_companies
        and document_type.strip().lower() == "invoice"
        and search_query
        and not re.search(r"(?i)\b[A-Z]{1,4}[- ]\d{4}[- ]\d{3,}\b", search_query)
    ):
        requested_companies = [search_query]
        search_query = ""

    query_tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", (search_query or "").lower())
        if len(token) > 1
    ]
    if not requested_companies and not query_tokens:
        return json.dumps(
            {
                "documents": [],
                "count": 0,
                "message": "Provide a company name or search term.",
            }
        )

    db = SessionLocal()
    try:
        query = db.query(DocumentRecord).filter(DocumentRecord.status == "confirmed")
        if document_type:
            query = query.filter(
                DocumentRecord.document_type == document_type.strip().lower()
            )
        records = query.order_by(
            DocumentRecord.created_at.desc(), DocumentRecord.id.desc()
        ).all()

        matches = []
        identity_keys = (
            "company_name",
            "vendor_name",
            "customer_name",
            "supplier_name",
            "buyer_name",
            "bill_to_name",
            "ship_to_name",
            "account_name",
        )
        for record in records:
            fields = record.extracted_data or {}
            if requested_companies:
                identities = [
                    _normalize_lookup_text(fields.get(key, ""))
                    for key in identity_keys
                    if fields.get(key)
                ]
                # Company filtering is identity-field-only. Filename/body matches
                # are deliberately insufficient for invoices and other documents.
                identity_match = any(
                    requested in identity or identity in requested
                    for requested in (
                        _normalize_lookup_text(name) for name in requested_companies
                    )
                    for identity in identities
                    if requested
                    and identity
                    and min(len(requested), len(identity)) >= 5
                )
                if not identity_match:
                    continue

            if query_tokens:
                searchable = " ".join(
                    [
                        record.filename,
                        record.document_type,
                        " ".join(_collect_document_strings(fields)),
                    ]
                )
                normalized_searchable = _normalize_lookup_text(searchable)
                matched = all(
                    _normalize_lookup_text(token) in normalized_searchable
                    for token in query_tokens
                )
                if not matched:
                    continue

            matches.append(
                {
                    "filename": record.filename,
                    "document_type": record.document_type,
                    "created_at": record.created_at.isoformat()
                    if record.created_at
                    else None,
                    "fields": fields,
                }
            )
            if len(matches) >= 25:
                break

        _finance_debug(
            "CONFIRMED_DOCUMENT_SEARCH",
            search_query=search_query or None,
            requested_companies=requested_companies,
            document_type=document_type or None,
            result_count=len(matches),
            filenames=[item["filename"] for item in matches],
        )
        return json.dumps(
            {"documents": matches, "count": len(matches)},
            ensure_ascii=False,
            default=str,
        )
    finally:
        db.close()


@tool("list_financial_companies")
def list_financial_companies():
    """List every distinct company represented by confirmed financial-report records."""
    db = SessionLocal()
    try:
        records = (
            db.query(DocumentRecord)
            .filter(
                DocumentRecord.status == "confirmed",
                DocumentRecord.document_type == "financial_report",
            )
            .order_by(DocumentRecord.created_at.desc(), DocumentRecord.id.desc())
            .all()
        )
        companies = []
        seen = set()
        for record in records:
            fields = record.extracted_data or {}
            name = str(fields.get("company_name") or "").strip()
            key = _normalize_lookup_text(name)
            if name and key and key not in seen:
                seen.add(key)
                companies.append(name)
        return json.dumps(
            {"companies": companies, "count": len(companies)}, ensure_ascii=False
        )
    finally:
        db.close()


# Keep search results small enough for a small local model's context window.
_SEARCH_TEXT_CHARS_PER_REPORT = 4000
_SEARCH_MAX_REPORTS = 50


@tool("search_financial_data_points")
def search_financial_data_points(
    company_name: str = "",
    company_names: str = "",
    search_query: str = "",
    reporting_period: str = "",
    section: str = "",
    metric_name: str = "",
    limit: int = 100,
):
    """Search individual financial observations extracted from confirmed financial reports. Filter by company, reporting period, report section, and/or metric. Use this for detailed line items, category breakdowns, and any financial figure not covered by standard summary fields. Pass company_name/company_names for company-scoped queries; use ALL only for explicitly broad requests. Returns values with source report, section, row context, and source text."""
    requested_companies = _resolve_company_names(company_name, company_names)
    normalized_companies = [
        _normalize_lookup_text(name)
        for name in requested_companies
        if _normalize_lookup_text(name)
    ]
    if (
        not normalized_companies
        and not search_query
        and not metric_name
        and not section
    ):
        return json.dumps(
            {
                "observations": [],
                "count": 0,
                "message": "Provide a company, metric, section, reporting period, or search query.",
            }
        )

    safe_limit = max(1, min(int(limit or 100), 250))
    db = SessionLocal()
    try:
        query = (
            db.query(FinancialDataPoint, DocumentRecord)
            .join(
                DocumentRecord,
                FinancialDataPoint.document_id == DocumentRecord.id,
            )
            .filter(
                DocumentRecord.status == "confirmed",
                DocumentRecord.document_type == "financial_report",
            )
        )

        rows = query.order_by(
            DocumentRecord.created_at.desc(),
            FinancialDataPoint.id.asc(),
        ).all()

        query_terms = [
            _normalize_lookup_text(term)
            for term in re.findall(r"[a-z0-9]+", search_query.lower())
            if len(term) > 1
        ]
        metric_key = _normalize_lookup_text(metric_name)
        section_key = _normalize_lookup_text(section)
        period_key = _normalize_lookup_text(reporting_period)

        observations = []
        for point, record in rows:
            fields = record.extracted_data or {}
            report_company = str(fields.get("company_name") or point.company_name or "")
            if normalized_companies:
                company_key = _normalize_lookup_text(report_company)
                if not any(
                    requested
                    and company_key
                    and (requested in company_key or company_key in requested)
                    for requested in normalized_companies
                ):
                    continue

            point_period = _normalize_lookup_text(
                point.reporting_period or fields.get("reporting_period") or ""
            )
            if period_key and period_key not in point_period:
                continue

            point_metric = _normalize_lookup_text(point.metric_name or "")
            point_section = _normalize_lookup_text(point.section or "")
            if (
                metric_key
                and metric_key not in point_metric
                and point_metric not in metric_key
            ):
                continue
            if section_key and section_key not in point_section:
                continue

            searchable = _normalize_lookup_text(
                " ".join(
                    [
                        str(point.metric_name or ""),
                        str(point.row_label or ""),
                        str(point.section or ""),
                        str(point.source_text or ""),
                        json.dumps(
                            point.row_context or {}, ensure_ascii=False, default=str
                        ),
                    ]
                )
            )
            if query_terms and not all(term in searchable for term in query_terms):
                continue

            observations.append(
                {
                    "company_name": report_company or None,
                    "reporting_period": point.reporting_period
                    or fields.get("reporting_period"),
                    "filename": record.filename,
                    "section": point.section,
                    "metric_name": point.metric_name,
                    "row_label": point.row_label,
                    "numeric_value": str(point.numeric_value),
                    "raw_value": point.raw_value,
                    "currency": point.currency or fields.get("currency"),
                    "unit": point.unit,
                    "row_context": point.row_context or {},
                    "source_page": point.source_page,
                    "source_table": point.source_table,
                    "source_text": point.source_text,
                    "confidence": point.confidence,
                }
            )
            if len(observations) >= safe_limit:
                break

        _finance_debug(
            "FINANCIAL_DATA_POINT_SEARCH",
            requested_companies=requested_companies,
            search_query=search_query or None,
            reporting_period=reporting_period or None,
            section=section or None,
            metric_name=metric_name or None,
            result_count=len(observations),
            filenames=list(dict.fromkeys(item["filename"] for item in observations)),
        )
        return json.dumps(
            {"observations": observations, "count": len(observations)},
            ensure_ascii=False,
            default=str,
        )
    finally:
        db.close()


@tool("search_financial_records")
def search_financial_records(search_query: str, company_names: str = "ALL"):
    """Retrieve report-level evidence from confirmed financial reports, including detailed category breakdowns and other information in the extracted report text. Use whenever the requested information is not fully present in the standard financial figures. Pass the user's requested details as search_query and comma-separated company names or ALL. Returns source metadata, structured fields, and extracted report text."""
    query_terms = [
        term
        for term in re.findall(r"[a-z0-9]+", (search_query or "").lower())
        if len(term) > 2
    ]
    requested_names = [
        name.strip() for name in (company_names or "ALL").split(",") if name.strip()
    ]
    all_companies = not requested_names or any(
        name.lower() in {"all", "all companies", "every company"}
        for name in requested_names
    )
    normalized_names = [_normalize_lookup_text(name) for name in requested_names]

    db = SessionLocal()
    try:
        records = (
            db.query(DocumentRecord)
            .filter(
                DocumentRecord.status == "confirmed",
                DocumentRecord.document_type == "financial_report",
            )
            .order_by(DocumentRecord.created_at.desc(), DocumentRecord.id.desc())
            .all()
        )
        results = []
        for record in records:
            fields = record.extracted_data or {}
            sections = fields.get("sections") or {}
            extracted_text = (
                sections.get("extracted_text", "") if isinstance(sections, dict) else ""
            )
            company = str(fields.get("company_name") or "")
            if not all_companies:
                # Match on the company name first; only fall back to the
                # filename/text when the report has no company name.
                haystack = (
                    _normalize_lookup_text(company)
                    if company.strip()
                    else _normalize_lookup_text(record.filename + " " + extracted_text)
                )
                if not any(name and name in haystack for name in normalized_names):
                    continue
            searchable = " ".join(
                [
                    company,
                    record.filename,
                    json.dumps(fields, ensure_ascii=False, default=str),
                    extracted_text,
                ]
            )
            lower_searchable = searchable.lower()
            matched_terms = [term for term in query_terms if term in lower_searchable]
            results.append(
                {
                    "company_name": company or None,
                    "reporting_period": fields.get("reporting_period"),
                    "currency": fields.get("currency"),
                    "filename": record.filename,
                    "structured_fields": {
                        k: v for k, v in fields.items() if k != "sections"
                    },
                    "matched_query_terms": matched_terms,
                    "extracted_report_text": extracted_text[
                        :_SEARCH_TEXT_CHARS_PER_REPORT
                    ],
                }
            )
            if len(results) >= _SEARCH_MAX_REPORTS:
                break

        _finance_debug(
            "FINANCIAL_RECORD_SEARCH",
            search_query=search_query,
            requested_companies=requested_names,
            returned_report_count=len(results),
            returned_companies=[item.get("company_name") for item in results],
        )
        return json.dumps(
            {"reports": results, "report_count": len(results)},
            ensure_ascii=False,
            default=str,
        )
    finally:
        db.close()


def _decimal_percent(value: str, default: str = "0") -> Decimal:
    """Parse a percentage safely; blank/auto means no change."""
    if value is None or str(value).strip().lower() in {
        "",
        "auto",
        "none",
        "null",
        "n/a",
    }:
        value = default
    raw = str(value).strip().lower().replace(",", "")
    if raw in {"", "auto", "none", "null", "n/a"}:
        return Decimal("0")

    direction = (
        Decimal("-1")
        if any(
            word in raw
            for word in ("decrease", "decreased", "drop", "down", "reduce", "reduced")
        )
        else Decimal("1")
    )
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    if not match:
        raise ValueError(f"Invalid percentage or amount: {value}")
    parsed = Decimal(match.group(0))
    if match.group(0).startswith("-"):
        return parsed
    return parsed * direction


def _decimal_amount(value: str) -> Decimal:
    """Parse a plain money amount (e.g. a target). Words never flip the sign."""
    raw = str(value).replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    if not match:
        raise ValueError(f"Invalid amount: {value}")
    return Decimal(match.group(0))


def _calculate_one_company(
    company_name: str,
    revenue_change: Decimal,
    expense_change: Decimal,
    target_nod: Decimal | None = None,
    target_mode: str = "auto",
) -> dict:
    matches = _get_company_financial_records(company_name)
    if not matches:
        return {
            "company": company_name,
            "error": "No confirmed financial record matched.",
        }

    report = matches[0]
    figures = report.get("figures", {})
    revenue = _to_decimal_amount(figures.get("revenue"))
    expenses = _to_decimal_amount(figures.get("operating_expenses"))
    if revenue is None or expenses is None:
        return {
            "company": report.get("company_name") or company_name,
            "reporting_period": report.get("reporting_period"),
            "error": "Revenue or operating expenses are missing from the confirmed report.",
        }

    new_revenue = revenue * (Decimal("1") + revenue_change / Decimal("100"))
    new_expenses = expenses * (Decimal("1") + expense_change / Decimal("100"))
    nod = new_revenue - new_expenses
    # These reports may not explicitly report operating income. In that case,
    # use revenue less operating expenses as a derived operating-profit proxy.
    baseline_operating_profit = revenue - expenses
    baseline_operating_margin = (
        (baseline_operating_profit / revenue * 100).quantize(Decimal("0.01"))
        if revenue
        else None
    )
    scenario_operating_margin = (
        (nod / new_revenue * 100).quantize(Decimal("0.01")) if new_revenue else None
    )
    result = {
        "company": report.get("company_name") or company_name,
        "reporting_period": report.get("reporting_period"),
        "currency": report.get("currency") or "INR",
        "baseline_revenue": _format_financial_amount(revenue),
        "baseline_operating_expenses": _format_financial_amount(expenses),
        "baseline_net_operating_difference": _format_financial_amount(
            baseline_operating_profit
        ),
        "baseline_operating_profit_used_for_margin": _format_financial_amount(
            baseline_operating_profit
        ),
        "baseline_operating_margin_percent": (
            str(baseline_operating_margin)
            if baseline_operating_margin is not None
            else None
        ),
        "revenue_change_percent": str(revenue_change),
        "expense_change_percent": str(expense_change),
        "scenario_revenue": _format_financial_amount(new_revenue),
        "scenario_operating_expenses": _format_financial_amount(new_expenses),
        "scenario_net_operating_difference": _format_financial_amount(nod),
        "scenario_operating_margin_percent": (
            str(scenario_operating_margin)
            if scenario_operating_margin is not None
            else None
        ),
        "operating_expenses_as_percent_of_revenue": str(
            (expenses / revenue * 100).quantize(Decimal("0.01"))
        )
        if revenue
        else None,
    }
    if target_nod is not None:
        mode = (target_mode or "auto").strip().lower()
        result["target_nod"] = _format_financial_amount(target_nod)

        if mode in {"revenue_unchanged", "keep_revenue_unchanged", "fixed_revenue"}:
            required_expenses = revenue - target_nod
            reduction = expenses - required_expenses
            change = (reduction / expenses * 100) if expenses else None
            result["required_expenses_if_revenue_unchanged"] = _format_financial_amount(
                required_expenses
            )
            result["required_expense_reduction"] = _format_financial_amount(reduction)
            result["required_expense_reduction_percent"] = (
                str(change.quantize(Decimal("0.01"))) if change is not None else None
            )
        elif mode in {
            "expenses_unchanged",
            "keep_expenses_unchanged",
            "fixed_expenses",
        }:
            required_revenue = target_nod + expenses
            change = ((required_revenue - revenue) / revenue * 100) if revenue else None
            result["required_revenue_if_expenses_unchanged"] = _format_financial_amount(
                required_revenue
            )
            result["required_revenue_increase_percent"] = (
                str(change.quantize(Decimal("0.01"))) if change is not None else None
            )
        elif target_nod >= revenue - expenses:
            required_revenue = target_nod + expenses
            change = ((required_revenue - revenue) / revenue * 100) if revenue else None
            result["required_revenue_if_expenses_unchanged"] = _format_financial_amount(
                required_revenue
            )
            result["required_revenue_increase_percent"] = (
                str(change.quantize(Decimal("0.01"))) if change is not None else None
            )
        else:
            required_expenses = revenue - target_nod
            reduction = expenses - required_expenses
            change = (reduction / expenses * 100) if expenses else None
            result["required_expense_reduction"] = _format_financial_amount(reduction)
            result["required_expense_reduction_percent"] = (
                str(change.quantize(Decimal("0.01"))) if change is not None else None
            )
    return result


@tool("calculate_financial_metrics")
def calculate_financial_metrics(
    company_names: str,
    revenue_change_percent: str = "0",
    expense_change_percent: str = "0",
    target_nod: str = "",
    target_mode: str = "auto",
    ranking_order: str = "unspecified",
    ranking_metric: str = "expense_ratio",
):
    """Retrieve confirmed financial-record figures and perform exact Decimal calculations, including derived operating margin. Pass comma-separated company names or ALL. For target NOD, use revenue_unchanged or expenses_unchanged when specified. For rankings, set ranking_metric to revenue, operating_expenses, net_operating_difference, operating_margin, or expense_ratio, and pass ascending or descending. Do not assume a direction when the user did not request one."""
    try:
        revenue_change = _decimal_percent(revenue_change_percent)
        expense_change = _decimal_percent(expense_change_percent)
        target = _decimal_amount(target_nod) if target_nod not in (None, "") else None
    except ValueError as error:
        return json.dumps({"error": str(error)})

    if company_names.strip().lower() in {"all", "all companies", "every company"}:
        db = SessionLocal()
        try:
            rows = (
                db.query(DocumentRecord)
                .filter(
                    DocumentRecord.status == "confirmed",
                    DocumentRecord.document_type == "financial_report",
                )
                .order_by(DocumentRecord.created_at.desc(), DocumentRecord.id.desc())
                .all()
            )
            names, seen = [], set()
            for row in rows:
                name = str((row.extracted_data or {}).get("company_name") or "").strip()
                key = _normalize_lookup_text(name)
                if name and key and key not in seen:
                    seen.add(key)
                    names.append(name)
        finally:
            db.close()
    else:
        names = [name.strip() for name in company_names.split(",") if name.strip()]

    results = [
        _calculate_one_company(
            name, revenue_change, expense_change, target, target_mode
        )
        for name in names
    ]
    valid = [item for item in results if "error" not in item]
    combined = None
    if len(valid) > 1:
        fields = (
            "baseline_revenue",
            "baseline_operating_expenses",
            "baseline_net_operating_difference",
            "scenario_revenue",
            "scenario_operating_expenses",
            "scenario_net_operating_difference",
        )
        combined = {}
        for field in fields:
            combined[field] = _format_financial_amount(
                sum(
                    (Decimal(item[field].replace(",", "")) for item in valid),
                    Decimal("0"),
                )
            )
        combined["company_count"] = len(valid)
        currencies = {item.get("currency") or "INR" for item in valid}
        if len(currencies) == 1:
            combined["currency"] = currencies.pop()
        else:
            # Never add amounts across currencies silently.
            combined = {
                "error": "Reports use different currencies; combined totals not computed.",
                "currencies": sorted(currencies),
            }

    ranking = []
    normalized_order = (ranking_order or "unspecified").strip().lower()
    normalized_metric = (ranking_metric or "expense_ratio").strip().lower()
    metric_fields = {
        "revenue": "baseline_revenue",
        "operating_expenses": "baseline_operating_expenses",
        "net_operating_difference": "baseline_net_operating_difference",
        "operating_margin": "baseline_operating_margin_percent",
        "expense_ratio": "operating_expenses_as_percent_of_revenue",
    }
    if normalized_order in {"ascending", "descending"}:
        source_field = metric_fields.get(normalized_metric)
        if source_field:
            ranking = []
            for item in valid:
                value = item.get(source_field)
                if value is None:
                    continue
                ranking.append(
                    {
                        "company": item["company"],
                        "reporting_period": item.get("reporting_period"),
                        "currency": item.get("currency") or "INR",
                        "revenue": item.get("baseline_revenue"),
                        "operating_expenses": item.get("baseline_operating_expenses"),
                        "net_operating_difference": item.get(
                            "baseline_net_operating_difference"
                        ),
                        "operating_margin_percent": item.get(
                            "baseline_operating_margin_percent"
                        ),
                        "operating_expenses_as_percent_of_revenue": item.get(
                            "operating_expenses_as_percent_of_revenue"
                        ),
                        "ranked_metric": normalized_metric,
                        "ranked_value": value,
                    }
                )
            ranking.sort(
                key=lambda item: Decimal(str(item["ranked_value"]).replace(",", "")),
                reverse=(normalized_order == "descending"),
            )
        for index, item in enumerate(ranking, start=1):
            item["rank"] = index
    _finance_debug(
        "FINANCIAL_RECORD_RANKING_PREPARED",
        ranking_order=normalized_order,
        ranking_metric=normalized_metric,
        ranked_company_count=len(ranking),
        company_count=len(valid),
    )

    return json.dumps(
        {
            "results": results,
            "combined": combined,
            "expense_ratio_ranking": ranking,
            "ranking_order": normalized_order,
            "ranking_metric": normalized_metric,
        },
        ensure_ascii=False,
    )


@tool("calculate_report_receivables")
def calculate_report_receivables(company_names: str):
    """Calculate accounts-receivable totals from confirmed financial-report rows. Pass comma-separated company names or ALL. Prefer persisted FinancialDataPoint rows and their row_context; fall back to legacy report-text parsing only when no observations exist."""
    if (company_names or "").strip().lower() in {
        "all",
        "all companies",
        "every company",
    }:
        db = SessionLocal()
        try:
            records = (
                db.query(DocumentRecord)
                .filter(
                    DocumentRecord.status == "confirmed",
                    DocumentRecord.document_type == "financial_report",
                )
                .order_by(DocumentRecord.created_at.desc(), DocumentRecord.id.desc())
                .all()
            )
            names, seen = [], set()
            for record in records:
                name = str(
                    (record.extracted_data or {}).get("company_name") or ""
                ).strip()
                key = _normalize_lookup_text(name)
                if name and key and key not in seen:
                    seen.add(key)
                    names.append(name)
        finally:
            db.close()
    else:
        names = [
            name.strip() for name in (company_names or "").split(",") if name.strip()
        ]

    results = []
    for name in names:
        needle = _normalize_lookup_text(name)
        db = SessionLocal()
        try:
            reports = (
                db.query(DocumentRecord)
                .filter(
                    DocumentRecord.status == "confirmed",
                    DocumentRecord.document_type == "financial_report",
                )
                .order_by(DocumentRecord.created_at.desc(), DocumentRecord.id.desc())
                .all()
            )
            matched_report = None
            for candidate in reports:
                fields = candidate.extracted_data or {}
                sections = fields.get("sections") or {}
                extracted_text = (
                    sections.get("extracted_text", "")
                    if isinstance(sections, dict)
                    else ""
                )
                if _report_matches_company(
                    needle, fields, candidate.filename, extracted_text
                ):
                    matched_report = candidate
                    break

            if matched_report is None:
                results.append(
                    {"company": name, "error": "No confirmed financial report matched."}
                )
                continue

            fields = matched_report.extracted_data or {}
            company = fields.get("company_name") or name
            datapoints = (
                db.query(FinancialDataPoint)
                .filter(FinancialDataPoint.document_id == matched_report.id)
                .order_by(FinancialDataPoint.id.asc())
                .all()
            )

            # Receivables are represented by an amount observation whose row_context
            # carries invoice identity, customer, due date and status. Do not parse
            # invoice IDs or dates from the flattened report text when these rows exist.
            rows = []
            for point in datapoints:
                context = point.row_context or {}
                if not isinstance(context, dict) or not context.get("invoice_id"):
                    continue
                metric = _normalize_lookup_text(point.metric_name or "")
                if "receivable" not in metric and not context.get("customer"):
                    continue
                amount = point.numeric_value
                if amount is None:
                    amount = _to_decimal_amount(point.raw_value)
                if amount is None:
                    continue
                rows.append(
                    {
                        "invoice_id": context.get("invoice_id"),
                        "customer": context.get("customer") or "Not reported",
                        "amount": str(amount),
                        "invoice_date": context.get("invoice_date"),
                        "due_date": context.get("due_date"),
                        "payment_date": context.get("payment_date"),
                        "status": context.get("status") or "Unknown",
                        "status_source": "reported"
                        if context.get("status")
                        else "not_reported",
                    }
                )

            if not rows:
                # Backward compatibility for older reports that predate datapoint
                # persistence or do not contain invoice-level row context.
                legacy_reports = _get_company_financial_records(name)
                if legacy_reports:
                    rows = legacy_reports[0].get("receivables", [])

            totals = {
                "Pending": Decimal("0"),
                "Overdue": Decimal("0"),
                "Paid": Decimal("0"),
                "Unknown": Decimal("0"),
            }
            for row in rows:
                status = str(row.get("status") or "Unknown").strip().capitalize()
                if status not in totals:
                    status = "Unknown"
                amount = _to_decimal_amount(row.get("amount"))
                if amount is not None:
                    totals[status] += amount

            results.append(
                {
                    "company": company,
                    "reporting_period": fields.get("reporting_period"),
                    "currency": fields.get("currency") or "INR",
                    "invoice_rows": rows,
                    "invoice_count": len(rows),
                    "pending_total": _format_financial_amount(totals["Pending"]),
                    "overdue_total": _format_financial_amount(totals["Overdue"]),
                    "paid_total": _format_financial_amount(totals["Paid"]),
                    "unknown_status_total": _format_financial_amount(totals["Unknown"]),
                    "outstanding_total": _format_financial_amount(
                        totals["Pending"] + totals["Overdue"]
                    ),
                    "pending_invoice_count": sum(
                        1
                        for row in rows
                        if str(row.get("status") or "").strip().lower() == "pending"
                    ),
                    "source_file": matched_report.filename,
                    "retrieval_source": "financial_data_points"
                    if datapoints and rows
                    else "legacy_report_text",
                }
            )
        finally:
            db.close()

    return json.dumps({"results": results}, ensure_ascii=False, default=str)


def _to_decimal_amount(value):
    """Convert an explicitly extracted financial value to Decimal."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    match = re.search(r"-?\d[\d,]*(?:\.\d{1,2})?", str(value))
    if not match:
        return None
    return Decimal(match.group(0).replace(",", ""))


def _extract_explicit_report_amount(text, labels):
    """Read a value only when it appears beside an explicit financial label."""
    for label in labels:
        pattern = (
            rf"(?im)^\s*(?:{label})\s*(?:[:|–—-])?\s*"
            rf"(?:INR|Rs\.?|₹)?\s*(-?\d[\d,]*(?:\.\d{{1,2}})?)\s*$"
        )
        match = re.search(pattern, text or "")
        if match:
            return _to_decimal_amount(match.group(1))
    return None


def _extract_report_receivables(extracted_text: str) -> list[dict]:
    """Extract invoice rows from the Accounts Receivable section only.

    Date and status fields are included only when explicitly present in the
    extracted report. Missing dates remain None and missing statuses are marked
    Unknown; no date or payment status is inferred from payment terms/current date.
    """
    if not extracted_text:
        return []

    section_match = re.search(
        r"(?is)\baccounts?\s+receivable\b(.*?)(?=\n\s*(?:\d+(?:\.\d+)*[.)]?\s+)?"
        r"(?:accounting\s+notes|management\s+notes|notes|cash\s+flow|"
        r"financial\s+position|income\s+statement)\b|\Z)",
        extracted_text,
    )
    section = section_match.group(1) if section_match else extracted_text
    raw_lines = [line.strip() for line in section.splitlines() if line.strip()]
    lines = [re.sub(r"\s+", " ", line).strip(" |") for line in raw_lines]

    invoice_re = re.compile(r"\b([A-Z]{2,}-\d{2,4}-\d{2,4})\b", re.I)
    date_re = re.compile(
        r"\b(?:\d{1,2}[\s-]+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s-]+\d{4}"
        r"|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b",
        re.I,
    )
    status_re = re.compile(
        r"\b(Pending|Overdue|Paid|Unpaid|Partially\s+Paid|Settled)\b", re.I
    )
    amount_re = re.compile(r"^(?:₹|INR|Rs\.?)?\s*([\d,]+(?:\.\d{1,2})?)\s*$", re.I)

    # Infer date labels only from explicit column headings in the report.
    date_labels = []
    for label in ("invoice date", "due date", "payment date"):
        match = re.search(rf"\b{label}\b", section, flags=re.I)
        if match:
            date_labels.append((match.start(), label.replace(" ", "_")))
    date_labels = [label for _, label in sorted(date_labels)]

    rows, seen = [], set()
    for line in lines:
        invoice_match = invoice_re.search(line)
        if not invoice_match:
            continue
        dates = [m.group(0) for m in date_re.finditer(line)]
        amount_matches = [
            m
            for m in re.finditer(
                r"(?<![A-Za-z0-9])(?:₹|INR|Rs\.?)?\s*([\d,]+(?:\.\d{1,2})?)",
                line,
            )
            if not (m.start() < invoice_match.end() and m.end() > invoice_match.start())
            and not any(
                m.start() < d.end() and m.end() > d.start()
                for d in date_re.finditer(line)
            )
        ]
        if not amount_matches:
            continue
        status_match = status_re.search(line)
        amount_match = (
            amount_matches[-1] if len(amount_matches) > 1 else amount_matches[0]
        )
        amount = str(Decimal(amount_match.group(1).replace(",", "")))
        first_date_start = min(
            (m.start() for m in date_re.finditer(line)), default=amount_match.start()
        )
        customer = line[invoice_match.end() : first_date_start].strip(" \t|:-–—■₹")
        # If customer/date columns are reordered, retain a non-empty customer
        # segment between the invoice ID and the amount/status fields.
        if not customer:
            customer = "Not reported"

        row = {
            "invoice_id": invoice_match.group(1).upper(),
            "customer": customer,
            "amount": amount,
            "invoice_date": None,
            "due_date": None,
            "payment_date": None,
            "status": status_match.group(1).title() if status_match else "Unknown",
            "status_source": "reported" if status_match else "not_reported",
        }
        if dates:
            if date_labels and len(date_labels) == len(dates):
                for label, value in zip(date_labels, dates):
                    row[label] = value
            elif len(dates) == 1:
                # Legacy report table has a single date column explicitly titled Due Date.
                row["due_date"] = dates[0]
            elif len(dates) == 2:
                row["invoice_date"], row["due_date"] = dates
            elif len(dates) >= 3:
                row["invoice_date"], row["due_date"], row["payment_date"] = dates[:3]

        identity = (row["invoice_id"], row["amount"], row["status"])
        if identity not in seen:
            rows.append(row)
            seen.add(identity)

    if rows:
        return rows

    # Conservative column-oriented fallback for PDF extractors that place each
    # table column on separate lines. Dates are mapped to due_date by default,
    # matching the historical report layout; no invoice/payment date is invented.
    invoice_ids = [
        m.group(1).upper() for line in lines for m in invoice_re.finditer(line)
    ]
    dates = [m.group(0) for line in lines for m in date_re.finditer(line)]
    statuses = [
        m.group(1).title() for line in lines if (m := status_re.fullmatch(line))
    ]
    amounts = []
    for line in lines:
        match = amount_re.fullmatch(line)
        if match:
            amounts.append(str(Decimal(match.group(1).replace(",", ""))))

    header_words = {
        "invoice id",
        "invoice",
        "customer",
        "invoice date",
        "due date",
        "payment date",
        "amount",
        "amount (inr)",
        "status",
        "inr",
        "rs",
        "accounts receivable",
    }
    customers = []
    for line in lines:
        if line.lower().strip(":") in header_words:
            continue
        if invoice_re.search(line) or date_re.search(line) or status_re.fullmatch(line):
            continue
        if amount_re.fullmatch(line):
            continue
        if re.search(r"[A-Za-z]", line) and not re.match(
            r"(?i)^(selected customer invoices|recorded in the report|invoice id|customer|due date|invoice date|payment date|amount|status|currency)\b",
            line,
        ):
            customers.append(line.strip(" :-|"))

    count = min(len(invoice_ids), len(amounts), len(customers))
    if not count:
        return []

    # In column-oriented PDF text, values may be grouped by column rather than
    # row. Use explicit header labels to map date blocks; otherwise preserve the
    # legacy single Due Date column only.
    mapped_dates = {
        field: [None] * count for field in ("invoice_date", "due_date", "payment_date")
    }
    if date_labels and len(dates) >= count * len(date_labels):
        for column_index, field in enumerate(date_labels):
            block = dates[column_index * count : (column_index + 1) * count]
            mapped_dates[field] = block
    elif dates:
        mapped_dates["due_date"] = dates[:count] + [None] * max(0, count - len(dates))

    for i in range(count):
        row = {
            "invoice_id": invoice_ids[i],
            "customer": customers[i],
            "amount": amounts[i],
            "invoice_date": mapped_dates["invoice_date"][i],
            "due_date": mapped_dates["due_date"][i],
            "payment_date": mapped_dates["payment_date"][i],
            "status": statuses[i] if i < len(statuses) else "Unknown",
            "status_source": "reported" if i < len(statuses) else "not_reported",
        }
        identity = (row["invoice_id"], row["amount"], row["status"])
        if identity not in seen:
            rows.append(row)
            seen.add(identity)
    return rows


def _report_matches_company(
    needle: str, fields: dict, filename: str, text: str
) -> bool:
    """Match a requested company against the report's own company name first.

    Only when the report has no company name do we fall back to the filename and
    body text. This prevents a customer listed in Company A's receivables from
    being mistaken for a company with its own report.
    """
    name_key = _normalize_lookup_text(fields.get("company_name") or "")
    if name_key:
        if len(needle) < 3 or len(name_key) < 3:
            return needle == name_key
        return needle in name_key or name_key in needle
    return needle in _normalize_lookup_text(f"{filename} {text}")


def _get_company_financial_records(company_name: str) -> list[dict]:
    """Return explicit financial-report figures for one named company."""
    needle = _normalize_lookup_text(company_name)
    if not needle:
        return []

    db = SessionLocal()
    try:
        records = (
            db.query(DocumentRecord)
            .filter(
                DocumentRecord.status == "confirmed",
                DocumentRecord.document_type == "financial_report",
            )
            .order_by(DocumentRecord.created_at.desc(), DocumentRecord.id.desc())
            .all()
        )

        matches = []
        for record in records:
            fields = record.extracted_data or {}
            sections = fields.get("sections") or {}
            extracted_text = (
                sections.get("extracted_text", "") if isinstance(sections, dict) else ""
            )
            if not _report_matches_company(
                needle, fields, record.filename, extracted_text
            ):
                continue

            explicit = {}
            for key, labels in {
                "revenue": (r"total\s+revenue", r"revenue"),
                "operating_expenses": (
                    r"total\s+operating\s+expenses",
                    r"operating\s+expenses",
                ),
                "gross_profit": (r"gross\s+profit",),
                "operating_income": (r"operating\s+income",),
                "net_income": (r"net\s+(?:income|profit|earnings)",),
                "total_assets": (r"total\s+assets",),
                "total_liabilities": (r"total\s+liabilities",),
                "equity": (r"(?:shareholders'?\s+)?equity",),
                "current_assets": (r"current\s+assets",),
                "current_liabilities": (r"current\s+liabilities",),
                "inventory": (r"(?:closing\s+)?inventory",),
                "cash_and_cash_equivalents": (
                    r"cash(?:\s+and\s+cash)?\s+equivalents",
                    r"cash\s+balance",
                ),
                "accounts_receivable": (
                    r"accounts?\s+receivable",
                    r"trade\s+receivables",
                ),
                "accounts_payable": (r"accounts?\s+payable", r"trade\s+payables"),
                "total_debt": (r"total\s+debt", r"borrowings"),
                "ebitda": (r"ebitda",),
                "net_operating_difference": (r"net\s+operating\s+difference",),
            }.items():
                value = _to_decimal_amount(fields.get(key))
                if value is None:
                    value = _extract_explicit_report_amount(extracted_text, labels)
                if value is not None:
                    explicit[key] = value

            # This is a derived operating difference, not audited net profit.
            if (
                "net_operating_difference" not in explicit
                and explicit.get("revenue") is not None
                and explicit.get("operating_expenses") is not None
            ):
                explicit["net_operating_difference"] = (
                    explicit["revenue"] - explicit["operating_expenses"]
                )
                explicit["net_operating_difference_calculated"] = True

            matches.append(
                {
                    "filename": record.filename,
                    "company_name": fields.get("company_name"),
                    "reporting_period": fields.get("reporting_period"),
                    "currency": fields.get("currency"),
                    "figures": {key: str(value) for key, value in explicit.items()},
                    "receivables": _extract_report_receivables(extracted_text),
                }
            )
        return matches
    finally:
        db.close()


def _safe_ratio(numerator, denominator):
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


@tool("analyze_financial_health")
def analyze_financial_health(company_name: str = "", company_names: str = ""):
    """Calculate evidence-backed profitability, liquidity, leverage and return ratios from the latest confirmed report. Accepts company_name or company_names."""
    requested = _resolve_company_names(company_name, company_names)
    if not requested:
        return json.dumps({"error": "Provide company_name or company_names."})
    results = [_analyze_financial_health_one(name) for name in requested]
    if len(results) == 1:
        return json.dumps(results[0], ensure_ascii=False, default=str)
    return json.dumps({"results": results}, ensure_ascii=False, default=str)


def _analyze_financial_health_one(company_name: str):
    reports = _get_company_financial_records(company_name)
    if not reports:
        return {
            "company": company_name,
            "error": "No confirmed financial report matched.",
        }
    report = reports[0]
    f = report.get("figures") or {}
    get = lambda key: _to_decimal_amount(f.get(key))
    revenue, expenses = get("revenue"), get("operating_expenses")
    gross_profit, operating_income, net_income = (
        get("gross_profit"),
        get("operating_income"),
        get("net_income"),
    )
    current_assets, current_liabilities = (
        get("current_assets"),
        get("current_liabilities"),
    )
    inventory, cash = get("inventory"), get("cash_and_cash_equivalents")
    assets, liabilities, equity = (
        get("total_assets"),
        get("total_liabilities"),
        get("equity"),
    )
    debt, ebitda = get("total_debt"), get("ebitda")
    receivables, payables = get("accounts_receivable"), get("accounts_payable")
    operating_profit = operating_income
    if operating_profit is None and revenue is not None and expenses is not None:
        operating_profit = revenue - expenses

    def pct(n, d):
        value = _safe_ratio(n, d)
        return (
            str((value * 100).quantize(Decimal("0.01"))) if value is not None else None
        )

    def ratio(n, d):
        value = _safe_ratio(n, d)
        return str(value.quantize(Decimal("0.01"))) if value is not None else None

    ratios = {
        "gross_profit_margin_percent": pct(gross_profit, revenue),
        "operating_margin_percent": pct(operating_profit, revenue),
        "net_profit_margin_percent": pct(net_income, revenue),
        "operating_expense_ratio_percent": pct(expenses, revenue),
        "current_ratio": ratio(current_assets, current_liabilities),
        "quick_ratio": ratio(current_assets - inventory, current_liabilities)
        if current_assets is not None and inventory is not None
        else None,
        "cash_ratio": ratio(cash, current_liabilities),
        "liabilities_to_equity": ratio(liabilities, equity),
        "debt_to_equity": ratio(debt, equity),
        "return_on_assets_percent": pct(net_income, assets),
        "return_on_equity_percent": pct(net_income, equity),
        "ebitda_margin_percent": pct(ebitda, revenue),
        "receivables_to_payables": ratio(receivables, payables),
    }
    return {
        "company": report.get("company_name") or company_name,
        "reporting_period": report.get("reporting_period"),
        "currency": report.get("currency") or "INR",
        "source_file": report.get("filename"),
        "ratios": ratios,
        "unavailable_ratios": [k for k, v in ratios.items() if v is None],
        "note": "Ratios use only explicitly extracted report values. Missing inputs are unavailable, not zero. These indicators are not an audit or credit rating.",
    }


@tool("analyze_financial_trends")
def analyze_financial_trends(
    company_name: str = "",
    company_names: str = "",
    anomaly_threshold_percent: str = "20",
):
    """Compare confirmed reports for one company. Accepts company_name or company_names and flags large movements for review."""
    requested = _resolve_company_names(company_name, company_names)
    if not requested:
        return json.dumps({"error": "Provide company_name or company_names."})
    results = [
        _analyze_financial_trends_one(name, anomaly_threshold_percent)
        for name in requested
    ]
    if len(results) == 1:
        return json.dumps(results[0], ensure_ascii=False, default=str)
    return json.dumps({"results": results}, ensure_ascii=False, default=str)


def _analyze_financial_trends_one(
    company_name: str, anomaly_threshold_percent: str = "20"
):
    reports = _get_company_financial_records(company_name)
    if not reports:
        return {
            "company": company_name,
            "error": "No confirmed financial report matched.",
        }
    try:
        threshold = abs(_decimal_percent(anomaly_threshold_percent))
    except ValueError as error:
        return {"company": company_name, "error": str(error)}
    reports = list(
        reversed(reports)
    )  # Existing retrieval order is newest upload first.
    tracked = (
        "revenue",
        "operating_expenses",
        "gross_profit",
        "operating_income",
        "net_income",
        "total_assets",
        "total_liabilities",
        "equity",
    )
    timeline, flags, previous = [], [], None
    for report in reports:
        f = report.get("figures") or {}
        values = {key: _to_decimal_amount(f.get(key)) for key in tracked}
        row = {
            "reporting_period": report.get("reporting_period")
            or "Period not specified",
            "source_file": report.get("filename"),
            "currency": report.get("currency") or "INR",
            "figures": {},
            "period_changes_percent": {},
        }
        for key, current in values.items():
            if current is None:
                continue
            row["figures"][key] = _format_financial_amount(current)
            prior = previous.get(key) if previous else None
            if prior is not None and prior != 0:
                change = (current - prior) / abs(prior) * 100
                row["period_changes_percent"][key] = str(
                    change.quantize(Decimal("0.01"))
                )
                if (
                    key in {"revenue", "operating_expenses"}
                    and abs(change) >= threshold
                ):
                    flags.append(
                        {
                            "period": row["reporting_period"],
                            "metric": key,
                            "change_percent": str(change.quantize(Decimal("0.01"))),
                            "threshold_percent": str(threshold),
                            "flag": "Large movement requiring review",
                        }
                    )
        timeline.append(row)
        previous = {key: value for key, value in values.items() if value is not None}
    return {
        "company": reports[-1].get("company_name") or company_name,
        "report_count": len(timeline),
        "ordering_basis": "record upload/creation order, oldest first; period labels are preserved as stored",
        "timeline": timeline,
        "movement_flags": flags,
        "note": "Adjacent uploaded reports may not be consecutive or equally spaced fiscal periods. Flags are review prompts, not proof of fraud, error, or cause.",
    }


@tool("forecast_financial_baseline")
def forecast_financial_baseline(
    company_name: str = "", company_names: str = "", periods_ahead: str = "1"
):
    """Produce a simple linear baseline projection using at least three reports. Accepts company_name or company_names."""
    requested = _resolve_company_names(company_name, company_names)
    if not requested:
        return json.dumps({"error": "Provide company_name or company_names."})
    results = [
        _forecast_financial_baseline_one(name, periods_ahead) for name in requested
    ]
    if len(results) == 1:
        return json.dumps(results[0], ensure_ascii=False, default=str)
    return json.dumps({"results": results}, ensure_ascii=False, default=str)


def _forecast_financial_baseline_one(company_name: str, periods_ahead: str = "1"):
    reports = _get_company_financial_records(company_name)
    if not reports:
        return {
            "company": company_name,
            "error": "No confirmed financial report matched.",
        }
    try:
        steps = int(periods_ahead)
        if not 1 <= steps <= 4:
            raise ValueError
    except (TypeError, ValueError):
        return {
            "company": company_name,
            "error": "periods_ahead must be an integer from 1 to 4.",
        }
    reports = list(reversed(reports))
    history = []
    for report in reports:
        f = report.get("figures") or {}
        history.append(
            {
                "period": report.get("reporting_period") or "Period not specified",
                "currency": report.get("currency") or "INR",
                "revenue": _to_decimal_amount(f.get("revenue")),
                "expenses": _to_decimal_amount(f.get("operating_expenses")),
            }
        )
    if len(history) < 3:
        return {
            "company": company_name,
            "report_count": len(history),
            "error": "At least three confirmed reports are required.",
        }
    currencies = {row["currency"] for row in history}
    if len(currencies) != 1:
        return {
            "company": company_name,
            "error": "Different currencies found; projection not calculated.",
            "currencies": sorted(currencies),
        }

    def project(field):
        values = [row[field] for row in history]
        if any(value is None for value in values):
            return None
        average_delta = sum(
            (values[i] - values[i - 1] for i in range(1, len(values))), Decimal("0")
        ) / Decimal(len(values) - 1)
        estimate = values[-1] + average_delta * Decimal(steps)
        return {
            "latest_observed": _format_financial_amount(values[-1]),
            "average_absolute_change_per_report": _format_financial_amount(
                average_delta
            ),
            "projected_value": _format_financial_amount(estimate),
            "method": "latest value plus average absolute change per uploaded report",
        }

    revenue_projection, expense_projection = project("revenue"), project("expenses")
    projected_difference = None
    if revenue_projection and expense_projection:
        projected_difference = Decimal(
            revenue_projection["projected_value"].replace(",", "")
        ) - Decimal(expense_projection["projected_value"].replace(",", ""))
    return {
        "company": reports[-1].get("company_name") or company_name,
        "currency": next(iter(currencies)),
        "historical_reports_used": len(history),
        "periods_ahead": steps,
        "revenue_projection": revenue_projection,
        "operating_expense_projection": expense_projection,
        "projected_net_operating_difference": _format_financial_amount(
            projected_difference
        )
        if projected_difference is not None
        else None,
        "limitations": [
            "Simple linear baseline, not seasonality-aware or causal.",
            "Uploaded reports may not represent equally spaced periods.",
            "Missing source values prevent that metric from being projected.",
            "Not an audited result or guaranteed outcome.",
        ],
    }


def _format_financial_amount(value) -> str:
    """Format a database amount without changing its numeric value."""
    # Extracted report amounts may contain thousands separators, e.g. "248,000".
    raw = str(value).strip().replace(",", "")
    amount = Decimal(raw)
    formatted = format(amount, ",f")
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted


def _is_company_wide_financial_summary_query(user_query: str) -> bool:
    """Identify company-wide summary requests, excluding customer lookups."""
    query = user_query.lower()
    customer_terms = ("customer", "client", "invoice for", "payment from")
    if any(term in query for term in customer_terms):
        return False

    asks_financial_metric = any(
        term in query
        for term in ("revenue", "income", "expense", "profit", "financial summary")
    )
    # Only explicit internal/possessive wording authorizes internal totals.
    asks_company_scope = bool(
        re.search(r"\b(?:our|ours|organization|organisation|internal)\b", query)
    )
    return asks_financial_metric and asks_company_scope


def _requested_reporting_period(user_query: str):
    """Return a period label when the user explicitly requests a reporting period."""
    patterns = (
        r"\bFY\s*\d{4}(?:\s*[-/–]\s*\d{2,4})?\b",
        r"\b(?:financial|fiscal) year\s+(?:\d{4})(?:\s*[-/–]\s*\d{2,4})?\b",
        r"\b(?:in|for|during)\s+(?:the\s+)?(?:year|quarter|month)\s+(?:20\d{2})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, user_query, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def _period_unavailable_response(user_query: str, period: str) -> str:
    query = user_query.lower()
    requested = []
    if "revenue" in query or "income" in query:
        requested.append("total revenue")
    if "expense" in query or "spending" in query:
        requested.append("total expenses")
    if "profit" in query or "net difference" in query:
        requested.append("net profit")
    if not requested:
        requested = ["the requested financial figures"]
    items = "\n".join(f"- {metric}: unavailable for {period}" for metric in requested)
    return (
        f"The internal financial tools cannot retrieve period-specific records for {period}.\n"
        f"{items}\n"
        "The available summary is an aggregate and is not filtered by reporting period. "
        "I have not substituted aggregate totals, estimated values, or calculated "
        "missing figures."
    )


def _is_latest_invoice_detail_query(user_query: str) -> bool:
    """Detect a request for the latest uploaded invoice document."""
    query = user_query.lower()
    asks_latest = bool(re.search(r"\b(latest|most recent)\b", query))
    asks_invoice = bool(re.search(r"\binvoices?\b", query))
    asks_details = any(
        term in query
        for term in ("detail", "details", "show me", "tell me", "what is", "give me")
    )
    return asks_latest and asks_invoice and asks_details


def _normalize_lookup_text(value: str) -> str:
    """Normalize company names and identifiers, including spoken initials/digits."""
    tokens = re.findall(r"[a-z0-9]+", str(value).lower())

    collapsed = []
    i = 0
    while i < len(tokens):
        if len(tokens[i]) == 1 and tokens[i].isalpha():
            j = i
            letters = []
            while j < len(tokens) and len(tokens[j]) == 1 and tokens[j].isalpha():
                letters.append(tokens[j])
                j += 1
            if len(letters) > 1:
                collapsed.append("".join(letters))
                i = j
                continue
        if tokens[i].isdigit():
            j = i
            digits = []
            while j < len(tokens) and tokens[j].isdigit() and len(tokens[j]) == 1:
                digits.append(tokens[j])
                j += 1
            if len(digits) >= 4:
                collapsed.append("".join(digits))
                i = j
                continue
        collapsed.append(tokens[i])
        i += 1

    normalized = []
    for token in collapsed:
        if len(token) > 4 and token.endswith("ies"):
            token = token[:-3] + "y"
        elif len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        normalized.append(token)
    return "".join(normalized)


def _original_user_utterance(user_query: str) -> str:
    """Return only the user's message from the Supervisor's wrapped input.

    The old substring search matched the words ``USER REQUEST`` inside the
    heading ``ORIGINAL USER REQUEST`` and then retained the Supervisor
    assignment too. That duplicated percentage/direction language and could
    make the deterministic scenario parser reject an otherwise clear request.
    """
    text = str(user_query or "").strip()
    wrapped = re.search(
        r"(?is)^\s*ORIGINAL USER REQUEST:\s*(.*?)"
        r"(?:\n\s*SUPERVISOR ASSIGNMENT FOR [A-Z]+ AGENT:\s*|\Z)",
        text,
    )
    if wrapped:
        return wrapped.group(1).strip()

    # Support older wrappers that used a standalone USER REQUEST heading.
    legacy = re.search(r"(?im)^USER REQUEST:\s*(.*)\Z", text)
    if legacy:
        return legacy.group(1).strip()
    return text


# Words that look like a company name to the regexes below but never are one,
# e.g. "show me the invoice summary" must not look up a company called "summary".
_LOOKUP_STOPWORDS = {
    "the",
    "a",
    "an",
    "this",
    "that",
    "it",
    "me",
    "us",
    "our",
    "my",
    "all",
    "summary",
    "summaries",
    "total",
    "totals",
    "status",
    "statuses",
    "detail",
    "details",
    "pending",
    "overdue",
    "paid",
    "unpaid",
    "amount",
    "amounts",
    "list",
    "record",
    "records",
    "report",
    "reports",
    "last",
    "next",
    "month",
    "year",
    "quarter",
    "week",
    "today",
    "breakdown",
    "overview",
    "count",
    "how",
    "what",
    "when",
    "where",
    "why",
    "who",
    "which",
    "does",
    "do",
    "is",
    "are",
    "was",
    "were",
    "yet",
    "receive",
    "received",
    "from",
    "its",
    "their",
    "customer",
    "customers",
    "client",
    "clients",
    "supplier",
    "suppliers",
    "money",
    "identify",
    "including",
}


def _is_stopword_candidate(candidate: str) -> bool:
    words = re.findall(r"[a-z0-9]+", candidate.lower())
    return not words or words[0] in _LOOKUP_STOPWORDS


def _extract_invoice_lookup_term(user_query: str) -> str | None:
    """Extract a company name or complete invoice ID from the actual utterance."""
    query = _original_user_utterance(user_query)

    # Prefer a structured invoice ID: letter prefix + year + serial number.
    id_match = re.search(
        r"(?i)\binvoice\s*(?:number|no\.?|#)?\s*[:\-]?\s*"
        r"((?:[a-z]\s*){1,4})\s*(?:dash|hyphen|[-])?\s*"
        r"((?:\d\s*){4})\s*(?:dash|hyphen|[-])?\s*"
        r"((?:\d\s*){3,})",
        query,
    )
    if id_match:
        prefix = re.sub(r"\s+", "", id_match.group(1)).upper()
        year = re.sub(r"\D", "", id_match.group(2))
        serial = re.sub(r"\D", "", id_match.group(3))
        if prefix and len(year) == 4 and len(serial) >= 3:
            return f"{prefix}-{year}-{serial}"

    conventional = re.search(
        r"(?i)\b([a-z]{1,4})\s*[- ]\s*(\d{4})\s*[- ]\s*(\d{3,})\b",
        query,
    )
    if conventional:
        return f"{conventional.group(1).upper()}-{conventional.group(2)}-{conventional.group(3)}"

    digit_groups = re.findall(r"(?<!\d)(?:\d[\s-]*){6,}\d?(?!\d)", query)
    if digit_groups:
        digits = re.sub(
            r"\D", "", max(digit_groups, key=lambda item: len(re.sub(r"\D", "", item)))
        )
        if len(digits) >= 6:
            return digits

    invoice_match = re.search(
        r"\binvoice\s*(?:number|no\.?|#)?\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9\s/_-]{3,50})",
        query,
        flags=re.IGNORECASE,
    )
    if invoice_match:
        candidate = invoice_match.group(1).strip(" .,!?:;")
        candidate = re.sub(r"\s+", " ", candidate)
        if re.search(r"\d", candidate):
            return candidate

    # First recognize a proper-noun company phrase anywhere in the actual
    # utterance. This handles constructions such as:
    # "How much money is RedWood Agritech yet to receive from its customers?"
    # The older "from <phrase>" pattern incorrectly selected "its customers".
    proper_name_matches = re.finditer(
        r"\b([A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){1,5})\b",
        query,
    )
    proper_name_candidates = []
    for match in proper_name_matches:
        candidate = match.group(1).strip(" .,!?:;")
        if not _is_stopword_candidate(candidate):
            proper_name_candidates.append(candidate)
    if proper_name_candidates:
        # Prefer the longest candidate; legal suffixes are retained only when
        # the user actually included them in the query.
        return max(proper_name_candidates, key=len)

    # Prefer explicit company-introducing phrases before the generic word
    # "invoice". Otherwise phrases such as "invoice dates" can be mistaken
    # for a company name when the query also asks for invoice dates.
    patterns = (
        r"\b(?:for|from|about|named|name)\s+(?:the\s+)?([A-Z][A-Za-z0-9&.' -]{1,80}?)(?:\s*[?.!,]|$)",
        r"\bcompany\s+([A-Z][A-Za-z0-9&.' -]{1,80}?)(?:\s*[?.!,]|$)",
        r"\binvoice\s+for\s+(?:the\s+)?([A-Z][A-Za-z0-9&.' -]{1,80}?)(?:\s*[?.!,]|$)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, query, flags=re.IGNORECASE):
            candidate = match.group(1).strip(" .,!?:;")
            if not _is_stopword_candidate(candidate):
                return candidate
    return None


def _collect_document_strings(value):
    """Collect searchable scalar values from nested extracted document data."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _collect_document_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _collect_document_strings(item)
    elif value is not None:
        yield str(value)


def _find_confirmed_uploaded_invoices(search_term: str) -> list[dict]:
    """Find confirmed uploaded invoices by company/vendor name or invoice number."""
    needle = _normalize_lookup_text(search_term)
    if not needle:
        return []

    db = SessionLocal()
    try:
        records = (
            db.query(DocumentRecord)
            .filter(
                DocumentRecord.status == "confirmed",
                DocumentRecord.document_type == "invoice",
            )
            .order_by(DocumentRecord.created_at.desc(), DocumentRecord.id.desc())
            .all()
        )

        matches = []
        for record in records:
            fields = record.extracted_data or {}
            searchable_values = [record.filename, *_collect_document_strings(fields)]
            needle_digits = re.sub(r"\D", "", search_term)
            text_match = any(
                needle in _normalize_lookup_text(value) for value in searchable_values
            )
            digit_match = bool(needle_digits and len(needle_digits) >= 6) and any(
                needle_digits in re.sub(r"\D", "", str(value))
                for value in searchable_values
            )
            if text_match or digit_match:
                matches.append(
                    {
                        "filename": record.filename,
                        "document_type": record.document_type,
                        "created_at": record.created_at.isoformat()
                        if record.created_at
                        else None,
                        "fields": fields,
                    }
                )
        return matches
    finally:
        db.close()


def _is_named_invoice_lookup_query(user_query: str) -> bool:
    """Identify invoice detail questions that contain a company or invoice identifier."""
    query = user_query.lower()
    asks_invoice = bool(re.search(r"\binvoice(s)?\b", query))
    asks_details = any(
        term in query
        for term in ("detail", "details", "show", "find", "look up", "check")
    )
    return (
        asks_invoice
        and asks_details
        and _extract_invoice_lookup_term(user_query) is not None
    )


def _named_invoice_response(user_query: str) -> str:
    """Return matching confirmed uploaded invoice records without customer-table lookup."""
    search_term = _extract_invoice_lookup_term(user_query)
    if not search_term:
        return "Please provide a company name or invoice number to look up."

    matches = _find_confirmed_uploaded_invoices(search_term)
    if not matches:
        return (
            f"No confirmed uploaded invoice matched '{search_term}'. "
            "This lookup searches uploaded invoice records, not the customer table."
        )

    return f"Confirmed uploaded invoice matches for '{search_term}':\n" + "\n\n".join(
        f"Filename: {record['filename']}\n"
        f"Uploaded at: {record['created_at']}\n"
        "Extracted invoice fields:\n"
        + json.dumps(record["fields"], indent=2, ensure_ascii=False, default=str)
        for record in matches
    )


def _get_latest_confirmed_invoice_details() -> dict | None:
    """Read the newest confirmed uploaded invoice directly from SQLite."""
    db = SessionLocal()
    try:
        record = (
            db.query(DocumentRecord)
            .filter(
                DocumentRecord.status == "confirmed",
                DocumentRecord.document_type == "invoice",
            )
            .order_by(DocumentRecord.created_at.desc(), DocumentRecord.id.desc())
            .first()
        )
        if record is None:
            return None

        return {
            "filename": record.filename,
            "document_type": record.document_type,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "fields": record.extracted_data or {},
        }
    finally:
        db.close()


def _latest_invoice_response() -> str:
    """Return only the latest confirmed uploaded invoice, without legacy aggregates."""
    record = _get_latest_confirmed_invoice_details()
    if record is None:
        return "No confirmed uploaded invoice was found in the financial database."

    return (
        "Latest confirmed uploaded invoice\n"
        f"Filename: {record['filename']}\n"
        f"Document type: {record['document_type']}\n"
        f"Uploaded at: {record['created_at']}\n"
        "Extracted invoice fields:\n"
        + json.dumps(record["fields"], indent=2, ensure_ascii=False, default=str)
    )


# ---------------------------------------------------------------------------
# Anti-hallucination layer
#
# Design: Qwen decides WHICH tools to call. Python executes them and does all
# arithmetic. Qwen only explains. After Qwen answers, Python checks that:
#   (a) every tool the query clearly requires was actually called, and
#   (b) every number in the answer appears in a tool result (or the user query).
# If either check fails, Qwen is asked to explain again from the tool results
# alone (no tools bound). If that is still ungrounded, Python renders the tool
# results itself, so a made-up number can never reach the user.
# ---------------------------------------------------------------------------

_TOOL_MAP = {
    tool.name: tool
    for tool in (
        saved_document_records,
        search_confirmed_documents,
        company_financial_records,
        list_financial_companies,
        search_financial_records,
        calculate_financial_metrics,
        calculate_report_receivables,
        analyze_financial_health,
        analyze_financial_trends,
        forecast_financial_baseline,
    )
}


_NUMBER_RE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def _numbers_in(text) -> set:
    """Return every numeric value in a text as Decimals (commas ignored)."""
    found = set()
    for token in _NUMBER_RE.findall(str(text)):
        try:
            found.add(Decimal(token.replace(",", "").rstrip(".")))
        except InvalidOperation:
            continue
    return found


def _ungrounded_numbers(answer: str, allowed: set) -> list:
    """Numbers in the answer that appear in neither tool results nor the query."""
    tolerance = Decimal("0.01")
    bad = []
    # Dates are labels, not financial quantities; do not flag their day/month/year
    # components as unsupported arithmetic values.
    numeric_answer = re.sub(
        r"\b\d{1,2}[\s/-]+(?:[A-Za-z]{3}|\d{1,2})[\s/-]+\d{2,4}\b",
        " ",
        str(answer),
        flags=re.IGNORECASE,
    )
    for number in _numbers_in(numeric_answer):
        is_whole = number == number.to_integral_value()
        if is_whole and number <= 10:  # list numerals, small counts
            continue
        if is_whole and 1900 <= number <= 2100:  # years
            continue
        if any(abs(number - known) <= tolerance for known in allowed):
            continue
        bad.append(number)
    return sorted(bad)


def _collect_tool_results(messages) -> list[dict]:
    """Pull (tool name, parsed data) pairs out of the agent's ToolMessages."""
    collected = []
    for message in messages or []:
        if not getattr(message, "tool_call_id", None):
            continue
        content = getattr(message, "content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, default=str)
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            data = content
        collected.append(
            {
                "tool": getattr(message, "name", None) or "unknown",
                "data": data,
                "raw_content": content,
            }
        )
    return collected


_EXPLAIN_PROMPT = """You are explaining retrieved financial source data to a user.
Rules:
- Use only source facts and amounts contained in TOOL RESULTS.
- You MAY calculate requested derived values from those source amounts.
- Show the formula and substituted source values for material calculations.
- Do not invent source inputs, reporting periods, company names, or currencies.
- If an input is missing or a denominator is zero, state that the result is unavailable.
- Keep every amount and derived result associated with the correct company and period.
- Clearly distinguish reported values from your own calculations.
- Never relabel a net operating difference as audited net profit.
- Do not claim a result is typical, healthy, excessive, strong, weak, efficient, or
  better/worse than peers unless TOOL RESULTS contain explicit evidence supporting
  that comparison or judgment.
- Do not invent industry averages, industry standards, competitor results, or peer
  benchmarks. If the user asks for such an assessment and no benchmark is present,
  state that the available figures alone cannot establish it.
- Preserve all source figures and valid calculations even when removing an
  unsupported conclusion.
- Include every requested entity and metric; omit unrelated information.
- Present multiple-company comparisons in a concise table.
- No greetings or offers of further help."""


def _render_multi_company_comparison(tool_results: list[dict]) -> str | None:
    """Render multi-company financial records from deterministic calculations."""
    record_payload = next(
        (
            item.get("data")
            for item in tool_results
            if item.get("tool") == "company_financial_records"
        ),
        None,
    )
    if not isinstance(record_payload, dict):
        return None

    entries = record_payload.get("results")
    if not isinstance(entries, list):
        entries = [record_payload]
    entries = [
        item for item in entries if isinstance(item, dict) and item.get("matches")
    ]
    if len(entries) < 2:
        return None

    company_names = [
        str(item.get("company") or item["matches"][0].get("company_name") or "").strip()
        for item in entries
    ]
    company_names = [name for name in company_names if name]
    if len(company_names) < 2:
        return None

    raw_metrics = calculate_financial_metrics.invoke(
        {
            "company_names": ",".join(company_names),
            "revenue_change_percent": "0",
            "expense_change_percent": "0",
        }
    )
    try:
        metrics_payload = json.loads(raw_metrics)
    except (TypeError, json.JSONDecodeError):
        _finance_debug(
            "MULTI_COMPANY_COMPARISON_FAILED",
            reason="Invalid calculation-tool response",
        )
        return None

    calculated = metrics_payload.get("results")
    if not isinstance(calculated, list) or len(calculated) < 2:
        _finance_debug(
            "MULTI_COMPANY_COMPARISON_FAILED",
            reason="Calculation tool did not return all company results",
            returned_count=len(calculated) if isinstance(calculated, list) else 0,
            requested_count=len(company_names),
        )
        return None

    lines = [
        "**Financial comparison**",
        "",
        "| Company | Reporting period | Revenue | Operating expenses | Net operating difference | Derived operating margin |",
        "|---|---|---:|---:|---:|---:|",
    ]
    valid = []
    for item in calculated:
        if not isinstance(item, dict):
            continue
        if item.get("error"):
            lines.append(
                f"| {item.get('company', 'Company')} | — | Unavailable | Unavailable | Unavailable | Unavailable |"
            )
            continue
        currency = item.get("currency") or "INR"
        revenue = item.get("baseline_revenue")
        expenses = item.get("baseline_operating_expenses")
        difference = item.get("baseline_net_operating_difference")
        margin = item.get("baseline_operating_margin_percent")
        lines.append(
            f"| {item.get('company', 'Company')} | {item.get('reporting_period') or 'Not reported'} "
            f"| {_money(revenue, currency) if revenue is not None else 'Unavailable'} "
            f"| {_money(expenses, currency) if expenses is not None else 'Unavailable'} "
            f"| {_money(difference, currency) if difference is not None else 'Unavailable'} "
            f"| {margin + '%' if margin is not None else 'Unavailable'} |"
        )
        if difference is not None:
            valid.append(item)

    if not valid:
        return None

    revenue_values = [
        item for item in valid if item.get("baseline_revenue") is not None
    ]
    difference_values = [
        item
        for item in valid
        if item.get("baseline_net_operating_difference") is not None
    ]
    margin_values = [
        item
        for item in valid
        if item.get("baseline_operating_margin_percent") is not None
    ]

    def highest(items, field):
        return (
            max(
                items,
                key=lambda item: Decimal(str(item[field]).replace(",", "")),
            )
            if items
            else None
        )

    revenue_leader = highest(revenue_values, "baseline_revenue")
    difference_leader = highest(difference_values, "baseline_net_operating_difference")
    margin_leader = highest(margin_values, "baseline_operating_margin_percent")

    lines.extend(["", "**Comparison results**"])
    if revenue_leader:
        lines.append(f"- Highest revenue: **{revenue_leader['company']}**.")
    if difference_leader:
        lines.append(
            f"- Highest net operating difference: **{difference_leader['company']}** "
            f"({_money(difference_leader['baseline_net_operating_difference'], difference_leader.get('currency') or 'INR')})."
        )
    if margin_leader:
        lines.append(
            f"- Highest derived operating margin: **{margin_leader['company']}** "
            f"({margin_leader['baseline_operating_margin_percent']}%)."
        )
    lines.append(
        "- Net operating difference is revenue minus operating expenses; it is a derived operating-profit measure, not audited net profit. "
        "Operating margin uses that derived measure when the report does not provide operating income."
    )
    _finance_debug(
        "MULTI_COMPANY_COMPARISON_RENDERED",
        company_count=len(calculated),
        revenue_leader=revenue_leader.get("company") if revenue_leader else None,
        net_operating_difference_leader=difference_leader.get("company")
        if difference_leader
        else None,
        operating_margin_leader=margin_leader.get("company") if margin_leader else None,
    )
    return "\\n".join(lines)


def _explain_from_results(
    user_query: str, tool_results: list[dict], scope_note: str = ""
) -> str:
    """Ask Qwen to explain verified results with no tools available."""
    payload = json.dumps(tool_results, indent=2, ensure_ascii=False, default=str)
    note = f"SCOPE: {scope_note}\n\n" if scope_note else ""
    response = llm.invoke(
        [
            SystemMessage(content=_EXPLAIN_PROMPT),
            HumanMessage(
                content=f"{note}USER QUESTION:\n{user_query}\n\nTOOL RESULTS:\n{payload}"
            ),
        ]
    )
    return _strip_think(response.content)


def _money(value, currency: str = "INR") -> str:
    symbol = "₹" if currency == "INR" else f"{currency} "
    return f"{symbol}{_format_financial_amount(value)}"


def _format_report_expense_breakdown(extracted_text: str) -> list[tuple[str, str]]:
    """Read expense category/amount pairs from same-line or adjacent-line text."""
    if not extracted_text:
        return []

    lines = [line.strip() for line in extracted_text.splitlines() if line.strip()]
    in_expense_section = False
    pending_label = None
    rows = []

    for line in lines:
        lower = line.lower()
        if re.search(r"\b(?:operating\s+)?expense\s+breakdown\b", lower):
            in_expense_section = True
            pending_label = None
            continue
        if not in_expense_section:
            continue
        if re.match(r"^\d+\.\s+", line) or re.search(
            r"\btotal\s+operating\s+expenses\b", lower
        ):
            break
        if lower in {"expense category", "amount", "amount (inr)"}:
            continue

        amount_match = re.fullmatch(r"[■₹\s]*([\d,]+(?:\.\d{1,2})?)[■₹\s]*", line)
        if amount_match and pending_label:
            rows.append((pending_label, amount_match.group(1)))
            pending_label = None
            continue

        same_line = re.match(r"^(.*?)\s+[■₹]?\s*([\d,]+(?:\.\d{1,2})?)$", line)
        if same_line:
            label = same_line.group(1).strip(" :-|")
            if label and label.lower() not in {
                "expense category",
                "amount (inr)",
                "amount",
            }:
                rows.append((label, same_line.group(2)))
            pending_label = None
            continue

        # A new category label is paired with the following amount-only line.
        pending_label = line.strip(" :-|")

    return rows


def _plain_render(tool_results: list[dict]) -> str:
    """Render retrieved finance data as a clean, consistently structured Markdown report."""
    reports = {}
    calculations = []
    document_records = []
    receivable_results = []
    rankings = []
    health_results = []
    trend_results = []
    forecast_results = []

    metric_labels = {
        "revenue": "Revenue",
        "operating_expenses": "Total expenses",
        "net_operating_difference": "Net financial difference",
        "gross_profit": "Gross profit",
        "operating_income": "Operating income",
        "net_income": "Net income",
        "total_assets": "Total assets",
        "total_liabilities": "Total liabilities",
        "equity": "Equity",
        "cost_of_goods_sold": "Cost of goods sold",
    }

    def add_report(report: dict):
        company = (
            report.get("company_name")
            or report.get("company")
            or "Company not specified"
        )
        period = report.get("reporting_period") or "Period not specified"
        identity = (str(company).casefold(), str(period).casefold())
        current = reports.setdefault(
            identity,
            {
                "company": company,
                "period": period,
                "currency": report.get("currency") or "INR",
                "figures": {},
                "breakdown": [],
            },
        )
        figures = report.get("figures") or report.get("structured_fields") or {}
        metadata_keys = {"company_name", "report_title", "reporting_period", "currency"}
        for key, value in figures.items():
            if key in metadata_keys or key == "net_operating_difference_calculated":
                continue
            if value is not None and _to_decimal_amount(value) is not None:
                current["figures"].setdefault(key, _format_financial_amount(value))

        breakdown = _format_report_expense_breakdown(
            report.get("extracted_report_text") or ""
        )
        if breakdown and not current["breakdown"]:
            current["breakdown"] = breakdown

    for item in tool_results:
        name, data = item.get("tool", "result"), item.get("data")
        if not isinstance(data, dict):
            continue
        if name == "company_financial_records":
            for report in data.get("matches") or []:
                add_report(report)
            for company_result in data.get("results") or []:
                for report in company_result.get("matches") or []:
                    add_report(report)
        elif name == "search_financial_records":
            for report in data.get("reports") or []:
                add_report(report)
        elif name == "calculate_financial_metrics":
            calculations.extend(data.get("results") or [])
            rankings.extend(data.get("expense_ratio_ranking") or [])
        elif name == "calculate_report_receivables":
            receivable_results.extend(data.get("results") or [])
        elif name == "analyze_financial_health":
            health_results.extend(data.get("results") or [data])
        elif name == "analyze_financial_trends":
            trend_results.extend(data.get("results") or [data])
        elif name == "forecast_financial_baseline":
            forecast_results.extend(data.get("results") or [data])
        elif name == "saved_document_records":
            records = data if isinstance(data, list) else data.get("records", [])
            document_records.extend(records or [])

    lines = ["# Financial results"]
    if reports:
        ordered = list(reports.values())
        metric_keys = []
        for report in ordered:
            for key in report["figures"]:
                if key not in metric_keys:
                    metric_keys.append(key)

        # Keep the most commonly requested headline metrics in a predictable order.
        preferred_order = [
            "revenue",
            "operating_expenses",
            "net_operating_difference",
            "gross_profit",
            "operating_income",
            "net_income",
            "cost_of_goods_sold",
            "total_assets",
            "total_liabilities",
            "equity",
        ]
        metric_keys.sort(
            key=lambda key: (
                preferred_order.index(key)
                if key in preferred_order
                else len(preferred_order),
                key,
            )
        )

        headers = ["Company", "Reporting period"]
        headers.extend(
            metric_labels.get(key, key.replace("_", " ").strip().capitalize())
            for key in metric_keys
        )
        lines.extend(
            [
                "",
                "## Company comparison",
                "",
                "| " + " | ".join(headers) + " |",
                "| " + " | ".join(["---"] * len(headers)) + " |",
            ]
        )
        for report in ordered:
            row = [str(report["company"]), str(report["period"])]
            for key in metric_keys:
                value = report["figures"].get(key)
                row.append(
                    _money(value, report["currency"]) if value is not None else "—"
                )
            lines.append("| " + " | ".join(row) + " |")

        breakdown_reports = [report for report in ordered if report["breakdown"]]
        if breakdown_reports:
            lines.extend(["", "## Expense breakdown"])
            for report in breakdown_reports:
                lines.extend(
                    [
                        "",
                        f"### {report['company']} — {report['period']}",
                        "",
                        "| Expense category | Amount |",
                        "|:--|--:|",
                    ]
                )
                for label, amount in report["breakdown"]:
                    lines.append(f"| {label} | {_money(amount, report['currency'])} |")

    if rankings:
        metric = rankings[0].get("ranked_metric", "metric")
        lines.extend(
            [
                "",
                f"## Ranking by {metric.replace('_', ' ')}",
                "",
                "| Rank | Company | Reporting period | Value |",
                "|---:|---|---|---:|",
            ]
        )
        for item in rankings:
            value = item.get("ranked_value")
            currency = item.get("currency") or "INR"
            rendered = (
                f"{value}%" if metric == "expense_ratio" else _money(value, currency)
            )
            lines.append(
                f"| {item.get('rank')} | {item.get('company')} | {item.get('reporting_period') or '—'} | {rendered} |"
            )

    if receivable_results:
        lines.extend(["", "## Accounts receivable"])
        for item in receivable_results:
            lines.extend(
                [
                    "",
                    f"### {item.get('company', 'Company')} — {item.get('reporting_period') or 'Period not specified'}",
                ]
            )
            if item.get("error"):
                lines.append(item["error"])
                continue
            currency = item.get("currency") or "INR"
            lines.append(
                f"- **Pending total:** {_money(item.get('pending_total', '0'), currency)}"
            )
            lines.append(
                f"- **Overdue total:** {_money(item.get('overdue_total', '0'), currency)}"
            )
            lines.append(
                f"- **Paid total:** {_money(item.get('paid_total', '0'), currency)}"
            )
            lines.append(
                f"- **Unknown-status total:** {_money(item.get('unknown_status_total', '0'), currency)}"
            )
            lines.append(
                f"- **Outstanding total (reported Pending + Overdue):** {_money(item.get('outstanding_total', '0'), currency)}"
            )
            if item.get("invoice_rows"):
                lines.extend(
                    [
                        "",
                        "| Invoice | Customer | Amount | Invoice date | Due date | Payment date | Reported status |",
                        "|---|---|---:|---|---|---|---|",
                    ]
                )
                for row in item["invoice_rows"]:
                    lines.append(
                        f"| {row.get('invoice_id')} | {row.get('customer')} | {_money(row.get('amount', '0'), currency)} | {row.get('invoice_date') or 'Not reported'} | {row.get('due_date') or 'Not reported'} | {row.get('payment_date') or 'Not reported'} | {row.get('status') or 'Unknown'} |"
                    )

    if calculations:
        lines.extend(["", "## Calculated results"])
        for result in calculations:
            company = result.get("company", "Company")
            period = result.get("reporting_period")
            lines.extend(["", f"### {company}" + (f" — {period}" if period else "")])
            for key, value in result.items():
                if (
                    key in {"company", "reporting_period", "currency", "error"}
                    or value is None
                ):
                    continue
                label = key.replace("_", " ").strip().capitalize()
                if any(
                    token in key
                    for token in ("revenue", "expenses", "difference", "target")
                ):
                    try:
                        value = _money(value, result.get("currency") or "INR")
                    except (InvalidOperation, ValueError):
                        pass
                lines.append(f"- **{label}:** {value}")
            if result.get("error"):
                lines.append(f"- {result['error']}")

    if health_results:
        lines.extend(["", "## Financial health ratios"])
        for item in health_results:
            lines.extend(
                [
                    "",
                    f"### {item.get('company', 'Company')} — {item.get('reporting_period') or 'Period not specified'}",
                ]
            )
            if item.get("error"):
                lines.append(item["error"])
                continue
            lines.extend(["", "| Ratio | Result |", "|---|---:|"])
            for key, value in (item.get("ratios") or {}).items():
                label = key.replace("_", " ").capitalize()
                lines.append(
                    f"| {label} | {value if value is not None else 'Unavailable'} |"
                )
            if item.get("note"):
                lines.extend(["", item["note"]])

    if trend_results:
        lines.extend(["", "## Financial trends"])
        for item in trend_results:
            lines.extend(["", f"### {item.get('company', 'Company')}"])
            if item.get("error"):
                lines.append(item["error"])
                continue
            lines.extend(
                [
                    "",
                    "| Reporting period | Metric | Value | Change |",
                    "|---|---|---:|---:|",
                ]
            )
            for period in item.get("timeline") or []:
                for metric, value in (period.get("figures") or {}).items():
                    change = (period.get("period_changes_percent") or {}).get(
                        metric, "—"
                    )
                    lines.append(
                        f"| {period.get('reporting_period')} | {metric.replace('_', ' ').capitalize()} | {value} | {change}{'%' if change != '—' else ''} |"
                    )
            if item.get("movement_flags"):
                lines.extend(["", "**Movements to review:**"])
                for flag in item["movement_flags"]:
                    lines.append(
                        f"- {flag.get('period')}: {flag.get('metric')} changed by {flag.get('change_percent')}% (review threshold {flag.get('threshold_percent')}%)."
                    )
            if item.get("note"):
                lines.extend(["", item["note"]])

    if forecast_results:
        lines.extend(["", "## Financial baseline projection"])
        for item in forecast_results:
            lines.extend(["", f"### {item.get('company', 'Company')}"])
            if item.get("error"):
                lines.append(item["error"])
                continue
            currency = item.get("currency") or "INR"
            for label, key in (
                ("Revenue", "revenue_projection"),
                ("Operating expenses", "operating_expense_projection"),
            ):
                projection = item.get(key)
                if projection:
                    lines.append(
                        f"- **{label}:** {_money(projection['projected_value'], currency)}"
                    )
                else:
                    lines.append(f"- **{label}:** Unavailable")
            if item.get("projected_net_operating_difference") is not None:
                lines.append(
                    f"- **Projected net operating difference:** {_money(item['projected_net_operating_difference'], currency)}"
                )
            for limitation in item.get("limitations") or []:
                lines.append(f"- Limitation: {limitation}")

    if document_records:
        lines.extend(["", "## Retrieved documents"])
        for record in document_records:
            lines.extend(
                [
                    "",
                    f"### {record.get('filename', 'Document')}",
                    f"**Document type:** {record.get('document_type', 'unspecified')}",
                ]
            )
            for key, value in (record.get("fields") or {}).items():
                if value is None or key == "sections":
                    continue
                rendered = (
                    json.dumps(value, ensure_ascii=False, default=str)
                    if isinstance(value, (dict, list))
                    else str(value)
                )
                lines.append(f"- **{key.replace('_', ' ').capitalize()}:** {rendered}")

    if len(lines) == 1:
        return "No presentable financial results were returned by the tools."
    return "\n".join(lines)


# Filler sentences a small model likes to add that no tool result supports.
_UNSUPPORTED_CLAIM_RE = re.compile(
    r"(?i)(latest available|latest data|up[- ]to[- ]date|derived directly|"
    r"provided tools|all figures (?:are|were)|based on the (?:latest|available)|"
    r"let me know if)"
)


def _strip_unsupported_claims(answer: str) -> str:
    """Drop filler sentences such as 'All figures are derived from the tools'."""
    cleaned_lines = []
    for line in answer.splitlines():
        sentences = re.split(r"(?<=[.!])\s+", line)
        kept = [s for s in sentences if not _UNSUPPORTED_CLAIM_RE.search(s)]
        cleaned_lines.append(" ".join(kept))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned_lines)).strip()


# Claims that require explicit benchmark evidence in retrieved source data.
_INDUSTRY_COMPARISON_RE = re.compile(
    r"(?i)\b(?:industry|sector)\s+(?:average|benchmark|standard|norm|range|"
    r"median|typical)\b|\btypical\s+range\s+for\b|"
    r"\b(?:compared\s+with|compared\s+to|better\s+than|worse\s+than)\s+"
    r"(?:its\s+)?(?:industry|sector|competitors?|peers?)\b|"
    r"\b(?:competitors?|peer\s+companies|industry\s+peers)\b"
)
_QUALITATIVE_JUDGMENT_RE = re.compile(
    r"(?i)\b(?:healthy|unhealthy|strong|weak|good|poor|efficient|inefficient|"
    r"excessive|overspending|underperforming|overperforming)\b|"
    r"\btoo\s+(?:high|low|much|little)\b"
)
_JUDGMENT_UNCERTAINTY_RE = re.compile(
    r"(?i)\b(?:cannot|can't|unable\s+to|not\s+enough|insufficient|"
    r"without\s+(?:an?\s+)?(?:industry\s+)?(?:benchmark|comparison)|"
    r"no\s+(?:industry\s+)?(?:benchmark|comparison)|"
    r"does\s+not\s+establish|cannot\s+determine|cannot\s+conclude)\b"
)
_BENCHMARK_EVIDENCE_RE = re.compile(
    r"(?i)\b(?:industry\s+(?:average|benchmark|standard|norm|range|median)|"
    r"sector\s+(?:average|benchmark|standard|range|median)|"
    r"peer\s+(?:average|benchmark|company|companies)|competitor\s+"
    r"(?:average|benchmark|data)|benchmark\s+data)\b"
)


def _unsupported_analysis_claims(answer: str, tool_results: list[dict]) -> list[str]:
    """Identify benchmark comparisons and judgments unsupported by retrieved data."""
    source_text = json.dumps(tool_results, ensure_ascii=False, default=str)
    benchmark_available = bool(_BENCHMARK_EVIDENCE_RE.search(source_text))
    violations = []
    for sentence in re.split(r"(?<=[.!?])\s+", str(answer or "")):
        if not sentence.strip():
            continue
        if not benchmark_available and _INDUSTRY_COMPARISON_RE.search(sentence):
            violations.append("unsupported industry/competitor comparison")
            continue
        if (
            not benchmark_available
            and _QUALITATIVE_JUDGMENT_RE.search(sentence)
            and not _JUDGMENT_UNCERTAINTY_RE.search(sentence)
        ):
            violations.append("unsupported qualitative judgment")
    return list(dict.fromkeys(violations))


def _remove_unsupported_analysis_claims(answer: str, tool_results: list[dict]) -> str:
    """Remove only unsupported analytical sentences; retain figures/calculations."""
    source_text = json.dumps(tool_results, ensure_ascii=False, default=str)
    benchmark_available = bool(_BENCHMARK_EVIDENCE_RE.search(source_text))
    cleaned_lines = []
    for line in str(answer or "").splitlines():
        kept = []
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            if not sentence.strip():
                continue
            unsupported_benchmark = not benchmark_available and bool(
                _INDUSTRY_COMPARISON_RE.search(sentence)
            )
            unsupported_judgment = (
                not benchmark_available
                and bool(_QUALITATIVE_JUDGMENT_RE.search(sentence))
                and not bool(_JUDGMENT_UNCERTAINTY_RE.search(sentence))
            )
            if not (unsupported_benchmark or unsupported_judgment):
                kept.append(sentence)
        cleaned_lines.append(" ".join(kept))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned_lines)).strip()


def _verify_and_repair(
    user_query: str, answer: str, tool_results: list[dict], scope_note: str = ""
) -> str:
    """Reject unsupported comparisons while preserving source figures and arithmetic."""
    violations = _unsupported_analysis_claims(answer, tool_results)
    _finance_debug(
        "ANSWER_CHECK",
        answer_empty=not answer.strip(),
        collected_tool_names=[item.get("tool") for item in tool_results],
        violations=violations,
    )

    if answer.strip() and not violations:
        return answer

    if tool_results:
        retry = _strip_unsupported_claims(
            _explain_from_results(user_query, tool_results, scope_note)
        )
        retry_violations = _unsupported_analysis_claims(retry, tool_results)
        _finance_debug(
            "ANSWER_RETRY_CHECK",
            answer_empty=not retry.strip(),
            violations=retry_violations,
        )
        if retry.strip():
            if retry_violations:
                _finance_debug(
                    "ANSWER_UNSUPPORTED_CLAIMS_REMOVED",
                    violations=retry_violations,
                )
                retry = _remove_unsupported_analysis_claims(retry, tool_results)
            if retry.strip():
                return retry

        if answer.strip():
            cleaned = _remove_unsupported_analysis_claims(answer, tool_results)
            if cleaned:
                return cleaned
        return "I retrieved financial records, but could not produce a reliable answer."

    if answer.strip():
        return _remove_unsupported_analysis_claims(answer, tool_results)

    return (
        "I could not retrieve confirmed financial records for this request, "
        "so I cannot provide a grounded answer."
    )


def _is_report_receivables_query(user_query: str) -> bool:
    """Identify named-company requests for receivables/invoice status from reports."""
    query = _original_user_utterance(user_query).lower()
    asks_receivables = bool(
        re.search(
            r"\b(receivables?|outstanding\s+invoices?|paid\s+invoices?|overdue\s+invoices?)\b",
            query,
        )
    )
    asks_invoice_status = bool(
        re.search(r"\b(invoices?|payment\s+status|paid|overdue|pending)\b", query)
    )
    return asks_receivables or asks_invoice_status


def _render_deterministic_receivables(company_name: str, raw_result: str) -> str:
    """Render Python receivables output without asking Qwen to choose tools or invent dates."""
    try:
        payload = json.loads(raw_result)
    except (TypeError, json.JSONDecodeError):
        return "The receivables calculation tool returned an unreadable result."
    results = payload.get("results") or []
    if not results:
        return f"No confirmed financial report was retrieved for {company_name}. This does not establish that the company has no outstanding invoices."

    item = results[0]
    if item.get("error"):
        return f"{item.get('error')} Company requested: {company_name}. No conclusion about the absence of receivables can be made from this result."

    lines = [
        f"## Report-listed receivables — {item.get('company') or company_name}",
        f"**Reporting period:** {item.get('reporting_period') or 'Not reported'}",
        f"**Source currency:** {item.get('currency') or 'Not reported'}",
        "",
        f"- **Pending total (reported):** {_money(item.get('pending_total', '0'), item.get('currency') or 'INR')}",
        f"- **Overdue total (reported):** {_money(item.get('overdue_total', '0'), item.get('currency') or 'INR')}",
        f"- **Paid total (reported):** {_money(item.get('paid_total', '0'), item.get('currency') or 'INR')}",
        f"- **Unknown-status total:** {_money(item.get('unknown_status_total', '0'), item.get('currency') or 'INR')}",
        f"- **Outstanding total (reported Pending + Overdue):** {_money(item.get('outstanding_total', '0'), item.get('currency') or 'INR')}",
        "",
    ]
    rows = item.get("invoice_rows") or []
    if rows:
        lines.extend(
            [
                "| Invoice | Customer | Amount | Invoice date | Due date | Payment date | Status |",
                "|---|---|---:|---|---|---|---|",
            ]
        )
        for row in rows:
            lines.append(
                f"| {row.get('invoice_id') or 'Not reported'} | {row.get('customer') or 'Not reported'} | "
                f"{_money(row.get('amount', '0'), item.get('currency') or 'INR')} | "
                f"{row.get('invoice_date') or 'Not reported'} | {row.get('due_date') or 'Not reported'} | "
                f"{row.get('payment_date') or 'Not reported'} | {row.get('status') or 'Unknown'} |"
            )
    else:
        lines.append(
            "No invoice-level rows could be extracted from the matched report. "
            "This is not evidence that there are no outstanding invoices."
        )
    lines.extend(
        [
            "",
            "Dates and statuses above are shown only when present in the uploaded report. "
            "Payment dates are not inferred from payment terms, and invoices are not marked overdue from the current date.",
        ]
    )
    return "\n".join(lines)


def _is_financial_scenario_query(user_query: str) -> bool:
    """Identify quantitative what-if questions that require deterministic scenario calculations."""
    query = str(user_query or "").lower()
    has_percentage = bool(re.search(r"\b\d+(?:\.\d+)?\s*%", query))
    has_financial_metric = bool(
        re.search(
            r"\b(revenue|sales|income|operating\s+expenses?|expenses?|costs?)\b", query
        )
    )
    has_scenario_intent = bool(
        re.search(
            r"\b(if|assuming|assume|scenario|what[\s-]?if|increase|increased|"
            r"decrease|decreased|rise|rises|reduce|reduced|unchanged|stays?|remain|"
            r"remains|new|projected|projection)\b",
            query,
        )
    )
    return has_percentage and has_financial_metric and has_scenario_intent


def _company_tokens(value: str) -> set[str]:
    """Normalize company-name tokens and remove legal suffixes."""
    tokens = re.findall(r"[a-z0-9]+", str(value or "").lower())
    normalized = []
    for token in tokens:
        if len(token) > 4 and token.endswith("ies"):
            token = token[:-3] + "y"
        elif len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        normalized.append(token)
    legal_suffixes = {
        "private",
        "pvt",
        "limited",
        "ltd",
        "llp",
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "company",
        "co",
    }
    return {token for token in normalized if token not in legal_suffixes}


_SCENARIO_QUERY_STOPWORDS = {
    "if",
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "by",
    "of",
    "what",
    "will",
    "would",
    "its",
    "their",
    "assuming",
    "assume",
    "stays",
    "stay",
    "stayed",
    "unchanged",
    "remain",
    "remains",
    "remaining",
    "same",
    "new",
    "operating",
    "expense",
    "expenses",
    "cost",
    "costs",
    "revenue",
    "sales",
    "income",
    "increase",
    "increases",
    "increased",
    "decrease",
    "decreases",
    "decreased",
    "rise",
    "rises",
    "reduced",
    "reduce",
    "reduces",
    "by",
    "what",
    "then",
    "and",
    "or",
    "for",
    "from",
    "company",
    "business",
    "calculate",
    "calculate",
    "result",
    "difference",
    "net",
    "financial",
    "scenario",
    "projected",
    "projection",
    "percent",
    "percentage",
}


def _resolve_report_company_name(user_query: str) -> str | None:
    """Resolve a company mention against confirmed report identities, tolerating legal suffixes and inflection."""
    query_tokens = {
        token
        for token in _company_tokens(user_query)
        if token not in _SCENARIO_QUERY_STOPWORDS
    }
    if not query_tokens:
        return None

    db = SessionLocal()
    try:
        records = (
            db.query(DocumentRecord)
            .filter(
                DocumentRecord.status == "confirmed",
                DocumentRecord.document_type == "financial_report",
            )
            .order_by(DocumentRecord.created_at.desc(), DocumentRecord.id.desc())
            .all()
        )
        ranked = []
        seen = set()
        for record in records:
            company = str(
                (record.extracted_data or {}).get("company_name") or ""
            ).strip()
            key = _normalize_lookup_text(company)
            if not company or not key or key in seen:
                continue
            seen.add(key)
            company_tokens = _company_tokens(company)
            overlap = query_tokens & company_tokens
            if not overlap:
                continue
            # Require at least two identifying tokens for multiword names. A
            # single-token match is accepted only for a genuinely one-token name.
            required = 1 if len(company_tokens) == 1 else 2
            if len(overlap) >= required:
                ranked.append((len(overlap), len(company_tokens), company))
        if not ranked:
            return None
        ranked.sort(key=lambda item: (item[0], -item[1]), reverse=True)
        best = ranked[0]
        tied = [item for item in ranked if item[:2] == best[:2]]
        if len(tied) > 1:
            return None
        return best[2]
    finally:
        db.close()


def _parse_scenario_changes(user_query: str) -> tuple[Decimal, Decimal] | None:
    """Map each percentage to a metric and direction within its own clause.

    Clause-local matching avoids assigning an expense change to a nearby
    unchanged-revenue phrase (or vice versa). Multiple changes must be stated
    clearly enough to map one percentage, metric, and direction per clause.
    """
    query = str(user_query or "").strip()
    if not query:
        return None

    # Split coordinated changes into separate clauses. A clause with no
    # percentage (for example, 'assuming revenue stays unchanged') does not
    # create a second change; its metric therefore retains the default 0%.
    clause_pattern = r"[,;.!?]+|\b(?:and|while|whereas|but)\b"
    clauses = [
        part.strip()
        for part in re.split(clause_pattern, query, flags=re.I)
        if part.strip()
    ]
    changes = {"revenue": Decimal("0"), "expenses": Decimal("0")}
    assigned = set()
    percentage_count = 0

    metric_patterns = (
        ("revenue", r"\b(?:revenue|sales|income)\b"),
        ("expenses", r"\b(?:operating\s+expenses?|expenses?|costs?)\b"),
    )
    direction_patterns = (
        (
            Decimal("-1"),
            r"\b(?:decrease(?:d|s)?|reduction|reduce(?:d|s)?|drop(?:ped|s)?|fall|falls|fell|down|lower|cut|cuts)\b",
        ),
        (
            Decimal("1"),
            r"\b(?:increase(?:d|s)?|rise|rises|rose|grow|grows|grew|growth|up|higher)\b",
        ),
    )

    for clause in clauses:
        percentages = list(re.finditer(r"(?<![\w.])(\d+(?:\.\d+)?)\s*%", clause))
        if not percentages:
            continue
        # More than one percentage in a single clause is not safely
        # attributable without a separate metric/direction clause.
        if len(percentages) != 1:
            return None

        metrics = [
            metric
            for metric, pattern in metric_patterns
            if re.search(pattern, clause, re.I)
        ]
        directions = [
            sign
            for sign, pattern in direction_patterns
            if re.search(pattern, clause, re.I)
        ]
        if len(metrics) != 1 or len(directions) != 1:
            return None

        metric = metrics[0]
        if metric in assigned:
            return None
        changes[metric] = Decimal(percentages[0].group(1)) * directions[0]
        assigned.add(metric)
        percentage_count += 1

    if percentage_count == 0:
        return None
    return changes["revenue"], changes["expenses"]


def _render_deterministic_scenario(raw_result: str) -> str:
    """Render scenario calculations directly from Decimal-tool output."""
    try:
        payload = json.loads(raw_result)
    except (TypeError, json.JSONDecodeError):
        return "The financial scenario calculation returned an unreadable result."

    results = payload.get("results") or []
    if not results:
        return "No financial scenario result was returned."
    item = results[0]
    if item.get("error"):
        return (
            f"{item.get('error')} "
            "The scenario cannot be calculated without the required confirmed inputs."
        )

    currency = item.get("currency") or "INR"
    symbol = "₹" if currency == "INR" else f"{currency} "
    revenue_change = Decimal(str(item.get("revenue_change_percent") or "0"))
    expense_change = Decimal(str(item.get("expense_change_percent") or "0"))
    lines = [
        f"## Financial scenario — {item.get('company') or 'Company'}",
        f"**Reporting period:** {item.get('reporting_period') or 'Not reported'}",
        "",
        "**Confirmed baseline figures**",
        f"- Revenue: {symbol}{item['baseline_revenue']}",
        f"- Operating expenses: {symbol}{item['baseline_operating_expenses']}",
        f"- Net operating difference: {symbol}{item['baseline_net_operating_difference']}",
        "",
        "**Scenario results**",
    ]
    if revenue_change != 0:
        lines.append(
            f"- Revenue change: {revenue_change:+}% → {symbol}{item['scenario_revenue']}"
        )
    else:
        lines.append(f"- Revenue (unchanged): {symbol}{item['scenario_revenue']}")
    if expense_change != 0:
        lines.append(
            f"- Operating expenses change: {expense_change:+}% → {symbol}{item['scenario_operating_expenses']}"
        )
    else:
        lines.append(
            f"- Operating expenses (unchanged): {symbol}{item['scenario_operating_expenses']}"
        )
    lines.append(
        f"- **New net operating difference: {symbol}{item['scenario_net_operating_difference']}**"
    )
    lines.extend(
        [
            "",
            "**Calculation basis**",
            f"- Scenario revenue = {symbol}{item['baseline_revenue']} × (1 + {revenue_change}% / 100) = {symbol}{item['scenario_revenue']}",
            f"- Scenario operating expenses = {symbol}{item['baseline_operating_expenses']} × (1 + {expense_change}% / 100) = {symbol}{item['scenario_operating_expenses']}",
            f"- Net operating difference = scenario revenue − scenario operating expenses = {symbol}{item['scenario_net_operating_difference']}",
            "",
            "Baseline figures come from the confirmed report; scenario figures are calculated projections based on the stated percentage changes.",
        ]
    )
    return "\n".join(lines)


def finance_node_result(user_query: str):
    """Run Finance Agent with deterministic routing for quantitative scenarios and report receivables."""
    original_query = _original_user_utterance(user_query)

    # Quantitative what-if questions bypass free-form model arithmetic. Resolve
    # the company against confirmed report identities and let the Decimal tool
    # calculate every baseline and scenario value.
    if _is_financial_scenario_query(original_query):
        company_name = _resolve_report_company_name(original_query)
        changes = _parse_scenario_changes(original_query)
        if not company_name:
            return (
                "I could not confidently match the company in your scenario request "
                "to a confirmed financial report. Please use the company name shown "
                "in the uploaded report."
            )
        if changes is None:
            return (
                "I could not safely associate each percentage change with revenue "
                "or operating expenses. Please clarify which financial metric each "
                "percentage changes and whether it increases or decreases."
            )

        revenue_change, expense_change = changes
        _finance_debug(
            "DETERMINISTIC_SCENARIO_ROUTE",
            company_name=company_name,
            revenue_change_percent=str(revenue_change),
            expense_change_percent=str(expense_change),
            user_query=original_query,
        )
        raw_result = calculate_financial_metrics.invoke(
            {
                "company_names": company_name,
                "revenue_change_percent": str(revenue_change),
                "expense_change_percent": str(expense_change),
            }
        )
        _finance_debug(
            "DETERMINISTIC_SCENARIO_RESULT",
            company_name=company_name,
            result=raw_result,
        )
        return _render_deterministic_scenario(raw_result)

    if _is_report_receivables_query(original_query):
        company_name = _extract_invoice_lookup_term(original_query)
        if company_name:
            _finance_debug(
                "DETERMINISTIC_RECEIVABLES_ROUTE",
                company_name=company_name,
                user_query=original_query,
            )
            raw_result = calculate_report_receivables.invoke(
                {"company_names": company_name}
            )
            _finance_debug(
                "DETERMINISTIC_RECEIVABLES_RESULT",
                company_name=company_name,
                result=raw_result,
            )
            return _render_deterministic_receivables(company_name, raw_result)

    response = finance_agent.invoke({"messages": [HumanMessage(content=user_query)]})
    messages = response.get("messages", [])
    _log_agent_tool_trace(messages)

    answer = _strip_think(messages[-1].content) if messages else ""
    tool_results = _collect_tool_results(messages)
    deterministic_comparison = _render_multi_company_comparison(tool_results)
    if deterministic_comparison:
        return deterministic_comparison
    answer = _strip_unsupported_claims(answer)
    verified = _verify_and_repair(user_query, answer, tool_results)
    return _strip_unsupported_claims(
        _remove_unsupported_analysis_claims(verified, tool_results)
    )


# One Finance Agent. All financial tools read confirmed records from
# DocumentRecord; the source document type does not create a separate company
# or "external report" path.
finance_agent = create_react_agent(
    model=llm,
    # Retrieval tools establish the source data; deterministic Python tools
    # perform all financial calculations.
    tools=[
        saved_document_records,
        search_confirmed_documents,
        company_financial_records,
        list_financial_companies,
        search_financial_records,
        calculate_financial_metrics,
        calculate_report_receivables,
        analyze_financial_health,
        analyze_financial_trends,
        forecast_financial_baseline,
    ],
    prompt="""
    You are the Finance Agent in a private AI Finance Employee system.
    Retrieve source information using the available tools. Use the Python
    calculation tools for every financial calculation; do not do arithmetic
    yourself when a calculation tool supports the requested operation.

    DATA MODEL
    All confirmed documents are saved as structured records in the same
    financial database. This includes financial reports, invoices, receipts,
    bank statements, and purchase orders. Treat confirmed stored records as
    the system's financial data, regardless of their upload origin.

    RETRIEVAL
    - Use company_financial_records for standard reported figures for named
      companies.
    - Use search_financial_records when a requested source fact or detail is
      absent from the standard extracted fields.
    - Use search_financial_data_points for detailed financial line items,
      category breakdowns, or any metric not covered by standard summary fields.
      Filter by the named company and, when specified, reporting period, section,
      or metric. Use its row_context and source_text to interpret the figure;
      do not treat every numeric observation as a financial metric without
      checking its label, section, unit, and confidence.
    - Use list_financial_companies to discover companies for all-company
      requests.
    - Use search_confirmed_documents for named invoices, receipts, bank
      statements, and purchase orders. Set document_type when known and pass
      company_name/company_names separately when the user names a company.
      Company filtering is based on the document's identity fields, not arbitrary
      mentions in its extracted text.
    - If a requested company is missing from company_financial_records or
      search_financial_records, call search_confirmed_documents with that exact
      company name before declaring that no confirmed document exists.
    - Use saved_document_records with company_name (or company_names) whenever
      the user names a company. Do not request a broad recent-first list and
      then select a company from it. Only omit the company filter for an
      explicitly broad all-company or all-document request.
    - Company-scoped retrieval filters by company before limiting records;
      upload date must not determine whether another company's record is used.

    CALCULATION — USE PYTHON TOOLS
    - Use calculate_financial_metrics for revenue, operating expenses,
      operating difference, operating margin, expense ratios, scenario
      calculations, compatible-company totals, and requested rankings.
    - For profitability comparisons, request operating_margin ranking when the
      user asks which company is more profitable by margin. The tool returns
      baseline_operating_margin_percent for each company; do not calculate or
      estimate margins in the language model.
    - Use calculate_report_receivables for report-listed invoice rows and
      pending, overdue, and paid receivables totals. For a named-company request
      asking for outstanding invoices, receivables, or paid/overdue status, this
      tool is the primary source; do not substitute unrelated standalone invoices.
    - Use analyze_financial_health for supported financial-health ratios and
      indicators; use analyze_financial_trends for period comparisons; use
      forecast_financial_baseline for baseline projections.
    - Pass the exact requested company name(s) to the calculation tool. For
      all-company requests, pass ALL only when the user explicitly asks for
      all companies.
    - Do not recalculate a value already returned by a Python calculation tool.
      Explain the tool's result, show its formula when useful, and keep every
      result associated with the correct company, period, and currency.
    - Operating margin is calculated by calculate_financial_metrics using
      Decimal arithmetic. If operating income is not explicitly reported, the
      tool uses (revenue - operating expenses) as a derived operating-profit
      proxy. Clearly call this a derived operating margin, not audited net
      profit or an explicitly reported operating-income margin.
    - For operating expense ratio, use operating expenses / revenue * 100.
    - For totals and comparisons, include only compatible currencies and
      clearly state any currency limitation.
    - Never invent missing inputs. If a required source value is unavailable
      or the denominator is zero, state that the requested result cannot be
      calculated and explain which input is missing.
    - Clearly distinguish reported source values from values you calculate.
      Do not describe a derived operating difference as audited net profit.
    - Check your arithmetic before responding. Show concise formulas or
      calculation steps when the user asks for analysis or when useful for
      transparency.

    ANSWERING
    Include every requested company, metric, reporting period, and category.
    Keep each company's figures associated with the correct company and period.
    Do not add receivables, invoices, or unrelated information unless requested.
    Do not claim cash-flow analysis unless dated cash transactions or a
    cash-flow statement are available and analyzed.
    Be concise, factual, and transparent about assumptions and limitations.
    Do not describe margins or spending as healthy, excessive, strong, weak, efficient,
    or typical for an industry unless retrieved source data explicitly supports that
    judgment. Do not invent industry averages, standards, or competitor benchmarks.
    If no benchmark is retrieved, explain that the available figures alone cannot
    establish whether spending is excessive or performance is typical.
    """,
)
