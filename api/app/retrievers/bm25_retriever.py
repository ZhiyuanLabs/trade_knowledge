"""
BM25 Keyword Retriever.
Loads the pre-built BM25 index from disk and searches it.
"""

import json
import os
import pickle

from rank_bm25 import BM25Okapi
from dotenv import load_dotenv
from app.utils.tokenizer import tokenize

load_dotenv()

BM25_CORPUS_PATH = os.path.abspath(os.getenv("BM25_CORPUS_PATH", "./data/bm25_corpus.json"))
BM25_INDEX_PATH = os.path.join(os.path.dirname(BM25_CORPUS_PATH), "bm25_index.pkl")
CHUNKS_PATH = os.path.abspath(os.getenv("CHUNKS_PATH", "./data/chunks.json"))

_bm25: BM25Okapi | None = None
_corpus_meta: list[dict] | None = None
_chunks_by_id: dict[str, dict] | None = None


def _load_index():
    global _bm25, _corpus_meta, _chunks_by_id

    if _bm25 is not None:
        return

    if not os.path.exists(BM25_INDEX_PATH):
        raise FileNotFoundError(
            f"BM25 index not found at {BM25_INDEX_PATH}. Run ingestion first."
        )

    with open(BM25_INDEX_PATH, "rb") as f:
        _bm25 = pickle.load(f)

    with open(BM25_CORPUS_PATH) as f:
        _corpus_meta = json.load(f)

    with open(CHUNKS_PATH) as f:
        chunks = json.load(f)
        _chunks_by_id = {c["chunk_id"]: c for c in chunks}


def bm25_search(query: str, top_k: int = 10) -> list[dict]:
    """
    Search the BM25 index with the given query.
    Returns top_k chunks sorted by BM25 score (descending).
    """
    _load_index()

    tokenized_query = tokenize(query)
    scores = _bm25.get_scores(tokenized_query)

    # Get top_k indices sorted by score
    scored = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]

    results = []
    for idx, score in scored:
        if score <= 0:
            continue
        meta = _corpus_meta[idx]
        chunk_id = meta["chunk_id"]
        chunk = _chunks_by_id.get(chunk_id, {})
        results.append({**chunk, "bm25_score": float(score)})

    return results
