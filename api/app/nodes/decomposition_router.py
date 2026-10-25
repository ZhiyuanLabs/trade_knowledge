"""
Decomposition Router Node

Manages the sub-question queue between the Planner and the retrieval pipeline.
Uses a sentinel field `_active_sub_question` for deterministic routing.

Routing logic:
  - Sentinel is str  → sub-question was just popped → go retrieve
  - Sentinel is None → queue was already empty     → back to orchestrator
"""

from app.state.schema import GraphState
from app.utils.logger import get_logger

log = get_logger(__name__)


def decomposition_router_node(state: GraphState) -> GraphState:
    """
    Pops the next pending sub-question and sets `_active_sub_question` as sentinel.
    - Sentinel = str   → a sub-question was popped, route to retrieval pipeline
    - Sentinel = None  → queue empty, route back to planner (orchestrator)
    """
    pending = list(state.get("pending_sub_questions", []))
    processed = list(state.get("processed_sub_questions", []))

    if not pending:
        return {
            **state,
            "_active_sub_question": None,
        }

    current = pending.pop(0)
    processed.append(current)

    return {
        **state,
        "rewritten_queries": [current],
        "pending_sub_questions": pending,
        "processed_sub_questions": processed,
        "_active_sub_question": current,
    }


def route_from_decomposition(state: GraphState) -> str:
    """
    Conditional edge after decomposition_router_node.
    Routes based on the sentinel field set by the node.
    """
    active = state.get("_active_sub_question")
    if active:
        return "retrieve"
    return "judge"
