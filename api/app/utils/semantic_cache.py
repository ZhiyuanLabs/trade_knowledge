"""
Semantic Caching Layer

Intercepts user queries to return immediate responses for previously answered questions
or semantically matched equivalent queries. Relies on ChromaDB and SentenceTransformers.
"""

import os
import json
import hashlib

import chromadb
from dotenv import load_dotenv

from app.state.schema import GraphState
from app.utils.logger import get_logger
from app.utils.model_registry import get_embedding_model

log = get_logger(__name__)

load_dotenv()

CHROMA_PATH = os.path.abspath(os.getenv("CHROMA_PATH", "./data/chroma_db"))
CACHE_COLLECTION_NAME = "semantic_cache"

_cache_collection = None

def _get_cache_collection():
    global _cache_collection
    if _cache_collection is None:
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        # Create or Get collection
        _cache_collection = client.get_or_create_collection(CACHE_COLLECTION_NAME)
    return _cache_collection

def check_semantic_cache(user_query: str, threshold: float = 0.95) -> dict | None:
    """
    Checks if the user query is semantically identical or extremely similar to a past query.
    Returns the parsed state dictionary (cache hit) or None (cache miss).
    """
    try:
        collection = _get_cache_collection()
        if collection.count() == 0:
            return None
        
        embedder = get_embedding_model()
        query_vec = embedder.encode([user_query])[0].tolist()

        # Search for the best match (top 1)
        results = collection.query(
            query_embeddings=[query_vec],
            n_results=1,
            include=["metadatas", "distances"]
        )

        if not results["ids"] or not results["ids"][0]:
            return None

        # Chroma uses cosine distances (0 is perfect match, 1 is orthogonal)
        distance = results["distances"][0][0]
        similarity = 1.0 - distance

        if similarity >= threshold:
            log.info("cache.hit", similarity=round(similarity, 3))
            metadata = results["metadatas"][0][0]
            current_evidence_score = float(metadata.get("evidence_score", 0.0))
            best_evidence_score = float(
                metadata.get("best_evidence_score", current_evidence_score)
            )
            
            # Reconstruct the GraphState dictionary. Only catalog queries are
            # cached, so route defaults to "catalog"; business_result is stored
            # as a JSON string for completeness.
            br_raw = metadata.get("business_result")
            try:
                business_result = json.loads(br_raw) if br_raw else None
            except (TypeError, ValueError):
                business_result = None

            cached_state = {
                "user_query": user_query,
                "route": metadata.get("route", "catalog") or "catalog",
                "business_result": business_result,
                "final_answer": metadata.get("final_answer", ""),
                "citations": json.loads(metadata.get("citations", "[]")),
                "evidence_score": current_evidence_score,
                "best_evidence_score": best_evidence_score,
                "_from_cache": True
            }
            return cached_state

        log.debug("cache.miss", similarity=round(similarity, 3), threshold=threshold)
        return None

    except Exception as e:
        log.warning("cache.check_error", error=str(e))
        return None

def save_to_semantic_cache(user_query: str, final_state: dict) -> None:
    """
    Saves a finalized query and its final answer into the semantic cache vector DB.
    """
    try:
        if final_state.get("_from_cache"): return # Avoid caching cached items

        answer = final_state.get("final_answer")

        # Don't cache broken/empty answers
        if not answer or "Error" in answer: return

        # Never cache a "no evidence / not found" fallback. A failed retrieval
        # (e.g. an empty planner result) would otherwise be permanently
        # remembered and keep returning the empty answer to every semantically
        # similar future query. A successful answer always carries at least
        # document citations OR a business result.
        has_citations = bool(final_state.get("citations"))
        has_business_result = bool(final_state.get("business_result"))
        if not has_citations and not has_business_result:
            log.info("cache.skip_empty_evidence", query_preview=user_query[:60])
            return

        collection = _get_cache_collection()
        embedder = get_embedding_model()
        
        # Generate hash id based on exact text query
        query_id = hashlib.sha256(user_query.encode("utf-8")).hexdigest()
        
        query_vec = embedder.encode([user_query])[0].tolist()
        
        # Prepare metadata (Chroma allows str/int/float/bool; nested values are
        # stored as JSON strings).
        route = final_state.get("route") or "catalog"
        metadata = {
            "final_answer": answer,
            "citations": json.dumps(final_state.get("citations", []), ensure_ascii=False),
            "route": route,
            "business_result": json.dumps(
                final_state.get("business_result") or None, ensure_ascii=False
            ),
            "evidence_score": float(final_state.get("evidence_score", 0.0)),
            "best_evidence_score": float(
                final_state.get("best_evidence_score", final_state.get("evidence_score", 0.0))
            ),
        }

        # Upsert into Cache Collection
        collection.upsert(
            ids=[query_id],
            embeddings=[query_vec],
            documents=[user_query],
            metadatas=[metadata]
        )
        log.info("cache.saved", query_preview=user_query[:60])

    except Exception as e:
        log.warning("cache.save_error", error=str(e))
