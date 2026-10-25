"""
LangGraph Graph Builder — Agentic trading-house assistant.

Architecture:

  START
    └→ intent_router (supervisor: catalog vs business vs hybrid)
         ├─ business → business_agent (ERP tools + Japanese answer) → END
         ├─ hybrid   → business_tools → planner (catalog RAG below)
         └─ catalog  → planner
              ├─ [enough_evidence=True] → final_synthesizer → END
              └─ [enough_evidence=False] → decomposition_router
                                                 ├─ [queue has items] → retrieval_specialist
                                                 │      → retriever → reranker → chunk_reader
                                                 │      └───────────────────────────────┘
                                                 │                   (loops back)
                                                 └─ [queue empty] → planner
"""

from langgraph.graph import StateGraph, START, END

from app.state.schema import GraphState
from app.nodes.intent_router import intent_router_node, route_after_intent, _BUSINESS_KEYWORDS
from app.nodes.business_agent import business_agent_node, business_tools_node
from app.nodes.planner import planner_node
from app.nodes.decomposition_router import decomposition_router_node, route_from_decomposition
from app.nodes.retrieval_specialist import retrieval_specialist_node
from app.nodes.retriever import retriever_node
from app.nodes.reranker import reranker_node
from app.nodes.chunk_reader import chunk_reader_node
from app.nodes.final_synthesizer import final_synthesizer_node
from app.utils.semantic_cache import check_semantic_cache, save_to_semantic_cache
from app.utils.events import emit


def _route_from_orchestrator(state: GraphState) -> str:
    """Conditional edge from the Orchestrator (planner): synthesize if enough evidence."""
    if state.get("enough_evidence", False):
        return "synthesize"
    return "tools"


def _looks_like_business_query(query: str) -> bool:
    """Cheap keyword guard so live operational data is never served from cache."""
    return any(k in query for k in _BUSINESS_KEYWORDS)


def build_graph() -> StateGraph:
    """Build and compile the agentic LangGraph."""
    graph = StateGraph(GraphState)

    # ── Register all nodes ───────────────────────────────────────
    graph.add_node("intent_router", intent_router_node)
    graph.add_node("business_agent", business_agent_node)
    graph.add_node("business_tools", business_tools_node)
    graph.add_node("planner", planner_node)
    graph.add_node("decomposition_router", decomposition_router_node)
    graph.add_node("retrieval_specialist", retrieval_specialist_node)
    graph.add_node("retriever", retriever_node)
    graph.add_node("reranker", reranker_node)
    graph.add_node("chunk_reader", chunk_reader_node)
    graph.add_node("final_synthesizer", final_synthesizer_node)

    # ── Entry: intent routing ────────────────────────────────────
    graph.add_edge(START, "intent_router")
    graph.add_conditional_edges(
        "intent_router",
        route_after_intent,
        {
            "business_agent": "business_agent",   # business -> tools + answer -> END
            "business_tools": "business_tools",   # hybrid -> tools then RAG
            "planner": "planner",                 # catalog -> RAG
        },
    )

    # business route answers directly
    graph.add_edge("business_agent", END)

    # hybrid: run business tools first, then the catalog RAG pipeline
    graph.add_edge("business_tools", "planner")

    # Orchestrator decides whether to synthesize or retrieve
    graph.add_conditional_edges(
        "planner",
        _route_from_orchestrator,
        {
            "synthesize": "final_synthesizer",
            "tools": "decomposition_router",
        },
    )

    # Decomposition conditional: route to specialist OR loop back to orchestrator
    graph.add_conditional_edges(
        "decomposition_router",
        route_from_decomposition,
        {
            "retrieve": "retrieval_specialist",
            "judge":    "planner",
        },
    )

    # Retrieval pipeline (linear tools loop)
    graph.add_edge("retrieval_specialist", "retriever")
    graph.add_edge("retriever", "reranker")
    graph.add_edge("reranker", "chunk_reader")
    graph.add_edge("chunk_reader", "decomposition_router")

    graph.add_edge("final_synthesizer", END)

    return graph.compile()


_compiled_graph = None


def get_graph():
    """Return the compiled graph, building it once (singleton)."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


_NODE_TITLES = {
    "intent_router": "① 意図ルーター（LLM 分類）",
    "business_agent": "業務エージェント（ツール＋日本語回答）",
    "business_tools": "業務ツール実行（ERP 照会）",
    "planner": "プランナー（証拠の十分性を判定）",
    "decomposition_router": "クエリ分解ルーター",
    "retrieval_specialist": "検索スペシャリスト（BM25/ベクトル計画）",
    "retriever": "混合検索（BM25 ＋ ベクトル）",
    "reranker": "リランカー（Cross-Encoder）",
    "chunk_reader": "チャンクリーダー（証拠抽出）",
    "final_synthesizer": "最終回答シンセサイザー",
}


def _node_summary(node: str, d: dict) -> tuple[str, str]:
    """Human-readable one-line summary for a node's state update."""
    title = _NODE_TITLES.get(node, node)
    parts: list[str] = []
    if node == "intent_router":
        parts.append(f"route={d.get('route')}")
    elif node == "planner":
        parts.append(f"enough_evidence={d.get('enough_evidence')}, iteration={d.get('iteration_count')}")
    elif node == "retrieval_specialist":
        plan = d.get("retrieval_plan") or {}
        parts.append(f"strategy={plan.get('strategy')}")
        parts.append(f"bm25={len(plan.get('bm25_queries', []))}, vector={len(plan.get('vector_queries', []))}")
    elif node == "retriever":
        parts.append(f"candidate_chunks={len(d.get('candidate_chunks') or [])}")
    elif node == "reranker":
        parts.append(f"ranked_chunks={len(d.get('ranked_chunks') or [])}")
    elif node == "chunk_reader":
        score = round(float(d.get('evidence_score') or 0.0), 3)
        parts.append(f"evidence={len(d.get('evidence_items') or [])}, score={score}")
    elif node in ("business_tools", "business_agent"):
        br = d.get("business_result") or {}
        if br:
            parts.append(
                f"stock={len(br.get('stock', []))}, orders={len(br.get('orders', []))}, "
                f"shipments={len(br.get('shipments', []))}, alerts={len(br.get('alerts', []))}"
            )
    elif node == "final_synthesizer":
        parts.append(f"citations={len(d.get('citations') or [])}")
    elif node == "decomposition_router":
        parts.append(f"pending={len(d.get('pending_sub_questions') or [])}")
    return title, ", ".join(parts)


def _build_initial_state(user_query: str) -> GraphState:
    return {
        "user_query": user_query,
        "route": "",
        "business_context": "",
        "business_result": {},
        "rewritten_queries": [],
        "sub_questions": [],
        "retrieval_routes": [],
        "pending_sub_questions": [],
        "processed_sub_questions": [],
        "_active_sub_question": None,
        "retrieval_plan": {
            "strategy": "hybrid",
            "bm25_queries": [],
            "vector_queries": [],
            "rationale": "",
        },
        "candidate_chunks": [],
        "ranked_chunks": [],
        "evidence_items": [],
        "evidence_score": 0.0,
        "best_evidence_score": 0.0,
        "last_retrieval_new_items": 0,
        "last_retrieval_evidence_delta": 0.0,
        "consecutive_stalled_cycles": 0,
        "enough_evidence": False,
        "iteration_count": 0,
        "citations": [],
        "final_answer": "",
    }


def run_query(user_query: str) -> dict:
    """
    Execute the graph for a single query. Returns the final state dict.
    Catalog questions are intercepted by the semantic cache; operational
    (business/hybrid) queries bypass the cache so DB figures always stay live.
    """
    use_cache = not _looks_like_business_query(user_query)

    if use_cache:
        cached = check_semantic_cache(user_query)
        if cached:
            return cached

    graph = get_graph()
    final_state = graph.invoke(_build_initial_state(user_query))

    if use_cache:
        save_to_semantic_cache(user_query, final_state)

    return final_state


def run_query_traced(user_query: str) -> dict:
    """
    Streaming variant: run the graph node-by-node with graph.stream and emit a
    `node` event for every transition (plus cache status). LLM/tool/SQL events
    are emitted by the respective modules via the active trace.
    """
    use_cache = not _looks_like_business_query(user_query)

    if use_cache:
        cached = check_semantic_cache(user_query)
        if cached:
            emit("cache", hit=True, reason="semantic cache HIT（ウォーム経路）")
            return cached
        emit("cache", hit=False, reason="カタログ質問：セマンティックキャッシュなし（コールド経路）")
    else:
        emit("cache", hit=False, reason="業務質問のためキャッシュをスキップ（在庫は常に最新）")

    graph = get_graph()
    latest: dict = {}
    for update in graph.stream(_build_initial_state(user_query)):
        for node, delta in update.items():
            if isinstance(delta, dict):
                title, detail = _node_summary(node, delta)
                emit("node", node=node, title=title, detail=detail)
                latest = {**latest, **delta}

    if use_cache:
        save_to_semantic_cache(user_query, latest)

    return latest
