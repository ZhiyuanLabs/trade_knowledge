"""
Node 4 — Chunk Reader (Evidence Extractor)
Transforms ranked chunks into structured EvidenceItems.
Uses the LLM to extract key claims from each chunk.
"""

import json
import os
from app.memory.evidence_store import compute_coverage_score
from app.state.schema import GraphState, EvidenceItem
from app.utils.llm import chat
from app.utils.logger import get_logger

log = get_logger(__name__)

# Word-based limit avoids cutting in the middle of code blocks.
# ~400 words ≈ 500-600 tokens for technical English — safe for most LLM context windows.
_CHUNK_MAX_WORDS = int(os.getenv("CHUNK_READER_MAX_WORDS", "400"))


def _truncate_to_words(text: str, max_words: int) -> str:
    """Return text truncated to at most max_words words, preserving word boundaries."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " …"


_READER_SYSTEM = """You are an evidence extraction specialist for a Japanese trading company's product catalog.
Given a question and multiple product catalog chunks, extract structured evidence from ALL chunks in one pass.

Respond with a JSON array — one object per chunk:
[
  {
    "chunk_index": 0,
    "claims": ["key fact 1", "key fact 2"],
    "confidence": 0.85
  },
  ...
]

Rules:
- claims: up to 3 key factual statements relevant to the question (empty list if irrelevant)
- Preserve product names, model numbers (品番), specifications, prices and units exactly as written
- confidence: 0.0–1.0 (relevance score; use < 0.3 for irrelevant chunks)
- Always return an entry for EVERY chunk, even if irrelevant (confidence=0.1, claims=[])
"""


def chunk_reader_node(state: GraphState) -> GraphState:
    """
    Processes all ranked chunks in a SINGLE batched LLM call.
    Extracts structured evidence and accumulates into evidence_items.
    """
    ranked = state.get("ranked_chunks", [])
    user_query = state["user_query"]

    existing_evidence = state.get("evidence_items", [])
    previous_evidence_score = float(state.get("evidence_score", 0.0))
    previous_best_evidence_score = float(state.get("best_evidence_score", previous_evidence_score))
    existing_keys = {(e["file_path"], e["content"][:80]) for e in existing_evidence}

    if not ranked:
        return state

    # Build a single prompt with all chunks, truncating by word count
    chunks_text = ""
    for i, chunk in enumerate(ranked):
        content = _truncate_to_words(chunk.get("content", ""), _CHUNK_MAX_WORDS)
        chunks_text += (
            f"\n[Chunk {i}] Source: {chunk.get('file_path', '')}\n"
            f"Section: {chunk.get('section', '')}\n"
            f"Content: {content}\n"
        )

    messages = [
        {"role": "system", "content": _READER_SYSTEM},
        {
            "role": "user",
            "content": f"Question: {user_query}\n\nChunks to analyze:{chunks_text}",
        },
    ]

    try:
        raw = chat(messages, temperature=0.0, label="chunk_reader")
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed_list = json.loads(raw)
        if not isinstance(parsed_list, list):
            raise ValueError("Expected a JSON array")
    except Exception as e:
        log.error("chunk_reader.parse_error", error_type=type(e).__name__, error=str(e))
        parsed_list = [
            {"chunk_index": i, "claims": [chunk.get("content", "")[:150]], "confidence": min(0.9, max(0.4, chunk.get("rerank_score", 0.5)))}
            for i, chunk in enumerate(ranked)
        ]

    new_evidence: list[EvidenceItem] = []
    for entry in parsed_list:
        idx = entry.get("chunk_index", 0)
        if idx >= len(ranked):
            continue
        chunk = ranked[idx]
        key = (chunk.get("file_path", ""), chunk.get("content", "")[:80])
        if key in existing_keys:
            continue
        confidence = float(entry.get("confidence", 0.3))
        if confidence < 0.3:
            continue
        new_evidence.append(EvidenceItem(
            content=chunk.get("content", ""),
            source=chunk.get("source", "product catalog"),
            file_path=chunk.get("file_path", ""),
            relevance_score=chunk.get("rerank_score", 0.0),
            claims=entry.get("claims", []),
            confidence=confidence,
        ))
        existing_keys.add(key)

    all_evidence = existing_evidence + new_evidence
    evidence_score = compute_coverage_score(all_evidence)
    best_evidence_score = max(previous_best_evidence_score, evidence_score)
    evidence_delta = evidence_score - previous_evidence_score
    stalled_cycles = state.get("consecutive_stalled_cycles", 0)
    consecutive_stalled_cycles = stalled_cycles + 1 if len(new_evidence) == 0 else 0

    log.info(
        "chunk_reader.done",
        new_items=len(new_evidence),
        total_items=len(all_evidence),
        evidence_score=round(evidence_score, 3),
        best_evidence_score=round(best_evidence_score, 3),
        evidence_delta=round(evidence_delta, 3),
        stalled_cycles=consecutive_stalled_cycles,
    )

    return {
        **state,
        "evidence_items": all_evidence,
        "evidence_score": evidence_score,
        "best_evidence_score": best_evidence_score,
        "last_retrieval_new_items": len(new_evidence),
        "last_retrieval_evidence_delta": evidence_delta,
        "consecutive_stalled_cycles": consecutive_stalled_cycles,
    }
