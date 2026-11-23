from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import os
import json
import shutil
import tempfile
import time
import uuid
from typing import Optional

from dotenv import load_dotenv
from livekit import api as livekit_api

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    UploadFile,
    File,
)
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.db import get_db, initialize_database
from database.models import (
    Transaction,
    DocumentRecord,
    InvoiceDocument,
    ReceiptDocument,
    BankStatementDocument,
    FinancialReportDocument,
    FinancialDataPoint,
    PurchaseOrderDocument,
)
from backend.document_extractor import extract_document_fields

from rag.ingest import (
    extract_text_from_pdf,
    extract_text_from_image,
    extract_text_from_document,
    chunk_text,
    extract_financial_fields,
)

from rag.document_manager import (
    DOCUMENT_DIR,
    SUPPORTED_EXTENSIONS,
    get_document_metadata,
    get_vector_store,
)

from tools.financial_tools import (
    get_revenue_summary,
    get_invoice_summary,
)
from tools.transaction_tools import get_expenses_by_category
from tools.customer_tools import get_customer_financial_summary


# Load LiveKit credentials from the project's environment file.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / "api" / ".env")
load_dotenv(PROJECT_ROOT / ".env")


# --------------------------------------------------
# APPLICATION
# --------------------------------------------------

app = FastAPI(title="AI Finance Employee API")


@app.on_event("startup")
def _initialize_database_tables():
    initialize_database()


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# REQUEST MODELS
# --------------------------------------------------


class TransactionCreate(BaseModel):
    description: str = Field(..., min_length=1)
    transaction_type: str
    amount: float = Field(..., gt=0)
    transaction_date: date


class TransactionUpdate(BaseModel):
    description: Optional[str] = None
    transaction_type: Optional[str] = None
    amount: Optional[float] = Field(default=None, gt=0)
    transaction_date: Optional[date] = None


class DocumentSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)


class LiveKitTokenRequest(BaseModel):
    room_name: str = Field(default="finance-room", min_length=1, max_length=128)
    identity: Optional[str] = Field(default=None, min_length=1, max_length=128)


# --------------------------------------------------
# HELPERS
# --------------------------------------------------


def serialize_transaction(transaction):
    return {
        "id": transaction.id,
        "description": transaction.description,
        "transaction_type": transaction.transaction_type,
        "category": transaction.category,
        "amount": transaction.amount,
        "transaction_date": transaction.transaction_date.isoformat(),
    }


def serialize_document(filename, metadata):
    return {
        "filename": filename,
        "size": metadata["size"],
        "modified": metadata["modified"],
        "extension": Path(filename).suffix.lower(),
    }


# Unconfirmed uploads are kept outside DOCUMENT_DIR, so they are not
# visible to the document library or FAISS until the user confirms.
PENDING_DOCUMENT_DIR = Path(tempfile.gettempdir()) / "ai_finance_pending_documents"
PENDING_DOCUMENT_TTL_SECONDS = 24 * 60 * 60


def _pending_paths(upload_id: str):
    if len(upload_id) != 32 or not all(
        c in "0123456789abcdef" for c in upload_id.lower()
    ):
        raise HTTPException(status_code=400, detail="Invalid pending upload ID.")
    return (
        PENDING_DOCUMENT_DIR / f"{upload_id}.bin",
        PENDING_DOCUMENT_DIR / f"{upload_id}.meta",
    )


def _cleanup_expired_pending_uploads():
    if not PENDING_DOCUMENT_DIR.exists():
        return
    cutoff = time.time() - PENDING_DOCUMENT_TTL_SECONDS
    for path in PENDING_DOCUMENT_DIR.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            pass


# --------------------------------------------------
# HOME
# --------------------------------------------------


@app.get("/")
def home():
    return {"message": "AI Finance Employee API is running"}


# --------------------------------------------------
# LIVEKIT TOKEN API
# --------------------------------------------------


@app.post("/livekit/token")
def create_livekit_token(data: LiveKitTokenRequest):
    """Create a room-join token for the React voice interface."""

    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")
    livekit_url = os.getenv("LIVEKIT_URL")

    if not api_key or not api_secret or not livekit_url:
        raise HTTPException(
            status_code=500,
            detail="LiveKit credentials are not configured on the backend.",
        )

    identity = data.identity or f"user-{uuid.uuid4().hex[:12]}"

    try:
        token = (
            livekit_api.AccessToken(api_key, api_secret)
            .with_identity(identity)
            .with_name(identity)
            .with_grants(
                livekit_api.VideoGrants(
                    room_join=True,
                    room=data.room_name,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,
                )
            )
            .to_jwt()
        )

        return {
            "server_url": livekit_url,
            "participant_token": token,
            "room_name": data.room_name,
            "identity": identity,
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"LiveKit token generation failed: {error}",
        )


# --------------------------------------------------
# FINANCIAL SUMMARY APIs
# --------------------------------------------------


@app.get("/finance/revenue")
def revenue_summary(db: Session = Depends(get_db)):
    return get_revenue_summary(db)


@app.get("/finance/invoices")
def invoice_summary(db: Session = Depends(get_db)):
    return get_invoice_summary(db)


@app.get("/finance/expenses")
def expense_summary(db: Session = Depends(get_db)):
    return get_expenses_by_category(db)


@app.get("/finance/customer/{customer_name}")
def customer_summary(
    customer_name: str,
    db: Session = Depends(get_db),
):
    return get_customer_financial_summary(db, customer_name)


@app.get("/finance/company-overview")
def company_overview(db: Session = Depends(get_db)):
    """Return company-level financial observations extracted from uploaded reports.

    Values remain grouped by reporting period and currency; unlike-for-like
    figures are deliberately not combined into one misleading grand total.
    """
    observations = (
        db.query(FinancialDataPoint)
        .order_by(
            FinancialDataPoint.company_name,
            FinancialDataPoint.reporting_period,
            FinancialDataPoint.metric_name,
        )
        .all()
    )

    grouped = {}
    for point in observations:
        company = (point.company_name or "").strip()
        if not company:
            continue
        period = point.reporting_period or "Unspecified period"
        currency = point.currency or "Unspecified currency"
        key = (company, period, currency)
        item = grouped.setdefault(
            key,
            {
                "company_name": company,
                "reporting_period": period,
                "currency": currency,
                "metrics": [],
                "document_ids": set(),
            },
        )
        item["metrics"].append(
            {
                "metric_name": point.metric_name,
                "row_label": point.row_label,
                "value": float(point.numeric_value)
                if point.numeric_value is not None
                else None,
                "raw_value": point.raw_value,
                "unit": point.unit,
                "source_page": point.source_page,
                "source_table": point.source_table,
            }
        )
        item["document_ids"].add(point.document_id)

    companies = sorted({key[0] for key in grouped})
    reports = []
    for item in grouped.values():
        item["document_count"] = len(item.pop("document_ids"))
        reports.append(item)

    return {
        "total_companies": len(companies),
        "total_company_periods": len(reports),
        "companies": companies,
        "reports": reports,
    }


# --------------------------------------------------
# FINANCIAL RECORDS CRUD APIs
# --------------------------------------------------


@app.get("/finance/transactions")
def get_transactions(db: Session = Depends(get_db)):
    transactions = (
        db.query(Transaction)
        .order_by(
            Transaction.transaction_date.desc(),
            Transaction.id.desc(),
        )
        .all()
    )

    return [serialize_transaction(t) for t in transactions]


@app.post("/finance/transactions")
def create_transaction(
    data: TransactionCreate,
    db: Session = Depends(get_db),
):
    transaction_type = data.transaction_type.strip().lower()

    if transaction_type not in ["income", "expense"]:
        raise HTTPException(
            status_code=400,
            detail="Transaction type must be income or expense",
        )

    transaction = Transaction(
        transaction_type=transaction_type,
        category="General",
        description=data.description.strip(),
        amount=data.amount,
        transaction_date=data.transaction_date,
    )

    db.add(transaction)
    db.commit()
    db.refresh(transaction)

    return serialize_transaction(transaction)


@app.put("/finance/transactions/{transaction_id}")
def update_transaction(
    transaction_id: int,
    data: TransactionUpdate,
    db: Session = Depends(get_db),
):
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()

    if not transaction:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found",
        )

    updates = data.model_dump(exclude_unset=True)

    if "transaction_type" in updates:
        transaction_type = updates["transaction_type"].strip().lower()

        if transaction_type not in ["income", "expense"]:
            raise HTTPException(
                status_code=400,
                detail="Transaction type must be income or expense",
            )

        transaction.transaction_type = transaction_type

    if "description" in updates:
        transaction.description = updates["description"].strip()

    if "amount" in updates:
        transaction.amount = updates["amount"]

    if "transaction_date" in updates:
        transaction.transaction_date = updates["transaction_date"]

    db.commit()
    db.refresh(transaction)

    return serialize_transaction(transaction)


@app.delete("/finance/transactions/{transaction_id}")
def delete_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
):
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()

    if not transaction:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found",
        )

    db.delete(transaction)
    db.commit()

    return {"message": "Transaction deleted successfully"}


# --------------------------------------------------
# OCR DOCUMENT EXTRACTION
# Existing receipt/invoice OCR functionality
# --------------------------------------------------


@app.post("/ocr/extract")
async def extract_document(file: UploadFile = File(...)):
    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()

    if suffix not in [
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        ".bmp",
        ".webp",
    ]:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Upload a PDF or image.",
        )

    content = await file.read()

    if not content:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is empty.",
        )

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
        ) as temp_file:
            temp_file.write(content)
            temp_path = Path(temp_file.name)

        if suffix == ".pdf":
            extracted_text = extract_text_from_pdf(temp_path)
        else:
            extracted_text = extract_text_from_image(temp_path)

        if not extracted_text.strip():
            raise HTTPException(
                status_code=422,
                detail="No readable text was found. Try a clearer scan or image.",
            )

        extracted_fields = extract_financial_fields(extracted_text)

        return {
            "filename": filename,
            "extracted_text": extracted_text,
            "chunks": chunk_text(extracted_text),
            "extracted_fields": extracted_fields,
        }

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"OCR extraction failed: {error}",
        )

    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)


# --------------------------------------------------
# DOCUMENT MANAGEMENT
# --------------------------------------------------


@app.post("/documents/upload")
async def upload_document_for_review(file: UploadFile = File(...)):
    """Compatibility alias: uploads are temporary until the user confirms."""
    return await process_document_for_review(file)


@app.post("/documents/process")
async def process_document_for_review(file: UploadFile = File(...)):
    """Extract a document into temporary storage; do not save or index it yet."""

    filename = Path(file.filename or "").name
    if not filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format: {suffix}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    _cleanup_expired_pending_uploads()
    PENDING_DOCUMENT_DIR.mkdir(parents=True, exist_ok=True)

    upload_id = uuid.uuid4().hex
    pending_file, metadata_file = _pending_paths(upload_id)
    extraction_path = PENDING_DOCUMENT_DIR / f"{upload_id}{suffix}"

    try:
        extraction_path.write_bytes(content)
        extracted_text = extract_text_from_document(extraction_path)
        if not extracted_text.strip():
            raise HTTPException(
                status_code=422,
                detail="No readable text was found in this document.",
            )

        extracted_fields = extract_document_fields(extracted_text)

        # Keep the original bytes and filename temporarily for confirmation.
        pending_file.write_bytes(content)
        metadata_file.write_text(
            json.dumps({"filename": filename}),
            encoding="utf-8",
        )

        return {
            "message": "Document processed for review. Nothing has been saved or indexed yet.",
            "upload_id": upload_id,
            "filename": filename,
            "extracted_text": extracted_text,
            "extracted_fields": extracted_fields,
            "indexed": False,
            "saved": False,
        }

    except HTTPException:
        pending_file.unlink(missing_ok=True)
        metadata_file.unlink(missing_ok=True)
        raise
    except Exception as error:
        pending_file.unlink(missing_ok=True)
        metadata_file.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail=f"Document processing failed: {error}",
        )
    finally:
        extraction_path.unlink(missing_ok=True)


class ConfirmDocumentRecord(BaseModel):
    upload_id: str = Field(..., min_length=1)
    document_type: str = Field(..., min_length=1)
    fields: dict
    confidence: str = "low"


@app.post("/documents/records")
def confirm_document_record(data: ConfirmDocumentRecord, db: Session = Depends(get_db)):
    """After explicit user approval, persist the original, index it, and save reviewed fields."""

    pending_file, metadata_file = _pending_paths(data.upload_id)
    if not pending_file.is_file() or not metadata_file.is_file():
        raise HTTPException(
            status_code=404,
            detail="Pending upload not found or expired. Please upload the document again.",
        )

    try:
        pending_metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        filename = Path(pending_metadata["filename"]).name
    except Exception:
        raise HTTPException(
            status_code=400, detail="Pending upload metadata is invalid."
        )

    table_by_type = {
        "invoice": InvoiceDocument,
        "receipt": ReceiptDocument,
        "bank_statement": BankStatementDocument,
        "financial_report": FinancialReportDocument,
        "purchase_order": PurchaseOrderDocument,
    }
    model = table_by_type.get(data.document_type)
    if not model:
        raise HTTPException(
            status_code=400, detail="Unsupported or unknown document type"
        )

    DOCUMENT_DIR.mkdir(parents=True, exist_ok=True)
    destination = DOCUMENT_DIR / filename
    if destination.exists():
        raise HTTPException(
            status_code=409,
            detail="A document with this filename already exists. Rename it or remove the existing document first.",
        )

    moved_to_library = False
    try:
        # The original enters the permanent library only after confirmation.
        shutil.move(str(pending_file), str(destination))
        moved_to_library = True

        # Index only after the original has been committed to the document library.
        get_vector_store()

        record = DocumentRecord(
            filename=filename,
            document_type=data.document_type,
            status="confirmed",
            extracted_data=data.fields,
            confidence=data.confidence,
        )
        db.add(record)
        db.flush()

        db.add(model(document_id=record.id, data=data.fields))

        # Persist extracted financial observations as queryable database rows.
        # Keep the reviewed observations in extracted_data as well for traceability.
        financial_data_point_count = 0
        if data.document_type == "financial_report":
            observations = data.fields.get("financial_data_points", [])
            if observations is None:
                observations = []
            if not isinstance(observations, list):
                raise ValueError("financial_data_points must be a list.")

            for observation in observations:
                if not isinstance(observation, dict):
                    continue

                metric_name = str(observation.get("metric_name") or "").strip()
                raw_numeric_value = observation.get("numeric_value")
                if not metric_name or raw_numeric_value is None:
                    continue

                try:
                    numeric_value = Decimal(str(raw_numeric_value))
                except (InvalidOperation, TypeError, ValueError):
                    continue

                if not numeric_value.is_finite():
                    continue

                row_context = observation.get("row_context")
                if not isinstance(row_context, dict):
                    row_context = {}

                db.add(
                    FinancialDataPoint(
                        document_id=record.id,
                        company_name=observation.get("company_name"),
                        reporting_period=observation.get("reporting_period"),
                        section=observation.get("section"),
                        metric_name=metric_name,
                        row_label=observation.get("row_label"),
                        numeric_value=numeric_value,
                        raw_value=observation.get("raw_value"),
                        currency=observation.get("currency"),
                        unit=observation.get("unit"),
                        row_context=row_context,
                        source_page=observation.get("source_page"),
                        source_table=observation.get("source_table"),
                        source_text=observation.get("source_text"),
                        confidence=str(observation.get("confidence") or "low"),
                    )
                )
                financial_data_point_count += 1

        db.commit()
        db.refresh(record)

        metadata_file.unlink(missing_ok=True)
        return {
            "message": "Document confirmed, saved to the library, indexed in FAISS, and structured record saved.",
            "record_id": record.id,
            "filename": filename,
            "document_type": record.document_type,
            "financial_data_points_saved": financial_data_point_count,
            "indexed": True,
        }

    except Exception as error:
        db.rollback()
        if moved_to_library and destination.exists():
            try:
                shutil.move(str(destination), str(pending_file))
            except OSError:
                destination.unlink(missing_ok=True)
        try:
            get_vector_store()
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Unable to confirm document: {error}",
        )


class UpdateDocumentRecord(BaseModel):
    fields: dict
    confidence: Optional[str] = None


@app.put("/documents/records/{record_id}")
def update_document_record(
    record_id: int,
    data: UpdateDocumentRecord,
    db: Session = Depends(get_db),
):
    """Update reviewed structured fields for an already-confirmed document."""
    typed_models = {
        "invoice": InvoiceDocument,
        "receipt": ReceiptDocument,
        "bank_statement": BankStatementDocument,
        "financial_report": FinancialReportDocument,
        "purchase_order": PurchaseOrderDocument,
    }
    record = (
        db.query(DocumentRecord)
        .filter(DocumentRecord.id == record_id, DocumentRecord.status == "confirmed")
        .first()
    )
    if record is None:
        raise HTTPException(
            status_code=404, detail="Confirmed document record not found."
        )

    typed_model = typed_models.get(record.document_type)
    typed_record = None
    if typed_model is not None:
        typed_record = (
            db.query(typed_model).filter(typed_model.document_id == record.id).first()
        )
        if typed_record is None:
            raise HTTPException(
                status_code=409,
                detail="The document's structured record is missing; changes were not saved.",
            )

    try:
        # Keep both canonical extracted_data and the document-type-specific JSON in sync.
        record.extracted_data = data.fields
        if data.confidence is not None:
            record.confidence = data.confidence
        if typed_record is not None:
            typed_record.data = data.fields

        # Financial report observations are derived rows, so replace them atomically
        # from the edited reviewed payload.
        if record.document_type == "financial_report":
            db.query(FinancialDataPoint).filter(
                FinancialDataPoint.document_id == record.id
            ).delete(synchronize_session=False)

            observations = data.fields.get("financial_data_points") or []
            if not isinstance(observations, list):
                raise ValueError("financial_data_points must be a list.")
            for observation in observations:
                if not isinstance(observation, dict):
                    continue
                metric_name = str(observation.get("metric_name") or "").strip()
                raw_value = observation.get("numeric_value")
                if not metric_name or raw_value in (None, ""):
                    continue
                numeric_value = Decimal(str(raw_value))
                if not numeric_value.is_finite():
                    continue
                row_context = observation.get("row_context")
                if not isinstance(row_context, dict):
                    row_context = {}
                db.add(
                    FinancialDataPoint(
                        document_id=record.id,
                        company_name=observation.get("company_name"),
                        reporting_period=observation.get("reporting_period"),
                        section=observation.get("section"),
                        metric_name=metric_name,
                        row_label=observation.get("row_label"),
                        numeric_value=numeric_value,
                        raw_value=observation.get("raw_value"),
                        currency=observation.get("currency"),
                        unit=observation.get("unit"),
                        row_context=row_context,
                        source_page=observation.get("source_page"),
                        source_table=observation.get("source_table"),
                        source_text=observation.get("source_text"),
                        confidence=str(
                            observation.get("confidence") or record.confidence or "low"
                        ),
                    )
                )

        db.commit()
        db.refresh(record)
        return {
            "message": "Saved document fields updated successfully.",
            "record_id": record.id,
            "filename": record.filename,
            "document_type": record.document_type,
            "fields": record.extracted_data,
            "confidence": record.confidence,
            "original_file_unchanged": True,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as error:
        db.rollback()
        raise HTTPException(
            status_code=400, detail=f"Unable to update document fields: {error}"
        )


@app.get("/documents/file/{filename}")
def view_document_file(filename: str):
    """Serve the original saved document for in-browser viewing."""
    safe_filename = Path(filename).name
    if safe_filename != filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    file_path = DOCUMENT_DIR / safe_filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document file not found.")
    return FileResponse(
        path=file_path,
        filename=safe_filename,
        media_type="application/pdf" if file_path.suffix.lower() == ".pdf" else None,
        content_disposition_type="inline",
    )


@app.delete("/documents/pending/{upload_id}")
def discard_pending_document(upload_id: str):
    """Discard an unconfirmed upload without adding it to the library or FAISS."""

    pending_file, metadata_file = _pending_paths(upload_id)
    pending_file.unlink(missing_ok=True)
    metadata_file.unlink(missing_ok=True)
    return {"message": "Unconfirmed upload discarded.", "upload_id": upload_id}


@app.get("/documents/records")
def get_document_records(
    document_type: Optional[str] = None, db: Session = Depends(get_db)
):
    query = db.query(DocumentRecord)
    if document_type:
        query = query.filter(DocumentRecord.document_type == document_type)
    rows = query.order_by(DocumentRecord.created_at.desc()).all()
    return [
        {
            "id": row.id,
            "filename": row.filename,
            "document_type": row.document_type,
            "status": row.status,
            "fields": row.extracted_data,
            "confidence": row.confidence,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@app.get("/documents")
def list_documents():
    """Return all supported documents saved on the backend."""

    metadata = get_document_metadata()

    documents = [
        serialize_document(filename, details)
        for filename, details in sorted(metadata.items())
    ]

    return {
        "total_documents": len(documents),
        "documents": documents,
    }


@app.delete("/documents/{filename}")
def delete_document(filename: str, db: Session = Depends(get_db)):
    """Delete a document, its database records, and synchronize FAISS."""

    safe_filename = Path(filename).name

    if safe_filename != filename:
        raise HTTPException(
            status_code=400,
            detail="Invalid filename.",
        )

    file_path = DOCUMENT_DIR / safe_filename

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    # Also remove older duplicate records created by previous delete behaviour.
    typed_models = {
        "invoice": InvoiceDocument,
        "receipt": ReceiptDocument,
        "bank_statement": BankStatementDocument,
        "financial_report": FinancialReportDocument,
        "purchase_order": PurchaseOrderDocument,
    }

    try:
        records = (
            db.query(DocumentRecord)
            .filter(DocumentRecord.filename == safe_filename)
            .all()
        )

        for record in records:
            typed_model = typed_models.get(record.document_type)
            if typed_model is not None:
                (
                    db.query(typed_model)
                    .filter(typed_model.document_id == record.id)
                    .delete(synchronize_session=False)
                )
            db.delete(record)

        db.commit()
        file_path.unlink()

        # Synchronize the existing FAISS index and metadata.
        get_vector_store()

        return {
            "message": "Document and associated database records deleted successfully.",
            "filename": safe_filename,
            "deleted_records": len(records),
        }

    except Exception as error:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Document deletion failed: {error}",
        )


# --------------------------------------------------
# DOCUMENT INDEXING
# --------------------------------------------------


@app.post("/documents/index")
def index_documents():
    """
    Index new and modified documents.
    Uses the existing document_manager and FAISS vector store.
    """

    try:
        metadata = get_document_metadata()

        vector_store = get_vector_store()

        return {
            "message": "Document indexing completed.",
            "total_documents": len(metadata),
            "documents": list(metadata.keys()),
            "index_size": (
                vector_store.index.ntotal if vector_store.index is not None else 0
            ),
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Document indexing failed: {error}",
        )


# --------------------------------------------------
# RAG SEMANTIC SEARCH
# --------------------------------------------------


@app.post("/documents/search")
def search_documents(data: DocumentSearchRequest):
    """
    Retrieve relevant document chunks using the existing
    sentence-transformer embeddings and FAISS index.
    """

    query = data.query.strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Search query cannot be empty.",
        )

    try:
        vector_store = get_vector_store()

        if vector_store.index is None or vector_store.index.ntotal == 0:
            return {
                "query": query,
                "total_results": 0,
                "results": [],
            }

        results = vector_store.search(
            query,
            top_k=data.top_k,
        )

        return {
            "query": query,
            "total_results": len(results),
            "results": results,
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Document search failed: {error}",
        )
