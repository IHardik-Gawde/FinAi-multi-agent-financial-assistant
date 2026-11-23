from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    Float,
    ForeignKey,
    JSON,
    DateTime,
    Text,
    Numeric,
    Index,
)
from database.db import Base
from sqlalchemy.orm import relationship


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, nullable=False)

    email = Column(String, unique=True, nullable=False)

    company = Column(String, nullable=True)

    phone = Column(String, nullable=True)

    invoices = relationship("Invoice", back_populates="customer")


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)

    invoice_number = Column(String, unique=True, nullable=False)

    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)

    amount = Column(Float, nullable=False)

    issue_date = Column(Date, nullable=False)

    due_date = Column(Date, nullable=False)

    status = Column(String, default="pending")

    customer = relationship("Customer", back_populates="invoices")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)

    transaction_type = Column(String, nullable=False)

    category = Column(String, nullable=False)

    description = Column(String, nullable=True)

    amount = Column(Float, nullable=False)

    transaction_date = Column(Date, nullable=False)


# Document Intelligence records. Existing Customer, Invoice and Transaction tables are retained.
from datetime import datetime


class DocumentRecord(Base):
    __tablename__ = "document_records"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False, index=True)
    document_type = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="confirmed")
    extracted_data = Column(JSON, nullable=False, default=dict)
    confidence = Column(String, nullable=False, default="low")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    financial_data_points = relationship(
        "FinancialDataPoint",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class InvoiceDocument(Base):
    __tablename__ = "invoice_documents"
    id = Column(Integer, primary_key=True)
    document_id = Column(
        Integer,
        ForeignKey("document_records.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    data = Column(JSON, nullable=False, default=dict)


class ReceiptDocument(Base):
    __tablename__ = "receipt_documents"
    id = Column(Integer, primary_key=True)
    document_id = Column(
        Integer,
        ForeignKey("document_records.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    data = Column(JSON, nullable=False, default=dict)


class BankStatementDocument(Base):
    __tablename__ = "bank_statement_documents"
    id = Column(Integer, primary_key=True)
    document_id = Column(
        Integer,
        ForeignKey("document_records.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    data = Column(JSON, nullable=False, default=dict)


class FinancialReportDocument(Base):
    __tablename__ = "financial_report_documents"
    id = Column(Integer, primary_key=True)
    document_id = Column(
        Integer,
        ForeignKey("document_records.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    data = Column(JSON, nullable=False, default=dict)


class PurchaseOrderDocument(Base):
    __tablename__ = "purchase_order_documents"
    id = Column(Integer, primary_key=True)
    document_id = Column(
        Integer,
        ForeignKey("document_records.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    data = Column(JSON, nullable=False, default=dict)


class FinancialDataPoint(Base):
    """A traceable numeric observation extracted from an uploaded document."""

    __tablename__ = "financial_data_points"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(
        Integer,
        ForeignKey("document_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    company_name = Column(String, nullable=True, index=True)
    reporting_period = Column(String, nullable=True, index=True)
    section = Column(String, nullable=True, index=True)
    metric_name = Column(String, nullable=False, index=True)
    row_label = Column(String, nullable=True)

    # Decimal numeric storage avoids binary floating-point representation
    # for financial amounts and ratios.
    numeric_value = Column(Numeric(20, 4), nullable=False)
    raw_value = Column(String, nullable=True)
    currency = Column(String, nullable=True, index=True)
    unit = Column(String, nullable=True)

    # Keeps row-specific dimensions such as customer, invoice, status,
    # account, category, and other table columns without fixed schema limits.
    row_context = Column(JSON, nullable=False, default=dict)

    source_page = Column(Integer, nullable=True)
    source_table = Column(String, nullable=True)
    source_text = Column(Text, nullable=True)
    confidence = Column(String, nullable=False, default="low")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    document = relationship(
        "DocumentRecord",
        back_populates="financial_data_points",
    )


Index(
    "ix_financial_data_company_period_metric",
    FinancialDataPoint.company_name,
    FinancialDataPoint.reporting_period,
    FinancialDataPoint.metric_name,
)
