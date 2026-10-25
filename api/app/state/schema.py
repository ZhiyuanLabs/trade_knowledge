"""
Graph State Schema for the trade_knowledge system.
All nodes read from and write to this shared state.
"""

from typing import TypedDict, Annotated
import operator


class EvidenceItem(TypedDict):
    """Structured evidence extracted from a retrieved chunk."""
    content: str
    source: str
    file_path: str
    relevance_score: float
    claims: list[str]
    confidence: float


class DocChunk(TypedDict):
    """A single indexed document chunk."""
    doc_id: str
    title: str
    section: str
    content: str
    source: str
    file_path: str
    chunk_id: str
    tokens: int


class RetrievalPlan(TypedDict):
    """Structured retrieval execution plan produced by the Retrieval Specialist."""
    strategy: str             # "hybrid" | "bm25_only" | "vector_only"
    bm25_queries: list[str]   # keyword-optimized queries for BM25
    vector_queries: list[str] # semantic-optimized queries for vector search
    rationale: str            # why this strategy was chosen


class GraphState(TypedDict):
    """
    Central state object passed through the LangGraph graph.
    Keys are updated by nodes as the graph executes.
    """
    # Input
    user_query: str

    # Planner outputs
    rewritten_queries: list[str]
    sub_questions: list[str]
    retrieval_routes: list[str]

    # Decomposition queue
    pending_sub_questions: list[str]    # sub-questions yet to be retrieved
    processed_sub_questions: list[str]  # sub-questions already executed
    _active_sub_question: str | None    # sentinel: current sub-question being retrieved

    # Retrieval Specialist output
    retrieval_plan: RetrievalPlan

    # Retrieval outputs
    candidate_chunks: list[DocChunk]
    ranked_chunks: list[DocChunk]

    # Evidence accumulation
    evidence_items: list[EvidenceItem]
    evidence_score: float
    best_evidence_score: float
    last_retrieval_new_items: int
    last_retrieval_evidence_delta: float
    consecutive_stalled_cycles: int

    # Routing control
    enough_evidence: bool
    iteration_count: int

    # Intent routing (catalog RAG vs business tools vs hybrid)
    route: str                       # "" | "catalog" | "business" | "hybrid"
    business_context: str            # serialized business tool results for the LLM
    business_result: dict            # structured payload for the frontend cards

    # Final output
    citations: list[str]
    final_answer: str
