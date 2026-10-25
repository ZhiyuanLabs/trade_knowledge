import argparse
import json
import os
import statistics
import time
import urllib.request
from datetime import datetime, UTC
from pathlib import Path
from urllib.error import HTTPError, URLError

import chromadb
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DEFAULT_QUERIES = [
    "How does caching work in the Next.js App Router?",
    "How do cookies(), headers(), and searchParams affect static optimization, caching, and dynamic rendering in the Next.js App Router?",
    "How do generateStaticParams, dynamicParams, and notFound() interact in the Next.js App Router, and what are the practical implications for static generation and runtime behavior?",
]

CACHE_COLLECTION_NAME = "semantic_cache"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "eval"


def _resolve_chroma_path() -> Path:
    configured = os.getenv("CHROMA_PATH", "./data/chroma_db")
    path = Path(configured)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def clear_semantic_cache() -> None:
    """Delete only the semantic cache collection, preserving the docs index."""
    client = chromadb.PersistentClient(path=str(_resolve_chroma_path()))
    try:
        client.delete_collection(CACHE_COLLECTION_NAME)
        print("Semantic cache cleared.")
    except Exception:
        print("Semantic cache was already empty or unavailable.")


def ask(base_url: str, query: str, timeout: float) -> tuple[float, dict]:
    payload = json.dumps({"query": query}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/ask",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    elapsed = time.perf_counter() - start
    return elapsed, body


def summarize(times: list[float]) -> dict:
    if not times:
        return {
            "avg_seconds": 0.0,
            "median_seconds": 0.0,
            "min_seconds": 0.0,
            "max_seconds": 0.0,
        }
    return {
        "avg_seconds": round(statistics.mean(times), 4),
        "median_seconds": round(statistics.median(times), 4),
        "min_seconds": round(min(times), 4),
        "max_seconds": round(max(times), 4),
    }


def run_phase(phase: str, base_url: str, queries: list[str], timeout: float) -> dict:
    phase_results = []
    elapsed_values: list[float] = []

    print(f"\n{phase.upper()} phase")
    print("-" * 32)

    for index, query in enumerate(queries, start=1):
        try:
            elapsed, body = ask(base_url, query, timeout)
        except HTTPError as exc:
            raise RuntimeError(f"[{phase}:{index}] HTTP error {exc.code}: {exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"[{phase}:{index}] Connection error: {exc.reason}") from exc

        elapsed_values.append(elapsed)
        phase_results.append(
            {
                "query": query,
                "elapsed_seconds": round(elapsed, 4),
                "evidence_score": round(float(body.get("evidence_score", 0.0)), 4),
                "best_evidence_score": round(float(body.get("best_evidence_score", 0.0)), 4),
                "current_evidence_score": round(float(body.get("current_evidence_score", 0.0)), 4),
                "citations_count": len(body.get("citations", [])),
            }
        )

        print(f"[{index}] {elapsed:.2f}s")
        print(f"      query: {query}")
        print(
            "      scores:"
            f" evidence={body.get('evidence_score', 0.0):.4f}"
            f" best={body.get('best_evidence_score', 0.0):.4f}"
            f" current={body.get('current_evidence_score', 0.0):.4f}"
        )
        print(f"      citations: {len(body.get('citations', []))}")

    summary = summarize(elapsed_values)
    print("\nSummary")
    print(f"  avg:    {summary['avg_seconds']:.2f}s")
    print(f"  median: {summary['median_seconds']:.2f}s")
    print(f"  min:    {summary['min_seconds']:.2f}s")
    print(f"  max:    {summary['max_seconds']:.2f}s")

    return {
        "phase": phase,
        "summary": summary,
        "results": phase_results,
    }


def save_results(output_path: Path, payload: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nSaved results to {output_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Local latency benchmark for the trade_knowledge /ask endpoint with cold and warm modes.",
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000",
        help="Base URL for the API. Default: %(default)s",
    )
    parser.add_argument(
        "--query",
        action="append",
        help="Query to benchmark. Can be provided multiple times. If omitted, built-in queries are used.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Per-request timeout in seconds. Default: %(default)s",
    )
    parser.add_argument(
        "--mode",
        choices=["cold", "warm", "both"],
        default="both",
        help="Benchmark mode. Default: %(default)s",
    )
    parser.add_argument(
        "--preserve-cache",
        action="store_true",
        help="Do not clear the semantic cache before the cold phase.",
    )
    parser.add_argument(
        "--output",
        help="Optional JSON file path for benchmark results. Defaults to data/eval/benchmark_<timestamp>.json",
    )
    args = parser.parse_args()

    queries = args.query or DEFAULT_QUERIES
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else (DEFAULT_OUTPUT_DIR / f"benchmark_{timestamp}.json")
    )

    print("trade_knowledge local benchmark")
    print(f"Target: {args.url.rstrip('/')}/ask")
    print(f"Mode: {args.mode}")
    print(f"Queries: {len(queries)}")

    phases: list[dict] = []

    if args.mode in {"cold", "both"}:
        if not args.preserve_cache:
            clear_semantic_cache()
        phases.append(run_phase("cold", args.url, queries, args.timeout))

    if args.mode in {"warm", "both"}:
        if args.mode == "warm":
            print("\nWarm mode assumes these queries are already cached.")
        phases.append(run_phase("warm", args.url, queries, args.timeout))

    payload = {
        "timestamp_utc": timestamp,
        "target_url": args.url.rstrip("/"),
        "mode": args.mode,
        "queries": queries,
        "preserve_cache": args.preserve_cache,
        "phases": phases,
    }

    if len(phases) == 2:
        cold_avg = phases[0]["summary"]["avg_seconds"]
        warm_avg = phases[1]["summary"]["avg_seconds"]
        if warm_avg > 0:
            payload["speedup_ratio"] = round(cold_avg / warm_avg, 2)
            print(f"\nCold/Warm speedup: {payload['speedup_ratio']:.2f}x")

    save_results(output_path, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
