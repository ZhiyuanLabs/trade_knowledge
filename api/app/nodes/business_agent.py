"""
Business Agent node(s).

The Agent chooses ERP tools (stock / orders / shipments / low-stock), executes
them against the simulated database, and:

  - business_agent_node (business route): synthesizes the final Japanese answer
    with purchase recommendations and ends the graph.
  - business_tools_node (hybrid route): runs only the tools and stores their
    results in state, then hands control to the catalog RAG pipeline so the
    final synthesizer can combine DB facts and catalog documentation.

Agentic behavior:
  - The LLM selects tools and arguments (function-calling style JSON).
  - When a queried product is below safety stock, the node proactively issues a
    shipment/ETA follow-up query even if the LLM did not request one, so the
    answer always includes incoming replenishment and a purchase suggestion.
"""

import json
import re

from app.state.schema import GraphState
from app.tools.business_tools import (
    TOOL_SPECS,
    identify_products,
    _norm,
    _product_aliases,
    run_tools,
)
from app.utils.llm import chat, answer_chat
from app.utils.logger import get_logger

log = get_logger(__name__)

_PLANNER_SYSTEM = """あなたは商社業務エージェントのツール選択担当です。質問に答えるために必要なツールを1つ以上選び、引数を設定してください。

ツール一覧:
{specs}

ルール:
- 在庫数・在庫状況・倉庫を聞かれたら query_stock
- 受注・注文・納期・顧客を聞かれたら query_orders
- 入荷・出荷・物流・いつ届くかを聞かれたら query_shipments
- 安全在庫を下回る商品・発注すべき商品を確認するなら check_low_stock
- 在庫と入荷予定の両方が必要な場合など、必要なら複数のツールを選んでよい
- keyword は商品名・品番・受注番号・顧客名の中核語のみ（修飾語は除く）。全社的な確認なら空文字。

JSONのみで返答:
{{"calls": [{{"tool": "...", "args": {{"keyword": "..."}}}}]}}
"""

_SYNTH_SYSTEM = """あなたは日本の総合商社の営業アシスタントです。
業務データベースの照会結果だけを使い、在庫・受注・入荷状況を日本語で正確に回答してください。

ルール:
- 数値、品番、受注番号、入荷予定日、倉庫名はデータを忠実に記載し、データにない情報は推測しないでください。
- 在庫が安全在庫を下回る商品には、推奨発注数量と入荷予定（ETA）を明示し、「発注をおすすめします」と助言してください。
- 在庫わずか・在庫切れの場合は、入荷予定があれば併記してください。
- Markdownのパイプ表（| ... | の表）は一切使わないでください。在庫・受注・入荷の数値は画面上の専用カードにも表示されるため、本文はまず1〜2文で結論を述べ、続けて要点を箇条書き（-）で簡潔にまとめてください。
- 回答の最後に参照したデータソースを [Source: DB: 商品 品番]、[Source: DB: 受注 受注番号]、[Source: DB: 入出荷 入荷番号] の形式で箇条書きしてください。
- ツール名（query_stock など）や「安全在庫アラート」といったラベルを引用として書かないでください。具体的な品番・伝票番号のみを含めてください。
- 簡潔で読みやすいMarkdown（見出し、箇条書き、太字）で記述してください。
"""


def _parse_json(raw: str) -> dict:
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(cleaned)


def _plan_tools(user_query: str) -> list[dict]:
    """Ask the LLM to select tools and arguments."""
    try:
        raw = chat(
            [
                {"role": "system", "content": _PLANNER_SYSTEM.format(
                    specs=json.dumps(TOOL_SPECS, ensure_ascii=False, indent=2)
                )},
                {"role": "user", "content": f"Question: {user_query}"},
            ],
            temperature=0.0,
            label="business_agent.tool_planning",
        )
        parsed = _parse_json(raw)
        calls = parsed.get("calls", [])
        if isinstance(calls, list) and calls:
            return calls
    except Exception as e:
        log.warning("business_agent.plan_error", error=str(e))
    return []


def _refine_calls(calls: list[dict], user_query: str) -> list[dict]:
    """
    Deterministic guard: when the query mentions concrete product codes (e.g.
    20A / M12 / 6204ZZ / T20), make sure every selected tool targets those
    codes instead of pulling the full table. Keeps the LLM's tool choice,
    only narrows the keyword.
    """
    codes = identify_products(user_query)
    if not codes:
        return calls

    refined: list[dict] = []
    for call in calls:
        name = call.get("tool")
        kw = str((call.get("args") or {}).get("keyword", "")).strip()
        kw_norm = _norm(kw)
        uncovered = [
            code for code in codes
            if not any(_norm(a) in kw_norm for a in _product_aliases(code, ""))
        ]
        if not uncovered:
            # The LLM keyword already pinpoints the mentioned product(s)
            refined.append(call)
        else:
            # Prefer exact code lookup over a broad keyword
            for code in uncovered:
                refined.append({"tool": name, "args": {"keyword": code}})
    return refined


_ORDER_NO_RE = re.compile(r"SO-\d+(?:-\d+)*")
_SHIPMENT_NO_RE = re.compile(r"(?:RC|SH)-\d+")
_BROAD_WORDS = ("すべて", "全部", "全て", "一覧", "全社", "全体", "全商品", "全件", "まとめて")


def _order_keyword(token: str) -> str:
    """
    Normalize an order number into a lookup keyword. Order numbers carry a year
    prefix (SO-2026-1042), so both the full number and the short form SO-1042
    are searched by the >=4-digit tail (1042).
    """
    tail = token.split("-")[-1]
    return tail if len(tail) >= 4 else token


def _deterministic_guard(user_query: str) -> list[dict] | None:
    """
    When the query contains a concrete business document number (order SO-xxxx,
    inbound RC-xxxx, outbound SH-xxxx), force exact single-document lookups
    instead of trusting the LLM's tool plan. This guarantees a typed order /
    shipment number never fans out into a full-table scan.
    """
    upper = user_query.upper()
    order_nos = list(dict.fromkeys(_ORDER_NO_RE.findall(upper)))
    ship_nos = list(dict.fromkeys(n.upper() for n in _SHIPMENT_NO_RE.findall(upper)))
    if not order_nos and not ship_nos:
        return None

    calls: list[dict] = []
    for no in order_nos:
        calls.append({"tool": "query_orders", "args": {"keyword": _order_keyword(no)}})
    for no in ship_nos:
        calls.append({"tool": "query_shipments", "args": {"keyword": no}})
    log.info("business_agent.deterministic_guard", orders=order_nos, shipments=ship_nos)
    return calls


def _strip_unguided_full_scans(calls: list[dict], user_query: str) -> list[dict]:
    """
    Drop empty-keyword full-table scans unless the user explicitly asks for a
    portfolio-wide listing (all / 一覧 / 全件). check_low_stock is inherently
    global and is always kept.
    """
    if any(word in user_query for word in _BROAD_WORDS):
        return calls
    kept: list[dict] = []
    for call in calls:
        name = call.get("tool")
        kw = str((call.get("args") or {}).get("keyword", "")).strip()
        if not kw and name in ("query_stock", "query_orders", "query_shipments"):
            continue
        kept.append(call)
    return kept


def _execute_with_enrichment(calls: list[dict], user_query: str = "") -> dict:
    """Run tools, then proactively add ETA follow-ups for understocked products."""
    calls = _refine_calls(calls, user_query)
    result = run_tools(calls)

    # Proactive agentic step: every alert product without shipment data
    # triggers an inbound/outbound follow-up so the answer can state ETA.
    alerts = result.get("alerts", [])
    shipment_rows = result["tools"].get("query_shipments", {}).get("rows", [])
    codes_with_shipments = {r.get("product_code") for r in shipment_rows}

    follow_up = []
    for alert in alerts:
        code = alert["product_code"]
        if code not in codes_with_shipments:
            follow_up.append({"tool": "query_shipments", "args": {"keyword": code}})

    if follow_up:
        extra = run_tools(follow_up)
        extra_rows = extra["tools"].get("query_shipments", {}).get("rows", [])
        if extra_rows:
            result["tools"].setdefault("query_shipments", {"tool": "query_shipments", "rows": [], "alerts": []})
            existing = {r.get("shipment_no") for r in result["tools"]["query_shipments"]["rows"]}
            for r in extra_rows:
                if r.get("shipment_no") not in existing:
                    result["tools"]["query_shipments"]["rows"].append(r)
            log.info("business_agent.proactive_eta", follow_ups=len(follow_up))

    return result


def _build_context_text(result: dict) -> str:
    """Serialize tool results into a readable context block for the LLM."""
    lines: list[str] = []
    tool_labels = {
        "query_stock": "在庫照会",
        "query_orders": "受注照会",
        "query_shipments": "入出荷・物流照会",
        "check_low_stock": "安全在庫アラート",
    }
    for tool_name, output in result.get("tools", {}).items():
        lines.append(f"## ツール: {tool_labels.get(tool_name, tool_name)} ({tool_name})")
        rows = output.get("rows", [])
        if not rows:
            lines.append("(該当するデータはありません)")
        for row in rows:
            lines.append(json.dumps(row, ensure_ascii=False))

    if result.get("alerts"):
        lines.append("\n## 安全在庫アラート（発注推奨）")
        for alert in result["alerts"]:
            lines.append(
                f"- {alert['name']}（{alert['product_code']}）: 在庫 {alert['stock_qty']}{alert['unit']} "
                f"/ 安全在庫 {alert['safety_stock']}{alert['unit']} → 推奨発注数 {alert['suggested_purchase_qty']}{alert['unit']}"
            )
    return "\n".join(lines)


def _build_citations(result: dict) -> list[str]:
    cites: list[str] = []
    for r in result.get("tools", {}).get("query_stock", {}).get("rows", []):
        cites.append(f"[Source: DB: 商品 {r['product_code']}]")
    for r in result.get("tools", {}).get("query_orders", {}).get("rows", []):
        cites.append(f"[Source: DB: 受注 {r['order_no']}]")
    for r in result.get("tools", {}).get("query_shipments", {}).get("rows", []):
        cites.append(f"[Source: DB: 入出荷 {r['shipment_no']}]")
    for r in result.get("tools", {}).get("check_low_stock", {}).get("rows", []):
        cites.append(f"[Source: DB: 商品 {r['product_code']}]")
    # de-duplicate preserving order
    seen, deduped = set(), []
    for c in cites:
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    return deduped


def _build_business_result(result: dict) -> dict:
    """Shape the structured payload consumed by the frontend cards."""
    tools = result.get("tools", {})
    return {
        "stock": tools.get("query_stock", {}).get("rows", []),
        "orders": tools.get("query_orders", {}).get("rows", []),
        "shipments": tools.get("query_shipments", {}).get("rows", []),
        "alerts": result.get("alerts", []),
    }


def _run_business_tools(state: GraphState) -> tuple[GraphState, dict]:
    """Shared logic: plan -> execute (with enrichment) -> assemble artifacts."""
    user_query = state["user_query"]

    forced = _deterministic_guard(user_query)
    if forced is not None:
        # Exact document number: deterministic lookup, no LLM tool planning and
        # no product-code resolution (avoids an unrelated full product scan).
        # An empty result means "document not found" — never fall back to a
        # full-table scan that would dump unrelated rows.
        result = run_tools(forced)
        return state, result

    calls = _plan_tools(user_query)
    calls = _strip_unguided_full_scans(calls, user_query)
    result = _execute_with_enrichment(calls, user_query)

    has_rows = any(output.get("rows") for output in result.get("tools", {}).values())
    if not has_rows:
        # Defensive fallback: full stock lookup on the raw query.
        result = _execute_with_enrichment(
            [{"tool": "query_stock", "args": {"keyword": ""}}], user_query
        )

    return state, result


def business_agent_node(state: GraphState) -> GraphState:
    """business route: run tools then synthesize the final answer (graph ends here)."""
    state, result = _run_business_tools(state)
    context = _build_context_text(result)
    citations = _build_citations(result)

    has_rows = any(output.get("rows") for output in result.get("tools", {}).values())
    if not has_rows:
        answer = (
            "該当する業務データ（在庫・受注・入荷）が見つかりませんでした。\n"
            "商品名・品番・受注番号をご確認のうえ、再度お問い合わせください。"
        )
    else:
        try:
            answer = answer_chat(
                [
                    {"role": "system", "content": _SYNTH_SYSTEM},
                    {"role": "user", "content": (
                        f"Question: {state['user_query']}\n\n"
                        f"業務データベース照会結果:\n{context}\n"
                    )},
                ],
                temperature=0.1,
                label="business_agent.synthesis",
            )
        except Exception as e:
            log.error("business_agent.synth_error", error=str(e))
            answer = "**業務データの照会結果:**\n\n" + context

    return {
        **state,
        "route": state.get("route", "business"),
        "enough_evidence": True,
        "business_context": context,
        "business_result": _build_business_result(result),
        "final_answer": answer,
        "citations": citations,
    }


def business_tools_node(state: GraphState) -> GraphState:
    """hybrid route: run tools and continue into the catalog RAG pipeline."""
    state, result = _run_business_tools(state)
    context = _build_context_text(result)

    log.info(
        "business_tools.hybrid_done",
        tools=list(result.get("tools", {}).keys()),
        alerts=len(result.get("alerts", [])),
    )

    return {
        **state,
        "route": "hybrid",
        "business_context": context,
        "business_result": _build_business_result(result),
        "citations": _build_citations(result),
    }
