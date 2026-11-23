from rag.ingest import process_all_pdfs
from rag.vector_store import VectorStore


def update_vector_store():

    print("\n1. Processing all PDFs...")

    chunks = process_all_pdfs("data/documents")

    print("\n2. Creating vector store...")

    vector_store = VectorStore()

    print("\n3. Generating embeddings and adding chunks...")

    vector_store.add_documents(chunks)

    print("\n4. Saving updated vector store...")

    vector_store.save("data/vector_store")

    print("\nVector store updated successfully!")


if __name__ == "__main__":
    update_vector_store()
