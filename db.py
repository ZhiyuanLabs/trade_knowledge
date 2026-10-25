"""
Container-side SQLite helper for the trade_knowledge business demo DB.
Runs INSIDE the api container against /app/data/business.db.
Usually invoked by the project-root db.ps1 wrapper; you can also run it
manually:  docker exec nextjs-docs-rag-api-1 python /tmp/db.py products
"""
import sys
import io
import sqlite3

# Force UTF-8 stdout so Japanese rows survive the PowerShell redirect.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

DB = "/app/data/business.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

PRESETS = {
    "products": "SELECT * FROM products",
    "orders": "SELECT * FROM orders",
    "shipments": "SELECT * FROM shipments",
    "low": (
        "SELECT product_code,name,stock_qty,safety_stock,warehouse "
        "FROM products WHERE stock_qty<=safety_stock ORDER BY stock_qty"
    ),
    "tables": "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
}


def show(rows):
    if not rows:
        print("(0 rows)")
        return
    cols = rows[0].keys()
    print(" | ".join(cols))
    print("-" * 70)
    for r in rows:
        print(" | ".join(str(r[c]) for c in cols))
    print("-" * 70)
    print(f"({len(rows)} rows)")


cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"

if cmd == "summary":
    for t in ("products", "orders", "shipments"):
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"{t}: {n} rows")
    print("\n[Low stock  stock_qty <= safety_stock]")
    show(conn.execute(PRESETS["low"]).fetchall())
elif cmd in PRESETS:
    show(conn.execute(PRESETS[cmd]).fetchall())
elif cmd in ("sql", "write"):
    sql = open("/tmp/db_sql.txt", encoding="utf-8").read()
    cur = conn.execute(sql)
    conn.commit()
    if cmd == "write":
        print("OK: statement executed and committed.")
    else:
        rows = cur.fetchall()
        if rows:
            show(rows)
        else:
            print("(no result set; statement executed)")
else:
    print("Unknown command:", cmd)
    print("commands: summary | tables | products | orders | shipments | low "
          "| sql \"<SELECT ...>\" | write \"<INSERT/UPDATE/DELETE ...>\"")
