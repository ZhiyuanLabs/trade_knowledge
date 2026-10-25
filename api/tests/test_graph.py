"""
Tests for the trade_knowledge graph structure and node logic.
Uses mocks to avoid real API/DB calls.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── Shared helpers ────────────────────────────────────────────────────────────

def _base_state(**overrides) -> dict:
    """Return a minimal valid GraphState dict, with optional overrides."""
    state = {
        "user_query": "How does the App Router work?",
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
    state.update(overrides)
    return state


# ─── Graph State Schema ───────────────────────────────────────────────────────

def test_graph_state_keys():
    from app.state.schema import GraphState
    keys = GraphState.__annotations__.keys()
    required = {
        "user_query", "rewritten_queries", "sub_questions",
        "candidate_chunks", "ranked_chunks", "evidence_items",
        "evidence_score", "enough_evidence", "iteration_count",
        "citations", "final_answer",
    }
    assert required.issubset(keys), f"Missing keys: {required - keys}"


# ─── Scoring Utils ────────────────────────────────────────────────────────────

def test_normalize_scores_basic():
    from app.utils.scoring import normalize_scores
    result = normalize_scores([0.0, 5.0, 10.0])
    assert result == [0.0, 0.5, 1.0]


def test_normalize_scores_uniform():
    from app.utils.scoring import normalize_scores
    result = normalize_scores([3.0, 3.0, 3.0])
    assert all(s == 1.0 for s in result)


def test_normalize_scores_empty():
    from app.utils.scoring import normalize_scores
    assert normalize_scores([]) == []


def test_rrf_fusion_deduplication():
    from app.utils.scoring import reciprocal_rank_fusion
    list_a = [{"chunk_id": "A"}, {"chunk_id": "B"}]
    list_b = [{"chunk_id": "B"}, {"chunk_id": "C"}]
    fused = reciprocal_rank_fusion([list_a, list_b])
    ids = [c["chunk_id"] for c in fused]
    assert len(ids) == len(set(ids)), "Duplicates in fused result"
    # B appears in both lists — should rank highest
    assert ids[0] == "B"


def test_rrf_fusion_preserves_all_docs():
    from app.utils.scoring import reciprocal_rank_fusion
    list_a = [{"chunk_id": "X"}, {"chunk_id": "Y"}]
    list_b = [{"chunk_id": "Z"}]
    fused = reciprocal_rank_fusion([list_a, list_b])
    assert {c["chunk_id"] for c in fused} == {"X", "Y", "Z"}


# ─── Graph Routing ────────────────────────────────────────────────────────────

def test_graph_routing_enough_evidence():
    from app.graph.builder import _route_from_orchestrator
    state = _base_state(enough_evidence=True)
    assert _route_from_orchestrator(state) == "synthesize"


def test_graph_routing_not_enough():
    from app.graph.builder import _route_from_orchestrator
    state = _base_state(enough_evidence=False)
    assert _route_from_orchestrator(state) == "tools"


# ─── Graph Compilation ────────────────────────────────────────────────────────

def test_graph_compiles():
    from app.graph.builder import build_graph
    graph = build_graph()
    assert graph is not None


# ─── Decomposition Router ─────────────────────────────────────────────────────

def test_decomposition_router_pops_first_item():
    from app.nodes.decomposition_router import decomposition_router_node
    state = _base_state(
        pending_sub_questions=["sub1", "sub2"],
        processed_sub_questions=[],
    )
    result = decomposition_router_node(state)
    assert result["_active_sub_question"] == "sub1"
    assert result["pending_sub_questions"] == ["sub2"]
    assert result["processed_sub_questions"] == ["sub1"]
    assert result["rewritten_queries"] == ["sub1"]


def test_decomposition_router_empty_queue():
    from app.nodes.decomposition_router import decomposition_router_node
    state = _base_state(pending_sub_questions=[], processed_sub_questions=["sub1"])
    result = decomposition_router_node(state)
    assert result["_active_sub_question"] is None


def test_decomposition_route_retrieve():
    from app.nodes.decomposition_router import route_from_decomposition
    state = _base_state(_active_sub_question="sub1")
    assert route_from_decomposition(state) == "retrieve"


def test_decomposition_route_judge():
    from app.nodes.decomposition_router import route_from_decomposition
    state = _base_state(_active_sub_question=None)
    assert route_from_decomposition(state) == "judge"


# ─── Planner Node ────────────────────────────────────────────────────────────

def test_planner_forces_synthesis_at_max_iterations():
    from app.nodes.planner import planner_node
    state = _base_state(iteration_count=3)
    result = planner_node(state)
    assert result["enough_evidence"] is True


def test_planner_sets_pending_sub_questions_on_first_call():
    from app.nodes.planner import planner_node

    mock_response = '{"enough_evidence": false, "rewritten_queries": ["app router routing"], "sub_questions": ["How does App Router handle nested layouts?"], "retrieval_routes": ["hybrid"]}'

    with patch("app.nodes.planner.chat", return_value=mock_response):
        state = _base_state(iteration_count=0)
        result = planner_node(state)

    assert result["enough_evidence"] is False
    assert len(result["pending_sub_questions"]) >= 1
    assert result["iteration_count"] == 1


def test_planner_returns_enough_evidence_true():
    from app.nodes.planner import planner_node

    mock_response = '{"enough_evidence": true, "rewritten_queries": [], "sub_questions": [], "retrieval_routes": []}'

    with patch("app.nodes.planner.chat", return_value=mock_response):
        state = _base_state(iteration_count=1, evidence_items=[
            {"file_path": "docs/routing.md", "claims": ["App Router uses file-system routing"], "confidence": 0.9, "content": "...", "source": "docs", "relevance_score": 0.9}
        ])
        result = planner_node(state)

    assert result["enough_evidence"] is True


def test_planner_llm_parse_error_falls_back():
    from app.nodes.planner import planner_node

    with patch("app.nodes.planner.chat", return_value="not valid json {{{"):
        state = _base_state(iteration_count=0)
        result = planner_node(state)

    # On parse error at iteration 0, fallback sets enough_evidence=False
    assert result["enough_evidence"] is False


def test_planner_early_stops_on_strong_evidence_with_low_gain():
    from app.nodes.planner import planner_node

    state = _base_state(
        iteration_count=1,
        evidence_items=[
            {
                "file_path": f"docs/item-{i}.mdx",
                "claims": [f"claim {i}"],
                "confidence": 0.86,
                "content": f"content {i}",
                "source": "docs",
                "relevance_score": 0.9,
            }
            for i in range(4)
        ],
        evidence_score=0.86,
        best_evidence_score=0.86,
        last_retrieval_new_items=1,
        last_retrieval_evidence_delta=0.0,
        consecutive_stalled_cycles=0,
    )

    with patch("app.nodes.planner.chat") as mock_chat:
        result = planner_node(state)

    mock_chat.assert_not_called()
    assert result["enough_evidence"] is True
    assert result["iteration_count"] == 2


def test_planner_does_not_early_stop_when_evidence_is_weak():
    from app.nodes.planner import planner_node

    mock_response = '{"enough_evidence": false, "rewritten_queries": ["app router routing"], "sub_questions": ["How does App Router handle nested layouts?"], "retrieval_routes": ["hybrid"]}'

    with patch("app.nodes.planner.chat", return_value=mock_response) as mock_chat:
        state = _base_state(
            iteration_count=1,
            evidence_items=[
                {
                    "file_path": "docs/routing.mdx",
                    "claims": ["partial evidence"],
                    "confidence": 0.7,
                    "content": "...",
                    "source": "docs",
                    "relevance_score": 0.7,
                }
            ],
            evidence_score=0.7,
            best_evidence_score=0.7,
            last_retrieval_new_items=0,
            last_retrieval_evidence_delta=0.0,
            consecutive_stalled_cycles=1,
        )
        result = planner_node(state)

    mock_chat.assert_called_once()
    assert result["enough_evidence"] is False


def test_planner_synthesizes_when_only_repeated_subquestions_remain():
    from app.nodes.planner import planner_node

    mock_response = (
        '{"enough_evidence": false, '
        '"rewritten_queries": ["when should cache no-store be used"], '
        '"sub_questions": ["When should cache: no-store be used in Next.js App Router?"], '
        '"retrieval_routes": ["hybrid"]}'
    )

    with patch("app.nodes.planner.chat", return_value=mock_response):
        state = _base_state(
            iteration_count=2,
            processed_sub_questions=["When should cache: no-store be used in Next.js App Router?"],
            evidence_items=[
                {
                    "file_path": "docs/app/caching.mdx",
                    "claims": ["cache: no-store disables caching for that fetch"],
                    "confidence": 0.82,
                    "content": "...",
                    "source": "docs",
                    "relevance_score": 0.88,
                }
            ],
            evidence_score=0.82,
            best_evidence_score=0.82,
        )
        result = planner_node(state)

    assert result["enough_evidence"] is True
    assert result["iteration_count"] == 3


# ─── Chunk Reader Node ────────────────────────────────────────────────────────

def test_chunk_reader_extracts_evidence():
    from app.nodes.chunk_reader import chunk_reader_node

    mock_response = '[{"chunk_index": 0, "claims": ["App Router is file-system based"], "confidence": 0.85}]'

    chunk = {
        "chunk_id": "c1", "file_path": "docs/routing.md",
        "section": "App Router", "content": "The App Router is...",
        "source": "next.js docs", "rerank_score": 5.0,
    }

    with patch("app.nodes.chunk_reader.chat", return_value=mock_response):
        state = _base_state(ranked_chunks=[chunk])
        result = chunk_reader_node(state)

    assert len(result["evidence_items"]) == 1
    assert result["evidence_items"][0]["claims"] == ["App Router is file-system based"]
    assert result["evidence_score"] > 0


def test_chunk_reader_skips_low_confidence():
    from app.nodes.chunk_reader import chunk_reader_node

    mock_response = '[{"chunk_index": 0, "claims": [], "confidence": 0.1}]'

    chunk = {
        "chunk_id": "c1", "file_path": "docs/routing.md",
        "section": "App Router", "content": "Irrelevant content",
        "source": "next.js docs", "rerank_score": 0.1,
    }

    with patch("app.nodes.chunk_reader.chat", return_value=mock_response):
        state = _base_state(ranked_chunks=[chunk])
        result = chunk_reader_node(state)

    assert len(result["evidence_items"]) == 0


def test_chunk_reader_empty_ranked_chunks():
    from app.nodes.chunk_reader import chunk_reader_node
    state = _base_state(ranked_chunks=[])
    result = chunk_reader_node(state)
    assert result["evidence_items"] == []


def test_chunk_reader_tracks_progress_signals():
    from app.nodes.chunk_reader import chunk_reader_node

    mock_response = '[{"chunk_index": 0, "claims": ["App Router uses layouts"], "confidence": 0.9}]'
    chunk = {
        "chunk_id": "c1", "file_path": "docs/routing.md",
        "section": "Layouts", "content": "Layouts are shared UI.",
        "source": "next.js docs", "rerank_score": 5.0,
    }

    with patch("app.nodes.chunk_reader.chat", return_value=mock_response):
        state = _base_state(ranked_chunks=[chunk], evidence_score=0.0, consecutive_stalled_cycles=2)
        result = chunk_reader_node(state)

    assert result["last_retrieval_new_items"] == 1
    assert result["last_retrieval_evidence_delta"] > 0
    assert result["consecutive_stalled_cycles"] == 0
    assert result["best_evidence_score"] == pytest.approx(result["evidence_score"])


def test_chunk_reader_uses_weighted_coverage_score():
    from app.nodes.chunk_reader import chunk_reader_node
    from app.memory.evidence_store import compute_coverage_score

    mock_response = '[{"chunk_index": 0, "claims": ["high-confidence claim"], "confidence": 0.9}]'
    chunk = {
        "chunk_id": "c1", "file_path": "docs/high-confidence.md",
        "section": "High Confidence", "content": "High confidence content.",
        "source": "next.js docs", "rerank_score": 5.0,
    }
    existing = [{
        "file_path": "docs/low-confidence.md",
        "claims": ["low-confidence claim"],
        "confidence": 0.5,
        "content": "Low confidence content.",
        "source": "next.js docs",
        "relevance_score": 1.0,
    }]

    with patch("app.nodes.chunk_reader.chat", return_value=mock_response):
        state = _base_state(ranked_chunks=[chunk], evidence_items=existing, evidence_score=0.5)
        result = chunk_reader_node(state)

    expected_score = compute_coverage_score(result["evidence_items"])
    assert result["evidence_score"] == pytest.approx(expected_score)
    assert result["evidence_score"] != pytest.approx(0.7)


def test_chunk_reader_increments_stalled_cycles_when_no_new_evidence():
    from app.nodes.chunk_reader import chunk_reader_node

    mock_response = '[{"chunk_index": 0, "claims": ["App Router uses layouts"], "confidence": 0.9}]'
    chunk = {
        "chunk_id": "c1", "file_path": "docs/routing.md",
        "section": "Layouts", "content": "Layouts are shared UI.",
        "source": "next.js docs", "rerank_score": 5.0,
    }
    existing = [{
        "file_path": "docs/routing.md",
        "claims": ["App Router uses layouts"],
        "confidence": 0.9,
        "content": "Layouts are shared UI.",
        "source": "next.js docs",
        "relevance_score": 5.0,
    }]

    with patch("app.nodes.chunk_reader.chat", return_value=mock_response):
        state = _base_state(
            ranked_chunks=[chunk],
            evidence_items=existing,
            evidence_score=0.9,
            best_evidence_score=0.93,
            consecutive_stalled_cycles=1,
        )
        result = chunk_reader_node(state)

    assert result["last_retrieval_new_items"] == 0
    assert result["last_retrieval_evidence_delta"] == pytest.approx(0.0)
    assert result["consecutive_stalled_cycles"] == 2
    assert result["best_evidence_score"] == pytest.approx(0.93)


def test_planner_early_stops_using_best_evidence_score():
    from app.nodes.planner import planner_node

    state = _base_state(
        iteration_count=1,
        evidence_items=[
            {
                "file_path": f"docs/item-{i}.mdx",
                "claims": [f"claim {i}"],
                "confidence": 0.8,
                "content": f"content {i}",
                "source": "docs",
                "relevance_score": 0.85,
            }
            for i in range(4)
        ],
        evidence_score=0.72,
        best_evidence_score=0.88,
        last_retrieval_new_items=1,
        last_retrieval_evidence_delta=0.0,
        consecutive_stalled_cycles=0,
    )

    with patch("app.nodes.planner.chat") as mock_chat:
        result = planner_node(state)

    mock_chat.assert_not_called()
    assert result["enough_evidence"] is True


# ─── Final Synthesizer Node ───────────────────────────────────────────────────

def test_synthesizer_no_evidence_returns_fallback():
    from app.nodes.final_synthesizer import final_synthesizer_node
    state = _base_state(evidence_items=[])
    result = final_synthesizer_node(state)
    assert "could not find" in result["final_answer"].lower()
    assert result["citations"] == []


def test_synthesizer_parses_citations():
    from app.nodes.final_synthesizer import final_synthesizer_node

    mock_answer = (
        "The App Router uses file-system routing.\n\n---\n"
        "**Citations:**\n- [Source: docs/app/routing/page.md]"
    )

    evidence = [{
        "file_path": "docs/app/routing/page.md",
        "claims": ["App Router uses file-system routing"],
        "confidence": 0.9,
        "content": "The App Router...",
        "source": "next.js docs",
        "relevance_score": 0.9,
    }]

    with patch("app.nodes.final_synthesizer.chat", return_value=mock_answer):
        state = _base_state(evidence_items=evidence)
        result = final_synthesizer_node(state)

    assert "[Source: docs/app/routing/page.md]" in result["citations"]
    assert "App Router" in result["final_answer"]


def test_synthesizer_deduplicates_citations():
    from app.nodes.final_synthesizer import final_synthesizer_node

    mock_answer = (
        "Streaming works with Suspense.\n\n---\n"
        "**Citations:**\n"
        "- [Source: docs/streaming.mdx]\n"
        "- [Source: docs/streaming.mdx]\n"
        "- [Source: docs/loading.mdx]"
    )

    evidence = [{
        "file_path": "docs/streaming.mdx",
        "claims": ["Streaming works with Suspense"],
        "confidence": 0.9,
        "content": "Streaming content...",
        "source": "next.js docs",
        "relevance_score": 0.9,
    }]

    with patch("app.nodes.final_synthesizer.chat", return_value=mock_answer):
        state = _base_state(evidence_items=evidence)
        result = final_synthesizer_node(state)

    assert result["citations"] == [
        "[Source: docs/streaming.mdx]",
        "[Source: docs/loading.mdx]",
    ]


def test_synthesizer_strips_artificial_answer_wrapper():
    from app.nodes.final_synthesizer import final_synthesizer_node

    mock_answer = (
        "<answer>Next.js uses React Server Components and can render streaming responses.</answer>\n\n---\n"
        "**Citations:**\n"
        "- [Source: docs/streaming.mdx]"
    )

    evidence = [{
        "file_path": "docs/streaming.mdx",
        "claims": ["Next.js can stream responses"],
        "confidence": 0.9,
        "content": "Streaming content...",
        "source": "next.js docs",
        "relevance_score": 0.9,
    }]

    with patch("app.nodes.final_synthesizer.chat", return_value=mock_answer):
        state = _base_state(evidence_items=evidence)
        result = final_synthesizer_node(state)

    assert result["final_answer"].startswith("Next.js uses React Server Components")
    assert "<answer>" not in result["final_answer"]
    assert "</answer>" not in result["final_answer"]


def test_synthesizer_llm_error_uses_fallback():
    from app.nodes.final_synthesizer import final_synthesizer_node
    from openai import APIConnectionError

    evidence = [{
        "file_path": "docs/routing.md",
        "claims": ["App Router is file-system based"],
        "confidence": 0.85,
        "content": "The App Router...",
        "source": "next.js docs",
        "relevance_score": 0.85,
    }]

    with patch("app.nodes.final_synthesizer.chat", side_effect=APIConnectionError(request=MagicMock())):
        state = _base_state(evidence_items=evidence)
        result = final_synthesizer_node(state)

    # Fallback answer should still be non-empty
    assert result["final_answer"] != ""


def test_semantic_cache_restores_best_evidence_score():
    from app.utils.semantic_cache import check_semantic_cache

    fake_collection = MagicMock()
    fake_collection.count.return_value = 1
    fake_collection.query.return_value = {
        "ids": [["cache-id"]],
        "distances": [[0.0]],
        "metadatas": [[{
            "final_answer": "cached answer",
            "citations": '["[Source: docs/example.mdx]"]',
            "evidence_score": 0.71,
            "best_evidence_score": 0.88,
        }]],
    }

    fake_embedder = MagicMock()
    fake_vector = MagicMock()
    fake_vector.tolist.return_value = [0.1, 0.2, 0.3]
    fake_embedder.encode.return_value = [fake_vector]

    with patch("app.utils.semantic_cache._get_cache_collection", return_value=fake_collection), \
         patch("app.utils.semantic_cache.get_embedding_model", return_value=fake_embedder):
        result = check_semantic_cache("cached query")

    assert result is not None
    assert result["evidence_score"] == pytest.approx(0.71)
    assert result["best_evidence_score"] == pytest.approx(0.88)


def test_api_responds_with_best_and_current_evidence_scores():
    from fastapi.testclient import TestClient
    from api.main import app

    fake_result = {
        "final_answer": "answer",
        "citations": ["[Source: docs/example.mdx]"],
        "evidence_score": 0.71,
        "best_evidence_score": 0.88,
        "_from_cache": True,
    }

    with patch("api.main.PRELOAD_MODELS_ON_STARTUP", False), \
         patch("api.main.run_query", return_value=fake_result):
        with TestClient(app) as client:
            response = client.post("/ask", json={"query": "test query"})

    assert response.status_code == 200
    body = response.json()
    assert body["evidence_score"] == pytest.approx(0.88)
    assert body["best_evidence_score"] == pytest.approx(0.88)
    assert body["current_evidence_score"] == pytest.approx(0.71)
    assert body["from_cache"] is True


def test_source_download_returns_repo_file(tmp_path: Path):
    from fastapi.testclient import TestClient
    from api.main import app

    docs_root = tmp_path / "nextjs-repo"
    docs_root.mkdir()
    target = docs_root / "docs" / "guide.mdx"
    target.parent.mkdir(parents=True)
    target.write_text("# Guide\n", encoding="utf-8")

    with patch("api.main.PRELOAD_MODELS_ON_STARTUP", False), \
         patch("api.main.NEXTJS_REPO_ROOT", docs_root.resolve()):
        with TestClient(app) as client:
            response = client.get("/source/download", params={"path": "docs/guide.mdx"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "attachment" in response.headers["content-disposition"].lower()
    assert "# Guide" in response.text


def test_source_download_blocks_path_traversal(tmp_path: Path):
    from fastapi.testclient import TestClient
    from api.main import app

    docs_root = tmp_path / "nextjs-repo"
    docs_root.mkdir()
    outside = tmp_path / "outside.mdx"
    outside.write_text("outside", encoding="utf-8")

    with patch("api.main.PRELOAD_MODELS_ON_STARTUP", False), \
         patch("api.main.NEXTJS_REPO_ROOT", docs_root.resolve()):
        with TestClient(app) as client:
            response = client.get("/source/download", params={"path": "../outside.mdx"})

    assert response.status_code == 400


# ─── Reranker Node ────────────────────────────────────────────────────────────

def test_reranker_returns_top_k():
    import os
    os.environ["TOP_K_RERANK"] = "5"
    from app.nodes.reranker import reranker_node

    chunks = [
        {"chunk_id": f"c{i}", "content": f"content {i}", "bm25_score": float(i), "vector_score": float(i), "rrf_score": 0.0}
        for i in range(20)
    ]
    state = _base_state(candidate_chunks=chunks, rewritten_queries=["test query"])
    result = reranker_node(state)
    assert len(result["ranked_chunks"]) <= 5


def test_reranker_empty_candidates():
    from app.nodes.reranker import reranker_node
    state = _base_state(candidate_chunks=[])
    result = reranker_node(state)
    assert result["ranked_chunks"] == []


# ─── Evidence Store ───────────────────────────────────────────────────────────

def test_coverage_score_empty():
    from app.memory.evidence_store import compute_coverage_score
    assert compute_coverage_score([]) == 0.0


def test_coverage_score_single_item():
    from app.memory.evidence_store import compute_coverage_score
    items = [{"confidence": 0.8, "content": "", "source": "", "file_path": "", "relevance_score": 0, "claims": []}]
    score = compute_coverage_score(items)
    assert score == pytest.approx(0.8)


def test_top_evidence_ordering():
    from app.memory.evidence_store import get_top_evidence
    items = [
        {"confidence": 0.5, "content": "", "source": "", "file_path": "", "relevance_score": 0, "claims": []},
        {"confidence": 0.9, "content": "", "source": "", "file_path": "", "relevance_score": 0, "claims": []},
        {"confidence": 0.3, "content": "", "source": "", "file_path": "", "relevance_score": 0, "claims": []},
    ]
    top = get_top_evidence(items, top_k=2)
    assert top[0]["confidence"] == 0.9
    assert top[1]["confidence"] == 0.5


# ─── End-to-End (fully mocked) ────────────────────────────────────────────────

def test_e2e_graph_with_mocked_llm_and_retrievers():
    """
    Integration test: runs the full compiled graph with all external
    calls (LLM, BM25, ChromaDB) mocked.
    """
    from app.graph.builder import run_query

    planner_response = '{"enough_evidence": false, "rewritten_queries": ["app router routing"], "sub_questions": ["How does routing work?"], "retrieval_routes": ["hybrid"]}'
    planner_response_2 = '{"enough_evidence": true, "rewritten_queries": [], "sub_questions": [], "retrieval_routes": []}'
    chunk_reader_response = '[{"chunk_index": 0, "claims": ["App Router uses file-system routing"], "confidence": 0.88}]'
    specialist_response = '{"strategy": "hybrid", "bm25_queries": ["app router routing"], "vector_queries": ["How does App Router routing work in Next.js?"], "rationale": "test"}'
    synthesizer_response = "The App Router uses file-system routing.\n\n---\n**Citations:**\n- [Source: docs/app/routing.md]"

    call_count = {"n": 0}
    def mock_chat(messages, temperature=0.0):
        n = call_count["n"]
        call_count["n"] += 1
        if n == 0:
            return planner_response        # planner iteration 0
        elif n == 1:
            return specialist_response     # retrieval specialist
        elif n == 2:
            return chunk_reader_response   # chunk reader
        elif n == 3:
            return planner_response_2      # planner iteration 1 (enough evidence)
        else:
            return synthesizer_response    # final synthesizer

    fake_chunk = {
        "chunk_id": "c1", "doc_id": "d1", "title": "Routing", "section": "App Router",
        "content": "The App Router uses file-system routing.", "source": "next.js docs",
        "file_path": "docs/app/routing.md", "tokens": 10, "bm25_score": 1.0,
        "vector_score": 0.9, "rrf_score": 0.5,
    }

    with patch("app.nodes.planner.chat", side_effect=mock_chat), \
         patch("app.nodes.retrieval_specialist.chat", side_effect=mock_chat), \
         patch("app.nodes.chunk_reader.chat", side_effect=mock_chat), \
         patch("app.nodes.final_synthesizer.chat", side_effect=mock_chat), \
         patch("app.retrievers.bm25_retriever.bm25_search", return_value=[fake_chunk]), \
         patch("app.retrievers.vector_retriever.vector_search", return_value=[fake_chunk]), \
         patch("app.utils.semantic_cache.check_semantic_cache", return_value=None), \
         patch("app.utils.semantic_cache.save_to_semantic_cache", return_value=None):

        result = run_query("How does the App Router work in Next.js?")

    assert result.get("final_answer") != ""
    assert isinstance(result.get("citations"), list)
