import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))


from database.db import SessionLocal
from database.models import Customer
from datetime import date
from database.models import Invoice
from database.models import Transaction


def seed_customers():

    db = SessionLocal()

    try:
        customers = [
            Customer(
                name="Rahul Sharma",
                email="rahul@example.com",
                company="TechNova Solutions",
                phone="9876543210",
            ),
            Customer(
                name="Priya Mehta",
                email="priya@example.com",
                company="CloudEdge Technologies",
                phone="9876543211",
            ),
            Customer(
                name="Amit Patel",
                email="amit@example.com",
                company="DataSphere Pvt Ltd",
                phone="9876543212",
            ),
        ]

        db.add_all(customers)
        db.commit()

        print("3 customers inserted successfully!")

    except Exception as e:
        db.rollback()
        print("Error:", e)

    finally:
        db.close()


def seed_invoices():

    db = SessionLocal()

    try:
        invoices = [
            Invoice(
                invoice_number="INV001",
                customer_id=1,
                amount=50000,
                issue_date=date(2026, 10, 1),
                due_date=date(2026, 10, 15),
                status="pending",
            ),
            Invoice(
                invoice_number="INV002",
                customer_id=2,
                amount=75000,
                issue_date=date(2026, 10, 5),
                due_date=date(2026, 10, 20),
                status="pending",
            ),
            Invoice(
                invoice_number="INV003",
                customer_id=3,
                amount=30000,
                issue_date=date(2026, 10, 10),
                due_date=date(2026, 11, 15),
                status="pending",
            ),
            Invoice(
                invoice_number="INV004",
                customer_id=1,
                amount=25000,
                issue_date=date(2026, 10, 12),
                due_date=date(2026, 10, 25),
                status="paid",
            ),
        ]

        db.add_all(invoices)
        db.commit()

        print("4 invoices inserted successfully!")

    except Exception as e:
        db.rollback()
        print("Error:", e)

    finally:
        db.close()


def seed_transactions():

    db = SessionLocal()

    try:
        transactions = [
            Transaction(
                transaction_type="income",
                category="Sales",
                description="Product sales",
                amount=150000,
                transaction_date=date(2026, 10, 3),
            ),
            Transaction(
                transaction_type="income",
                category="Services",
                description="Consulting revenue",
                amount=80000,
                transaction_date=date(2026, 10, 12),
            ),
            Transaction(
                transaction_type="expense",
                category="Salary",
                description="Employee salaries",
                amount=60000,
                transaction_date=date(2026, 10, 15),
            ),
            Transaction(
                transaction_type="expense",
                category="Infrastructure",
                description="Cloud infrastructure",
                amount=15000,
                transaction_date=date(2026, 10, 20),
            ),
            Transaction(
                transaction_type="expense",
                category="Marketing",
                description="Marketing expenditure",
                amount=10000,
                transaction_date=date(2026, 10, 25),
            ),
        ]

        db.add_all(transactions)
        db.commit()

        print("5 transactions inserted successfully!")

    except Exception as e:
        db.rollback()
        print("Error:", e)

    finally:
        db.close()


if __name__ == "__main__":
    seed_transactions()
