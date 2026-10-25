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

_ROUTER_SYSTEM = """あなたは生鮮果実を扱う総合商社向け業務エージェントのルーターです。ユーザーの質問を分類してください。

- catalog: 商品カタログ、産地・原産国、品種、旬、等級・階級、選び方・食べごろ、保存・追熟、輸入・植物検疫・通関・関税、加工・包装・荷姿、コールドチェーンに関する質問。文書検索（RAG）が必要です。
- business: 在庫数、受注・注文、入荷・出荷、物流、納期、入庫、安全在庫、発注、欠品、緊急・特急手配、顧客（スーパー）への納品に関する質問。業務データベースの照会が必要です。
- hybrid: 両方が必要な質問。例: 在庫状況と産地・品種の両方、在庫不足の果物の代替品をカタログから探す、入荷状況と保存・包装条件の確認。

質問の言語に関わらず、必ず日本語で判断してください。
JSONのみで返答してください:
{"route": "catalog|business|hybrid", "reason": "1文での判断理由"}
"""

_BUSINESS_KEYWORDS = [
    "在庫", "入荷", "出荷", "受注", "注文", "発注", "仕入", "入庫", "出庫",
    "納品", "納期", "物流", "在庫切れ", "いつ届く", "いつ入", "何個", "何本",
    "何箱", "何パック", "何房", "補充", "入荷予定", "安全在庫",
    "欠品", "緊急", "特急", "エア便", "顧客", "スーパー", "棚卸",
]

_CATALOG_KEYWORDS = [
    "仕様", "規格", "用途", "使い方", "選定", "選び", "違い", "比較", "カタログ",
    "産地", "原産国", "輸入", "輸出", "検疫", "植物検疫", "通関", "関税", "届出",
    "等級", "階級", "選別", "包装", "荷姿", "段ボール", "ラベル", "表示",
    "加工", "カット", "冷凍", "追熟", "保存", "賞味", "旬", "食べごろ", "糖度",
    "温度帯", "冷蔵", "リーファー", "コールドチェーン", "エチレン", "HACCP",
    "品種", "種類", "サイズ",
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
