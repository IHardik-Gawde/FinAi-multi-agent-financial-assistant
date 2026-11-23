from pathlib import Path
import json

from rag.ingest import process_document
from rag.vector_store import VectorStore


DOCUMENT_DIR = Path("data/documents")
METADATA_FILE = Path("data/vector_store/document_metadata.json")
VECTOR_STORE_DIR = Path("data/vector_store")

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".csv",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
}

_vector_store = None


def get_document_metadata():
    """Get the current list of supported documents and their details."""

    DOCUMENT_DIR.mkdir(parents=True, exist_ok=True)

    metadata = {}

    for file_path in DOCUMENT_DIR.iterdir():
        if not file_path.is_file():
            continue

        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        metadata[file_path.name] = {
            "size": file_path.stat().st_size,
            "modified": file_path.stat().st_mtime,
        }

    return metadata


def load_saved_metadata():
    """Load metadata from the previous indexing operation."""

    if not METADATA_FILE.exists():
        return {}

    with open(METADATA_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def save_metadata(metadata):
    """Persist document metadata."""

    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(METADATA_FILE, "w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=4)


def index_all_documents(metadata):
    """Build the FAISS index from all supported documents."""

    vector_store = VectorStore()

    for document_name in metadata:
        document_path = DOCUMENT_DIR / document_name

        print(f"[INDEX] Processing {document_name}")

        chunks = process_document(document_path)

        vector_store.add_document(document_name, chunks)

    if vector_store.index is None:
        dimension = vector_store.model.get_sentence_embedding_dimension()
        vector_store.initialize_index(dimension)

    vector_store.save(VECTOR_STORE_DIR)
    save_metadata(metadata)

    return vector_store


def update_vector_store(current_metadata, saved_metadata):
    """Update only new, modified, or deleted documents."""

    global _vector_store

    new_files = set(current_metadata) - set(saved_metadata)

    deleted_files = set(saved_metadata) - set(current_metadata)

    modified_files = {
        name
        for name in set(current_metadata) & set(saved_metadata)
        if current_metadata[name] != saved_metadata[name]
    }

    if not new_files and not deleted_files and not modified_files:
        return _vector_store

    for document_name in sorted(deleted_files):
        print(f"[INDEX] Removing {document_name}")

        _vector_store.remove_document(document_name)

    for document_name in sorted(modified_files):
        print(f"[INDEX] Updating {document_name}")

        _vector_store.remove_document(document_name)

        chunks = process_document(DOCUMENT_DIR / document_name)

        _vector_store.add_document(document_name, chunks)

    for document_name in sorted(new_files):
        print(f"[INDEX] Adding {document_name}")

        chunks = process_document(DOCUMENT_DIR / document_name)

        _vector_store.add_document(document_name, chunks)

    _vector_store.save(VECTOR_STORE_DIR)
    save_metadata(current_metadata)

    return _vector_store


def get_vector_store():
    """Return an up-to-date persistent FAISS vector store."""

    global _vector_store

    current_metadata = get_document_metadata()
    saved_metadata = load_saved_metadata()

    index_path = VECTOR_STORE_DIR / "finance.index"
    documents_path = VECTOR_STORE_DIR / "documents.pkl"

    if (
        not index_path.exists()
        or not documents_path.exists()
        or not METADATA_FILE.exists()
    ):
        _vector_store = index_all_documents(current_metadata)
        return _vector_store

    if _vector_store is None:
        _vector_store = VectorStore()

        try:
            _vector_store.load(VECTOR_STORE_DIR)

            if not _vector_store.has_chunk_metadata:
                print(
                    "[INDEX] Legacy vector store detected; rebuilding with chunk metadata."
                )
                _vector_store = index_all_documents(current_metadata)
                return _vector_store

        except (TypeError, KeyError):
            _vector_store = index_all_documents(current_metadata)
            return _vector_store

    _vector_store = update_vector_store(
        current_metadata,
        saved_metadata,
    )

    return _vector_store
