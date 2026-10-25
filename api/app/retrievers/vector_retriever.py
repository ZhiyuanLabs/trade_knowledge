"""
Vector (Semantic) Retriever.
Uses ChromaDB + sentence-transformers for similarity search.
"""

import os

import chromadb
from dotenv import load_dotenv
from app.utils.model_registry import get_embedding_model

load_dotenv()

CHROMA_PATH = os.path.abspath(os.getenv("CHROMA_PATH", "./data/chroma_db"))
COLLECTION_NAME = "catalog_docs"

_collection = None


def _get_collection():
    global _collection
    if _collection is None:
        if not os.path.exists(CHROMA_PATH):
            raise FileNotFoundError(
                f"ChromaDB not found at {CHROMA_PATH}. Run ingestion first."
            )
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = client.get_collection(COLLECTION_NAME)
    return _collection

def vector_search(query: str, top_k: int = 10) -> list[dict]:
    """
    Embed the query and search ChromaDB for nearest neighbors.
    Returns top_k chunks with cosine similarity scores.
    """
    embedder = get_embedding_model()
    query_vec = embedder.encode([query])[0].tolist()

    collection = _get_collection()
    results = collection.query(
        query_embeddings=[query_vec],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    ids = results["ids"][0]
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    distances = results["distances"][0]

    for chunk_id, doc, meta, dist in zip(ids, docs, metas, distances):
        # ChromaDB cosine distance → similarity: 1 - distance
        similarity = 1.0 - dist
        chunks.append({
            "chunk_id": chunk_id,
            "doc_id": meta.get("doc_id", ""),
            "title": meta.get("title", ""),
            "section": meta.get("section", ""),
            "content": doc,
            "source": meta.get("source", "product catalog"),
            "file_path": meta.get("file_path", ""),
            "tokens": meta.get("tokens", 0),
            "vector_score": float(similarity),
        })

    return chunks
