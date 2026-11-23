from pathlib import Path
from pypdf import PdfReader
import pymupdf
import pytesseract
from PIL import Image
from io import BytesIO
import re
import csv
import shutil
import subprocess
import tempfile

from docx import Document
from openpyxl import load_workbook
import xlrd


# --------------------------------------------------
# PDF EXTRACTION
# --------------------------------------------------


def extract_text_from_pdf(pdf_path):
    """Extract text using PyPDF, with OCR fallback for scanned pages."""

    reader = PdfReader(str(pdf_path))
    pdf_document = pymupdf.open(str(pdf_path))

    extracted_text = []

    for page_number, page in enumerate(reader.pages):
        text = page.extract_text()

        if text and text.strip():
            extracted_text.append(text)
            print(f"[PyPDF] Extracted page {page_number + 1}")
        else:
            print(f"[OCR] Processing page {page_number + 1}")

            pdf_page = pdf_document[page_number]
            pix = pdf_page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
            image = Image.open(BytesIO(pix.tobytes("png")))

            ocr_text = pytesseract.image_to_string(image, lang="eng")
            extracted_text.append(ocr_text)

    pdf_document.close()

    return "\n".join(extracted_text)


# --------------------------------------------------
# IMAGE EXTRACTION
# --------------------------------------------------


def extract_text_from_image(image_path):
    """Extract text from images using Tesseract OCR."""

    image = Image.open(str(image_path))
    return pytesseract.image_to_string(image, lang="eng")


# --------------------------------------------------
# WORD DOCUMENT EXTRACTION
# --------------------------------------------------


def extract_text_from_docx(docx_path):
    """Extract paragraphs and tables from DOCX documents."""

    document = Document(str(docx_path))
    extracted_text = []

    for paragraph in document.paragraphs:
        if paragraph.text.strip():
            extracted_text.append(paragraph.text)

    for table in document.tables:
        for row in table.rows:
            row_text = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if row_text:
                extracted_text.append(" | ".join(row_text))

    return "\n".join(extracted_text)


def extract_text_from_doc(doc_path):
    """
    Extract legacy DOC files using LibreOffice conversion.
    Requires LibreOffice to be installed and available in PATH.
    """

    libreoffice = shutil.which("libreoffice") or shutil.which("soffice")

    if not libreoffice:
        raise RuntimeError(
            "Legacy .doc files require LibreOffice. "
            "Install LibreOffice or convert the file to .docx."
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        subprocess.run(
            [
                libreoffice,
                "--headless",
                "--convert-to",
                "docx",
                "--outdir",
                temp_dir,
                str(doc_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        converted_path = Path(temp_dir) / f"{Path(doc_path).stem}.docx"

        if not converted_path.exists():
            raise RuntimeError("LibreOffice could not convert the DOC file.")

        return extract_text_from_docx(converted_path)


# --------------------------------------------------
# EXCEL EXTRACTION
# --------------------------------------------------


def extract_text_from_xlsx(xlsx_path):
    """Extract data from all worksheets in an XLSX workbook."""

    workbook = load_workbook(filename=str(xlsx_path), read_only=True, data_only=True)

    extracted_text = []

    try:
        for sheet in workbook.worksheets:
            extracted_text.append(f"Sheet: {sheet.title}")

            for row in sheet.iter_rows(values_only=True):
                values = [
                    str(value).strip()
                    for value in row
                    if value is not None and str(value).strip()
                ]

                if values:
                    extracted_text.append(" | ".join(values))
    finally:
        workbook.close()

    return "\n".join(extracted_text)


def extract_text_from_xls(xls_path):
    """Extract data from legacy XLS workbooks."""

    workbook = xlrd.open_workbook(str(xls_path))
    extracted_text = []

    for sheet in workbook.sheets():
        extracted_text.append(f"Sheet: {sheet.name}")

        for row_index in range(sheet.nrows):
            values = [
                str(value).strip()
                for value in sheet.row_values(row_index)
                if str(value).strip()
            ]

            if values:
                extracted_text.append(" | ".join(values))

    return "\n".join(extracted_text)


# --------------------------------------------------
# CSV EXTRACTION
# --------------------------------------------------


def extract_text_from_csv(csv_path):
    """Extract rows from CSV files."""

    extracted_text = []

    with open(
        csv_path, "r", encoding="utf-8-sig", errors="replace", newline=""
    ) as file:
        reader = csv.reader(file)

        for row in reader:
            values = [value.strip() for value in row if value.strip()]

            if values:
                extracted_text.append(" | ".join(values))

    return "\n".join(extracted_text)


# --------------------------------------------------
# TXT EXTRACTION
# --------------------------------------------------


def extract_text_from_txt(txt_path):
    """Extract text from TXT files."""

    with open(txt_path, "r", encoding="utf-8-sig", errors="replace") as file:
        return file.read()


# --------------------------------------------------
# UNIVERSAL DOCUMENT EXTRACTION
# --------------------------------------------------


def extract_text_from_document(file_path):
    """
    Select the correct extractor based on file extension.
    Supports PDF, DOC, DOCX, XLS, XLSX, CSV, TXT and images.
    """

    file_path = Path(file_path)
    extension = file_path.suffix.lower()

    extractors = {
        ".pdf": extract_text_from_pdf,
        ".docx": extract_text_from_docx,
        ".doc": extract_text_from_doc,
        ".xlsx": extract_text_from_xlsx,
        ".xls": extract_text_from_xls,
        ".csv": extract_text_from_csv,
        ".txt": extract_text_from_txt,
        ".png": extract_text_from_image,
        ".jpg": extract_text_from_image,
        ".jpeg": extract_text_from_image,
        ".tiff": extract_text_from_image,
        ".tif": extract_text_from_image,
        ".bmp": extract_text_from_image,
        ".webp": extract_text_from_image,
    }

    extractor = extractors.get(extension)

    if extractor is None:
        raise ValueError(f"Unsupported document format: {extension}")

    print(f"[INGEST] Processing {file_path.name}")

    text = extractor(file_path)

    if not text or not text.strip():
        raise ValueError(f"No readable text found in {file_path.name}")

    return text


# --------------------------------------------------
# TEXT CHUNKING
# --------------------------------------------------


def chunk_text(text, chunk_size=1000, overlap=200):
    """Split text into overlapping chunks without cutting words."""

    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Invalid chunk_size or overlap")

    words = text.split()
    chunks = []
    current_chunk = []
    current_length = 0

    for word in words:
        additional_length = len(word) + (1 if current_chunk else 0)

        if current_chunk and current_length + additional_length > chunk_size:
            chunks.append(" ".join(current_chunk))

            overlap_words = []
            overlap_length = 0

            for previous_word in reversed(current_chunk):
                word_length = len(previous_word) + 1

                if overlap_length + word_length > overlap:
                    break

                overlap_words.insert(0, previous_word)
                overlap_length += word_length

            current_chunk = overlap_words
            current_length = len(" ".join(current_chunk))

        current_chunk.append(word)
        current_length += len(word) + (1 if len(current_chunk) > 1 else 0)

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


# --------------------------------------------------
# DOCUMENT PROCESSING
# --------------------------------------------------


def _extract_company_metadata(text):
    """Extract a company name only when the document labels it clearly."""
    company_match = re.search(
        r"(?im)^\s*company\s*:\s*(.+?)(?=\s+Reporting\s+period\s*:|\r?\n|$)",
        text,
    )
    if company_match:
        candidate = company_match.group(1).strip(" \t.,;:")
        if candidate:
            return candidate

    legal_suffix = re.compile(
        r"(?:private\s+limited|public\s+limited|pvt\.?\s*ltd\.?|"
        r"limited|ltd\.?|incorporated|inc\.?|llc|llp)\s*[.,;:]*$",
        re.IGNORECASE,
    )
    generic = re.compile(
        r"\b(sample financial report|financial performance report|"
        r"annual report|management report|financial statement)\b",
        re.IGNORECASE,
    )
    for line in text.splitlines()[:12]:
        candidate = re.sub(r"\s+", " ", line).strip(" \t#*-")
        if (
            candidate
            and legal_suffix.search(candidate)
            and not generic.search(candidate)
        ):
            return candidate.strip(" .,;:")
    return None


def _detect_document_type(text, file_path):
    """Classify common finance documents using explicit text indicators."""
    lower = text.casefold()
    if (
        sum(
            term in lower
            for term in (
                "financial report",
                "financial performance report",
                "financial statement",
                "revenue breakdown",
                "operating expense",
                "reporting period",
                "balance sheet",
            )
        )
        >= 2
    ):
        return "financial_report"
    if re.search(r"\b(invoice|tax invoice)\b", lower):
        return "invoice"
    if re.search(r"\b(receipt|payment received|payment receipt)\b", lower):
        return "receipt"
    if re.search(r"\b(bank statement|account statement)\b", lower):
        return "bank_statement"
    if Path(file_path).suffix.lower() in {".xls", ".xlsx", ".csv"}:
        return "spreadsheet"
    return "unknown"


def process_document(file_path):
    """
    Extract text and return chunks with inherited document metadata.

    page_number remains None because the current extraction pipeline combines
    page text before chunking and therefore cannot reliably map chunks to pages.
    """
    file_path = Path(file_path)
    text = extract_text_from_document(file_path)
    raw_chunks = chunk_text(text)

    document_metadata = {
        "source": file_path.name,
        "company": _extract_company_metadata(text),
        "document_type": _detect_document_type(text, file_path),
        "page_number": None,
    }

    chunks = [
        {
            "text": chunk,
            "metadata": {
                **document_metadata,
                "chunk_index": index,
            },
        }
        for index, chunk in enumerate(raw_chunks)
    ]

    print(
        f"[INGEST] {file_path.name}: {len(chunks)} chunks generated "
        f"(company={document_metadata['company']!r}, "
        f"type={document_metadata['document_type']})"
    )
    return chunks


def process_pdf(pdf_path):
    """Preserve the existing PDF processing interface."""

    return process_document(pdf_path)


def process_all_pdfs(directory="data/documents"):
    """Preserve the existing PDF batch-processing interface."""

    directory = Path(directory)
    pdf_files = list(directory.glob("*.pdf"))

    if not pdf_files:
        raise FileNotFoundError(f"No PDF files found in {directory}")

    all_chunks = []

    for pdf_path in pdf_files:
        print(f"\nProcessing: {pdf_path.name}")

        chunks = process_pdf(pdf_path)

        print(f"Generated {len(chunks)} chunks.")
        all_chunks.extend(chunks)

    print(f"\nTotal PDFs processed: {len(pdf_files)}")
    print(f"Total chunks generated: {len(all_chunks)}")

    return all_chunks


# --------------------------------------------------
# FINANCIAL FIELD EXTRACTION
# --------------------------------------------------


def extract_financial_fields(text):
    """Suggest transaction fields from receipt/invoice OCR text."""

    from datetime import datetime

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    normalized = "\n".join(lines)
    lower = normalized.lower()

    result = {
        "merchant": "",
        "description": "",
        "transaction_type": "",
        "amount": None,
        "transaction_date": "",
        "document_type": "unknown",
        "confidence": "low",
        "needs_review": True,
    }

    # Detect reports first: their totals must not become a single transaction.
    report_terms = [
        "financial report",
        "financial statement",
        "revenue breakdown",
        "operating expense breakdown",
        "accounts receivable",
        "reporting period",
    ]

    if sum(term in lower for term in report_terms) >= 2:
        result["document_type"] = "financial_report"

        company = re.search(
            r"(?im)^\s*company\s*:\s*(.+?)\s{2,}(?:reporting period|$)", normalized
        )

        if company:
            result["merchant"] = company.group(1).strip()
        else:
            for index, line in enumerate(lines[:6]):
                if (
                    re.search(
                        r"(?i)financial\s+(?:performance\s+)?report|financial\s+statement",
                        line,
                    )
                    and index > 0
                ):
                    result["merchant"] = lines[index - 1].strip(" |-")[:120]
                    break

            if not result["merchant"] and lines:
                result["merchant"] = lines[0][:120]

        result["description"] = next(
            (
                x[:120]
                for x in lines[:8]
                if re.search(
                    r"(?i)financial\s+(?:performance\s+)?report|financial\s+statement",
                    x,
                )
            ),
            "Financial report",
        )

        result["confidence"] = "high" if result["merchant"] else "medium"
        result["message"] = (
            "This looks like a financial report, not a single transaction. "
            "No transaction amount or type was auto-selected."
        )

        return result

    # Merchant extraction
    for pattern in [
        r"(?im)^\s*(?:merchant|vendor|seller|supplier|billed\s+by|from)\s*[:#-]\s*(.+?)\s*$",
        r"(?im)^\s*company\s*:\s*(.+?)\s*$",
    ]:
        match = re.search(pattern, normalized)

        if match:
            result["merchant"] = match.group(1).strip()[:120]
            break

    if not result["merchant"]:
        for line in lines[:5]:
            candidate = re.sub(r"\s+", " ", line).strip()

            if (
                len(candidate) <= 100
                and re.search(r"[A-Za-z]", candidate)
                and not re.search(
                    r"(?i)^(receipt|invoice|tax invoice|gstin|date|payment mode)",
                    candidate,
                )
                and not re.search(r"\d{4,}", candidate)
            ):
                result["merchant"] = candidate[:120]
                break

    # Date extraction
    date_patterns = [
        r"(?i)\b(?:invoice\s+date|receipt\s+date|transaction\s+date|date)\s*[:#-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})",
        r"(?i)\b(?:invoice\s+date|receipt\s+date|transaction\s+date|date)\s*[:#-]?\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
    ]

    for pattern in date_patterns:
        match = re.search(pattern, normalized)

        if not match:
            continue

        raw = match.group(1).strip()

        try:
            if re.match(r"\d{4}-", raw):
                parsed = datetime.strptime(raw, "%Y-%m-%d")

            elif re.search(r"[A-Za-z]", raw):
                parsed = (
                    datetime.strptime(raw, "%d %b %Y")
                    if len(raw.split()[1]) == 3
                    else datetime.strptime(raw, "%d %B %Y")
                )

            else:
                a, b, c = re.split(r"[/-]", raw)

                if len(c) == 2:
                    c = "20" + c

                parsed = datetime(int(c), int(b), int(a))

            result["transaction_date"] = parsed.strftime("%Y-%m-%d")
            break

        except (ValueError, TypeError):
            continue

    # Amount extraction
    amount_patterns = [
        r"(?im)\b(?:grand\s+total|invoice\s+total|total\s+amount|amount\s+due|balance\s+due|total\s+paid|amount\s+paid|net\s+payable)\s*[:\-~=₹$%]*\s*(?:rs\.?|inr)?\s*[₹$%~\-]*\s*([\d,]+(?:\.\d{1,2})?)",
        r"(?im)\btotal\s*[:\-~=₹$%]*\s*(?:rs\.?|inr)?\s*[₹$%~\-]*\s*([\d,]+(?:\.\d{1,2})?)",
    ]

    for pattern in amount_patterns:
        matches = re.findall(pattern, normalized)

        if matches:
            try:
                value = float(matches[-1].replace(",", ""))

                if value > 0:
                    result["amount"] = value
                    break

            except ValueError:
                pass

    # Transaction type
    if re.search(
        r"(?i)\b(receipt|payment\s+mode|thank\s+you\s+for\s+shopping|subtotal)\b", lower
    ):
        result["transaction_type"] = "Expense"

    elif re.search(
        r"(?i)\b(amount\s+received|payment\s+received|sales\s+invoice|customer\s+payment)\b",
        lower,
    ):
        result["transaction_type"] = "Income"

    elif re.search(
        r"(?i)\b(amount\s+paid|payment\s+to|purchase\s+invoice|expense\s+receipt|bill\s+to\s+pay)\b",
        lower,
    ):
        result["transaction_type"] = "Expense"

    result["description"] = next(
        (
            line[:120]
            for line in lines
            if re.search(r"(?i)\b(receipt|invoice|purchase|payment)\b", line)
        ),
        "Purchase",
    )

    populated = sum(
        bool(result[k])
        for k in ["merchant", "description", "transaction_type", "transaction_date"]
    ) + (result["amount"] is not None)

    if result["amount"] is not None and result["transaction_type"]:
        result["document_type"] = "transaction_document"
        result["confidence"] = "high" if populated >= 4 else "medium"

    elif any(word in lower for word in ["invoice", "receipt", "tax invoice"]):
        result["document_type"] = "invoice_or_receipt"

    result["needs_review"] = True

    result["message"] = (
        "Review every suggested field before saving. "
        "Missing or ambiguous fields were left blank."
    )

    return result
