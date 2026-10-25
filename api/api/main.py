"""
FastAPI — trade_knowledge API
POST /ask  →  { answer, citations, evidence_score, best_evidence_score, current_evidence_score, from_cache }
"""

import os
import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.graph.builder import get_graph, run_query, run_query_traced
from app.tools.database import init_db
from app.utils.events import Trace, set_trace, reset_trace
from app.utils.logger import get_logger
from app.utils.model_registry import preload_runtime_models

log = get_logger(__name__)

# ── Rate Limiter ─────────────────────────────────────────────────────────────
RATE_LIMIT = os.getenv("RATE_LIMIT", "10/minute")
limiter = Limiter(key_func=get_remote_address, default_limits=[RATE_LIMIT])

# ── CORS Origins ─────────────────────────────────────────────────────────────
_raw_origins = os.getenv("CORS_ORIGINS", "*")
CORS_ORIGINS: list[str] = (
    ["*"] if _raw_origins.strip() == "*"
    else [o.strip() for o in _raw_origins.split(",") if o.strip()]
)
DOCS_ROOT = Path(os.getenv("DOCS_DIR", "./data_docs")).resolve()

PRELOAD_MODELS_ON_STARTUP = os.getenv("PRELOAD_MODELS_ON_STARTUP", "true").lower() == "true"


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Initialize the simulated ERP/WMS database (idempotent)
    try:
        db_path = init_db()
        log.info("api.startup.db_ready", path=db_path)
    except Exception as e:
        log.error("api.startup.db_error", error=str(e))

    if PRELOAD_MODELS_ON_STARTUP:
        try:
            log.info("api.startup.preload.begin")
            get_graph()
            preload_runtime_models()
            log.info("api.startup.preload.done")
        except Exception as e:
            log.warning("api.startup.preload.error", error=str(e))
    yield

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="商社業務アシスタント — Catalog RAG + ERP Tools",
    description="Agentic system combining product-catalog RAG with stock/order/logistics tools.",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schemas ───────────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[str]
    evidence_score: float
    best_evidence_score: float
    current_evidence_score: float
    from_cache: bool
    route: str | None = None
    business_result: dict | None = None


def _resolve_repo_file(relative_path: str) -> Path:
    """Resolve a catalog-relative file path safely within the docs directory."""
    normalized = relative_path.strip().lstrip("/")
    if not normalized:
        raise HTTPException(status_code=400, detail="Path cannot be empty.")

    candidate = (DOCS_ROOT / normalized).resolve()
    try:
        candidate.relative_to(DOCS_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid path.") from exc

    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    return candidate


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/health")
def health_check():
    return {"status": "ok", "version": app.version}


@app.get("/source/download")
def download_source(path: str):
    source_file = _resolve_repo_file(path)
    media_type = (
        "application/pdf" if source_file.suffix.lower() == ".pdf"
        else "text/markdown; charset=utf-8"
    )
    return FileResponse(
        source_file,
        media_type=media_type,
        filename=source_file.name,
    )


def _build_response(result: dict) -> dict:
    """Map a final graph state into the public response payload."""
    current_evidence_score = round(float(result.get("evidence_score", 0.0)), 4)
    best_evidence_score = round(
        float(result.get("best_evidence_score", result.get("evidence_score", 0.0))),
        4,
    )
    return {
        "answer": result.get("final_answer", ""),
        "citations": result.get("citations", []),
        "evidence_score": best_evidence_score,
        "best_evidence_score": best_evidence_score,
        "current_evidence_score": current_evidence_score,
        "from_cache": bool(result.get("_from_cache", False)),
        "route": result.get("route"),
        "business_result": result.get("business_result") or None,
    }


def _sse(event: str, data: dict) -> str:
    """Format one Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/ask", response_model=QueryResponse)
@limiter.limit(RATE_LIMIT)
def ask(request: Request, body: QueryRequest):
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    log.info("api.ask.request", query_preview=body.query[:80])

    try:
        result = run_query(body.query)
    except Exception as e:
        log.error("api.ask.error", error=str(e))
        raise HTTPException(status_code=500, detail="Internal error processing your query.")

    payload = _build_response(result)
    log.info(
        "api.ask.response",
        evidence_score=payload["best_evidence_score"],
        current_evidence_score=payload["current_evidence_score"],
        from_cache=payload["from_cache"],
        citations=len(payload["citations"]),
    )
    return QueryResponse(**payload)


@app.post("/ask/stream")
def ask_stream(request: Request, body: QueryRequest):
    """
    Streaming endpoint (SSE). Emits ordered execution events so the UI can
    show the live agent trace and type the final answer:
      cache / node / llm / sql / tool / answer_delta / final / error
    """
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    log.info("api.ask.stream.request", query_preview=body.query[:80])

    def event_generator():
        trace = Trace()

        def worker():
            token = set_trace(trace)
            try:
                result = run_query_traced(body.query)
                trace.emit("final", data=_build_response(result))
            except Exception as e:
                log.error("api.ask.stream.error", error=str(e))
                trace.emit("error", message="Internal error processing your query.")
            finally:
                reset_trace(token)
                trace.close()

        threading.Thread(target=worker, daemon=True).start()

        yield _sse("status", {"stage": "started", "query": body.query})
        while True:
            event = trace.queue.get()
            if event is None:
                break
            kind = event.pop("type", "message")
            # Remove bookkeeping fields the client does not need.
            event.pop("seq", None)
            yield _sse(kind, event)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
