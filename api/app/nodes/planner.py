"""
Node 1 — Planner / Orchestrator

Acts as the central Brain of the Agentic RAG system.
First evaluates the Evidence Memory to determine if the query can be answered fully.
If yes, sets enough_evidence = True (routing to the Final Synthesizer).
If no, decomposes the query into sub-questions and sets enough_evidence = False (routing to Tools/Retrieval).
"""

import json
import os
import re
from app.state.schema import GraphState
from app.utils.llm import chat
from app.utils.logger import get_logger

log = get_logger(__name__)
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "3"))
PLANNER_EARLY_STOP_ENABLED = os.getenv("PLANNER_EARLY_STOP_ENABLED", "true").lower() == "true"
PLANNER_EARLY_STOP_MIN_EVIDENCE_SCORE = float(os.getenv("PLANNER_EARLY_STOP_MIN_EVIDENCE_SCORE", "0.76"))
PLANNER_EARLY_STOP_MIN_EVIDENCE_ITEMS = int(os.getenv("PLANNER_EARLY_STOP_MIN_EVIDENCE_ITEMS", "4"))
PLANNER_EARLY_STOP_MAX_EVIDENCE_DELTA = float(os.getenv("PLANNER_EARLY_STOP_MAX_EVIDENCE_DELTA", "0.02"))
PLANNER_EARLY_STOP_MIN_STALLED_CYCLES = int(os.getenv("PLANNER_EARLY_STOP_MIN_STALLED_CYCLES", "1"))


_ORCHESTRATOR_SYSTEM = """You are the master Orchestrator for an Agentic RAG system over a Japanese trading company's product catalog.
Your job is to analyze the user's question against the evidence collected so far.

DECISION 1: Is the evidence sufficient?
- If the collected evidence completely and correctly answers the user's question, set "enough_evidence": true.
- If the evidence is insufficient, partial, or empty, set "enough_evidence": false.

DECISION 2: If insufficient, plan the retrieval strategy.
- Deconstruct the user query into 1-2 focused sub-questions to search the knowledge base.
- Provide reformulated queries targeting those gaps.
- Never repeat sub-questions that were already processed in prior retrieval cycles.
- If recent retrieval cycles added little or no new evidence, prefer synthesizing from the current evidence instead of repeating the same search.
- IMPORTANT: ALWAYS formulate the rewritten queries and sub-questions in JAPANESE, keeping product names, 産地・品種・等級 (grade/size), and katakana terms exactly as they appear in the catalog.

Respond EXACTLY with valid JSON in this format:
{
  "enough_evidence": false,
  "rewritten_queries": ["query1", "query2"],
  "sub_questions": ["sub-question 1", "sub-question 2"],
  "retrieval_routes": ["hybrid"]
}
"""


def _normalize_question(text: str) -> str:
    """Normalize question text to detect semantically identical planning loops.

    Keeps Latin/alphanumeric characters AND Japanese (hiragana, katakana, CJK
    ideographs, prolonged-sound mark, iteration mark, full-width alphanumerics).
    Keeping only [a-z0-9] would strip every Japanese-only query to an empty
    string, after which the dedup guard treats it as redundant and drops all
    planned queries — the catalog retrieval would never run.
    """
    return re.sub(
        r"[^a-z0-9\u3040-\u30ff\u4e00-\u9fff\u3005\uff10-\uff5a]+",
        " ",
        text.lower(),
    ).strip()


def _looks_redundant(candidate: str, processed: list[str]) -> bool:
    """Treat close paraphrases as repeated work to avoid planner loops."""
    normalized_candidate = _normalize_question(candidate)
    if not normalized_candidate:
        return True

    candidate_tokens = set(normalized_candidate.split())

    for previous in processed:
        normalized_previous = _normalize_question(previous)
        if not normalized_previous:
            continue
        if normalized_candidate == normalized_previous:
            return True

        previous_tokens = set(normalized_previous.split())
        if not candidate_tokens or not previous_tokens:
            continue

        overlap = len(candidate_tokens & previous_tokens) / min(len(candidate_tokens), len(previous_tokens))
        if overlap >= 0.8:
            return True

    return False


def _filter_new_questions(candidates: list[str], processed: list[str]) -> list[str]:
    """Drop empty and already-processed questions while preserving order."""
    seen = [item for item in processed if item.strip()]
    filtered: list[str] = []

    for candidate in candidates:
        cleaned = candidate.strip()
        if not cleaned:
            continue
        if _looks_redundant(cleaned, seen):
            continue
        filtered.append(cleaned)
        seen.append(cleaned)

    return filtered


def _should_early_stop(
    iteration: int,
    evidence_items: list[dict],
    best_evidence_score: float,
    last_retrieval_evidence_delta: float,
    consecutive_stalled_cycles: int,
) -> tuple[bool, str]:
    """Use deterministic evidence-memory signals to stop retrieval early."""
    if not PLANNER_EARLY_STOP_ENABLED or iteration == 0:
        return False, ""

    if len(evidence_items) < PLANNER_EARLY_STOP_MIN_EVIDENCE_ITEMS:
        return False, ""

    if best_evidence_score < PLANNER_EARLY_STOP_MIN_EVIDENCE_SCORE:
        return False, ""

    if consecutive_stalled_cycles >= PLANNER_EARLY_STOP_MIN_STALLED_CYCLES:
        return True, "stalled"

    if last_retrieval_evidence_delta <= PLANNER_EARLY_STOP_MAX_EVIDENCE_DELTA:
        return True, "low_gain"

    return False, ""


def planner_node(state: GraphState) -> GraphState:
    """
    Evaluates state and decides to synthesize or plan further retrievals.
    Replaces the separate Sufficiency Judge node.
    """
    iteration = state.get("iteration_count", 0)
    user_query = state["user_query"]
    evidence_items = state.get("evidence_items", [])
    evidence_score = state.get("evidence_score", 0.0)
    best_evidence_score = float(state.get("best_evidence_score", evidence_score))
    processed_sub_questions = state.get("processed_sub_questions", [])
    last_retrieval_new_items = int(state.get("last_retrieval_new_items", 0))
    last_retrieval_evidence_delta = float(state.get("last_retrieval_evidence_delta", 0.0))
    consecutive_stalled_cycles = int(state.get("consecutive_stalled_cycles", 0))

    # Infinite loop safeguard
    max_iterations = MAX_ITERATIONS
    if iteration >= max_iterations:
        log.warning("planner.max_iterations", iteration=iteration, max=max_iterations)
        return {**state, "enough_evidence": True}

    should_stop, stop_reason = _should_early_stop(
        iteration=iteration,
        evidence_items=evidence_items,
        best_evidence_score=best_evidence_score,
        last_retrieval_evidence_delta=last_retrieval_evidence_delta,
        consecutive_stalled_cycles=consecutive_stalled_cycles,
    )
    if should_stop:
        log.info(
            "planner.early_stop",
            iteration=iteration,
            reason=stop_reason,
            evidence_items=len(evidence_items),
            evidence_score=round(evidence_score, 3),
            best_evidence_score=round(best_evidence_score, 3),
            evidence_delta=round(last_retrieval_evidence_delta, 3),
            stalled_cycles=consecutive_stalled_cycles,
        )
        return {
            **state,
            "enough_evidence": True,
            "iteration_count": iteration + 1,
        }

    # If we have no evidence, we obviously need to search
    if iteration == 0 and not evidence_items:
        user_content = f"Question: {user_query}\nEvidence collected: None (Initial Search)"
    else:
        evidence_summary = []
        for i, ev in enumerate(evidence_items[:8]):
            evidence_summary.append({
                "source": ev["file_path"],
                "claims": ev["claims"]
            })

        user_content = (
            f"Question: {user_query}\n"
            f"Evidence collected so far ({len(evidence_items)} items, avg score: {evidence_score:.2f}):\n"
            f"{json.dumps(evidence_summary, indent=2)}\n\n"
            f"Best evidence score so far: {best_evidence_score:.3f}\n"
            f"Processed sub-questions: {json.dumps(processed_sub_questions[-6:])}\n"
            f"Latest retrieval progress: new_items={last_retrieval_new_items}, "
            f"evidence_delta={last_retrieval_evidence_delta:.3f}, stalled_cycles={consecutive_stalled_cycles}\n\n"
            "Evaluate if the above evidence fully answers the question. If not, generate new queries."
        )

    messages = [
        {"role": "system", "content": _ORCHESTRATOR_SYSTEM},
        {"role": "user", "content": user_content}
    ]

    try:
        raw = chat(messages, temperature=0.1, label="planner")
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(raw)
    except Exception as e:
        log.error("planner.parse_error", error=str(e), iteration=iteration)
        parsed = {
            "enough_evidence": False if iteration == 0 else True,
            "rewritten_queries": [user_query],
            "sub_questions": [],
            "retrieval_routes": ["hybrid"],
        }

    enough = bool(parsed.get("enough_evidence", False))
    log.info("planner.decision", iteration=iteration, enough_evidence=enough, evidence_items=len(evidence_items))

    if enough:
        return {
            **state,
            "enough_evidence": True,
            "iteration_count": iteration + 1
        }

    rewritten = _filter_new_questions(parsed.get("rewritten_queries", [user_query]), processed_sub_questions)
    sub_qs = _filter_new_questions(parsed.get("sub_questions", []), processed_sub_questions)

    MAX_SUB_QUESTIONS = 2
    pending = sub_qs[:MAX_SUB_QUESTIONS] if sub_qs else rewritten[:1]

    if not pending:
        if evidence_items:
            # We already have evidence but the model produced no new retrieval
            # work: avoid repeating the same search and go synthesize.
            log.info(
                "planner.no_new_retrieval_work",
                iteration=iteration,
                evidence_items=len(evidence_items),
                processed=len(processed_sub_questions),
                stalled_cycles=consecutive_stalled_cycles,
            )
            return {
                **state,
                "enough_evidence": True,
                "iteration_count": iteration + 1,
            }

        # Zero evidence but no usable planned query (model returned empty arrays,
        # or every candidate was deduped). Never spin idle: deterministically
        # force a first retrieval using the original user question.
        pending = [user_query]
        rewritten = rewritten or [user_query]
        log.info(
            "planner.empty_plan_fallback",
            iteration=iteration,
            fallback_query=user_query[:80],
        )

    log.info("planner.sub_questions", planned=pending)

    return {
        **state,
        "enough_evidence": False,
        "rewritten_queries": rewritten,
        "sub_questions": sub_qs,
        "retrieval_routes": parsed.get("retrieval_routes", ["hybrid"]),
        "iteration_count": iteration + 1,
        "pending_sub_questions": pending,
        "processed_sub_questions": state.get("processed_sub_questions", []),
    }
