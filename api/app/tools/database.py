"""
Simulated business database (SQLite) for the trading-house demo.

This stands in for an ERP / WMS backend. It holds three tables:
  - products  : master data with live stock and safety-stock threshold
  - orders    : sales orders (受注) and their status
  - shipments : inbound / outbound logistics (入荷・出荷) and ETA

The DB is created and seeded automatically on first startup. All figures
are demo data.
"""

import os
import sqlite3
from contextlib import contextmanager

from dotenv import load_dotenv
from app.utils.logger import get_logger

load_dotenv()

log = get_logger(__name__)

DB_PATH = os.path.abspath(os.getenv("BUSINESS_DB_PATH", "./data/business.db"))


# ── Demo seed data ────────────────────────────────────────────────────────────
# product_code, name, category, spec, unit, price_jpy, stock, safety_stock, warehouse
_PRODUCTS = [
    ("T15-SUS304", "ステンレス鋼管 15A", "配管材料", "SUS304 外径21.7mm 長さ4m", "本", 1800, 120, 50, "東京倉庫"),
    ("T20-SUS304", "ステンレス鋼管 20A", "配管材料", "SUS304 外径27.2mm 長さ4m", "本", 2400, 45, 50, "東京倉庫"),
    ("T25-SUS304", "ステンレス鋼管 25A", "配管材料", "SUS304 外径34.0mm 長さ4m", "本", 3300, 80, 40, "横浜倉庫"),
    ("B-M12X50", "六角ボルト M12×50", "機械部品", "半ネジ SUS304 1箱100本", "箱", 3200, 8, 20, "東京倉庫"),
    ("B-M10X40", "六角ボルト M10×40", "機械部品", "半ネジ SUS304 1箱100本", "箱", 2100, 60, 15, "東京倉庫"),
    ("BR-6204ZZ", "ボールベアリング 6204ZZ", "機械部品", "深溝玉軸受 内径20mm 外径47mm 幅14mm", "個", 480, 5, 30, "横浜倉庫"),
    ("RH-19", "高圧ゴムホース 19mm", "配管材料", "内径19mm 1m単位 常用圧力1.0MPa", "m", 1900, 40, 15, "東京倉庫"),
    ("INV-04", "インバータ 0.4kW", "電機・制御", "三相200V 0.4kW", "台", 28000, 14, 5, "横浜倉庫"),
    ("GC-100", "ディスクグラインダー 100mm", "電動工具", "砥石径100mm 100V", "台", 9800, 22, 8, "東京倉庫"),
    ("PVC-VP20", "塩ビパイプ VP20", "配管材料", "呼び径20A 長さ4m", "本", 950, 200, 60, "東京倉庫"),
]

# order_no, customer, product_code, qty, status, order_date, due_date
_ORDERS = [
    ("SO-2026-1041", "三和工業株式会社", "B-M12X50", 5, "出荷済", "2026-10-14", "2026-10-16"),
    ("SO-2026-1042", "大洋建設株式会社", "T20-SUS304", 30, "手配中", "2026-10-17", "2026-10-22"),
    ("SO-2026-1043", "日の出エンジニアリング株式会社", "BR-6204ZZ", 20, "納品待ち", "2026-10-16", "2026-10-24"),
    ("SO-2026-1044", "丸福水産株式会社", "RH-19", 10, "受注済", "2026-10-18", "2026-10-25"),
]

# shipment_no, product_code, direction(入荷/出荷), qty, status, date_or_eta, warehouse
_SHIPMENTS = [
    ("RC-5512", "B-M12X50", "入荷", 30, "入荷予定", "2026-10-21", "東京倉庫"),
    ("RC-5513", "BR-6204ZZ", "入荷", 50, "入荷予定", "2026-10-23", "横浜倉庫"),
    ("RC-5515", "T20-SUS304", "入荷", 60, "入荷予定", "2026-10-22", "東京倉庫"),
    ("SH-8801", "T20-SUS304", "出荷", 30, "出荷済", "2026-10-18", "東京倉庫"),
    ("RC-5514", "PVC-VP20", "入荷", 100, "入荷済", "2026-10-15", "東京倉庫"),
]


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            product_code TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            category     TEXT,
            spec         TEXT,
            unit         TEXT,
            price_jpy    INTEGER,
            stock_qty    INTEGER,
            safety_stock INTEGER,
            warehouse    TEXT
        );

        CREATE TABLE IF NOT EXISTS orders (
            order_no   TEXT PRIMARY KEY,
            customer   TEXT,
            product_code TEXT,
            qty        INTEGER,
            status     TEXT,
            order_date TEXT,
            due_date   TEXT
        );

        CREATE TABLE IF NOT EXISTS shipments (
            shipment_no  TEXT PRIMARY KEY,
            product_code TEXT,
            direction    TEXT,
            qty          INTEGER,
            status       TEXT,
            date_or_eta  TEXT,
            warehouse    TEXT
        );
        """
    )


def _seed(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    if count and count > 0:
        return

    conn.executemany(
        "INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?)", _PRODUCTS
    )
    conn.executemany(
        "INSERT INTO orders VALUES (?,?,?,?,?,?,?)", _ORDERS
    )
    conn.executemany(
        "INSERT INTO shipments VALUES (?,?,?,?,?,?,?)", _SHIPMENTS
    )
    conn.commit()
    log.info(
        "db.seeded",
        products=len(_PRODUCTS),
        orders=len(_ORDERS),
        shipments=len(_SHIPMENTS),
    )


def init_db() -> str:
    """Create the SQLite DB file, schema and seed data (idempotent)."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        _create_schema(conn)
        _seed(conn)
    return DB_PATH


@contextmanager
def get_conn():
    """Yield a sqlite3 connection with row access by column name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
