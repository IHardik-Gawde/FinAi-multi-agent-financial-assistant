from pathlib import Path

from rag.ingest import process_all_pdfs
from rag.vector_store import VectorStore


pdf_path = Path("data/documents/sample_financial_report.pdf")

print("\n1. Processing PDF...")
chunks = process_all_pdfs("data/documents")

print("\n2. Creating vector store...")
vector_store = VectorStore()

print("\n3. Adding document chunks...")
vector_store.add_documents(chunks)

print("\n4. Saving vector store...")
vector_store.save()

print("\n5. Creating a fresh vector store...")
new_store = VectorStore()

print("\n6. Loading saved index...")
new_store.load()

print("\n7. Testing retrieval...")

query = "What was the total revenue in October 2026?"

results = new_store.search(query, top_k=2)

for i, result in enumerate(results, start=1):
    print(f"\nResult {i} | Score: {result['score']:.4f}")
    print(result["text"][:300])

print("\nPersistence test completed!")
