from rag.ingest import extract_text_from_pdf

PDF_PATH = "data/documents/mixed_ocr_test.pdf"

print("\nTesting mixed PDF extraction...")

text = extract_text_from_pdf(PDF_PATH)

print("\n========== EXTRACTED TEXT ==========")
print(text)
