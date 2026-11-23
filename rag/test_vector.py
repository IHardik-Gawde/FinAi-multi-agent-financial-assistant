from rag.document_manager import get_vector_store

store = get_vector_store()

results = store.search(
    "Redwood Agritech customer invoices pending payment invoice amount status", top_k=5
)

print("\nRETRIEVAL RESULTS:", len(results))

for i, result in enumerate(results):
    print(f"\n--- RESULT {i + 1} ---")
    print("SOURCE:", result["source"])
    print("SCORE:", result["score"])
    print("METADATA:", result["metadata"])
    print("TEXT:", result["text"])
