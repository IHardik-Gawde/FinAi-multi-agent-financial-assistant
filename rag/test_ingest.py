from rag.ingest import process_all_pdfs

print("\nTesting multiple PDF ingestion...")

chunks = process_all_pdfs("data/documents")

print("\nIngestion Summary")
print("=" * 40)
print(f"Total chunks: {len(chunks)}")

print("\nFirst chunk preview:")
print(chunks[0][:500])

print("\nMultiple PDF ingestion test completed!")
