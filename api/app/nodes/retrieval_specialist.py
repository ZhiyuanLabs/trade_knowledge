"""
LLM Subagent — Retrieval Specialist

This node sits between the Planner and the Retriever.
It is a dedicated LLM agent responsible for translating high-level
retrieval intent (from the Planner) into a precise, typed execution plan.

Responsibilities:
  - Decide retrieval strategy: hybrid / bm25_only / vector_only
  - Produce keyword-optimized queries for BM25 (exact terms, API names, flags)
  - Produce semantic queries for Vector search (conceptual, natural language)
  - Explain the rationale (used for debugging and observability)

This separates concerns:
  Planner   = WHAT to look for (intent, decomposition)
  Specialist = HOW to look for it (retrieval mechanics)
"""

import json
from app.state.schema import GraphState, RetrievalPlan
from app.utils.llm import chat
from app.utils.logger import get_logger

log = get_logger(__name__)


_SPECIALIST_SYSTEM = """You are a Retrieval Specialist for a Japanese trading company's product catalog search system.

You receive a set of search queries from a Planner and must produce a precise retrieval execution plan.

You have two search tools available:
1. **BM25 (keyword search)**: Best for exact product names, model numbers (品番), sizes, specifications, and katakana terms.
2. **Vector search (semantic)**: Best for natural-language questions about use cases, applications, and product categories.

Your job is to:
- Choose the right strategy: "hybrid", "bm25_only", or "vector_only"
- Rewrite queries optimized for BM25: short, keyword-dense, product-term focused
- Rewrite queries optimized for vector: full natural-language Japanese sentences

Rules:
- Always prefer "hybrid" unless the query is purely keyword (then "bm25_only") or purely conceptual (then "vector_only")
- Keep product names, model numbers, and katakana terms exactly as written
- ALWAYS write every query in JAPANESE

Respond ONLY with valid JSON:
{
  "strategy": "hybrid",
  "bm25_queries": ["ステンレス鋼管 呼び径 20A 仕様", "SUS304 鋼管 外径"],
  "vector_queries": ["ステンレス鋼管の呼び径ごとの仕様と用途を知りたい"],
  "rationale": "商品仕様に関する質問（hybrid: 品番・呼び径のキーワード + 用途の意味検索）"
}
"""


def _default_plan(queries: list[str]) -> RetrievalPlan:
    """Fallback plan when the LLM is unavailable."""
    return RetrievalPlan(
        strategy="hybrid",
        bm25_queries=queries,
        vector_queries=queries,
        rationale="LLM unavailable — using original queries for both retrievers.",
    )


def retrieval_specialist_node(state: GraphState) -> GraphState:
    """
    LLM Subagent: translates the active sub-question into a typed retrieval execution plan.
    Uses _active_sub_question (the specific question currently being retrieved) as the
    primary focus, falling back to rewritten_queries only when no sentinel is set.
    """
    active_sub_question = state.get("_active_sub_question")
    user_query = state["user_query"]
    iteration = state.get("iteration_count", 1)

    # Prefer the active sub-question — this is the precise retrieval target set by
    # decomposition_router. Using the full state (all sub_questions) would produce
    # plans that mix concerns from multiple iterations.
    if active_sub_question:
        focus_queries = [active_sub_question]
    else:
        focus_queries = state.get("rewritten_queries", []) or [user_query]

    context = (
        f"Original user question: {user_query}\n"
        f"Iteration: {iteration}\n"
        f"Current retrieval target:\n"
        + "\n".join(f"  - {q}" for q in focus_queries)
    )

    messages = [
        {"role": "system", "content": _SPECIALIST_SYSTEM},
        {"role": "user", "content": context},
    ]

    try:
        raw = chat(messages, temperature=0.0, label="retrieval_specialist")
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(raw)

        plan = RetrievalPlan(
            strategy=parsed.get("strategy", "hybrid"),
            bm25_queries=parsed.get("bm25_queries", focus_queries),
            vector_queries=parsed.get("vector_queries", focus_queries),
            rationale=parsed.get("rationale", ""),
        )

    except Exception as e:
        log.error("retrieval_specialist.llm_error", error_type=type(e).__name__, error=str(e))
        plan = _default_plan(focus_queries)

    log.info(
        "retrieval_specialist.plan",
        strategy=plan["strategy"],
        bm25_count=len(plan["bm25_queries"]),
        vector_count=len(plan["vector_queries"]),
        rationale=plan["rationale"],
    )

    return {**state, "retrieval_plan": plan}
