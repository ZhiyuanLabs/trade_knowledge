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
# 生鮮果実の商社デモ。在庫数が安全在庫を下回る品（stock <= safety_stock）を
# あえて複数含め、発注アラートのデモができるようにしている。
_PRODUCTS = [
    # ── 熱帯果実 ─────────────────────────────────────────────────────
    ("FRT-BAN-001", "フィリピン産バナナ（キャベンディッシュ）", "熱帯果実", "秀品 4房入 約13kg/箱 ミンダナオ産 13℃帯", "箱", 2600, 320, 120, "横浜本牧冷蔵倉庫"),
    ("FRT-BAN-002", "有機バナナ（ペルー産）", "熱帯果実", "有機JAS 8房/箱 約10kg 14℃帯 コープ産直向け", "箱", 3800, 90, 40, "横浜本牧冷蔵倉庫"),
    ("FRT-PIN-001", "フィリピン産パイナップル（ハニーグロー）", "熱帯果実", "秀品 1玉約1.5kg 10玉/箱", "箱", 4200, 75, 30, "横浜本牧冷蔵倉庫"),
    ("FRT-MNG-001", "フィリピン産マンゴー（カラバオ）", "熱帯果実", "赤秀 5kg/箱 セブ島産 空輸 要追熟", "箱", 9800, 6, 25, "成田空港冷蔵物流センター"),
    ("FRT-MNG-002", "タイ産マンゴー（ナムドークマイ）", "熱帯果実", "秀品 5kg/箱 空輸 要追熟", "箱", 12500, 40, 15, "成田空港冷蔵物流センター"),
    ("FRT-AVO-001", "メキシコ産アボカド（ハス種）", "熱帯果実", "M玉 約200g 48個/箱 追熟管理", "箱", 7600, 10, 20, "横浜本牧冷蔵倉庫"),
    ("FRT-AVO-002", "ペルー産アボカド（ハス種）", "熱帯果実", "L玉 約220g 40個/箱 追熟管理", "箱", 7200, 55, 20, "横浜本牧冷蔵倉庫"),
    ("FRT-PAP-001", "フィリピン産パパイヤ", "熱帯果実", "秀品 1玉約1kg 8玉/箱 要追熟", "箱", 5200, 30, 12, "横浜本牧冷蔵倉庫"),
    ("FRT-DRG-001", "ベトナム産ドラゴンフルーツ（赤肉）", "熱帯果実", "M玉 約400g 約10kg/箱", "箱", 6800, 48, 18, "成田空港冷蔵物流センター"),
    ("FRT-CNT-001", "タイ産ヤングココナッツ", "熱帯果実", "1玉約1kg 9個/箱 空輸", "箱", 4500, 26, 10, "成田空港冷蔵物流センター"),
    ("FRT-LYC-001", "台湾産ライチ（玉荷包）", "熱帯果実", "秀品 2kg/箱 空輸 旬5-7月", "箱", 9200, 0, 20, "成田空港冷蔵物流センター"),
    # ── 柑橘類 ───────────────────────────────────────────────────────
    ("FRT-ORG-001", "アメリカ産ネーブルオレンジ", "柑橘類", "L玉 40個/箱 約10kg 5℃帯", "箱", 4600, 140, 50, "横浜本牧冷蔵倉庫"),
    ("FRT-ORG-002", "オーストラリア産バレンシアオレンジ", "柑橘類", "M玉 40個/箱 10kg 季節関税対象", "箱", 4300, 85, 35, "横浜本牧冷蔵倉庫"),
    ("FRT-GRF-001", "南アフリカ産ルビーグレープフルーツ", "柑橘類", "35個/箱 15kg 8℃帯", "箱", 5200, 60, 24, "横浜本牧冷蔵倉庫"),
    ("FRT-LEM-001", "アメリカ産レモン（ユーレカ）", "柑橘類", "140個/箱 18kg 8-10℃帯", "箱", 7800, 110, 40, "横浜本牧冷蔵倉庫"),
    ("FRT-LIM-001", "メキシコ産ライム", "柑橘類", "10kg/箱 8℃帯 業務用", "箱", 6400, 42, 18, "横浜本牧冷蔵倉庫"),
    ("FRT-MIK-001", "和歌山県産温州みかん（早生）", "柑橘類", "秀品 2S 5kg/箱 5℃帯", "箱", 2800, 260, 100, "東京大田市場冷蔵センター"),
    ("FRT-MIK-002", "愛媛県産紅まどんな", "柑橘類", "赤秀 2L 3kg/箱 歳暮ギフト向け", "箱", 7400, 7, 30, "東京大田市場冷蔵センター"),
    ("FRT-YUZ-001", "高知県産ゆず", "柑橘類", "秀品 10kg 加工用 8℃帯", "kg", 1200, 80, 30, "東京大田市場冷蔵センター"),
    # ── 仁果類 ───────────────────────────────────────────────────────
    ("FRT-APP-001", "青森県産サンふじりんご", "仁果類", "特秀 40玉 10kg/箱 0-5℃帯", "箱", 5400, 180, 70, "東京大田市場冷蔵センター"),
    ("FRT-APP-002", "長野県産シナノゴールド", "仁果類", "秀品 36玉 10kg/箱 0-5℃帯", "箱", 5800, 65, 25, "東京大田市場冷蔵センター"),
    ("FRT-PEA-002", "山形県産ラ・フランス（洋梨）", "仁果類", "秀品 14玉 5kg 要追熟", "箱", 4600, 48, 20, "東京大田市場冷蔵センター"),
    # ── 核果類 ───────────────────────────────────────────────────────
    ("FRT-PLM-001", "チリ産プラム（サンタローザ）", "核果類", "秀品 5kg/箱 空輸 0-2℃帯", "箱", 5600, 36, 15, "成田空港冷蔵物流センター"),
    ("FRT-PRS-001", "和歌山県産平核無柿（たねなし柿）", "核果類", "秀品 10kg 箱", "箱", 3400, 120, 45, "東京大田市場冷蔵センター"),
    ("FRT-FIG-001", "愛知県産いちじく（とよみつひめ）", "核果類", "秀品 4パック入 2kg/箱 0-2℃帯", "箱", 4200, 24, 12, "東京大田市場冷蔵センター"),
    ("FRT-CHE-001", "山形県産佐藤錦さくらんぼ", "核果類", "特秀 500g×12パック/箱 旬6月 空輸", "箱", 8800, 0, 15, "成田空港冷蔵物流センター"),
    # ── ぶどう・ベリー類 ─────────────────────────────────────────────
    ("FRT-GRP-001", "長野県産シャインマスカット", "ぶどう・ベリー類", "特秀 1房約600g 4房/箱 0-2℃帯", "箱", 12800, 12, 30, "東京大田市場冷蔵センター"),
    ("FRT-GRP-002", "岡山県産ニューピオーネ", "ぶどう・ベリー類", "秀品 1房約500g 4房/箱 0-2℃帯", "箱", 7800, 30, 15, "東京大田市場冷蔵センター"),
    ("FRT-GRP-003", "チリ産種なしグレープ（レッドグローブ）", "ぶどう・ベリー類", "秀品 4.5kg/箱 0-2℃帯", "箱", 4600, 95, 35, "成田空港冷蔵物流センター"),
    ("FRT-KIW-001", "ニュージーランド産グリーンキウイ", "ぶどう・ベリー類", "33個/箱 約7kg 0-2℃帯 ゼスプリ", "箱", 5200, 130, 50, "横浜本牧冷蔵倉庫"),
    ("FRT-KIW-002", "ニュージーランド産サンゴールドキウイ", "ぶどう・ベリー類", "33個/箱 約7kg 0-2℃帯 ゼスプリ", "箱", 6200, 58, 25, "横浜本牧冷蔵倉庫"),
    ("FRT-BLB-001", "チリ産ブルーベリー", "ぶどう・ベリー類", "125g×12パック/箱 0-2℃帯 空輸", "箱", 6800, 18, 20, "成田空港冷蔵物流センター"),
    ("FRT-STR-001", "栃木県産とちあいかいちご", "ぶどう・ベリー類", "秀品 1パック270g 20パック/箱 0-2℃", "箱", 9800, 16, 40, "東京大田市場冷蔵センター"),
    ("FRT-STR-002", "福岡県産あまおういちご", "ぶどう・ベリー類", "赤秀 1パック270g 20パック/箱 0-2℃", "箱", 12800, 9, 30, "東京大田市場冷蔵センター"),
    # ── 瓜類 ─────────────────────────────────────────────────────────
    ("FRT-MEL-001", "茨城県産アンデスメロン（青肉）", "瓜類", "秀品 1玉約1.6kg 6玉/箱", "個", 980, 50, 20, "東京大田市場冷蔵センター"),
    ("FRT-MEL-002", "北海道産マスクメロン（赤肉）", "瓜類", "特秀 1玉約1.5kg 6玉/箱", "個", 3200, 8, 12, "東京大田市場冷蔵センター"),
    ("FRT-WML-001", "熊本県産小玉すいか", "瓜類", "秀品 1玉約2kg 4玉/箱", "個", 1600, 44, 18, "東京大田市場冷蔵センター"),
]

# order_no, customer, product_code, qty, status, order_date, due_date
# 販売先は大手スーパー・生協・コンビニ。クリスマス・お歳暮の季節特需を含む。
_ORDERS = [
    ("SO-2026-1101", "イオンリテール株式会社", "FRT-STR-001", 120, "手配中", "2026-10-23", "2026-12-18"),
    ("SO-2026-1102", "株式会社神戸物産（業務スーパー）", "FRT-BAN-001", 400, "受注済", "2026-10-24", "2026-10-30"),
    ("SO-2026-1103", "生活協同組合コープ", "FRT-MIK-002", 80, "手配中", "2026-10-24", "2026-12-05"),
    ("SO-2026-1104", "株式会社成城石井", "FRT-GRP-001", 60, "納品待ち", "2026-10-22", "2026-10-28"),
    ("SO-2026-1105", "株式会社イトーヨーカ堂", "FRT-AVO-001", 150, "手配中", "2026-10-25", "2026-10-31"),
    ("SO-2026-1106", "合同会社西友", "FRT-KIW-001", 200, "受注済", "2026-10-25", "2026-11-02"),
    ("SO-2026-1107", "株式会社ライフコーポレーション", "FRT-APP-001", 180, "出荷済", "2026-10-20", "2026-10-24"),
    ("SO-2026-1108", "株式会社ファミリーマート", "FRT-PIN-001", 90, "受注済", "2026-10-25", "2026-10-29"),
    ("SO-2026-1109", "オーケー株式会社", "FRT-MIK-001", 250, "受注済", "2026-10-25", "2026-11-01"),
]

# shipment_no, product_code, direction(入荷/出荷), qty, status, date_or_eta, warehouse
# 入荷は海外産地からのリーファー船・空輸、および国内産地からの集荷。
_SHIPMENTS = [
    ("RC-7001", "FRT-BAN-001", "入荷", 480, "入荷予定", "2026-10-27", "横浜本牧冷蔵倉庫"),
    ("RC-7002", "FRT-AVO-001", "入荷", 120, "入荷予定", "2026-10-29", "横浜本牧冷蔵倉庫"),
    ("RC-7003", "FRT-KIW-001", "入荷", 300, "入荷予定", "2026-11-02", "横浜本牧冷蔵倉庫"),
    ("RC-7004", "FRT-STR-001", "入荷", 60, "入荷予定", "2026-12-15", "東京大田市場冷蔵センター"),
    ("RC-7005", "FRT-MIK-002", "入荷", 90, "入荷予定", "2026-11-25", "東京大田市場冷蔵センター"),
    ("RC-7006", "FRT-MNG-001", "入荷", 40, "入荷予定", "2026-10-28", "成田空港冷蔵物流センター"),
    ("RC-7007", "FRT-ORG-001", "入荷", 200, "入荷済", "2026-10-22", "横浜本牧冷蔵倉庫"),
    ("SH-9001", "FRT-MIK-001", "出荷", 250, "出荷済", "2026-10-24", "東京大田市場冷蔵センター"),
    ("SH-9002", "FRT-APP-001", "出荷", 180, "出荷済", "2026-10-24", "東京大田市場冷蔵センター"),
    ("SH-9003", "FRT-GRP-001", "出荷", 40, "出荷準備中", "2026-10-28", "東京大田市場冷蔵センター"),
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
