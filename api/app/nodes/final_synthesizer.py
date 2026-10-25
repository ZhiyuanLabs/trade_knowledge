"""
Node 6 — Final Synthesizer
Generates the final answer grounded exclusively in collected evidence.
Produces citations from evidence file paths.
"""

import os
import re
from app.state.schema import GraphState
from app.utils.llm import answer_chat
from app.utils.logger import get_logger

log = get_logger(__name__)

_EVIDENCE_MAX_WORDS = int(os.getenv("EVIDENCE_MAX_WORDS", "500"))

# RESPONSE_LANGUAGE controls the output language of the final answer.
# "english" (default) — always respond in English regardless of query language.
# "match_query"       — respond in the same language as the user's question.
# Any other value     — treated as an explicit BCP-47 language tag (e.g. "pt", "es", "fr").
_RESPONSE_LANGUAGE = os.getenv("RESPONSE_LANGUAGE", "english").lower()


def _language_instruction() -> str:
    if _RESPONSE_LANGUAGE == "english":
        return "IMPORTANT: Always respond in English, regardless of the language of the user question."
    if _RESPONSE_LANGUAGE == "match_query":
        return "IMPORTANT: Respond in the same language as the user's question."
    return f"IMPORTANT: Always respond in {_RESPONSE_LANGUAGE}, regardless of the language of the user question."


def _build_system_prompt() -> str:
    return _SYNTHESIZER_SYSTEM_TEMPLATE.format(
        language_instruction=_language_instruction()
    )


def _truncate_to_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " …"


_SYNTHESIZER_SYSTEM_TEMPLATE = """You are a product catalog and business assistant for a Japanese trading company (商社).
You will receive a user question and structured evidence extracted from the company's product catalog,
optionally preceded by operational database results (stock / orders / shipments / safety-stock alerts).

Your task:
1. Write a clear, accurate, and complete answer using ONLY the provided evidence and business data.
2. {language_instruction}
3. Do NOT add information not present in the evidence or business data.
4. For operational questions, state figures, part numbers, order numbers, warehouses and ETAs exactly as given.
5. When safety-stock alerts appear, state the recommended purchase quantity and the incoming shipment ETA, and recommend placing a purchase order.
6. Do NOT use Markdown pipe tables for operational data (stock/orders/shipments); present those figures as short bullet points because the UI already renders them as dedicated cards. A small table is acceptable only when comparing product specifications side by side.
7. At the end, list citations as [Source: <file_path>] for catalog files. Keep any [Source: DB: ...] citations for business data.
8. Do NOT wrap the answer in XML or HTML tags such as <answer>, <response>, or <final_answer>.

Format your response as:
<answer text>

---
**Citations:**
- [Source: ...]
"""


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    """Remove duplicate citations while preserving their first appearance order."""
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        deduped.append(item)
        seen.add(item)
    return deduped


_ANSWER_WRAPPER_RE = re.compile(
    r"^\s*<(?P<tag>answer|response|final_answer)\b[^>]*>\s*(?P<body>.*)\s*</(?P=tag)>\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _strip_artificial_answer_wrapper(text: str) -> str:
    """Remove synthetic outer wrappers like <answer>...</answer> without touching inline doc tags."""
    cleaned = text.strip()

    while True:
        match = _ANSWER_WRAPPER_RE.match(cleaned)
        if not match:
            break
        cleaned = match.group("body").strip()

    return cleaned


def final_synthesizer_node(state: GraphState) -> GraphState:
    """
    Synthesizes the final answer from evidence_items.
    Extracts citations and populates final_answer and citations.
    """
    user_query = state["user_query"]
    evidence_items = state.get("evidence_items", [])
    business_context = state.get("business_context", "").strip()
    business_citations = [
        c for c in state.get("citations", [])
        if isinstance(c, str) and c.startswith("[Source: DB:")
    ]

    if not evidence_items and not business_context:
        return {
            **state,
            "final_answer": "該当する商品情報が見つかりませんでした。商品名・品番・仕様などのキーワードを変えてお試しください。",
            "citations": [],
        }

    # Build evidence context (sorted by confidence, top 8)
    sorted_evidence = sorted(evidence_items, key=lambda e: e["confidence"], reverse=True)[:8]

    # hybrid route: operational DB results are prepended as the first evidence block
    evidence_text = ""
    if business_context:
        evidence_text += f"[業務データベース照会結果]\n{business_context}\n\n"

    seen_sources: list[str] = []
    web_fallback_sources: list[str] = []
    for i, ev in enumerate(sorted_evidence):
        content = _truncate_to_words(ev["content"], _EVIDENCE_MAX_WORDS)
        is_web = ev.get("source_type") == "web_fallback" or ev.get("source", "") == "web_fallback"
        source_label = f"{ev['file_path']} [web]" if is_web else ev["file_path"]
        evidence_text += (
            f"\n[Evidence {i+1}] Source: {source_label}\n"
            f"Content: {content}\n"
            f"Key claims: {'; '.join(ev['claims'])}\n"
        )
        if ev["file_path"] not in seen_sources:
            seen_sources.append(ev["file_path"])
            if is_web:
                web_fallback_sources.append(ev["file_path"])

    messages = [
        {"role": "system", "content": _build_system_prompt()},
        {
            "role": "user",
            "content": f"Question: {user_query}\n\nEvidence:\n{evidence_text}",
        },
    ]

    try:
        answer_text = answer_chat(messages, temperature=0.1, label="final_synthesizer")
    except Exception as e:
        log.error("synthesizer.llm_error", error_type=type(e).__name__, error=str(e))
        # Assemble answer from raw evidence claims and business data
        lines = ["**商品カタログ・業務データに基づく回答:**\n"]
        if business_context:
            lines.append(business_context)
        for i, ev in enumerate(sorted_evidence):
            if ev["claims"]:
                lines.append(f"- {ev['claims'][0]}")
            else:
                lines.append(f"- {ev['content'][:300]}")
        answer_text = "\n".join(lines)

    # Parse citations block
    citations: list[str] = []
    if "---" in answer_text:
        parts = answer_text.split("---", 1)
        answer_body = _strip_artificial_answer_wrapper(parts[0].strip())
        citation_block = parts[1] if len(parts) > 1 else ""
        for line in citation_block.splitlines():
            line = line.strip()
            if line.startswith("- [Source:") or line.startswith("[Source:"):
                raw_citation = line.lstrip("- ").strip()
                # Mark web fallback citations so consumers can display them differently
                if any(wf in raw_citation for wf in web_fallback_sources):
                    raw_citation = raw_citation.rstrip("]") + " — web search]"
                citations.append(raw_citation)
        citations = _dedupe_preserve_order(citations)
    else:
        answer_body = _strip_artificial_answer_wrapper(answer_text.strip())
        citations = [
            f"[Source: {p} — web search]" if p in web_fallback_sources else f"[Source: {p}]"
            for p in seen_sources
        ]
        citations = _dedupe_preserve_order(citations)

    if web_fallback_sources:
        log.warning(
            "synthesizer.web_fallback_in_response",
            web_sources=len(web_fallback_sources),
            total_citations=len(citations),
        )

    # Only trust code-generated business citations; drop any free-form "DB:" rows
    # the LLM wrote (they are tool names rather than concrete record references).
    citations = [c for c in citations if not c.startswith("[Source: DB:")]
    # Merge business (DB) citations first, then catalog citations, de-duplicated
    citations = _dedupe_preserve_order(business_citations + citations)

    log.info("synthesizer.done", citations=len(citations))

    return {
        **state,
        "final_answer": answer_body,
        "citations": citations,
    }
