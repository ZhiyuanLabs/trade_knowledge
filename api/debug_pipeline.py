"""
Diagnostic script — run this to identify exactly which layer is failing.
Usage: python debug_pipeline.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

QUERY = "How does the App Router work in Next.js?"

print("=" * 60)
print("trade_knowledge DIAGNOSTIC")
print("=" * 60)

# ── 1. LLM connection ──────────────────────────────────────────
print("\n[1] Testing LLM connection...")
try:
    from app.utils.llm import chat, get_model, get_client
    client = get_client()
    model = get_model()
    print(f"    Provider: {os.getenv('LLM_PROVIDER')}")
    print(f"    Model:    {model}")
    print(f"    Base URL: {os.getenv('AZURE_FOUNDRY_BASE_URL')}")
    resp = chat([{"role": "user", "content": "Say only: OK"}])
    print(f"    ✅ LLM response: {resp}")
except Exception as e:
    print(f"    ❌ LLM FAILED: {e}")

# ── 2. BM25 retrieval ──────────────────────────────────────────
print("\n[2] Testing BM25 retrieval...")
try:
    from app.retrievers.bm25_retriever import bm25_search
    results = bm25_search(QUERY, top_k=3)
    print(f"    ✅ BM25 returned {len(results)} results")
    if results:
        print(f"    Top result: [{results[0]['file_path']}] score={results[0].get('bm25_score',0):.3f}")
except Exception as e:
    print(f"    ❌ BM25 FAILED: {e}")

# ── 3. Vector retrieval ────────────────────────────────────────
print("\n[3] Testing Vector retrieval...")
try:
    from app.retrievers.vector_retriever import vector_search
    results = vector_search(QUERY, top_k=3)
    print(f"    ✅ Vector returned {len(results)} results")
    if results:
        print(f"    Top result: [{results[0]['file_path']}] score={results[0].get('vector_score',0):.3f}")
except Exception as e:
    print(f"    ❌ Vector FAILED: {e}")

# ── 4. Planner node ────────────────────────────────────────────
print("\n[4] Testing Planner node...")
try:
    from app.nodes.planner import planner_node
    from app.state.schema import GraphState
    state: GraphState = {
        "user_query": QUERY,
        "rewritten_queries": [], "sub_questions": [],
        "retrieval_routes": [], "candidate_chunks": [],
        "ranked_chunks": [], "evidence_items": [],
        "evidence_score": 0.0, "enough_evidence": False,
        "iteration_count": 0, "citations": [], "final_answer": "",
    }
    out = planner_node(state)
    print(f"    ✅ Rewritten queries: {out['rewritten_queries']}")
except Exception as e:
    print(f"    ❌ Planner FAILED: {e}")

print("\n" + "=" * 60)
print("Diagnostic complete.")
