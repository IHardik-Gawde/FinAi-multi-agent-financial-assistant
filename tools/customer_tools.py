from sqlalchemy.orm import Session
from database.models import Customer, Invoice


def get_customer_financial_summary(
    db: Session,
    customer_name: str | None = None,
    company_name: str | None = None,
):
    """
    Return invoice totals for one customer or all customers of a company.

    Exactly one lookup key must be supplied. Company lookup uses Customer.company,
    not a guess based on customer names.
    """
    if bool(customer_name) == bool(company_name):
        return {"error": "Provide exactly one of customer_name or company_name."}

    query = db.query(Customer)
    if company_name:
        query = query.filter(Customer.company.ilike(f"%{company_name.strip()}%"))
        lookup_type, lookup_value = "company", company_name.strip()
    else:
        query = query.filter(Customer.name.ilike(f"%{customer_name.strip()}%"))
        lookup_type, lookup_value = "customer", customer_name.strip()

    customers = query.order_by(Customer.id).all()
    if not customers:
        return {"error": f"{lookup_type.title()} '{lookup_value}' not found"}

    customer_ids = [customer.id for customer in customers]
    invoices = (
        db.query(Invoice)
        .filter(Invoice.customer_id.in_(customer_ids))
        .order_by(Invoice.issue_date, Invoice.id)
        .all()
    )

    def status_total(status):
        return sum(
            (invoice.amount or 0)
            for invoice in invoices
            if (invoice.status or "").strip().lower() == status
        )

    return {
        "lookup_type": lookup_type,
        "lookup_value": lookup_value,
        "customers": [
            {
                "customer_name": customer.name,
                "company": customer.company,
                "customer_id": customer.id,
            }
            for customer in customers
        ],
        "customer_count": len(customers),
        "total_invoices": len(invoices),
        "total_invoiced": float(sum((invoice.amount or 0) for invoice in invoices)),
        "pending_amount": float(status_total("pending")),
        "paid_amount": float(status_total("paid")),
        "overdue_status_amount": float(status_total("overdue")),
        "currency": "INR",
        "note": "Operational Invoice-table totals; not financial-statement revenue.",
    }
