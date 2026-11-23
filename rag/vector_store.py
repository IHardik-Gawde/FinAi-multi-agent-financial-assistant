import faiss
import pickle
import re
import numpy as np
from pathlib import Path
from sentence_transformers import SentenceTransformer


class VectorStore:
    def __init__(self, model_name="BAAI/bge-base-en-v1.5"):

        self.model = SentenceTransformer(model_name, device="cuda")

        self.index = None
        self.documents = []
        self.document_ids = []
        # One metadata dictionary for every indexed chunk, aligned by position.
        self.chunk_metadata = []
        self.has_chunk_metadata = False

    def initialize_index(self, dimension):
        """Create an ID-mapped FAISS index."""

        base_index = faiss.IndexFlatIP(dimension)
        self.index = faiss.IndexIDMap2(base_index)

    def add_document(self, pdf_name, chunks, document_metadata=None):
        """Add text chunks and their metadata from one document.

        Each chunk may be a string or a dictionary containing ``text`` and
        ``metadata``. Document-level metadata is inherited by every chunk.
        """
        if not chunks:
            print(f"No chunks found for {pdf_name}.")
            return

        document_metadata = dict(document_metadata or {})
        chunk_texts = []
        supplied_metadata = []

        for chunk in chunks:
            if isinstance(chunk, dict):
                chunk_texts.append(str(chunk.get("text", "")))
                supplied_metadata.append(dict(chunk.get("metadata") or {}))
            else:
                chunk_texts.append(str(chunk))
                supplied_metadata.append({})

        valid = [
            (text, metadata)
            for text, metadata in zip(chunk_texts, supplied_metadata)
            if text.strip()
        ]
        if not valid:
            print(f"No non-empty chunks found for {pdf_name}.")
            return

        chunk_texts = [item[0] for item in valid]
        supplied_metadata = [item[1] for item in valid]

        embeddings = self.model.encode(
            chunk_texts,
            convert_to_numpy=True,
            show_progress_bar=False,
            normalize_embeddings=True,
        )

        embeddings = np.asarray(embeddings, dtype="float32")

        if self.index is None:
            self.initialize_index(embeddings.shape[1])

        # Generate unique IDs for the new chunks.
        start_id = max((chunk_id for chunk_id, _ in self.document_ids), default=0) + 1

        chunk_ids = np.arange(start_id, start_id + len(chunks), dtype="int64")

        self.index.add_with_ids(embeddings, chunk_ids)

        self.documents.extend(chunk_texts)
        self.document_ids.extend([(int(chunk_id), pdf_name) for chunk_id in chunk_ids])

        for chunk_id, chunk_meta in zip(chunk_ids, supplied_metadata):
            metadata = {
                **document_metadata,
                **chunk_meta,
                "source": pdf_name,
                "chunk_id": int(chunk_id),
            }
            metadata.setdefault("company", None)
            metadata.setdefault("document_type", "unknown")
            metadata.setdefault("page_number", None)
            self.chunk_metadata.append(metadata)

        self.has_chunk_metadata = True
        print(f"Added {len(chunk_texts)} chunks from {pdf_name}.")

    def remove_document(self, pdf_name):
        """Remove all chunks belonging to one PDF."""

        ids_to_remove = [
            chunk_id for chunk_id, source in self.document_ids if source == pdf_name
        ]

        if not ids_to_remove:
            return

        self.index.remove_ids(np.asarray(ids_to_remove, dtype="int64"))

        retained = [
            (document, document_id, chunk_metadata)
            for document, document_id, chunk_metadata in zip(
                self.documents, self.document_ids, self.chunk_metadata
            )
            if document_id[1] != pdf_name
        ]

        self.documents = [item[0] for item in retained]
        self.document_ids = [item[1] for item in retained]
        self.chunk_metadata = [item[2] for item in retained]

        print(f"Removed {len(ids_to_remove)} chunks from {pdf_name}.")

    def find_sources_for_entities(self, entities):
        """
        Find indexed source documents for full or conversational entity names.

        Matching ignores case, punctuation, and spacing. A short first-name
        alias is accepted only when it is unambiguous among the requested
        entities.
        """
        source_text = {}
        for document, (_, source) in zip(self.documents, self.document_ids):
            source_text.setdefault(source, []).append(str(document))

        def compact(value):
            return re.sub(r"[^a-z0-9]+", "", str(value).casefold())

        aliases_by_entity = {}
        alias_owners = {}
        for entity in entities:
            full_alias = compact(entity)
            aliases = {full_alias} if full_alias else set()

            words = re.findall(r"[a-z0-9]+", str(entity).casefold())
            # A conversational first-name alias is useful for names such as
            # "Redwood Agritech", but only if it is distinctive enough.
            if words and len(compact(words[0])) >= 6:
                aliases.add(compact(words[0]))

            aliases_by_entity[entity] = aliases
            for alias in aliases:
                alias_owners.setdefault(alias, set()).add(entity)

        matches = {}
        for entity, aliases in aliases_by_entity.items():
            eligible_aliases = [
                alias
                for alias in aliases
                if len(alias) >= 6 and len(alias_owners.get(alias, ())) == 1
            ]
            entity_sources = []
            for source, chunks in source_text.items():
                content = compact(" ".join(chunks))
                if any(alias in content for alias in eligible_aliases):
                    entity_sources.append(source)
            matches[entity] = entity_sources

        return matches

    def find_sources_for_entity(self, entity):
        """Find documents containing one requested entity."""
        return self.find_sources_for_entities([entity]).get(entity, [])

    def search(self, query, top_k=5, allowed_sources=None):
        """
        Search for the most relevant chunks.

        If allowed_sources is provided, only chunks from those source
        documents are eligible for the top_k results.
        """

        if self.index is None or self.index.ntotal == 0:
            raise ValueError("Vector store is empty. Add documents first.")

        if top_k <= 0:
            raise ValueError("top_k must be greater than zero.")

        query_embedding = self.model.encode(
            [query],
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        query_embedding = np.asarray(query_embedding, dtype="float32")

        id_to_document = {
            chunk_id: (document, source, chunk_metadata)
            for document, (chunk_id, source), chunk_metadata in zip(
                self.documents, self.document_ids, self.chunk_metadata
            )
        }

        # Search globally when no source filter is supplied.
        if allowed_sources is None:
            search_k = min(top_k, self.index.ntotal)
            scores, indices = self.index.search(query_embedding, search_k)

        else:
            allowed_sources = set(allowed_sources)
            allowed_ids = {
                chunk_id
                for chunk_id, source in self.document_ids
                if source in allowed_sources
            }

            if not allowed_ids:
                return []

            # FAISS returns candidates in descending similarity order.
            # Filter those ranked candidates by source, then keep top_k.
            scores, indices = self.index.search(
                query_embedding,
                self.index.ntotal,
            )

            filtered_results = [
                (float(score), int(chunk_id))
                for score, chunk_id in zip(scores[0], indices[0])
                if chunk_id != -1 and int(chunk_id) in allowed_ids
            ][:top_k]

            return [
                {
                    "text": id_to_document[chunk_id][0],
                    "source": id_to_document[chunk_id][1],
                    "metadata": id_to_document[chunk_id][2],
                    "score": score,
                }
                for score, chunk_id in filtered_results
            ]

        results = []
        for score, chunk_id in zip(scores[0], indices[0]):
            if chunk_id == -1:
                continue

            document, source, chunk_metadata = id_to_document[int(chunk_id)]
            results.append(
                {
                    "text": document,
                    "source": source,
                    "metadata": chunk_metadata,
                    "score": float(score),
                }
            )

        return results

    def save(self, directory="data/vector_store"):

        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        if self.index is None:
            raise ValueError("Cannot save an empty vector store.")

        faiss.write_index(self.index, str(directory / "finance.index"))

        with open(directory / "documents.pkl", "wb") as file:
            pickle.dump(
                {
                    "documents": self.documents,
                    "document_ids": self.document_ids,
                    "chunk_metadata": self.chunk_metadata,
                },
                file,
            )

        print(f"Vector store saved to: {directory}")

    def load(self, directory="data/vector_store"):

        directory = Path(directory)

        index_path = directory / "finance.index"
        documents_path = directory / "documents.pkl"

        if not index_path.exists() or not documents_path.exists():
            raise FileNotFoundError("Saved vector store files not found.")

        self.index = faiss.read_index(str(index_path))

        with open(documents_path, "rb") as file:
            saved_data = pickle.load(file)

        self.documents = saved_data["documents"]
        self.document_ids = saved_data["document_ids"]
        self.has_chunk_metadata = "chunk_metadata" in saved_data
        self.chunk_metadata = saved_data.get("chunk_metadata", [])

        # Backward compatibility for older saved stores. The document manager
        # will re-index legacy stores so each chunk receives complete metadata.
        if not self.chunk_metadata and self.documents:
            self.chunk_metadata = [
                {
                    "source": source,
                    "chunk_id": int(chunk_id),
                    "company": None,
                    "document_type": "unknown",
                    "page_number": None,
                }
                for chunk_id, source in self.document_ids
            ]

        if self.index.ntotal != len(self.documents):
            raise ValueError("FAISS index and document count do not match.")

        if len(self.documents) != len(self.document_ids):
            raise ValueError("Document ID count does not match.")

        if len(self.documents) != len(self.chunk_metadata):
            raise ValueError("Chunk metadata count does not match.")
