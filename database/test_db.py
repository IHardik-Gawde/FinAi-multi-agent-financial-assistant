import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from database.db import engine, Base
from database.models import Customer, Invoice, Transaction


try:
    Base.metadata.create_all(bind=engine)

    print("Database connection successful!")
    print("Customers table verified!")
    print("Invoices table verified!")
    print("Transactions table created successfully!")

except Exception as e:
    print("Error:", e)
