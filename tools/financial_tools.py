from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import (
    Customer,
    DocumentRecord,
    Invoice,
    InvoiceDocument,
    Transaction,
)


def get_revenue_summary(db: Session):
    """
    Return organization-wide transaction totals.

    Transaction has no company/customer foreign key in the current schema;
    therefore this function cannot produce company-specific totals.
    """
    total_income = (
        db.query(func.sum(Transaction.amount))
        .filter(func.lower(Transaction.transaction_type) == "income")
        .scalar()
        or 0
    )
    total_expenses = (
        db.query(func.sum(Transaction.amount))
        .filter(func.lower(Transaction.transaction_type) == "expense")
        .scalar()
        or 0
    )
    return {
        "total_income": float(total_income),
        "total_expenses": float(total_expenses),
        "net_difference": float(total_income - total_expenses),
        "currency": "INR",
        "scope": "organization_wide",
        "limitation": "Transactions are not linked to a company in the current schema.",
    }


def _parse_invoice_date(value):
    """Parse the ISO dates stored by the invoice extractor, with safe fallbacks."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    value = str(value).strip()
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _to_amount(value):
    """Return a finite numeric invoice amount, or None when it is unavailable."""
    if value in (None, ""):
        return None
    try:
        amount = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return amount if amount >= 0 and amount != float("inf") else None


def get_invoice_summary(db: Session, company_name: str | None = None):
    """Return all confirmed invoices plus pending/overdue outstanding summaries."""
    today = date.today()
    all_rows = []

    # Existing manually-created operational invoices.
    legacy_query = db.query(Invoice).join(Customer, Invoice.customer_id == Customer.id)
    if company_name:
        legacy_query = legacy_query.filter(
            Customer.company.ilike(f"%{company_name.strip()}%")
        )
    for invoice in legacy_query.order_by(Invoice.due_date, Invoice.id).all():
        status = (invoice.status or "pending").strip().lower()
        amount = _to_amount(invoice.amount) or 0.0
        due = _parse_invoice_date(invoice.due_date)
        normalized_status = (
            "paid"
            if status in {"paid", "settled"}
            else "overdue"
            if status == "overdue" or (status == "pending" and due and due < today)
            else "pending"
        )
        outstanding = 0.0 if normalized_status == "paid" else amount
        all_rows.append(
            {
                "invoice_number": invoice.invoice_number,
                "customer_name": invoice.customer.name
                if invoice.customer
                else "Unknown",
                "company": invoice.customer.company if invoice.customer else "Unknown",
                "amount": amount,
                "outstanding_amount": outstanding,
                "due_date": due,
                "status": normalized_status,
                "source": "operational_record",
            }
        )

    # Confirmed uploaded invoices are the source for the document upload workflow.
    uploaded = (
        db.query(InvoiceDocument, DocumentRecord)
        .join(DocumentRecord, InvoiceDocument.document_id == DocumentRecord.id)
        .filter(
            DocumentRecord.document_type == "invoice",
            DocumentRecord.status == "confirmed",
        )
        .order_by(DocumentRecord.created_at, DocumentRecord.id)
        .all()
    )
    for invoice_doc, record in uploaded:
        fields = invoice_doc.data or {}
        if not isinstance(fields, dict):
            continue
        vendor = str(fields.get("vendor_name") or "").strip() or None
        customer = str(fields.get("customer_name") or "").strip() or None
        if company_name:
            needle = company_name.strip().lower()
            if (
                needle not in (vendor or "").lower()
                and needle not in (customer or "").lower()
            ):
                continue

        total = _to_amount(fields.get("grand_total"))
        paid = _to_amount(fields.get("amount_paid")) or 0.0
        balance = _to_amount(fields.get("balance_due"))
        if balance is None:
            if total is None:
                continue
            balance = max(total - paid, 0.0)
        amount = total if total is not None else balance
        due = _parse_invoice_date(fields.get("due_date"))
        status = (
            "paid" if balance <= 0 else "overdue" if due and due < today else "pending"
        )

        all_rows.append(
            {
                "invoice_number": fields.get("invoice_number") or record.filename,
                "customer_name": customer or vendor or "Unknown",
                "company": vendor or customer or "Unknown",
                "amount": amount,
                "outstanding_amount": balance,
                "due_date": due,
                "status": status,
                "source": "uploaded_document",
                "filename": record.filename,
            }
        )

    # Uploaded documents take precedence over duplicate legacy invoice numbers.
    deduplicated = {}
    for row in all_rows:
        key = str(row.get("invoice_number") or "").strip().lower()
        if key:
            if key not in deduplicated or row["source"] == "uploaded_document":
                deduplicated[key] = row

    invoices = list(deduplicated.values())
    pending = [
        row
        for row in invoices
        if row["status"] in {"pending", "overdue"} and row["outstanding_amount"] > 0
    ]
    overdue = [row for row in pending if row["status"] == "overdue"]

    def serialize_due(value):
        return value.isoformat() if value else None

    all_invoice_details = [
        {
            "invoice_number": row["invoice_number"],
            "customer_name": row["customer_name"],
            "company": row["company"],
            "amount": float(row["amount"]),
            "outstanding_amount": float(row["outstanding_amount"]),
            "due_date": serialize_due(row["due_date"]),
            "status": row["status"],
            "source": row["source"],
            "filename": row.get("filename"),
        }
        for row in sorted(
            invoices,
            key=lambda item: (item["due_date"] or date.max, item["invoice_number"]),
        )
    ]

    return {
        "company_filter": company_name.strip() if company_name else None,
        "scope": "company" if company_name else "organization_wide",
        "total_invoices": len(invoices),
        "all_invoice_details": all_invoice_details,
        "total_pending_invoices": len(pending),
        "total_pending_amount": float(
            sum(row["outstanding_amount"] for row in pending)
        ),
        "overdue_invoice_count": len(overdue),
        "overdue_invoice_details": [
            {
                "invoice_number": row["invoice_number"],
                "customer_name": row["customer_name"],
                "company": row["company"],
                "amount": float(row["outstanding_amount"]),
                "due_date": serialize_due(row["due_date"]),
                "days_overdue": (today - row["due_date"]).days,
            }
            for row in overdue
        ],
        "total_overdue_amount": float(
            sum(row["outstanding_amount"] for row in overdue)
        ),
        "currency": "INR",
    }
