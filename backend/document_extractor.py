"""Type-aware extraction and validation for common financial documents.
Regex extraction is intentionally conservative: uncertain values stay blank for review.
"""

import re
from datetime import datetime

DOC_SCHEMAS = {
    "invoice": [
        "vendor_name",
        "vendor_address",
        "vendor_gstin",
        "vendor_email",
        "customer_name",
        "contact_person",
        "customer_address",
        "customer_gstin",
        "bank_name",
        "account_name",
        "invoice_number",
        "invoice_date",
        "due_date",
        "currency",
        "subtotal",
        "discount",
        "tax_rate",
        "cgst",
        "sgst",
        "igst",
        "tax_total",
        "shipping",
        "grand_total",
        "amount_paid",
        "balance_due",
        "payment_terms",
        "description",
        "line_items",
    ],
    "receipt": [
        "merchant_name",
        "receipt_number",
        "receipt_date",
        "currency",
        "subtotal",
        "tax",
        "tip",
        "discount",
        "total",
        "payment_method",
        "card_last4",
        "items",
    ],
    "bank_statement": [
        "bank_name",
        "account_holder",
        "account_number_masked",
        "statement_period_start",
        "statement_period_end",
        "opening_balance",
        "closing_balance",
        "total_deposits",
        "total_withdrawals",
        "currency",
        "transactions",
    ],
    "financial_report": [
        "company_name",
        "report_title",
        "reporting_period",
        "currency",
        "revenue",
        "cost_of_goods_sold",
        "gross_profit",
        "operating_expenses",
        "net_operating_difference",
        "operating_income",
        "net_income",
        "total_assets",
        "total_liabilities",
        "equity",
        "sections",
        "financial_data_points",
    ],
    "purchase_order": [
        "buyer_name",
        "supplier_name",
        "po_number",
        "po_date",
        "delivery_date",
        "currency",
        "subtotal",
        "tax",
        "shipping",
        "grand_total",
        "payment_terms",
        "delivery_address",
        "line_items",
    ],
}

LABELS = {
    "vendor_name": [r"(?:vendor|supplier|seller|billed\s+by)"],
    "supplier_name": [r"(?:supplier|vendor|seller)"],
    "customer_name": [r"(?:bill\s+to|customer|buyer)"],
    "merchant_name": [r"(?:merchant|store|sold\s+by)"],
    "company_name": [r"(?:company|business|organization)"],
    "currency": [r"currency"],
    "invoice_number": [r"invoice\s*(?:no|number|#)"],
    "receipt_number": [r"receipt\s*(?:no|number|#)"],
    "po_number": [r"(?:purchase\s+order|po)\s*(?:no|number|#)"],
    "invoice_date": [r"invoice\s+date"],
    "receipt_date": [r"receipt\s+date"],
    "po_date": [r"(?:po|order)\s+date"],
    "due_date": [r"due\s+date"],
    "delivery_date": [r"delivery\s+date"],
    "subtotal": [r"sub\s*total"],
    "discount": [r"discount"],
    "cgst": [r"cgst"],
    "sgst": [r"sgst"],
    "igst": [r"igst"],
    "tax_total": [r"(?:total\s+)?tax(?:es)?"],
    "tax": [r"tax(?:es)?"],
    "shipping": [r"shipping|freight"],
    "grand_total": [
        r"grand\s+total|invoice\s+total|total\s+amount|amount\s+payable|net\s+payable"
    ],
    "total": [r"(?:^|\b)total(?:\s+paid)?"],
    "amount_paid": [r"amount\s+paid|paid\s+amount"],
    "balance_due": [r"balance\s+due|amount\s+due"],
    "opening_balance": [r"opening\s+balance"],
    "closing_balance": [r"closing\s+balance"],
    "total_deposits": [r"total\s+(?:deposits|credits)"],
    "total_withdrawals": [r"total\s+(?:withdrawals|debits)"],
    "revenue": [r"revenue|sales"],
    "cost_of_goods_sold": [r"cost\s+of\s+(?:goods\s+)?sold|cogs"],
    "gross_profit": [r"gross\s+profit"],
    "operating_expenses": [r"operating\s+expenses"],
    "operating_income": [r"operating\s+income"],
    "net_income": [r"net\s+(?:income|profit|earnings)"],
    "total_assets": [r"total\s+assets"],
    "total_liabilities": [r"total\s+liabilities"],
    "equity": [r"(?:shareholders'?\s+)?equity"],
    "payment_terms": [r"payment\s+terms"],
    "payment_method": [r"payment\s+method|paid\s+by|payment\s+mode"],
    "bank_name": [r"bank\s+name"],
    "account_holder": [r"account\s+holder|account\s+name"],
    "statement_period_start": [r"(?:statement\s+)?from"],
    "statement_period_end": [r"(?:statement\s+)?to"],
    "reporting_period": [r"reporting\s+period|period\s+ended"],
    "report_title": [
        r"financial\s+(?:performance\s+)?report|income\s+statement|balance\s+sheet"
    ],
}

DATE_KEYS = {
    "invoice_date",
    "due_date",
    "receipt_date",
    "po_date",
    "delivery_date",
    "statement_period_start",
    "statement_period_end",
}
AMOUNT_KEYS = {
    "subtotal",
    "discount",
    "cgst",
    "sgst",
    "igst",
    "tax_total",
    "shipping",
    "grand_total",
    "amount_paid",
    "balance_due",
    "total",
    "tax",
    "opening_balance",
    "closing_balance",
    "total_deposits",
    "total_withdrawals",
    "revenue",
    "cost_of_goods_sold",
    "gross_profit",
    "operating_expenses",
    "net_operating_difference",
    "operating_income",
    "net_income",
    "total_assets",
    "total_liabilities",
    "equity",
}


def _clean_date(value):
    value = value.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return value


def classify_document(text):
    t = text.lower()
    scores = {
        "invoice": sum(
            x in t
            for x in (
                "invoice",
                "invoice number",
                "invoice no",
                "bill to",
                "tax invoice",
            )
        ),
        "receipt": sum(
            x in t
            for x in ("receipt", "thank you for shopping", "payment method", "cashier")
        ),
        "bank_statement": sum(
            x in t
            for x in (
                "bank statement",
                "account number",
                "opening balance",
                "closing balance",
                "debit",
                "credit",
            )
        ),
        "financial_report": sum(
            x in t
            for x in (
                "financial report",
                "financial performance report",
                "income statement",
                "balance sheet",
                "cash flow statement",
                "total assets",
                "net income",
                "total revenue",
                "operating expenses",
                "gross profit",
                "operating income",
                "net operating difference",
            )
        ),
        "purchase_order": sum(
            x in t
            for x in (
                "purchase order",
                "po number",
                "po no",
                "delivery terms",
                "ship to",
            )
        ),
    }
    best = max(scores, key=scores.get)
    if scores[best] < 2:
        return "unknown"
    # Explicit bank/report terms win over generic invoice/receipt mentions.
    for preferred in ("bank_statement", "financial_report", "purchase_order"):
        if scores[preferred] >= 2 and scores[preferred] >= scores[best] - 1:
            return preferred
    return best


def _extract_document_fields_legacy(text):
    doc_type = classify_document(text)
    keys = DOC_SCHEMAS.get(
        doc_type,
        ["document_title", "organization", "document_date", "currency", "notes"],
    )
    fields = {k: None for k in keys}
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    for key, patterns in LABELS.items():
        if key not in fields:
            continue
        for pat in patterns:
            # Match a label and value on the same line; do not guess from unrelated lines.
            m = re.search(
                rf"(?im)^[ \t]*(?:{pat})[ \t]*[:#-][ \t]*(?:₹|INR|Rs\.?[ \t]*)?([^\n|]+)",
                text,
            )
            if m:
                raw = m.group(1).strip().strip("| ")
                if key in AMOUNT_KEYS:
                    n = re.search(r"-?[\d,]+(?:\.\d{1,2})?", raw)
                    fields[key] = float(n.group(0).replace(",", "")) if n else None
                elif key in DATE_KEYS:
                    fields[key] = _clean_date(raw)
                else:
                    fields[key] = raw[:250]
                break
    # Infer a title/name only as a low-confidence suggestion, never overwrite explicit labels.
    if doc_type == "unknown":
        fields["document_title"] = lines[0][:160] if lines else None
    if doc_type == "financial_report":
        if not fields.get("company_name") and lines:
            fields["company_name"] = lines[0][:160]
        if not fields.get("report_title"):
            fields["report_title"] = next(
                (
                    x[:160]
                    for x in lines[:8]
                    if re.search(
                        r"(?i)financial report|income statement|balance sheet|cash flow",
                        x,
                    )
                ),
                None,
            )
        fields["sections"] = {"extracted_text": text}
    if doc_type in ("invoice", "purchase_order"):
        fields["line_items"] = []
    if doc_type == "receipt":
        fields["items"] = []
    if doc_type == "bank_statement":
        fields["transactions"] = []
    currency_match = re.search(r"(?i)\b(INR|USD|EUR|GBP|AED|CAD|AUD)\b|₹|\$|€|£", text)
    if "currency" in fields and currency_match:
        fields["currency"] = {"₹": "INR", "$": "USD", "€": "EUR", "£": "GBP"}.get(
            currency_match.group(0), currency_match.group(0).upper()
        )
    required = {
        "invoice": ["vendor_name", "invoice_number", "grand_total"],
        "receipt": ["merchant_name", "total"],
        "bank_statement": [
            "bank_name",
            "statement_period_start",
            "statement_period_end",
        ],
        "financial_report": ["company_name", "reporting_period"],
        "purchase_order": ["supplier_name", "po_number", "grand_total"],
    }.get(doc_type, [])
    missing = [k for k in required if not fields.get(k)]
    populated = sum(v not in (None, "", [], {}) for v in fields.values())
    confidence = (
        "high"
        if required and not missing and populated >= len(required) + 1
        else "medium"
        if populated >= 2
        else "low"
    )
    validation = []
    for a, b in (("subtotal", "grand_total"), ("opening_balance", "closing_balance")):
        if fields.get(a) is not None and fields.get(b) is not None and fields[b] < 0:
            validation.append(f"{b} is negative; verify this value")
    return {
        "document_type": doc_type,
        "fields": fields,
        "required_fields": required,
        "missing_fields": missing,
        "validation_warnings": validation,
        "confidence": confidence,
        "needs_review": True,
    }


# Context-aware enrichment layer. It supplements the conservative label parser
# with section-aware extraction for common invoice layouts (including two-column
# headers and item tables). It never fabricates absent values.
def _first_match(patterns, text, flags=re.IGNORECASE | re.MULTILINE):
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1).strip()
    return None


def _money(value):
    if value is None:
        return None
    match = re.search(r"-?\d[\d,]*(?:\.\d{1,2})?", str(value))
    return float(match.group(0).replace(",", "")) if match else None


def _invoice_enrichment(text, fields):
    # Header: supplier identity is commonly an unlabeled first line/logo text.
    lines = [
        re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()
    ]
    if not fields.get("vendor_name") and lines:
        # Invoices normally begin with the issuer name; avoid generic headings.
        candidate = next(
            (
                line
                for line in lines[:5]
                if not re.search(
                    r"(?i)^invoice$|business stationery|^tax invoice$", line
                )
                and not re.search(
                    r"(?i)invoice\s*(?:no|number)|invoice\s+date|due\s+date", line
                )
            ),
            None,
        )
        if candidate:
            fields["vendor_name"] = candidate[:250]

    # Two-column header fields may be extracted independently of their position.
    patterns = {
        "invoice_number": [
            r"\bInvoice\s*(?:No\.?|Number|#)\s*[:#]?\s*([A-Z0-9][A-Z0-9./_-]+)"
        ],
        "invoice_date": [r"\bInvoice\s+Date\s*[:#]?\s*([^\n|]+)"],
        "due_date": [r"\bDue\s+Date\s*[:#]?\s*([^\n|]+)"],
        "payment_terms": [r"\bPayment\s+Terms\s*[:#]?\s*([^\n|]+)"],
        "payment_method": [r"\bPayment\s+Method\s*[:#]?\s*([^\n|]+)"],
    }
    for key, pats in patterns.items():
        if not fields.get(key):
            raw = _first_match(pats, text)
            if raw:
                fields[key] = _clean_date(raw) if key in DATE_KEYS else raw.strip()

    # Seller details are often unlabeled lines beneath the issuer name.
    if lines:
        try:
            vendor_idx = lines.index(fields.get("vendor_name"))
        except ValueError:
            vendor_idx = -1
        if vendor_idx >= 0:
            vendor_block = lines[vendor_idx + 1 : vendor_idx + 8]
            if not fields.get("vendor_address"):
                address_lines = [
                    x
                    for x in vendor_block
                    if re.search(
                        r"(?i)\b(road|street|park|avenue|andheri|mumbai|pune|india|\d{5,6})\b",
                        x,
                    )
                ]
                if address_lines:
                    fields["vendor_address"] = ", ".join(
                        re.split(r"(?i)\s+Invoice\s+(?:No\.?|Date)\s*:", x)[0]
                        for x in address_lines[:2]
                    )
            if not fields.get("vendor_gstin"):
                fields["vendor_gstin"] = _first_match(
                    [r"\bGSTIN\s*[:#]?\s*([A-Z0-9]{10,})"], "\n".join(vendor_block)
                )
            if not fields.get("vendor_email"):
                fields["vendor_email"] = _first_match(
                    [r"\b([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})\b"],
                    "\n".join(vendor_block),
                )

    # BILL TO blocks may be extracted in reading order, with column headings
    # appearing as separate lines. Never treat a section heading as a person's name.
    bill_lines = []
    active_bill = False
    for line in lines:
        if re.search(r"(?i)\bBILL\s+TO\b", line):
            active_bill = True
            left = re.split(r"(?i)\bBILL\s+TO\b", line, maxsplit=1)[-1]
            left = re.split(r"(?i)\bPAYMENT\s+DETAILS\b", left, maxsplit=1)[0].strip()
            if left:
                bill_lines.append(left)
            continue
        if active_bill:
            if re.search(r"(?i)\b(?:ITEMIZED\s+CHARGES|NOTES)\b", line):
                break
            # A standalone right-column heading terminates/gets ignored; payment
            # labels on shared lines are removed while preserving the BILL TO value.
            if re.fullmatch(r"(?i)\s*PAYMENT\s+DETAILS\s*", line):
                continue
            left = re.split(
                r"(?i)\b(?:PAYMENT\s+TERMS|PAYMENT\s+METHOD|BANK\s*:|ACCOUNT\s+NAME\s*:|REFERENCE\s*:)",
                line,
                maxsplit=1,
            )[0].strip()
            if left and not re.match(r"(?i)^GSTIN\s*:", left):
                bill_lines.append(left)

    bill_lines = [
        x
        for x in bill_lines
        if x
        and not re.fullmatch(r"(?i)(?:BILL\s+TO|PAYMENT\s+DETAILS)", x)
        and not re.match(r"(?i)^GSTIN\s*:", x)
    ]
    if bill_lines:
        company = next(
            (
                x
                for x in bill_lines
                if re.search(r"(?i)\b(PVT|PRIVATE|LTD|LIMITED|LLP|INC|CORP)\b", x)
            ),
            None,
        )
        if not fields.get("customer_name"):
            fields["customer_name"] = (company or bill_lines[0])[:250]
        if not fields.get("contact_person") and company:
            company_index = bill_lines.index(company)
            preceding_names = [
                x
                for x in bill_lines[:company_index]
                if not re.search(
                    r"(?i)\b(floor|park|road|street|mumbai|pune|india|\d{5,6})\b",
                    x,
                )
            ]
            if preceding_names:
                fields["contact_person"] = preceding_names[-1][:250]
        if not fields.get("customer_address"):
            address = [
                x
                for x in bill_lines
                if re.search(
                    r"(?i)\b(floor|park|road|street|mumbai|pune|india|\d{5,6})\b",
                    x,
                )
            ]
            if address:
                fields["customer_address"] = ", ".join(address[:3])

    if not fields.get("customer_gstin"):
        gstins = re.findall(r"(?i)\bGSTIN\s*[:#]?\s*([A-Z0-9]{10,})", text)
        if len(gstins) > 1:
            fields["customer_gstin"] = gstins[1]

    # Legacy fallback for simpler single-column layouts.
    bill_match = re.search(
        r"(?is)BILL\s+TO\s+(.*?)(?=PAYMENT\s+DETAILS|ITEMIZED\s+CHARGES|$)", text
    )
    if bill_match:
        block = [
            re.sub(r"\s+", " ", x).strip()
            for x in bill_match.group(1).splitlines()
            if x.strip()
        ]
        block = [x for x in block if x.upper() not in {"BILL TO", "PAYMENT DETAILS"}]
        if not fields.get("customer_name") and block:
            # Prefer a company name when present; otherwise use the first named party.
            company = next(
                (
                    x
                    for x in block
                    if re.search(r"(?i)\b(PVT|PRIVATE|LTD|LIMITED|LLP|INC|CORP)\b", x)
                ),
                None,
            )
            fields["customer_name"] = (company or block[0])[:250]
        if not fields.get("contact_person") and len(block) > 1:
            fields["contact_person"] = block[0][:250]

    # Payment information can be embedded in a neighboring column.
    if not fields.get("bank_name"):
        fields["bank_name"] = _first_match([r"\bBank\s*:\s*([^\n|]+)"], text)
    if not fields.get("account_name"):
        fields["account_name"] = _first_match(
            [r"\bAccount\s+Name\s*:\s*([^\n|]+)"], text
        )

    # Totals are matched by semantic labels, so balance due is never mistaken
    # for grand total and tax components remain distinct.
    total_patterns = {
        "subtotal": [r"(?im)^\s*Sub\s*total\s*(?:[:|-])?\s*[^\n\d]*([\d,]+\.\d{2})"],
        "cgst": [r"(?im)^\s*CGST(?:\s*@\s*[\d.]+\s*%)?\s*[^\n\d]*([\d,]+\.\d{2})"],
        "sgst": [r"(?im)^\s*SGST(?:\s*@\s*[\d.]+\s*%)?\s*[^\n\d]*([\d,]+\.\d{2})"],
        "igst": [r"(?im)^\s*IGST(?:\s*@\s*[\d.]+\s*%)?\s*[^\n\d]*([\d,]+\.\d{2})"],
        "grand_total": [
            r"(?im)^\s*Grand\s+Total\s*(?:[:|-])?\s*[^\n\d]*([\d,]+\.\d{2})",
            r"(?im)^\s*Invoice\s+Total\s*(?:[:|-])?\s*[^\n\d]*([\d,]+\.\d{2})",
        ],
        "amount_paid": [
            r"(?im)^\s*Amount\s+Paid\s*(?:[:|-])?\s*[^\n\d]*([\d,]+\.\d{2})"
        ],
        "balance_due": [
            r"(?im)^\s*Balance\s+Due\s*(?:[:|-])?\s*[^\n\d]*([\d,]+\.\d{2})"
        ],
    }
    for key, pats in total_patterns.items():
        if fields.get(key) is None:
            raw = _first_match(pats, text)
            if raw:
                fields[key] = _money(raw)

    tax_rates = re.findall(r"(?i)\b(?:CGST|SGST|IGST)\s*@\s*(\d+(?:\.\d+)?)\s*%", text)
    if fields.get("tax_rate") is None and tax_rates:
        fields["tax_rate"] = float(tax_rates[0])
    if fields.get("tax_total") is None and (
        fields.get("cgst") is not None
        or fields.get("sgst") is not None
        or fields.get("igst") is not None
    ):
        fields["tax_total"] = sum(fields.get(k) or 0 for k in ("cgst", "sgst", "igst"))

    # Item tables are frequently flattened by PDF text extraction: description,
    # quantity, unit price and amount may each appear on separate lines.
    items = []
    in_items = False
    pending_description = []
    table_lines = []

    for line in lines:
        if re.search(r"(?i)\bITEMIZED\s+CHARGES\b", line):
            in_items = True
            continue
        if in_items and re.search(r"(?i)^\s*Subtotal\b", line):
            break
        if not in_items:
            continue
        if re.fullmatch(r"(?i)\s*(?:Description|Qty|Unit Price|Amount)\s*", line):
            continue
        table_lines.append(line.strip())

    def numeric_tokens(value):
        return re.findall(r"(?<![A-Za-z])\d[\d,]*(?:\.\d{1,2})?", value)

    i = 0
    while i < len(table_lines):
        line = table_lines[i]
        nums = numeric_tokens(line)

        # Case A: a complete item row is present on one line.
        if len(nums) >= 3:
            qty_raw, unit_raw, amount_raw = nums[-3:]
            description = line[: line.find(qty_raw)].strip(" |\t-")
            qty, unit_price, amount = (
                _money(qty_raw),
                _money(unit_raw),
                _money(amount_raw),
            )
            if (
                description
                and qty is not None
                and unit_price is not None
                and amount is not None
            ):
                items.append(
                    {
                        "description": description,
                        "quantity": int(qty) if qty.is_integer() else qty,
                        "unit_price": unit_price,
                        "amount": amount,
                    }
                )
                i += 1
                continue

        # Case B: PDF extraction has placed each table column on separate lines.
        if len(nums) == 1 and re.fullmatch(r"\s*\d+\s*", line):
            qty = _money(nums[0])
            if i >= 1 and i + 2 < len(table_lines):
                description = table_lines[i - 1].strip()
                unit_price = _money(table_lines[i + 1])
                amount = _money(table_lines[i + 2])
                if (
                    description
                    and qty is not None
                    and unit_price is not None
                    and amount is not None
                    and not re.fullmatch(r"\s*\d+\s*", description)
                ):
                    items.append(
                        {
                            "description": description,
                            "quantity": int(qty) if qty.is_integer() else qty,
                            "unit_price": unit_price,
                            "amount": amount,
                        }
                    )
                    i += 3
                    continue
        i += 1

    if items:
        fields["line_items"] = items

    # Currency can be inferred cautiously from strong country-specific evidence.
    # GSTIN is an India-specific tax identifier; mark this as contextual inference.
    if not fields.get("currency"):
        if re.search(r"(?i)\bGSTIN\s*[:#]?\s*[0-9]{2}[A-Z0-9]{10,}", text):
            fields["currency"] = "INR"

    return fields


def _financial_report_enrichment(text, fields):
    """Extract explicitly labelled financial-report fields without deriving metrics."""
    lines = [
        re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()
    ]

    # Prefer explicitly labelled company metadata over a generic first-line
    # fallback. Some PDF layouts place Company and Reporting period on one line.
    company_match = _first_match(
        [
            r"(?im)^\s*(?:Company|Company Name|Organization)\s*:\s*(.+?)"
            r"(?=\s{2,}(?:Reporting\s+Period)\s*:|\s+(?:Reporting\s+Period)\s*:|$)"
        ],
        text,
    )
    if company_match:
        fields["company_name"] = re.sub(r"\s+", " ", company_match).strip(" |,-")[:250]
    elif (
        not fields.get("company_name")
        or re.match(
            r"(?i)^\s*(?:sample\s+financial\s+report|financial\s+(?:performance\s+)?report)\b",
            str(fields.get("company_name") or ""),
        )
    ) and lines:
        candidate = next(
            (
                line
                for line in lines[:8]
                if not re.search(
                    r"(?i)^\s*(?:sample\s+financial\s+report|financial\s+(?:performance\s+)?report|fictional\s+training\s+data|document\s+status)\b",
                    line,
                )
                and not re.search(r"(?i)^\s*(?:reporting\s+period|currency)\s*:", line)
            ),
            None,
        )
        if candidate:
            fields["company_name"] = candidate[:250]

    if not fields.get("report_title"):
        title = next(
            (
                line
                for line in lines[:10]
                if re.search(
                    r"(?i)\b(?:financial\s+(?:performance\s+)?report|income\s+statement|balance\s+sheet|cash\s+flow\s+statement)\b",
                    line,
                )
            ),
            None,
        )
        if title:
            title = re.split(r"\s*[|]\s*", title, maxsplit=1)[0].strip()
            fields["report_title"] = title[:250]

    # Extract a reporting period wherever it appears, including on the same
    # line as the company name (common in flattened PDF text).
    period = _first_match(
        [
            r"(?i)\bReporting\s+Period\s*:\s*([A-Za-z]+\s+\d{4})\b",
            r"(?i)\bFinancial\s+(?:Performance\s+)?Report\s*[|:]\s*([A-Za-z]+\s+\d{4})\b",
            r"(?i)\bfor\s+\d{1,2}\s+([A-Za-z]+\s+\d{4})\s+to\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}\b",
        ],
        text,
    )
    if period:
        fields["reporting_period"] = period.strip()

    if not fields.get("currency") and re.search(r"(?i)\bAmount\s*\(\s*INR\s*\)", text):
        fields["currency"] = "INR"

    # These labels are exact report totals. Capture the amount on the same or
    # immediately following line (PDF text extraction often separates columns).
    amount_patterns = {
        "revenue": r"(?im)^\s*Total\s+Revenue\s*(?:[:|])?\s*(?:₹|■)?\s*([\d,]+(?:\.\d{1,2})?)\s*$",
        "operating_expenses": r"(?im)^\s*Total\s+Operating\s+Expenses\s*(?:[:|])?\s*(?:₹|■)?\s*([\d,]+(?:\.\d{1,2})?)\s*$",
        "net_operating_difference": r"(?im)^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?Net\s+Operating\s+Difference\s*(?:[:|])?\s*(?:₹|INR|Rs\.?|■)?\s*([\d,]+(?:\.\d{1,2})?)\s*$",
    }
    normalized = text.replace("\u25a0", "■")
    for key, pattern in amount_patterns.items():
        if fields.get(key) is not None:
            continue
        match = re.search(pattern, normalized)
        if not match:
            # Handle label and amount split across adjacent extracted-text lines.
            label = {
                "revenue": "Total Revenue",
                "operating_expenses": "Total Operating Expenses",
                "net_operating_difference": "Net Operating Difference",
            }[key]
            match = re.search(
                rf"(?im)^\s*{re.escape(label)}\s*$[\r\n]+[ \t]*(?:₹|INR|Rs\.?\s*|■)?\s*([\d,]+(?:\.\d{{1,2}})?)\s*$",
                normalized,
            )
        if match:
            fields[key] = _money(match.group(1))

    # Some reports state NOD in prose rather than as a clean table row, e.g.
    # "The resulting net operating difference was INR 168,000." Only capture
    # an amount explicitly tied to the NOD phrase; never calculate it here.
    if fields.get("net_operating_difference") is None:
        nod_patterns = [
            r"(?i)\bnet\s+operating\s+difference\s*"
            r"(?:was|is|of|amounts?\s+to|equals?)\s*"
            r"(?:INR|Rs\.?|₹|■)\s*([\d,]+(?:\.\d{1,2})?)",
            r"(?i)\bresult(?:ing)?\s+net\s+operating\s+difference\s*"
            r"(?:was|is|of)\s*(?:INR|Rs\.?|₹|■)\s*([\d,]+(?:\.\d{1,2})?)",
        ]
        nod_value = _first_match(
            nod_patterns, normalized, flags=re.IGNORECASE | re.DOTALL
        )
        if nod_value:
            fields["net_operating_difference"] = _money(nod_value)

    if "sections" in fields and not fields.get("sections"):
        fields["sections"] = {"extracted_text": text}

    return fields


# ---------------------------------------------------------------------------
# Generic financial observation extraction
# ---------------------------------------------------------------------------

_NUMBER_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?P<open>\()?\s*"
    r"(?P<currency>₹|INR\b|USD\b|EUR\b|GBP\b|Rs\.?|[$€£])?\s*"
    r"(?P<number>-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)"
    r"\s*(?P<percent>%)?\s*(?(open)\))",
    re.IGNORECASE,
)

_DATE_LIKE_RE = re.compile(
    r"^\s*(?:\d{1,4}[-/]\d{1,2}[-/]\d{1,4}|"
    r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})\s*$"
)
_ID_LABEL_RE = re.compile(
    r"(?i)\b(invoice|receipt|reference|account|customer|vendor|"
    r"transaction|voucher|order|po)\s*(?:no\.?|number|#|id)\b"
)
_SECTION_HINTS = (
    "income statement",
    "profit and loss",
    "balance sheet",
    "cash flow",
    "cashflow",
    "accounts receivable",
    "receivables",
    "accounts payable",
    "payables",
    "operating expenses",
    "revenue",
    "assets",
    "liabilities",
    "equity",
    "debt",
    "inventory",
    "tax",
    "sales",
    "expenses",
    "financial ratios",
)


def _normalise_currency(token, fallback=None):
    if not token:
        return fallback
    token = token.strip().upper()
    return {
        "₹": "INR",
        "RS": "INR",
        "RS.": "INR",
        "$": "USD",
        "€": "EUR",
        "£": "GBP",
    }.get(token, token)


def _numeric_value(raw_number, is_parenthesized=False):
    value = float(raw_number.replace(",", ""))
    return -abs(value) if is_parenthesized else value


def _is_probable_section_heading(line):
    cleaned = line.strip().lower().rstrip(":")
    return (
        len(cleaned) <= 100
        and not re.search(r"\d", cleaned)
        and any(hint in cleaned for hint in _SECTION_HINTS)
    )


def _extract_financial_data_points(text, fields):
    """
    Extract financial observations from flattened PDF text.

    Handles common PDF layouts where a row label and its amount are emitted
    on adjacent lines, and recognizes invoice-level receivables separately.
    Ambiguous prose numbers, dates, identifiers, and arithmetic notes are
    deliberately excluded rather than stored as financial observations.
    """
    company = fields.get("company_name")
    period = fields.get("reporting_period")
    default_currency = fields.get("currency")
    raw_lines = text.splitlines()

    points = []
    current_section = None
    previous_label = None
    page_number = 1

    def clean_line(value):
        return re.sub(r"\s+", " ", value).strip().strip("|")

    def is_amount_line(value):
        # The square glyph is used by this PDF as a currency-symbol placeholder.
        return bool(
            re.fullmatch(
                r"\s*(?:■|₹|INR\b|Rs\.?|[$€£])?\s*"
                r"-?\d[\d,]*(?:\.\d{1,2})?\s*",
                value,
                flags=re.IGNORECASE,
            )
        )

    def amount_from_line(value):
        match = re.search(r"-?\d[\d,]*(?:\.\d{1,2})?", value)
        if not match:
            return None
        return float(match.group(0).replace(",", ""))

    def add_point(
        metric_name,
        row_label,
        value,
        raw_value,
        line_number,
        section=None,
        row_context=None,
        confidence="medium",
    ):
        if value is None:
            return
        points.append(
            {
                "company_name": company,
                "reporting_period": period,
                "section": section or current_section,
                "metric_name": str(metric_name)[:250],
                "row_label": str(row_label)[:250] if row_label else None,
                "numeric_value": value,
                "raw_value": raw_value,
                "currency": default_currency,
                "unit": "currency" if default_currency else "numeric",
                "row_context": {
                    **(row_context or {}),
                    "source_line_number": line_number,
                    "needs_review": confidence != "high",
                },
                # Page attribution is available only when the upstream PDF
                # extraction preserves page boundaries as form-feed characters.
                "source_page": page_number if "\f" in text else None,
                "source_table": section or current_section,
                "source_text": raw_value,
                "confidence": confidence,
            }
        )

    # Keep original line positions so source line references remain meaningful.
    lines = [(i, clean_line(line)) for i, line in enumerate(raw_lines, start=1)]
    i = 0
    while i < len(lines):
        line_number, line = lines[i]

        if "\f" in line:
            page_number += line.count("\f")
            previous_label = None
            i += 1
            continue

        if not line:
            i += 1
            continue

        # Numbered section headings establish context and are never observations.
        section_match = re.match(r"^\d+(?:\.\d+)*[.)]?\s+(.+)$", line)
        if section_match and not re.search(r"\d", section_match.group(1)):
            current_section = section_match.group(1).strip()
            previous_label = None
            i += 1
            continue

        # Receivables table is flattened into one value per line:
        # invoice ID, customer, amount, due date, status.
        invoice_match = re.fullmatch(r"([A-Z]{2,}[A-Z0-9]*-\d{4}-\d{3})", line)
        if invoice_match and i + 4 < len(lines):
            invoice_id = invoice_match.group(1)
            customer = lines[i + 1][1]
            amount_line = lines[i + 2][1]
            due_date = lines[i + 3][1]
            status = lines[i + 4][1]

            if (
                is_amount_line(amount_line)
                and re.search(r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}", due_date)
                and status.lower() in {"pending", "paid", "overdue"}
            ):
                add_point(
                    metric_name="Accounts Receivable Amount",
                    row_label=customer,
                    value=amount_from_line(amount_line),
                    raw_value=amount_line,
                    line_number=lines[i + 2][0],
                    section="Accounts Receivable",
                    row_context={
                        "invoice_id": invoice_id,
                        "customer": customer,
                        "due_date": due_date,
                        "status": status,
                    },
                    confidence="high",
                )
                i += 5
                previous_label = None
                continue

        # Ignore prose containing arithmetic: it repeats summary figures and
        # should not create additional financial observations.
        if re.search(r"[=+\u2212]", line) or re.search(
            r"(?i)\b(?:for|from|to)\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}", line
        ):
            previous_label = None
            i += 1
            continue

        # A standalone currency amount belongs to the immediately preceding
        # non-header label in flattened two-column financial tables.
        if is_amount_line(line):
            label = previous_label
            if label and not re.fullmatch(
                r"(?i)(?:amount(?:\s*\([^)]+\))?|metric|revenue stream|"
                r"expense category|invoice id|customer|due date|status)",
                label,
            ):
                value = amount_from_line(line)
                add_point(
                    metric_name=label,
                    row_label=label,
                    value=value,
                    raw_value=line,
                    line_number=line_number,
                    row_context={"layout": "adjacent_label_value_lines"},
                    confidence="high",
                )
            previous_label = None
            i += 1
            continue

        # Header rows and dates are context, not financial metrics.
        if re.fullmatch(
            r"(?i)(?:metric|amount(?:\s*\([^)]+\))?|revenue stream|"
            r"expense category|invoice id|customer|due date|status)",
            line,
        ):
            previous_label = None
            i += 1
            continue
        if _DATE_LIKE_RE.fullmatch(line) or re.search(
            r"(?i)\b(?:reporting period|financial performance report|"
            r"document reference|end of report)\b",
            line,
        ):
            previous_label = None
            i += 1
            continue

        # Only remember plausible row labels. Do not turn arbitrary prose,
        # company names, identifiers, or dates into metric names.
        if (
            not re.search(r"\d", line)
            and len(line) <= 180
            and not re.search(
                r"(?i)\b(?:this report|the company|"
                r"selected customer invoices|invoice balances|"
                r"internally prepared|independently audited)\b",
                line,
            )
        ):
            previous_label = line
        else:
            previous_label = None

        i += 1

    return points


def extract_document_fields(text):
    result = _extract_document_fields_legacy(text)
    if result.get("document_type") == "financial_report":
        fields = result["fields"]
        _financial_report_enrichment(text, fields)
        fields["financial_data_points"] = _extract_financial_data_points(text, fields)
        required = result.get("required_fields", [])
        result["missing_fields"] = [key for key in required if not fields.get(key)]
        populated = sum(value not in (None, "", [], {}) for value in fields.values())
        result["confidence"] = (
            "high"
            if required
            and not result["missing_fields"]
            and populated >= len(required) + 1
            else "medium"
            if populated >= 2
            else "low"
        )
        result["field_confidence"] = {
            key: "missing" if fields.get(key) in (None, "", [], {}) else "high"
            for key in fields
        }
    elif result.get("document_type") == "invoice":
        fields = result["fields"]
        _invoice_enrichment(text, fields)
        required = result.get("required_fields", [])
        result["missing_fields"] = [key for key in required if not fields.get(key)]
        populated = sum(value not in (None, "", [], {}) for value in fields.values())
        has_warnings = bool(result.get("validation_warnings"))
        result["confidence"] = (
            "high"
            if required
            and not result["missing_fields"]
            and populated >= len(required) + 1
            and not has_warnings
            else "medium"
            if populated >= 2
            else "low"
        )
        # Distinguish directly extracted fields from contextually inferred values.
        result["field_confidence"] = {
            key: (
                "missing"
                if fields.get(key) in (None, "", [], {})
                else "medium"
                if key == "currency"
                and fields.get(key) == "INR"
                and not re.search(r"(?i)\bINR\b|₹", text)
                else "high"
            )
            for key in fields
        }
        if not fields.get("line_items"):
            result["validation_warnings"].append(
                "No line items could be confidently extracted; review the item table manually"
            )
    return result
