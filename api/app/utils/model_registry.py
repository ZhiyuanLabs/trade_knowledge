"""
Shared runtime model registry.

Keeps heavyweight local models loaded once per process without changing
the trade_knowledge graph flow.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv
from sentence_transformers import CrossEncoder, SentenceTransformer

from app.utils.logger import get_logger

load_dotenv()

log = get_logger(__name__)

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    """Load the sentence-transformers embedding model once per process."""
    log.info("models.embedding.loading", model=EMBEDDING_MODEL)
    return SentenceTransformer(EMBEDDING_MODEL)


@lru_cache(maxsize=1)
def get_reranker_model() -> CrossEncoder:
    """Load the reranker model once per process."""
    log.info("models.reranker.loading", model=RERANKER_MODEL)
    return CrossEncoder(RERANKER_MODEL)


def preload_runtime_models() -> None:
    """Warm local models during API startup to reduce first-request latency."""
    get_embedding_model()
    get_reranker_model()
