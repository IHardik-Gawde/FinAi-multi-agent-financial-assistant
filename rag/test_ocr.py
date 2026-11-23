import fitz
import pytesseract
from PIL import Image
from io import BytesIO
from pypdf import PdfReader

from rag.ingest import extract_text_from_pdf

PDF_PATH = r"data\ocr_data\ocr_test1.pdf"


def test_ocr():
    # Check normal PDF text extraction
    reader = PdfReader(PDF_PATH)

    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text()

        print(f"\nPage {page_number} - PyPDF:")
        print(text if text else "No extractable text found.")

    # Convert PDF pages into images
    doc = fitz.open(PDF_PATH)

    for page_number, page in enumerate(doc, start=1):
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        image = Image.open(BytesIO(pix.tobytes("png")))

        # Extract text using Tesseract
        extracted_text = pytesseract.image_to_string(image, lang="eng")

        print(f"\nPage {page_number} - OCR Result:")
        print(extracted_text)


if __name__ == "__main__":
    test_ocr()
print("\n========== INGEST.PY OCR TEST ==========")

text = extract_text_from_pdf(PDF_PATH)

print(text)
