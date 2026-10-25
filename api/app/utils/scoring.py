"""
Score normalization and fusion utilities.
Used during hybrid retrieval merging.
"""


def normalize_scores(scores: list[float]) -> list[float]:
    """Min-max normalize a list of scores to [0, 1]."""
    if not scores:
        return []
    min_s = min(scores)
    max_s = max(scores)
    if max_s == min_s:
        return [1.0 for _ in scores]
    return [(s - min_s) / (max_s - min_s) for s in scores]


def reciprocal_rank_fusion(
    results_lists: list[list[dict]],
    key: str = "chunk_id",
    k: int = 60,
) -> list[dict]:
    """
    Fuse multiple ranked lists using Reciprocal Rank Fusion (RRF).
    Each results_list is a list of dicts with at least a `key` field.
    Returns a deduplicated, fused list sorted by RRF score (descending).
    """
    scores: dict[str, float] = {}
    docs: dict[str, dict] = {}

    for result_list in results_lists:
        for rank, doc in enumerate(result_list):
            doc_id = doc[key]
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
            docs[doc_id] = doc  # keep the most recent version

    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    fused = []
    for doc_id in sorted_ids:
        doc = docs[doc_id].copy()
        doc["rrf_score"] = scores[doc_id]
        fused.append(doc)

    return fused
