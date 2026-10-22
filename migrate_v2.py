"""Migrasi skema v2 — idempoten, aman dijalankan berulang.

Perubahan utama:
- Tabel relasional untuk item pesanan, rincian ukuran, tahap produksi,
  checklist finishing, pembayaran, dan riwayat status.
- Token tracking publik (acak, bukan nomor urut) pada tabel orders.
- Kolom baru di orders: customer_name, agreed_date, tracking_token,
  total, updated_at.
- Backfill: setiap pesanan lama (JSON `data`) dipecah ke tabel baru,
  dibaca dari sumber yang sama sehingga nota/tracking tetap menampilkan
  data yang benar. `data` tetap disimpan sebagai arsip.

Dipakai oleh app.py (saat start) dan tools/check.py. Semua pernyataan
memakai IF NOT EXISTS sehingga database baru maupun lama sama-sama aman.

Catatan mode SQLite: `app.SQLiteConn` sudah menjalankan
`PRAGMA foreign_keys=ON`, jadi klausa `REFERENCES ... ON DELETE CASCADE`
di SCHEMA di bawah tetap berlaku. Karena tabel induk `orders` dibuat
lebih dulu oleh `app.initialize()`, urutan pembuatan tabel di sini aman.
"""
import json
import secrets
from datetime import datetime, timedelta, timezone

WIB = timezone(timedelta(hours=7))

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers(
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    wa TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items(
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    name TEXT NOT NULL,
    garment TEXT NOT NULL,
    material TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '',
    design TEXT NOT NULL DEFAULT '',
    printing TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    price INTEGER NOT NULL DEFAULT 0,
    qty INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS size_breakdowns(
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES order_items(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    qty INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS production_stages(
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    stage_key TEXT NOT NULL,
    label TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    target_date TEXT NOT NULL DEFAULT '',
    start_date TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    UNIQUE(order_id, stage_key)
);

CREATE TABLE IF NOT EXISTS production_checklist_items(
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    label TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    done_at TEXT NOT NULL DEFAULT '',
    UNIQUE(order_id, position)
);

CREATE TABLE IF NOT EXISTS payments(
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    amount INTEGER NOT NULL,
    date TEXT NOT NULL,
    method TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    reference TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'Pembayaran',
    recorded_at TEXT NOT NULL,
    voided INTEGER NOT NULL DEFAULT 0,
    void_reason TEXT NOT NULL DEFAULT '',
    void_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS order_status_history(
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    at TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'owner',
    message TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    visible INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS progress_notes(
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    stage_key TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL,
    at TEXT NOT NULL
);
"""

ORDER_COLUMNS = (
    ("life", "TEXT NOT NULL DEFAULT 'active'"),
    ("target", "TEXT NOT NULL DEFAULT ''"),
    ("customer_name", "TEXT NOT NULL DEFAULT ''"),
    ("agreed_date", "TEXT NOT NULL DEFAULT ''"),
    ("tracking_token", "TEXT NOT NULL DEFAULT ''"),
    ("total", "INTEGER NOT NULL DEFAULT 0"),
    ("updated_at", "TEXT NOT NULL DEFAULT ''"),
)

# Salinan STAGES/QC default; app.py memakai daftar ini sebagai acuan.
STAGE_DEFS = [
    ("potong", "Potong Bahan"),
    ("jahit", "Jahit"),
    ("finishing", "Finishing"),
    ("serah", "Penyerahan"),
]

CHECKLIST_DEFS = [
    "Buang sisa benang pada jahitan",
    "Periksa hasil jahitan",
    "Gosok atau setrika pakaian",
    "Lipat pakaian dengan rapi",
    "Pengecekan jumlah dan ukuran",
    "Packing",
]

VALID_STATES = ("pending", "running", "done")


def now():
    return datetime.now(WIB).isoformat(timespec="seconds")


def uid():
    return secrets.token_hex(16)


def _sqlite_ddl(script):
    """Kembalikan DDL apa adanya untuk SQLite."""
    return script


def ensure_schema(c):
    """Buat tabel/kolom baru bila belum ada."""
    # Lingkungan lokal (SQLite) dideteksi dari pembungkus cursor-nya:
    # app.SQLiteCursor punya atribut `.cur`, cursor psycopg2 tidak.
    is_sqlite = hasattr(c.cursor, "cur")
    c.executescript(_sqlite_ddl(SCHEMA) if is_sqlite else SCHEMA)
    
    if is_sqlite:
        # ALTER TABLE ADD COLUMN di SQLite tidak mendukung NOT NULL tanpa
        # default, jadi kolom baru selalu diberi DEFAULT.
        existing = {r["name"] for r in c.execute("PRAGMA table_info(orders)")}
        for name, decl in ORDER_COLUMNS:
            if name not in existing:
                c.execute(f"ALTER TABLE orders ADD COLUMN {name} {decl}")
    else:
        for name, decl in ORDER_COLUMNS:
            c.execute(f"ALTER TABLE orders ADD COLUMN IF NOT EXISTS {name} {decl}")

    # Tambahan untuk tabel photos (ImageKit)
    if is_sqlite:
        existing_photos = {r["name"] for r in c.execute("PRAGMA table_info(photos)")}
        if "remote_url" not in existing_photos:
            c.execute("ALTER TABLE photos ADD COLUMN remote_url TEXT NOT NULL DEFAULT ''")
        if "remote_id" not in existing_photos:
            c.execute("ALTER TABLE photos ADD COLUMN remote_id TEXT NOT NULL DEFAULT ''")
    else:
        c.execute("ALTER TABLE photos ADD COLUMN IF NOT EXISTS remote_url TEXT NOT NULL DEFAULT ''")
        c.execute("ALTER TABLE photos ADD COLUMN IF NOT EXISTS remote_id TEXT NOT NULL DEFAULT ''")

    c.execute("CREATE INDEX IF NOT EXISTS idx_items_order ON order_items(order_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pay_order ON payments(order_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_hist_order ON order_status_history(order_id)")
    # Indeks unik parsial tidak didukung SQLite; token unik sudah
    # dijamin oleh generator acak 32 byte.
    if not is_sqlite:
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_tracking_token "
            "ON orders(tracking_token) WHERE tracking_token <> ''"
        )


def new_token():
    return secrets.token_urlsafe(24)


def _blank_sizes(o):
    sizes = o.get("sizes") or {}
    return {str(k): int(v) for k, v in sizes.items() if int(v or 0) >= 0}


def backfill(c):
    """Pecah pesanan lama (JSON) ke tabel relasional bila belum ada."""
    rows = c.execute("SELECT id,number,data FROM orders").fetchall()
    migrated = 0
    for row in rows:
        oid = row["id"]
        o = json.loads(row["data"])
        token = c.execute(
            "SELECT tracking_token FROM orders WHERE id=%s", (oid,)
        ).fetchone()["tracking_token"]
        if not token:
            token = new_token()
        c.execute(
            "UPDATE orders SET customer_name=%s, agreed_date=%s, tracking_token=%s, "
            "total=%s, updated_at=COALESCE(NULLIF(updated_at,''), %s) WHERE id=%s",
            (o.get("customer", ""), o.get("deal", ""), token,
             int(o.get("total") or 0), now(), oid)
        )
        if c.execute("SELECT 1 FROM order_items WHERE order_id=%s LIMIT 1",
                     (oid,)).fetchone():
            continue
        created = o.get("created") or now()
        item_id = uid()
        c.execute(
            "INSERT INTO order_items(id,order_id,position,name,garment,material,"
            "color,design,printing,note,price,qty,created) "
            "VALUES(%s,%s,0,%s,%s,%s,%s,%s,'',%s,%s,%s,%s)",
            (item_id, oid, o.get("garment") or "Pesanan", o.get("garment") or "Pesanan",
             o.get("material", ""), o.get("color", ""), o.get("spec", ""),
             o.get("special", ""), int(o.get("price") or 0),
             int(o.get("qty") or 0), created)
        )
        for label, qty in _blank_sizes(o).items():
            c.execute(
                "INSERT INTO size_breakdowns(id,item_id,label,qty) VALUES(%s,%s,%s,%s)",
                (uid(), item_id, label, qty)
            )
        stages = o.get("stages") or []
        for i, (key, label) in enumerate(STAGE_DEFS):
            old = stages[i] if i < len(stages) else {}
            # Normalisasi state: nilai tak dikenal (mis. dari versi lama)
            # dianggap pending supaya constraint aplikasi tetap konsisten.
            state = old.get("state", "pending")
            if state not in VALID_STATES:
                state = "pending"
            c.execute(
                "INSERT INTO production_stages(id,order_id,stage_key,label,state,"
                "target_date,start_date,started_at,finished_at,note) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (uid(), oid, key, label, state,
                 old.get("estimate", ""), old.get("start", ""),
                 (old.get("start", "") + "T00:00:00+07:00") if old.get("start") else "",
                 old.get("finished", ""), old.get("note", ""))
            )
        checklist = o.get("checklist") or []
        for i, label in enumerate(CHECKLIST_DEFS):
            done = bool(checklist[i]) if i < len(checklist) else False
            c.execute(
                "INSERT INTO production_checklist_items(id,order_id,position,"
                "label,done,done_at) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (uid(), oid, i, label, 1 if done else 0, now() if done else "")
            )
        for p in o.get("payments") or []:
            c.execute(
                "INSERT INTO payments(id,order_id,amount,date,method,note,reference,"
                "kind,recorded_at) VALUES(%s,%s,%s,%s,%s,%s,'',%s,%s) "
                "ON CONFLICT DO NOTHING",
                (p.get("id") or uid(), oid, int(p.get("amount") or 0),
                 p.get("date") or o.get("deal", ""), "Tunai/Transfer",
                 p.get("note", ""), p.get("kind") or "Pembayaran",
                 p.get("at") or now())
            )
        for h in o.get("history") or []:
            c.execute(
                "INSERT INTO order_status_history(id,order_id,at,actor,message,"
                "detail,visible) VALUES(%s,%s,%s,'owner',%s,%s,0)",
                (uid(), oid, h.get("at") or now(), h.get("message", ""),
                 json.dumps(h.get("detail")) if h.get("detail") is not None else "")
            )
        migrated += 1
    return migrated