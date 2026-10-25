"""
Step 4 — Index chunks into ChromaDB (local sentence-transformers embeddings)
and BM25 (keyword index). Run once before starting the API.

Usage:
    python -m ingestion.indexer
"""

import json
import os
import pickle

import chromadb
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv
from app.utils.tokenizer import tokenize

load_dotenv()

CHROMA_PATH = os.path.abspath(os.getenv("CHROMA_PATH", "./data/chroma_db"))
CHUNKS_PATH = os.path.abspath(os.getenv("CHUNKS_PATH", "./data/chunks.json"))
BM25_CORPUS_PATH = os.path.abspath(os.getenv("BM25_CORPUS_PATH", "./data/bm25_corpus.json"))
BM25_INDEX_PATH = os.path.join(os.path.dirname(BM25_CORPUS_PATH), "bm25_index.pkl")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBED_BATCH_SIZE = 256  # sentence-transformers can handle larger batches
COLLECTION_NAME = "catalog_docs"

_embedder: SentenceTransformer | None = None


_log = None

def _get_log():
    global _log
    if _log is None:
        from app.utils.logger import get_logger
        _log = get_logger(__name__)
    return _log


def get_embedder() -> SentenceTransformer:
    """Lazy-load the embedding model (downloads once, cached locally)."""
    global _embedder
    if _embedder is None:
        _get_log().info("indexer.loading_embedder", model=EMBEDDING_MODEL)
        _embedder = SentenceTransformer(EMBEDDING_MODEL)
    return _embedder


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = get_embedder()
    vecs = model.encode(texts, show_progress_bar=False, batch_size=EMBED_BATCH_SIZE)
    return vecs.tolist()


def build_bm25_index(chunks: list[dict]) -> None:
    """Tokenize chunks and persist BM25 index."""
    log = _get_log()
    log.info("indexer.bm25_start", chunks=len(chunks))
    tokenized = [tokenize(c["content"]) for c in chunks]
    bm25 = BM25Okapi(tokenized)

    corpus_meta = [
        {"chunk_id": c["chunk_id"], "tokens": tokenize(c["content"])}
        for c in chunks
    ]
    os.makedirs(os.path.dirname(BM25_CORPUS_PATH), exist_ok=True)
    with open(BM25_CORPUS_PATH, "w") as f:
        json.dump(corpus_meta, f)

    with open(BM25_INDEX_PATH, "wb") as f:
        pickle.dump(bm25, f)

    log.info("indexer.bm25_done", path=BM25_INDEX_PATH)


def build_vector_index(chunks: list[dict]) -> None:
    """Embed all chunks and upsert into ChromaDB."""
    os.makedirs(CHROMA_PATH, exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    log = _get_log()
    total = len(chunks)
    log.info("indexer.embedding_start", total=total)

    for i in range(0, total, EMBED_BATCH_SIZE):
        batch = chunks[i : i + EMBED_BATCH_SIZE]
        texts = [c["content"] for c in batch]
        embeddings = embed_texts(texts)

        collection.add(
            ids=[c["chunk_id"] for c in batch],
            embeddings=embeddings,
            documents=texts,
            metadatas=[
                {
                    "doc_id": c["doc_id"],
                    "title": c["title"],
                    "section": c["section"],
                    "source": c["source"],
                    "file_path": c["file_path"],
                    "tokens": c["tokens"],
                }
                for c in batch
            ],
        )
        done = min(i + EMBED_BATCH_SIZE, total)
        log.info("indexer.embedding_progress", done=done, total=total)

    log.info("indexer.chroma_done", path=CHROMA_PATH)


def run_ingestion() -> None:
    from ingestion.parser import parse_docs
    from ingestion.chunker import chunk_sections

    docs_dir = os.path.abspath(os.getenv("DOCS_DIR", "./data_docs"))
    raw_sections = parse_docs(docs_dir)
    if not raw_sections:
        raise RuntimeError(
            f"No parseable documents found in {docs_dir}. Put .md/.txt/.pdf files there."
        )
    chunks = chunk_sections(raw_sections)

    os.makedirs(os.path.dirname(CHUNKS_PATH), exist_ok=True)
    with open(CHUNKS_PATH, "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)
    _get_log().info("indexer.chunks_persisted", path=CHUNKS_PATH, count=len(chunks))

    build_bm25_index(chunks)
    build_vector_index(chunks)

    _get_log().info("indexer.ingestion_complete")


if __name__ == "__main__":
    run_ingestion()
