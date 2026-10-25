"""
Evidence Memory — runtime store for evidence accumulated across iterations.
Currently implemented as in-state accumulation (GraphState is the memory).
This module provides helper utilities for querying and summarizing evidence.
"""

from app.state.schema import EvidenceItem


def get_top_evidence(evidence_items: list[EvidenceItem], top_k: int = 5) -> list[EvidenceItem]:
    """Return evidence items sorted by confidence, descending."""
    return sorted(evidence_items, key=lambda e: e["confidence"], reverse=True)[:top_k]


def compute_coverage_score(evidence_items: list[EvidenceItem]) -> float:
    """
    Aggregate evidence score: weighted mean of confidence values.
    High-confidence items get more weight.
    """
    if not evidence_items:
        return 0.0
    total = sum(e["confidence"] ** 2 for e in evidence_items)
    denom = sum(e["confidence"] for e in evidence_items)
    return total / denom if denom > 0 else 0.0


def format_evidence_for_prompt(evidence_items: list[EvidenceItem], max_items: int = 6) -> str:
    """Format top evidence as a readable string for LLM prompts."""
    top = get_top_evidence(evidence_items, top_k=max_items)
    lines = []
    for i, ev in enumerate(top):
        lines.append(
            f"[{i+1}] ({ev['file_path']}, conf={ev['confidence']:.2f})\n"
            f"  Claims: {'; '.join(ev['claims']) or 'N/A'}\n"
            f"  Excerpt: {ev['content'][:300]}..."
        )
    return "\n\n".join(lines)
