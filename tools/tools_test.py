import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))


from database.db import SessionLocal
from tools.financial_tools import get_revenue_summary, get_invoice_summary
from tools.transaction_tools import get_expenses_by_category
from tools.customer_tools import get_customer_financial_summary


db = SessionLocal()

try:
    result = get_revenue_summary(db)
    print("Revenue Summary:")
    print(result)

    invoice_result = get_invoice_summary(db)
    print("\nInvoice Summary:")
    print(invoice_result)

    category_result = get_expenses_by_category(db)

    print("\nExpenses by Category:")
    print(category_result)

    customer_result = get_customer_financial_summary(db, "Rahul Sharma")
    print("\nCustomer Financial Summary:")
    print(customer_result)

finally:
    db.close()
