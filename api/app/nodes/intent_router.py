"""
Node 0 — Intent Router (Agentic supervisor).

Decides which capability the user query needs:
  - catalog : product catalog documentation (specs / usage / selection) -> RAG pipeline
  - business: stock / orders / logistics / purchase -> business tools (ERP DB)
  - hybrid  : needs both DB facts and catalog documentation

The LLM does the classification; a deterministic keyword rule is the fallback
when the LLM is unavailable.
"""

import json
import re

from app.state.schema import GraphState
from app.utils.llm import chat
from app.utils.logger import get_logger

log = get_logger(__name__)

_ROUTER_SYSTEM = """あなたは商社向け業務エージェントのルーターです。ユーザーの質問を分類してください。

- catalog: 商品カタログ、仕様、用途、選定方法、商品同士の違い、取り付け・施工方法に関する質問。文書検索（RAG）が必要です。
- business: 在庫数、受注・注文、入荷・出荷、物流、納期、入庫、安全在庫、発注に関する質問。業務データベースの照会が必要です。
- hybrid: 両方が必要な質問。例: 在庫状況と商品仕様の両方、在庫不足商品の代替品をカタログから探す、入荷状況と用途の確認。

質問の言語に関わらず、必ず日本語で判断してください。
JSONのみで返答してください:
{"route": "catalog|business|hybrid", "reason": "1文での判断理由"}
"""

_BUSINESS_KEYWORDS = [
    "在庫", "入荷", "出荷", "受注", "注文", "発注", "仕入", "入庫", "出庫",
    "納品", "納期", "物流", "在庫切れ", "いつ届く", "いつ入", "何個", "何本",
    "補充", "入荷予定", "安全在庫",
]

_CATALOG_KEYWORDS = [
    "仕様", "規格", "用途", "使い方", "選定", "選び", "違い", "比較", "カタログ",
    "取り付け", "取付", "施工", "互換", "材質", "圧力", "温度", "対応", "種類",
    "サイズ", "寸法", "仕様書",
]


def _rule_based_route(query: str) -> str:
    has_business = any(k in query for k in _BUSINESS_KEYWORDS)
    has_catalog = any(k in query for k in _CATALOG_KEYWORDS)
    if has_business and has_catalog:
        return "hybrid"
    if has_business:
        return "business"
    if has_catalog:
        return "catalog"
    return "catalog"


def intent_router_node(state: GraphState) -> GraphState:
    """Classify the query and write the route into state."""
    user_query = state["user_query"]

    route: str | None = None
    try:
        raw = chat(
            [
                {"role": "system", "content": _ROUTER_SYSTEM},
                {"role": "user", "content": f"Question: {user_query}"},
            ],
            temperature=0.0,
            label="intent_router",
        )
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(raw)
        candidate = str(parsed.get("route", "")).strip().lower()
        if candidate in ("catalog", "business", "hybrid"):
            route = candidate
        log.info("intent_router.llm_decision", route=route, reason=parsed.get("reason", ""))
    except Exception as e:
        log.warning("intent_router.llm_error", error=str(e))

    if route is None:
        route = _rule_based_route(user_query)
        log.info("intent_router.rule_fallback", route=route)

    return {**state, "route": route}


def route_after_intent(state: GraphState) -> str:
    """Conditional edge: return the next node name."""
    route = state.get("route", "catalog")
    if route == "business":
        return "business_agent"
    if route == "hybrid":
        return "business_tools"
    return "planner"
