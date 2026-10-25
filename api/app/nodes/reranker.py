"""
Node 3 — Reranker
Re-scores candidate chunks using a weighted composite score (BM25 + vector).
Returns top-K for the chunk reader.
Phase 2: replace with cross-encoder (sentence-transformers) without API changes.
"""

import os
from app.state.schema import GraphState
from app.utils.logger import get_logger
from app.utils.model_registry import get_reranker_model
from dotenv import load_dotenv

load_dotenv()

log = get_logger(__name__)
TOP_K_RERANK = int(os.getenv("TOP_K_RERANK", "5"))
# The product catalog is a closed-domain knowledge base; web fallback is
# disabled by default so answers never pull in unrelated public web pages.
WEB_FALLBACK_ENABLED = os.getenv("WEB_FALLBACK_ENABLED", "false").strip().lower() in ("1", "true", "yes")

def reranker_node(state: GraphState) -> GraphState:
    """
    Reranks candidate_chunks using a Cross-Encoder for higher accuracy.
    Evaluates the pair (active_query, chunk_content).
    Returns top-K as ranked_chunks.
    """
    candidates = state.get("candidate_chunks", [])
    
    # We use the currently active sub-question as the context for reranking
    active_queries = state.get("rewritten_queries", [])
    query = active_queries[0] if active_queries else state["user_query"]

    if not candidates:
        log.warning("reranker.no_candidates")
        return {**state, "ranked_chunks": []}

    model = get_reranker_model()
    
    # Prepare query-document pairs
    # Note: CrossEncoders perform better when scoring the most relevant content
    pairs = [[query, chunk.get("content", "")] for chunk in candidates]
    
    # Perform batched prediction
    scores = model.predict(pairs)
    
    scored = []
    for chunk, score in zip(candidates, scores):
        scored.append({**chunk, "rerank_score": float(score)})

    scored.sort(key=lambda x: x["rerank_score"], reverse=True)
    
    # ── Optional Web Fallback (disabled for closed-domain catalogs) ──
    best_score = scored[0]["rerank_score"] if scored else -99.0

    if best_score < 0.0 and WEB_FALLBACK_ENABLED:
        log.warning("reranker.low_score_web_fallback", best_score=round(best_score, 3))
        try:
            from ddgs import DDGS
            web_results = DDGS().text(query, max_results=TOP_K_RERANK)

            web_chunks = []
            for i, res in enumerate(web_results):
                web_chunks.append({
                    "chunk_id": f"web_fallback_{i}",
                    "doc_id": "Web Search",
                    "title": res.get("title", "Web Result"),
                    "section": "DuckDuckGo Fallback",
                    "content": res.get("body", ""),
                    "source": "web_fallback",
                    "file_path": res.get("href", "URL"),
                    "tokens": len(res.get("body", "")) // 4,
                    "vector_score": 1.0,
                    "rerank_score": 10.0 - (i * 0.1),
                    "source_type": "web_fallback",
                })

            if web_chunks:
                log.info("reranker.web_fallback_done", chunks=len(web_chunks))
                return {**state, "ranked_chunks": web_chunks}
        except Exception as e:
            log.error("reranker.web_fallback_error", error=str(e))
    elif best_score < 0.0:
        # Closed-domain: keep the locally most relevant chunks (relative ranking).
        log.info("reranker.local_only_low_score", best_score=round(best_score, 3),
                 note="web fallback disabled; using local catalog chunks")
    # ──────────────────────────────────────────────────────────────

    top_k = scored[:TOP_K_RERANK]

    log.info("reranker.done", selected=len(top_k), total_candidates=len(candidates), best_score=round(best_score, 3))

    return {**state, "ranked_chunks": top_k}
