"""Repeatable evaluation for the Japanese fruit-trading assistant.

The suite always computes deterministic route, retrieval, business-data,
refusal, cache-consistency and latency metrics. Ragas faithfulness is optional
because structured facts should be checked against their authoritative data,
not delegated to an LLM judge.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
load_dotenv(API_ROOT / ".env")

DEFAULT_DATASET = Path(__file__).with_name("trade_knowledge_eval.json")
DEFAULT_OUTPUT_DIR = API_ROOT / "data" / "eval"
REFUSAL_MARKERS = ("見つかりません", "該当する情報がありません", "確認できません", "情報が不足", "回答できません")


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise ValueError("Evaluation dataset must contain a 'cases' list.")
    seen: set[str] = set()
    valid_categories = {"catalog", "business", "hybrid", "refusal"}
    for case in cases:
        case_id = str(case.get("id", ""))
        if not case_id or case_id in seen:
            raise ValueError(f"Missing or duplicate case id: {case_id!r}")
        seen.add(case_id)
        if case.get("category") not in valid_categories:
            raise ValueError(f"{case_id}: invalid category {case.get('category')!r}")
        if not case.get("question") or not case.get("expected_route"):
            raise ValueError(f"{case_id}: question and expected_route are required")
    return cases


def _source_name(value: str) -> str:
    value = value.strip().replace("\\", "/")
    if value.startswith("[Source:"):
        value = value[len("[Source:") :].rstrip("]").strip()
    return Path(value).name


def retrieved_sources(state: dict[str, Any], k: int) -> list[str]:
    evidence = sorted(
        state.get("evidence_items") or [],
        key=lambda item: float(item.get("confidence", 0.0)),
        reverse=True,
    )
    sources: list[str] = []
    for item in evidence:
        source = _source_name(str(item.get("file_path") or item.get("source") or ""))
        if source and source not in sources:
            sources.append(source)
        if len(sources) >= k:
            break
    return sources


def source_recall(expected: list[str], actual: list[str]) -> float | None:
    if not expected:
        return None
    expected_set = {_source_name(item) for item in expected}
    actual_set = {_source_name(item) for item in actual}
    return len(expected_set & actual_set) / len(expected_set)


def _row_matches(row: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(row.get(key) == value for key, value in expected.items())


def business_fact_accuracy(
    expected_facts: list[dict[str, Any]], business_result: dict[str, Any]
) -> tuple[int, int, list[dict[str, Any]]]:
    matched = 0
    missing: list[dict[str, Any]] = []
    for fact in expected_facts:
        rows = business_result.get(str(fact["section"])) or []
        expected_row = dict(fact["match"])
        if any(_row_matches(row, expected_row) for row in rows):
            matched += 1
        else:
            missing.append(fact)
    return matched, len(expected_facts), missing


def _has_business_rows(state: dict[str, Any]) -> bool:
    result = state.get("business_result") or {}
    return any(result.get(section) for section in ("stock", "orders", "shipments", "alerts"))


def refusal_passed(state: dict[str, Any]) -> bool:
    answer = str(state.get("final_answer", ""))
    return any(marker in answer for marker in REFUSAL_MARKERS) and not state.get("citations") and not _has_business_rows(state)


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def latency_summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean_seconds": 0.0, "p50_seconds": 0.0, "p95_seconds": 0.0}
    return {
        "mean_seconds": round(statistics.mean(values), 4),
        "p50_seconds": round(percentile(values, 0.50), 4),
        "p95_seconds": round(percentile(values, 0.95), 4),
    }


def _contexts(state: dict[str, Any]) -> list[str]:
    contexts = [
        str(item.get("content", "")).strip()
        for item in state.get("evidence_items") or []
        if str(item.get("content", "")).strip()
    ]
    business_context = str(state.get("business_context", "")).strip()
    if business_context:
        contexts.insert(0, business_context)
    return contexts


def evaluate_case(case: dict[str, Any], state: dict[str, Any], elapsed: float, k: int) -> dict[str, Any]:
    actual_sources = retrieved_sources(state, k)
    expected_sources = list(case.get("expected_sources") or [])
    matched, total, missing = business_fact_accuracy(
        list(case.get("expected_facts") or []), state.get("business_result") or {}
    )
    return {
        "id": case["id"], "category": case["category"], "question": case["question"],
        "expected_route": case["expected_route"], "actual_route": state.get("route"),
        "route_correct": state.get("route") == case["expected_route"],
        "latency_seconds": round(elapsed, 4), "expected_sources": expected_sources,
        f"retrieved_sources_at_{k}": actual_sources,
        f"retrieval_recall_at_{k}": source_recall(expected_sources, actual_sources),
        "business_facts_matched": matched, "business_facts_total": total,
        "business_accuracy": (matched / total) if total else None,
        "missing_business_facts": missing,
        "refusal_correct": refusal_passed(state) if case["category"] == "refusal" else None,
        "from_cache": bool(state.get("_from_cache", False)), "citations": state.get("citations") or [],
        "answer": state.get("final_answer", ""), "contexts": _contexts(state),
        "error": None, "faithfulness": None,
    }


def run_faithfulness(rows: list[dict[str, Any]]) -> str | None:
    eligible = [row for row in rows if row["contexts"] and not row["error"]]
    if not eligible:
        return "No successful rows with contexts were available for faithfulness."
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    base_url, model = os.getenv("OPENAI_BASE_URL"), os.getenv("LLM_MODEL")
    if not api_key or not model:
        return "OPENAI_API_KEY/DEEPSEEK_API_KEY and LLM_MODEL are required for faithfulness."
    try:
        from datasets import Dataset
        from langchain_openai import ChatOpenAI
        from ragas import evaluate
        from ragas.llms import LangchainLLMWrapper
        from ragas.metrics.collections import faithfulness

        judge = ChatOpenAI(
            model=model, api_key=api_key, base_url=base_url or None, temperature=0.0,
            timeout=float(os.getenv("LLM_TIMEOUT", "30")),
        )
        dataset = Dataset.from_dict({
            "user_input": [row["question"] for row in eligible],
            "response": [row["answer"] for row in eligible],
            "retrieved_contexts": [row["contexts"] for row in eligible],
        })
        scores = evaluate(
            dataset=dataset, metrics=[faithfulness], llm=LangchainLLMWrapper(judge),
            raise_exceptions=False,
        ).to_pandas()["faithfulness"].tolist()
        for row, score in zip(eligible, scores, strict=True):
            row["faithfulness"] = None if score is None or math.isnan(float(score)) else float(score)
        return None
    except Exception as exc:
        return f"Faithfulness evaluation failed: {type(exc).__name__}: {exc}"


def cache_consistency(run_query: Any, cases: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    selected = [case for case in cases if case["category"] == "catalog"][:count]
    results: list[dict[str, Any]] = []
    for case in selected:
        first, second = run_query(case["question"]), run_query(case["question"])
        result = {
            "id": case["id"], "cache_hit": bool(second.get("_from_cache", False)),
            "answer_equal": first.get("final_answer") == second.get("final_answer"),
            "citations_equal": first.get("citations") == second.get("citations"),
            "route_equal": first.get("route") == second.get("route"),
        }
        result["passed"] = all(result[key] for key in ("cache_hit", "answer_equal", "citations_equal", "route_equal"))
        results.append(result)
    return results


def summarize(rows: list[dict[str, Any]], cache_results: list[dict[str, Any]], k: int) -> dict[str, Any]:
    successful = [row for row in rows if not row["error"]]
    recall_values = [row[f"retrieval_recall_at_{k}"] for row in successful if row[f"retrieval_recall_at_{k}"] is not None]
    business_matched = sum(row["business_facts_matched"] for row in successful)
    business_total = sum(row["business_facts_total"] for row in successful)
    refusals = [row["refusal_correct"] for row in successful if row["refusal_correct"] is not None]
    faithfulness_values = [row["faithfulness"] for row in successful if row["faithfulness"] is not None]
    by_category: dict[str, list[float]] = defaultdict(list)
    for row in successful:
        by_category[row["category"]].append(row["latency_seconds"])
    return {
        "cases_total": len(rows), "cases_succeeded": len(successful),
        "route_accuracy": sum(row["route_correct"] for row in successful) / len(successful) if successful else None,
        f"retrieval_recall_at_{k}": statistics.mean(recall_values) if recall_values else None,
        "business_data_accuracy": business_matched / business_total if business_total else None,
        "refusal_accuracy": sum(refusals) / len(refusals) if refusals else None,
        "faithfulness": statistics.mean(faithfulness_values) if faithfulness_values else None,
        "cache_consistency": sum(item["passed"] for item in cache_results) / len(cache_results) if cache_results else None,
        "latency": latency_summary([row["latency_seconds"] for row in successful]),
        "latency_by_category": {category: latency_summary(values) for category, values in sorted(by_category.items())},
    }


def _write_results(output_dir: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = payload["timestamp_utc"].replace(":", "").replace("-", "")
    json_path, csv_path = output_dir / f"evaluation_{stamp}.json", output_dir / f"evaluation_{stamp}.csv"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = ["id", "category", "question", "expected_route", "actual_route", "route_correct", "latency_seconds", "business_accuracy", "refusal_correct", "from_cache", "faithfulness", "error"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(payload["results"])
    return json_path, csv_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--category", action="append", choices=["catalog", "business", "hybrid", "refusal"])
    parser.add_argument("--limit", type=int, help="Run only the first N selected cases.")
    parser.add_argument("--recall-k", type=int, default=5)
    parser.add_argument("--cache-cases", type=int, default=3)
    parser.add_argument("--skip-faithfulness", action="store_true")
    parser.add_argument("--skip-cache", action="store_true")
    parser.add_argument("--validate-only", action="store_true", help="Validate the dataset without calling the agent.")
    args = parser.parse_args()

    cases = load_cases(args.dataset.resolve())
    if args.category:
        cases = [case for case in cases if case["category"] in args.category]
    if args.limit is not None:
        cases = cases[: args.limit]
    print(f"Dataset valid: {len(cases)} selected cases ({args.dataset})")
    if args.validate_only:
        return 0

    from app.graph.builder import run_query
    from app.tools.database import init_db

    # The API lifespan normally performs this step. The evaluator invokes the
    # graph directly, so it must also support a clean database path.
    init_db()

    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index:02d}/{len(cases):02d}] {case['id']}: {case['question']}")
        started = time.perf_counter()
        try:
            state = run_query(case["question"])
            row = evaluate_case(case, state, time.perf_counter() - started, args.recall_k)
            print(f"  route={row['actual_route']} correct={row['route_correct']} latency={row['latency_seconds']:.2f}s")
        except Exception as exc:
            row = {
                "id": case["id"], "category": case["category"], "question": case["question"],
                "expected_route": case["expected_route"], "actual_route": None, "route_correct": False,
                "latency_seconds": round(time.perf_counter() - started, 4), "business_facts_matched": 0,
                "business_facts_total": len(case.get("expected_facts") or []), "business_accuracy": None,
                "refusal_correct": None, "from_cache": False, "faithfulness": None, "contexts": [],
                "answer": "", "citations": [], f"retrieval_recall_at_{args.recall_k}": None,
                "error": f"{type(exc).__name__}: {exc}",
            }
            print(f"  ERROR: {row['error']}")
        rows.append(row)

    faithfulness_warning = None if args.skip_faithfulness else run_faithfulness(rows)
    cache_results = [] if args.skip_cache or args.cache_cases <= 0 else cache_consistency(run_query, cases, args.cache_cases)
    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(), "dataset": str(args.dataset.resolve()),
        "recall_k": args.recall_k, "faithfulness_warning": faithfulness_warning,
        "summary": summarize(rows, cache_results, args.recall_k), "cache_results": cache_results,
        "results": rows,
    }
    json_path, csv_path = _write_results(args.output_dir.resolve(), payload)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    if faithfulness_warning:
        print(f"Warning: {faithfulness_warning}")
    print(f"JSON: {json_path}\nCSV:  {csv_path}")
    return 1 if any(row["error"] for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
