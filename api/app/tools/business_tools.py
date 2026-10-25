"""
Business tools — the callable "ERP/WMS tools" the Agent can invoke.

Each tool returns a structured, JSON-serializable dict:
    {"tool": ..., "rows": [...], "alerts": [...]}.
The LLM (intent/business nodes) selects tools and supplies keyword arguments;
the SQL database is the only source of truth for the numbers.
"""

import re

from app.tools.database import get_conn
from app.utils.logger import get_logger
from app.utils.events import emit

log = get_logger(__name__)

_PRODUCTS_SQL = (
    "SELECT * FROM products WHERE product_code LIKE ? OR name LIKE ? "
    "OR category LIKE ? OR spec LIKE ? ORDER BY product_code"
)
_ORDERS_SQL = (
    "SELECT o.order_no, o.customer, o.product_code, p.name AS product_name, o.qty, p.unit, "
    "o.status, o.order_date, o.due_date FROM orders o LEFT JOIN products p "
    "ON o.product_code = p.product_code WHERE o.order_no LIKE ? OR o.customer LIKE ? "
    "OR o.product_code LIKE ? OR p.name LIKE ? ORDER BY o.order_date DESC, o.order_no"
)
_SHIPMENTS_SQL = (
    "SELECT s.shipment_no, s.product_code, p.name AS product_name, s.direction, s.qty, p.unit, "
    "s.status, s.date_or_eta, s.warehouse FROM shipments s LEFT JOIN products p "
    "ON s.product_code = p.product_code WHERE s.shipment_no LIKE ? OR s.product_code LIKE ? "
    "OR p.name LIKE ? ORDER BY s.date_or_eta, s.shipment_no"
)


def _like(keyword: str | None) -> str:
    return f"%{keyword.strip()}%" if keyword else "%"


def _norm(s: str | None) -> str:
    """Normalize text for matching: upper-case, strip spaces/half/full-width, unify × and minus."""
    if not s:
        return ""
    table = str.maketrans({" ": "", "　": "", "×": "X", "−": "-", "ー": "-", "（": "(", "）": ")"})
    return s.upper().translate(table)


def _product_aliases(code: str, name: str) -> set[str]:
    """Generate robust aliases for a product code/name (model numbers, nominal sizes)."""
    aliases = {code, code.replace("-", "")}
    joined = code.replace("-", " ")
    for token in re.findall(r"[A-Za-z]{1,4}\d+[A-Za-z0-9]*", joined):
        aliases.add(token)
        m = re.match(r"([A-Za-z]+\d+)", token)
        if m:
            aliases.add(m.group(1))
    # Nominal sizes such as 15A / 20A / 25A in the name or code
    for nominal in re.findall(r"\d{2,3}\s*[A-Z]", name or ""):
        aliases.add(nominal.replace(" ", "").upper())
    # Only keep meaningful tokens (at least 3 chars and containing a digit)
    return {a for a in aliases if len(a) >= 3 and any(ch.isdigit() for ch in a)}


def identify_products(query: str) -> list[str]:
    """Deterministically extract product codes mentioned in a query (model-number matching)."""
    q = _norm(query)
    hits: list[str] = []
    products = _find_products("")
    for p in products:
        aliases = _product_aliases(p["product_code"], p["name"])
        if any(_norm(a) in q for a in aliases):
            hits.append(p["product_code"])
    return hits


def _stock_status(stock: int, safety: int) -> str:
    if stock <= 0:
        return "在庫切れ"
    if stock <= safety:
        return "在庫わずか"
    return "在庫あり"


def _make_alert(product: dict) -> dict:
    """Build a purchase recommendation alert for one understocked product."""
    suggested = max(product["safety_stock"] * 2 - product["stock_qty"], 0)
    return {
        "product_code": product["product_code"],
        "name": product["name"],
        "stock_qty": product["stock_qty"],
        "safety_stock": product["safety_stock"],
        "unit": product["unit"],
        "suggested_purchase_qty": suggested,
        "reason": (
            f"在庫数 {product['stock_qty']}{product['unit']} が安全在庫 "
            f"{product['safety_stock']}{product['unit']} を下回っています。"
        ),
    }


def _find_products(keyword: str | None) -> list[dict]:
    pattern = _like(keyword)
    params = (pattern, pattern, pattern, pattern)
    with get_conn() as conn:
        rows = conn.execute(_PRODUCTS_SQL, params).fetchall()
    result = [dict(r) for r in rows]
    emit("sql", table="products", sql=_PRODUCTS_SQL, params=list(params), rows=len(result),
         keyword=keyword or "")
    return result


# ── Tools ─────────────────────────────────────────────────────────────────────

def query_stock(keyword: str = "") -> dict:
    """Query live stock quantity, status, safety stock and warehouse."""
    products = _find_products(keyword)
    rows = []
    alerts = []
    for p in products:
        status = _stock_status(p["stock_qty"], p["safety_stock"])
        rows.append({
            "product_code": p["product_code"],
            "name": p["name"],
            "category": p["category"],
            "spec": p["spec"],
            "unit": p["unit"],
            "price_jpy": p["price_jpy"],
            "stock_qty": p["stock_qty"],
            "safety_stock": p["safety_stock"],
            "warehouse": p["warehouse"],
            "status": status,
        })
        if p["stock_qty"] <= p["safety_stock"]:
            alerts.append(_make_alert(p))

    return {"tool": "query_stock", "rows": rows, "alerts": alerts}


def query_orders(keyword: str = "") -> dict:
    """Query sales orders by order number, customer or product (name/code)."""
    pattern = _like(keyword)
    params = (pattern, pattern, pattern, pattern)
    with get_conn() as conn:
        rows = conn.execute(_ORDERS_SQL, params).fetchall()
    result = [dict(r) for r in rows]
    emit("sql", table="orders", sql=_ORDERS_SQL, params=list(params), rows=len(result),
         keyword=keyword or "")
    return {"tool": "query_orders", "rows": result, "alerts": []}


def query_shipments(keyword: str = "") -> dict:
    """Query inbound/outbound logistics and ETA by product (name/code) or shipment no."""
    pattern = _like(keyword)
    params = (pattern, pattern, pattern)
    with get_conn() as conn:
        rows = conn.execute(_SHIPMENTS_SQL, params).fetchall()
    result = [dict(r) for r in rows]
    emit("sql", table="shipments", sql=_SHIPMENTS_SQL, params=list(params), rows=len(result),
         keyword=keyword or "")
    return {"tool": "query_shipments", "rows": result, "alerts": []}


def check_low_stock(keyword: str = "") -> dict:
    """List every product below its safety stock with a purchase recommendation."""
    products = _find_products(keyword)
    alerts = [
        _make_alert(p) for p in products
        if p["stock_qty"] <= p["safety_stock"]
    ]
    return {"tool": "check_low_stock", "rows": alerts, "alerts": alerts}


# ── Tool registry (description shown to the LLM) ──────────────────────────────

TOOL_SPECS = [
    {
        "name": "query_stock",
        "description": "在庫数、在庫状況（在庫あり/わずか/切れ）、安全在庫、倉庫を照会する。",
        "arg_keyword": "商品名・品番・カテゴリ（指定がなければ空文字）",
    },
    {
        "name": "query_orders",
        "description": "受注・注文の状況（受注番号、顧客、手配中/出荷済み、納期）を照会する。",
        "arg_keyword": "受注番号・顧客名・商品名・品番",
    },
    {
        "name": "query_shipments",
        "description": "入荷・出荷・物流の状況と入荷予定日(ETA)を照会する。",
        "arg_keyword": "入荷番号・商品名・品番",
    },
    {
        "name": "check_low_stock",
        "description": "安全在庫を下回っている商品と推奨発注数量を確認する。",
        "arg_keyword": "商品名・品番（全件確認なら空文字）",
    },
]

_FUNCS = {
    "query_stock": query_stock,
    "query_orders": query_orders,
    "query_shipments": query_shipments,
    "check_low_stock": check_low_stock,
}


def _row_key(tool_name: str, row: dict) -> str:
    """Identity key for de-duplicating rows returned by repeated calls of one tool."""
    if tool_name == "query_shipments":
        # A product can have several inbound/outbound records — use the shipment number.
        return str(row.get("shipment_no") or row.get("product_code") or row)
    if tool_name == "query_orders":
        return str(row.get("order_no") or row.get("product_code") or row)
    return str(row.get("product_code") or row)


def run_tools(calls: list[dict]) -> dict:
    """
    Execute a list of {"tool": ..., "args": {"keyword": ...}} plans.
    Multiple calls to the same tool merge their rows (de-duplicated).
    Returns merged {"tools": {...}, "alerts": [...]} with de-duplicated alerts.
    """
    merged: dict = {}
    alerts: list[dict] = []
    seen_codes: set[str] = set()

    for call in calls or []:
        name = call.get("tool")
        args = call.get("args") or {}
        if name not in _FUNCS:
            continue
        keyword = str(args.get("keyword", "")).strip()
        try:
            output = _FUNCS[name](keyword)
        except Exception as e:
            log.error("tools.exec_error", tool=name, error=str(e))
            output = {"tool": name, "rows": [], "alerts": [], "error": str(e)}

        emit(
            "tool",
            tool=name,
            keyword=keyword,
            rows=len(output.get("rows", [])),
            alerts=len(output.get("alerts", [])),
            error=output.get("error"),
        )

        if name not in merged:
            merged[name] = {"tool": name, "rows": [], "alerts": []}
        bucket = merged[name]
        existing_keys = {_row_key(name, r) for r in bucket["rows"]}
        for row in output.get("rows", []):
            key = _row_key(name, row)
            if key not in existing_keys:
                existing_keys.add(key)
                bucket["rows"].append(row)

        for alert in output.get("alerts", []):
            if alert["product_code"] not in seen_codes:
                seen_codes.add(alert["product_code"])
                alerts.append(alert)

    return {"tools": merged, "alerts": alerts}
