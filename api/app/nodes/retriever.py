"""
Node 2 — Retriever
Hybrid search: BM25 + Vector. Merges results using Reciprocal Rank Fusion.
"""

import os
from app.state.schema import GraphState
from app.retrievers import bm25_retriever, vector_retriever
from app.utils.scoring import reciprocal_rank_fusion
from app.utils.logger import get_logger
from dotenv import load_dotenv

load_dotenv()

log = get_logger(__name__)
TOP_K = int(os.getenv("TOP_K_RETRIEVAL", "10"))


def retriever_node(state: GraphState) -> GraphState:
    """
    Executes hybrid retrieval using the Retrieval Specialist's execution plan.
    BM25 uses keyword-optimized queries; Vector uses semantic queries.
    Falls back to rewritten_queries if no plan is present.
    """
    plan = state.get("retrieval_plan")
    fallback_queries = state.get("rewritten_queries", [state["user_query"]])

    if plan:
        bm25_queries = plan.get("bm25_queries") or fallback_queries
        vector_queries = plan.get("vector_queries") or fallback_queries
        strategy = plan.get("strategy", "hybrid")
    else:
        bm25_queries = fallback_queries
        vector_queries = fallback_queries
        strategy = "hybrid"

    log.info("retriever.start", strategy=strategy)

    all_bm25: list[list[dict]] = []
    all_vector: list[list[dict]] = []

    if strategy in ("hybrid", "bm25_only"):
        for query in bm25_queries:
            all_bm25.append(bm25_retriever.bm25_search(query, top_k=TOP_K))

    if strategy in ("hybrid", "vector_only"):
        for query in vector_queries:
            all_vector.append(vector_retriever.vector_search(query, top_k=TOP_K))

    # Flatten and deduplicate within each source
    def dedup(results_lists):
        seen, out = set(), []
        for chunk in [c for r in results_lists for c in r]:
            if chunk["chunk_id"] not in seen:
                seen.add(chunk["chunk_id"])
                out.append(chunk)
        return out

    deduped_bm25 = dedup(all_bm25)
    deduped_vec = dedup(all_vector)

    # Merge with Reciprocal Rank Fusion
    lists_to_fuse = [l for l in [deduped_bm25, deduped_vec] if l]
    fused = reciprocal_rank_fusion(lists_to_fuse, key="chunk_id") if lists_to_fuse else []

    # Accumulate with previous iterations
    existing = state.get("candidate_chunks", [])
    existing_ids = {c["chunk_id"] for c in existing}
    new_chunks = [c for c in fused if c["chunk_id"] not in existing_ids]
    merged = existing + new_chunks

    log.info("retriever.done", new_chunks=len(new_chunks), pool_size=len(merged))

    return {**state, "candidate_chunks": merged}
