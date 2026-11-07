from __future__ import annotations

from pathlib import Path
from typing import List, Dict, Any, Optional

import chromadb

from rag.chunks import Chunk


import os

# Configuration
COLLECTION = "hr_policy_sections"
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
BGE_MODEL = "BAAI/bge-m3"
MODEL = os.getenv("EMBEDDING_MODEL", DEFAULT_MODEL)


def client_at(directory: Path):
    """Create a persistent ChromaDB client."""

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    return chromadb.PersistentClient(path=str(directory))


_CACHED_EMBEDDERS: Dict[str, Any] = {}


def embedder(model_name: Optional[str] = None):
    """Load and cache the BGE-M3 or sentence-transformer embedding model locally."""

    from sentence_transformers import SentenceTransformer

    target = model_name or os.getenv("EMBEDDING_MODEL") or MODEL
    if target in _CACHED_EMBEDDERS:
        return _CACHED_EMBEDDERS[target]

    # Try local cache first to avoid hanging on HuggingFace network requests
    try:
        model = SentenceTransformer(target, device="cpu", local_files_only=True)
        _CACHED_EMBEDDERS[target] = model
        return model
    except Exception:
        pass

    try:
        model = SentenceTransformer(target, device="cpu")
        _CACHED_EMBEDDERS[target] = model
        return model
    except Exception:
        # Graceful fallback to default local sentence-transformer if target is unavailable
        try:
            model = SentenceTransformer(DEFAULT_MODEL, device="cpu", local_files_only=True)
            _CACHED_EMBEDDERS[target] = model
            return model
        except Exception:
            model = SentenceTransformer(DEFAULT_MODEL, device="cpu")
            _CACHED_EMBEDDERS[target] = model
            return model


def rebuild(
    chunks: List[Chunk],
    directory: Path,
    model=None
) -> int:
    """Rebuild the policy vector index."""

    if not chunks:
        raise ValueError("No policy chunks to index")

    if model is None:
        model = embedder()

    client = client_at(directory)

    # Check whether the collection already exists.
    existing_collections = client.list_collections()

    existing_names = [
        collection.name
        if hasattr(collection, "name")
        else collection
        for collection in existing_collections
    ]

    # Delete the previous collection only when it exists.
    if COLLECTION in existing_names:
        client.delete_collection(name=COLLECTION)

    # Create a new collection.
    collection = client.create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"}
    )

    batch_size = 64

    for start in range(0, len(chunks), batch_size):

        batch = chunks[start:start + batch_size]

        # Generate embeddings.
        texts = [chunk.text for chunk in batch]

        vectors = model.encode(
            texts,
            normalize_embeddings=True
        ).tolist()

        # Prepare metadata.
        metadata = []

        for chunk in batch:
            metadata.append(
                {
                    "policy_id": chunk.policy_id,
                    "title": chunk.title,
                    "version": chunk.version,
                    "section": chunk.section,
                    "effective_from": chunk.effective_from,
                    "effective_to": chunk.effective_to,
                    "is_active": int(chunk.is_active),
                    "source": chunk.source,
                    "page": chunk.page if chunk.page is not None else 1,
                }
            )

        # Store vectors and documents.
        collection.add(
            ids=[chunk.id for chunk in batch],
            documents=texts,
            embeddings=vectors,
            metadatas=metadata
        )

    return collection.count()


def search(
    question: str,
    directory: Path,
    model=None,
    n: int = 4,
    policy_ids: Optional[List[int]] = None
) -> List[Dict[str, Any]]:
    """Retrieve relevant policy chunks using semantic search."""

    if not question.strip():
        return []

    if not policy_ids:
        return []

    if n <= 0:
        return []

    if model is None:
        model = embedder()

    client = client_at(directory)

    # Return no results if the index has not been created.
    existing_collections = client.list_collections()

    existing_names = [
        collection.name
        if hasattr(collection, "name")
        else collection
        for collection in existing_collections
    ]

    if COLLECTION not in existing_names:
        return []

    collection = client.get_collection(name=COLLECTION)

    count = collection.count()

    if count == 0:
        return []

    # Convert the question into an embedding.
    query_vector = model.encode(
        [question],
        normalize_embeddings=True
    ).tolist()[0]

    # Search only the applicable policy versions.
    results = collection.query(
        query_embeddings=[query_vector],
        n_results=min(n, count),
        where={
            "policy_id": {
                "$in": policy_ids
            }
        },
        include=[
            "documents",
            "metadatas",
            "distances"
        ]
    )

    # Convert ChromaDB results into a readable structure.
    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    output = []

    for document, metadata, distance in zip(
        documents,
        metadatas,
        distances
    ):
        output.append(
            {
                "text": document,
                "metadata": metadata,
                "distance": distance
            }
        )

    return output