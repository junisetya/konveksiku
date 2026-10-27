# ======================================================================
# ROFI JAYA — API v2 (manajemen pesanan, produksi, nota, tracking)
# ======================================================================
# Semua route di bawah ini memakai autentikasi owner yang sama dengan
# aplikasi v1 (`session["owner"]` + token CSRF). Halaman tracking
# konsumen memakai token acak per pesanan dan tidak memerlukan login.
#
# Sumber data utama adalah tabel relasional (orders, order_items,
# size_breakdowns, production_stages, production_checklist_items,
# payments, order_status_history). `orders.data` hanya arsip lama.
# ======================================================================

import sys as _sys
import urllib.parse
import urllib.request
import urllib.error
import base64
import json as _json
from pathlib import Path as _Path

_TOOLS = str(_Path(__file__).resolve().parent / "tools")
if _TOOLS not in _sys.path:
    _sys.path.insert(0, _TOOLS)
import migrate_v2 as _mig  # noqa: E402

from app import (  # noqa: E402  (app.py mengimpor modul ini di bagian akhir)
    app, authenticated, connect, fonnte_token, format_rupiah, jsonify,
    normalize_wa, now, request, Response, require, settings, text,
    session, uuid, json, re, html_escape, ValidationError, fonnte_send
)
from rofi_core import public_base_url, WIB  # noqa: E402
def tracking_block_reason(user_agent):
    """Kembalikan alasan bila permintaan terlihat sebagai bot."""
    ua = (user_agent or "").lower()
    if not ua:
        return "User-agent kosong."
    _INAPP_BROWSER_MARKERS = (
        "whatsapp/", "fban", "fbav", "fb_iab", "instagram", "line/", "micromessenger",
    )
    if any(m in ua for m in _INAPP_BROWSER_MARKERS):
        if "whatsappbot" in ua or "facebookexternalhit" in ua:
            return "User-agent crawler aplikasi pesan."
        return ""
    _BOT_MARKERS = (
        "preview", "bot", "crawl", "slack", "facebookexternalhit", "twitterbot",
        "linkedinbot", "skype", "curl", "wget", "python-requests", "python-httpx",
        "httpx", "headless",
    )
    for marker in _BOT_MARKERS:
        if marker in ua:
            return f"User-agent diperlakukan sebagai bot ({marker})."
    return ""
from rofi_ui import HTML  # noqa: E402

datetime = __import__("datetime").datetime

STAGE_KEYS = [k for k, _ in _mig.STAGE_DEFS]
STAGE_LABELS = dict(_mig.STAGE_DEFS)
STAGE_LABELS["serah"] = "Penyerahan"
CHECKLIST_DEFAULT = list(_mig.CHECKLIST_DEFS)

STAGE_STATE_LABEL = {
    "pending": "Belum Dimulai",
    "running": "Sedang Dikerjakan",
    "done": "Selesai",
}
PROD_LABELS = {
    "baru": "Menunggu Potong",
    "potong": "Sedang Dipotong",
    "potong_done": "Potong Selesai",
    "jahit": "Sedang Dijahit",
    "jahit_done": "Jahit Selesai",
    "finishing": "Sedang Finishing",
    "siap": "Siap Diserahkan",
    "serah": "Sedang Diserahkan",
    "diterima": "Selesai Diserahkan",
    "batal": "Dibatalkan",
}
METHODS = ["Tunai", "Transfer bank", "E-wallet", "Lainnya"]
HANDOVER = ["Diambil konsumen", "Kurir", "Ekspedisi", "Lainnya"]


def migrate_v2():
    with connect() as c:
        _mig.ensure_schema(c)
        _mig.backfill(c)


def _wa_url(number, message):
    return "https://wa.me/%s?text=%s" % (number, urllib.parse.quote(message, safe=""))


def _mask_name(name):
    """Samarkan nama untuk halaman tracking publik."""
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "Konsumen"
    first = parts[0]
    if len(first) <= 2:
        head = first
    else:
        head = first[:2] + "*" * max(1, len(first) - 2)
    return " ".join([head] + ["*" * max(2, len(p)) for p in parts[1:]])


def _num(value, minimum=0, maximum=10**12, label="Angka"):
    if isinstance(value, bool):
        raise ValidationError(f"{label} tidak valid.")
    if value in (None, ""):
        value = 0
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    raw = str(value).strip().replace(".", "")
    require(re.fullmatch(r"\d+", raw) is not None,
            f"{label} harus berupa angka bulat ≥ 0.")
    n = int(raw)
    require(minimum <= n <= maximum, f"{label} di luar batas.")
    return n


def _date(value, label="Tanggal", optional=False):
    if optional and not value:
        return ""
    require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value),
            f"{label} harus berformat YYYY-MM-DD.")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValidationError(f"{label} tidak valid.")
    return value


def _today_wib():
    return datetime.now(WIB).date().isoformat()


# -------------------------- Baca pesanan --------------------------

def _items_for(c, order_id):
    rows = c.execute(
        "SELECT * FROM order_items WHERE order_id=%s ORDER BY position, created",
        (order_id,)
    ).fetchall()
    sizes = c.execute(
        "SELECT s.item_id,s.label,s.qty FROM size_breakdowns s "
        "JOIN order_items i ON i.id=s.item_id WHERE i.order_id=%s "
        "ORDER BY s.label", (order_id,)
    ).fetchall()
    by_item = {}
    for s in sizes:
        by_item.setdefault(s["item_id"], []).append(
            {"label": s["label"], "qty": int(s["qty"])}
        )
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "name": r["name"], "garment": r["garment"],
            "material": r["material"], "color": r["color"],
            "design": r["design"], "printing": r["printing"],
            "note": r["note"], "price": int(r["price"]), "qty": int(r["qty"]),
            "subtotal": int(r["price"]) * int(r["qty"]),
            "sizes": by_item.get(r["id"], []),
        })
    return out


def _stages_for(c, order_id):
    rows = c.execute(
        "SELECT * FROM production_stages WHERE order_id=%s", (order_id,)
    ).fetchall()
    index = {r["stage_key"]: r for r in rows}
    out = []
    for key in STAGE_KEYS:
        r = index.get(key)
        out.append({
            "key": key, "label": STAGE_LABELS[key],
            "state": r["state"] if r else "pending",
            "target": r["target_date"] if r else "",
            "start": r["start_date"] if r else "",
            "started_at": r["started_at"] if r else "",
            "finished_at": r["finished_at"] if r else "",
            "note": r["note"] if r else "",
        })
    return out


def _checklist_for(c, order_id):
    rows = c.execute(
        "SELECT * FROM production_checklist_items WHERE order_id=%s "
        "ORDER BY position", (order_id,)
    ).fetchall()
    return [{"id": r["id"], "label": r["label"], "done": bool(r["done"]),
             "done_at": r["done_at"]} for r in rows]


def _payments_for(c, order_id):
    rows = c.execute(
        "SELECT * FROM payments WHERE order_id=%s AND voided=0 "
        "ORDER BY date, recorded_at", (order_id,)
    ).fetchall()
    voided = c.execute(
        "SELECT * FROM payments WHERE order_id=%s AND voided=1 "
        "ORDER BY date, recorded_at", (order_id,)
    ).fetchall()
    def shape(r):
        return {"id": r["id"], "amount": int(r["amount"]), "date": r["date"],
                "method": r["method"], "note": r["note"],
                "reference": r["reference"], "kind": r["kind"],
                "recorded_at": r["recorded_at"],
                "void_reason": r["void_reason"], "void_at": r["void_at"]}
    return [shape(r) for r in rows], [shape(r) for r in voided]


def _history_for(c, order_id, limit=200):
    rows = c.execute(
        "SELECT * FROM order_status_history WHERE order_id=%s "
        "ORDER BY at DESC, id DESC LIMIT %s", (order_id, limit)
    ).fetchall()
    out = []
    for r in rows:
        detail = r["detail"]
        try:
            detail = json.loads(detail) if detail else None
        except ValueError:
            pass
        out.append({"at": r["at"], "actor": r["actor"],
                    "message": r["message"], "detail": detail})
    return out


def _customer_row(c, name, wa, company, address):
    """Pakai ulang pelanggan berdasarkan nomor WhatsApp, atau buat baru."""
    stamp = now()
    if wa:
        row = c.execute("SELECT * FROM customers WHERE wa=%s", (wa,)).fetchone()
        if row:
            c.execute(
                "UPDATE customers SET name=%s, company=%s, address=%s, updated=%s "
                "WHERE id=%s",
                (name, company or row["company"], address or row["address"],
                 stamp, row["id"])
            )
            return row["id"]
    cid = uuid.uuid4().hex
    c.execute(
        "INSERT INTO customers(id,name,wa,company,address,created,updated) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s)",
        (cid, name, wa, company or "", address or "", stamp, stamp)
    )
    return cid


def _log(c, order_id, message, detail=None, visible=False):
    c.execute(
        "INSERT INTO order_status_history(id,order_id,at,actor,message,detail,visible)"
        " VALUES(%s,%s,%s,'owner',%s,%s,%s)",
        (uuid.uuid4().hex, order_id, now(), message,
         json.dumps(detail, ensure_ascii=False) if detail is not None else "",
         1 if visible else 0)
    )


def _bump(c, order_id):
    c.execute(
        "UPDATE orders SET version=version+1, updated_at=%s WHERE id=%s",
        (now(), order_id)
    )


def _totals(items, discount, extra):
    base = sum(i["subtotal"] for i in items)
    total = base - discount + extra
    require(total >= 0, "Total pesanan tidak boleh negatif.")
    return base, total


def load_order(c, ident, by="id"):
    """Muat satu pesanan lengkap dari tabel relasional."""
    if by == "token":
        row = c.execute(
            "SELECT * FROM orders WHERE tracking_token=%s", (ident,)
        ).fetchone()
    elif by == "number":
        row = c.execute("SELECT * FROM orders WHERE number=%s", (ident,)).fetchone()
    else:
        row = c.execute("SELECT * FROM orders WHERE id=%s", (ident,)).fetchone()
    if not row:
        return None
    o = json.loads(row["data"])
    o.setdefault("life", "active")
    o.setdefault("final_label", "")
    o.setdefault("shipping", None)
    o.setdefault("received", "")
    o.setdefault("ready_at", "")
    o.setdefault("target_payment", "")
    o.setdefault("work_start", "")
    o.setdefault("customer_note", "")
    o.setdefault("agreement_note", "")
    o.setdefault("discount", 0)
    o.setdefault("extra", 0)
    o.setdefault("wa", "")
    o.setdefault("company", "")
    o.setdefault("address", "")
    oid = row["id"]
    items = _items_for(c, oid)
    stages = _stages_for(c, oid)
    checklist = _checklist_for(c, oid)
    payments, voided = _payments_for(c, oid)
    received_amount = sum(p["amount"] for p in payments)
    total = int(row["total"]) or int(o.get("total") or 0)
    remaining = total - received_amount
    if o["life"] == "cancelled":
        pay_status = "Dibatalkan"
    elif remaining == 0:
        pay_status = "Lunas"
    elif remaining < 0:
        pay_status = "Kelebihan Bayar"
    elif not payments:
        pay_status = "Belum Bayar"
    elif len(payments) == 1 and payments[0]["kind"] == "DP":
        pay_status = "DP Dibayar"
    else:
        pay_status = "Pembayaran Sebagian"

    by_key = {s["key"]: s for s in stages}
    prod = "baru"
    if o["life"] == "cancelled":
        prod = "batal"
    elif by_key["serah"]["state"] == "done":
        prod = "diterima"
    elif by_key["serah"]["state"] == "running":
        prod = "serah"
    elif by_key["finishing"]["state"] == "done":
        prod = "siap"
    elif by_key["finishing"]["state"] == "running":
        prod = "finishing"
    elif by_key["jahit"]["state"] == "done":
        prod = "jahit_done"
    elif by_key["jahit"]["state"] == "running":
        prod = "jahit"
    elif by_key["potong"]["state"] == "done":
        prod = "potong_done"
    elif by_key["potong"]["state"] == "running":
        prod = "potong"
    elif o["life"] == "done":
        prod = "diterima"

    qty = sum(i["qty"] for i in items) or int(o.get("qty") or 0)
    today = _today_wib()
    target = row.get("target") or o.get("target") or row["agreed_date"] or today
    late = False
    if o["life"] in ("active", "paused", "unpaid"):
        if target and target < today and prod not in ("siap", "diterima", "serah"):
            late = True
        if any(s["state"] == "running" and s["target"] and s["target"] < today
               for s in stages):
            late = True

    return {
        "id": oid, "number": row["number"], "version": row["version"],
        "life": row["life"] or o.get("life") or "active", "final_label": o.get("final_label", ""),
        "created": o.get("created", ""), "updated_at": row["updated_at"],
        "deal": row["agreed_date"], "target": target,
        "target_payment": o.get("target_payment", ""),
        "work_start": o.get("work_start", ""),
        "customer": row["customer_name"], "wa": o.get("wa", ""),
        "company": o.get("company", ""), "address": o.get("address", ""),
        "customer_note": o.get("customer_note", ""),
        "agreement_note": o.get("agreement_note", o.get("special", "")),
        "garment": items[0]["garment"] if items else o.get("garment", ""),
        "items": items, "qty": qty,
        "discount": int(o.get("discount") or 0),
        "extra": int(o.get("extra") or 0),
        "base": sum(i["subtotal"] for i in items),
        "total": total, "paid": received_amount, "remaining": remaining,
        "payment_status": pay_status, "status": PROD_LABELS[prod],
        "prod": prod, "late": late,
        "stages": stages, "checklist": checklist,
        "payments": payments, "voided_payments": voided,
        "history": _history_for(c, oid),
        "tracking_token": row["tracking_token"],
        "shipping": o.get("shipping"),
        "received": o.get("received", ""),
        "ready_at": o.get("ready_at", ""),
        "ready_note": o.get("ready_note", ""),
        "checklist_labels": [x["label"] for x in checklist],
    }


def serialize_v2(c, row):
    o = load_order(c, row["id"])
    photos = c.execute(
        "SELECT id,stage,caption,uploaded,remote_url FROM photos WHERE order_id=%s "
        "ORDER BY uploaded", (row["id"],)
    ).fetchall()
    o["photos"] = [dict(x) for x in photos]
    return o


def order_urls(ident, number, token=""):
    base = public_base_url()
    t = token or ident
    return {
        "nota": f"{base}/nota/{t}",
        "tracking": f"{base}/tracking/{t}",
    }


# -------------------------- API v2 --------------------------

PUBLIC_CSS = """
:root{--bg:#101211;--surface:#171A19;--card:#202522;--line:#343B36;
--text:#F1F2ED;--muted:#B0B8B0;--accent:#B5C7A8;--warn:#E0A458;--bad:#D9756A}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--accent)}
.wrap{max-width:880px;margin:0 auto;padding:0 18px}
header.top{border-bottom:1px solid var(--line);padding:18px 0;background:var(--surface)}
header.top .wrap{display:flex;justify-content:space-between;align-items:center;gap:12px}
.brand{font-weight:800;letter-spacing:.14em;font-size:14px}
.brand small{display:block;color:var(--muted);letter-spacing:.08em;font-weight:500;
font-size:11px;margin-top:2px}
main{padding:26px 0 60px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:20px;margin-bottom:18px}
h1{font-size:24px;margin:0 0 4px;letter-spacing:-.5px}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);
margin:0 0 14px;font-weight:600}
h3{font-size:16px;margin:0 0 8px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.kv{display:grid;grid-template-columns:150px 1fr;gap:6px 14px;font-size:14px}
.kv span{color:var(--muted)}
.kv b{font-weight:600}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;color:var(--muted);font-size:11px;letter-spacing:.08em;
text-transform:uppercase;border-bottom:1px solid var(--line);padding:8px 6px}
td{padding:10px 6px;border-bottom:1px solid var(--line);vertical-align:top}
.right{text-align:right}
.muted{color:var(--muted)}
.tiny{font-size:12px}
.badge{display:inline-block;padding:4px 10px;border-radius:999px;font-size:11.5px;
border:1px solid var(--line);background:#1b201d;color:var(--muted)}
.b-done{background:#233026;border-color:#3d5443;color:#C7DDBB}
.b-run{background:#262a30;border-color:#3b4552;color:#B9CBE0}
.b-warn{background:#2d2620;border-color:#4d3f2c;color:var(--warn)}
.b-bad{background:#2e2220;border-color:#4d3330;color:var(--bad)}
.timeline{list-style:none;margin:0;padding:0}
.timeline li{position:relative;padding:0 0 20px 30px;border-left:1px solid var(--line);
margin-left:8px}
.timeline li:last-child{border-left-color:transparent;padding-bottom:0}
.timeline li:before{content:"";position:absolute;left:-6px;top:4px;width:11px;height:11px;
border-radius:50%;background:#3b443d;border:1px solid var(--line)}
.timeline li.done:before{background:var(--accent);border-color:var(--accent)}
.timeline li.running:before{background:#B9CBE0}
.progress{height:8px;background:#1b201d;border-radius:99px;overflow:hidden;
border:1px solid var(--line)}
.progress>i{display:block;height:100%;background:var(--accent)}
.btn{display:inline-flex;align-items:center;gap:8px;padding:11px 16px;border-radius:10px;
border:1px solid var(--line);background:var(--card);color:var(--text);text-decoration:none;
font-weight:600;font-size:14px;cursor:pointer}
.btn.primary{background:var(--accent);color:#11150F;border-color:var(--accent)}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.empty{padding:40px 20px;text-align:center;color:var(--muted)}
footer{border-top:1px solid var(--line);padding:20px 0;color:var(--muted);font-size:12px}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:14px}
figure{margin:0;background:var(--bg);border-radius:12px;overflow:hidden;border:1px solid var(--line)}
figure img{width:100%;display:block;aspect-ratio:3/4;object-fit:cover}
figcaption{padding:9px 11px;font-size:12.5px;color:var(--muted)}
figcaption b{display:block;color:#1c2622;font-weight:600;font-size:13px}
@media(max-width:640px){.grid2{grid-template-columns:1fr}.kv{grid-template-columns:120px 1fr}
h1{font-size:20px}}
@media print{
 body{background:#fff;color:#111}
 header.top,footer,.no-print{display:none!important}
 .card{border:1px solid #ddd;box-shadow:none;break-inside:avoid;background:#fff}
 .kv span,.muted,.tiny,h2{color:#555}
 a{color:#111}
 .badge{background:#f2f2f2;color:#333;border-color:#ccc}
 main{padding:0}.wrap{max-width:none;padding:0}
}
@page{size:A4;margin:14mm}
"""


def public_page(title, body, order=None, extra_head="", refresh_seconds=0):
    """Rangka halaman publik.

    `refresh_seconds` > 0 menyisipkan `<meta http-equiv="refresh">` di
    <head> agar halaman memuat ulang sendiri tanpa JavaScript inline.
    Ini penting karena CSP situs tidak mengizinkan `<script>` inline di
    masa depan; tanpa meta ini halaman tracking tidak akan auto-refresh.
    """
    meta = ""
    if refresh_seconds and refresh_seconds > 0:
        meta = f'<meta http-equiv="refresh" content="{int(refresh_seconds)}">'
    return Response(
        "<!doctype html><html lang=\"id\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta name=\"robots\" content=\"noindex,nofollow\">"
        "<meta http-equiv=\"Content-Security-Policy\" content=\"upgrade-insecure-requests\">"
        f"{meta}"
        f"<title>{html_escape(title)}</title>{extra_head}"
        f"<style>{PUBLIC_CSS}</style></head><body>"
        '<header class="top"><div class="wrap"><div class="brand">ROFI JAYA'
        '<small>KONVEKSI &amp; FASHION</small></div>'
        + (f'<span class="badge">{html_escape(order)}</span>' if order else "")
        + '</div></header><main><div class="wrap">' + body + "</div></main>"
        '<footer><div class="wrap">Halaman ini hanya dapat dibuka melalui tautan '
        "yang diberikan Rofi Jaya. Jangan bagikan tautan ini ke pihak lain.</div></footer>"
        "</body></html>",
        mimetype="text/html")


def _badge_for_state(state):
    cls = {"done": "b-done", "running": "b-run"}.get(state, "")
    return f'<span class="badge {cls}">{html_escape(STAGE_STATE_LABEL[state])}</span>'


def _stage_items_html(o):
    out = []
    for it in o["items"]:
        sizes = ", ".join(f"{s['label']}: {s['qty']}" for s in it["sizes"]) or "—"
        out.append(
            "<tr><td><b>%s</b><div class='tiny muted'>%s</div></td>"
            "<td>%s</td><td class='tiny'>%s</td><td class='right'>%d pcs</td>"
            "<td class='right'>%s</td><td class='right'>%s</td></tr>" % (
                html_escape(it["garment"]),
                html_escape(" · ".join(x for x in (it["material"], it["color"]) if x) or "—"),
                html_escape(sizes), html_escape(it["design"] or it["note"] or "—"),
                it["qty"], format_rupiah(it["price"]), format_rupiah(it["subtotal"]))
        )
    return "".join(out)


def _public_blocked():
    """Preview/bot aplikasi lain tidak boleh mengambil halaman privat."""
    reason = tracking_block_reason(request.headers.get("User-Agent", ""))
    if not reason:
        return None
    return public_page(
        "Tautan hanya untuk konsumen",
        '<div class="card"><div class="empty">Halaman ini berisi data pesanan '
        "satu konsumen dan hanya dapat dibuka langsung di browser.<br>"
        "Salin tautannya ke browser (Chrome/Safari) untuk melihat progres."
        "</div></div>"), 403


@app.get("/nota/<token>")
def public_nota(token):
    blocked = _public_blocked()
    if blocked:
        return blocked
    with connect() as c:
        o = load_order(c, token, by="token")
        if not o:
            return public_page(
                "Nota tidak tersedia",
                '<div class="card"><div class="empty">Tautan nota tidak valid '
                "atau sudah tidak tersedia.<br>Hubungi Rofi Jaya untuk nota terbaru."
                "</div></div>"), 404
    urls = order_urls(o["id"], o["number"], o["tracking_token"])
    rows = _stage_items_html(o)
    pays = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td class='right'>%s</td></tr>" % (
            html_escape(p["date"]), html_escape(p["kind"]),
            html_escape(p["note"] or p["method"] or "—"),
            format_rupiah(p["amount"]))
        for p in o["payments"]
    ) or "<tr><td colspan='4' class='muted'>Belum ada pembayaran diterima.</td></tr>"
    body = f"""
<div class="card">
 <div class="row" style="justify-content:space-between;align-items:flex-start">
  <div><h1>Nota Pesanan</h1>
   <div class="muted tiny">Nomor {html_escape(o['number'])} · versi data {o['version']}</div>
   <div class="tiny muted">Diperbarui {html_escape((o['updated_at'] or '')[:16].replace('T',' '))} WIB</div>
  </div>
  <div class="row no-print"><a class="btn" href="javascript:window.print()">Cetak / Simpan PDF</a></div>
 </div>
</div>
<div class="grid2">
 <div class="card"><h2>Konsumen</h2><div class="kv">
  <span>Nama</span><b>{html_escape(o['customer'])}</b>
  <span>WhatsApp</span><b>+{html_escape(o['wa'])}</b>
  <span>Instansi</span><b>{html_escape(o['company'] or '—')}</b>
  <span>Alamat</span><b>{html_escape(o['address'] or '—')}</b>
 </div></div>
 <div class="card"><h2>Kesepakatan</h2><div class="kv">
  <span>Tanggal kesepakatan</span><b>{html_escape(o['deal'])}</b>
  <span>Estimasi selesai</span><b>{html_escape(o['target'])}</b>
  <span>Target pelunasan</span><b>{html_escape(o['target_payment'] or '—')}</b>
  <span>Status produksi</span><b>{html_escape(o['status'])}</b>
 </div></div>
</div>
<div class="card"><h2>Rincian pesanan</h2>
<table><thead><tr><th>Model</th><th>Ukuran</th><th>Spesifikasi</th>
<th class="right">Jumlah</th><th class="right">Harga/pcs</th><th class="right">Subtotal</th>
</tr></thead><tbody>{rows}</tbody></table></div>
<div class="grid2">
 <div class="card"><h2>Ringkasan biaya</h2><div class="kv">
  <span>Total item</span><b>{format_rupiah(o['base'])}</b>
  <span>Diskon</span><b>{format_rupiah(o['discount'])}</b>
  <span>Biaya tambahan</span><b>{format_rupiah(o['extra'])}</b>
  <span>Total kesepakatan</span><b>{format_rupiah(o['total'])}</b>
  <span>Pembayaran diterima</span><b>{format_rupiah(o['paid'])}</b>
  <span>Sisa pembayaran</span><b>{format_rupiah(o['remaining'])}</b>
  <span>Status pembayaran</span><b>{html_escape(o['payment_status'])}</b>
 </div></div>
 <div class="card"><h2>Pembayaran</h2>
 <table><thead><tr><th>Tanggal</th><th>Jenis</th><th>Catatan</th>
 <th class="right">Nominal</th></tr></thead><tbody>{pays}</tbody></table></div>
</div>
<div class="card"><h2>Catatan kesepakatan</h2>
 <p class="tiny" style="white-space:pre-wrap;margin:0">{html_escape(o['agreement_note'] or '—')}</p>
</div>
<div class="card"><h2>Pantau produksi</h2>
 <p class="tiny muted">Estimasi selesai bersifat perkiraan dan dapat berubah sesuai
 kondisi produksi. Progres terbaru selalu dapat dilihat melalui tautan berikut.</p>
 <a class="btn primary" href="{html_escape(urls['tracking'])}">Buka tracking produksi</a>
</div>
"""
    return public_page(f"Nota {o['number']} · Rofi Jaya", body, o["number"])


@app.get("/tracking/<token>")
def public_tracking(token):
    blocked = _public_blocked()
    if blocked:
        return blocked
    with connect() as c:
        o = load_order(c, token, by="token")
        if not o:
            return public_page(
                "Link tracking tidak valid",
                '<div class="card"><div class="empty">Link tracking tidak valid '
                "atau tidak tersedia.<br>Periksa kembali tautan dari Rofi Jaya."
                "</div></div>"), 404
        s = settings(c)
        photos = c.execute(
            "SELECT stage, caption, remote_url FROM photos WHERE order_id=%s ORDER BY uploaded", 
            (o["id"],)
        ).fetchall()
        
    done = sum(1 for x in o["stages"] if x["state"] == "done")
    pct = int(done / len(o["stages"]) * 100)
    steps = []
    for i, st in enumerate(o["stages"]):
        when = []
        if st["start"]:
            when.append(f"Mulai {html_escape(st['start'])}")
        if st["finished_at"]:
            when.append("Selesai " + html_escape(st["finished_at"][:16].replace("T", " ")))
        if st["target"]:
            when.append("Target " + html_escape(st["target"]))
        note = ""
        if st["note"] and st["state"] != "pending":
            note = f"<div class='tiny muted' style='margin-top:4px'>{html_escape(st['note'])}</div>"
        steps.append(
            f"<li class='{html_escape(st['state'])}'><div class='row' "
            f"style='justify-content:space-between'><b>{i + 1}. {html_escape(st['label'])}</b>"
            f"{_badge_for_state(st['state'])}</div>"
            f"<div class='tiny muted'>{' · '.join(when) or '—'}</div>{note}</li>"
        )
    steps.insert(0, "<li class='done'><div class='row' style='justify-content:space-between'>"
                    "<b>Pesanan disepakati</b><span class='badge b-done'>Selesai</span></div>"
                    f"<div class='tiny muted'>{html_escape(o['deal'])}</div></li>")
    types = ", ".join(sorted({i["garment"] for i in o["items"]})) or o["garment"]
    late = ('<div class="badge b-warn" style="margin-bottom:10px">Melewati estimasi — '
            "sedang ditindaklanjuti</div>") if o["late"] else ""
            
    # Render Galeri Foto
    photos_html = ""
    if photos:
        figures = []
        for p in photos:
            if not p["remote_url"]: continue
            figures.append(
                f"<figure><a href='{html_escape(p['remote_url'])}' target='_blank' "
                f"rel='noopener noreferrer'>"
                f"<img loading='lazy' referrerpolicy='no-referrer' "
                f"src='{html_escape(p['remote_url'])}' alt='{html_escape(p['caption'] or p['stage'])}'></a>"
                f"<figcaption><b>{html_escape(str(p['stage']).capitalize())}</b>"
                f"{html_escape(p['caption'] or '')}</figcaption></figure>"
            )
        if figures:
            photos_html = f"<div class='card'><h2>Galeri Foto Progres</h2><div class='gallery'>{''.join(figures)}</div></div>"

    body = f"""
<div class="card">
 <h1>Progres Pesanan</h1>
 <div class="muted tiny">Nomor {html_escape(o['number'])} · atas nama {html_escape(_mask_name(o['customer']))}</div>
 {late}
 <div class="row" style="margin:16px 0 8px;justify-content:space-between">
  <b>{html_escape(o['status'])}</b><span class="tiny muted">{done} dari {len(o['stages'])} tahap selesai</span></div>
 <div class="progress"><i style="width:{pct}%"></i></div>
 <div class="grid2" style="margin-top:18px">
  <div class="kv"><span>Jenis pakaian</span><b>{html_escape(types)}</b>
   <span>Jumlah</span><b>{o['qty']} pcs</b>
   <span>Estimasi selesai</span><b>{html_escape(o['target'])}</b></div>
  <div class="kv"><span>Tanggal kesepakatan</span><b>{html_escape(o['deal'])}</b>
   <span>Status pembayaran</span><b>{html_escape(o['payment_status'])}</b>
   <span>Diperbarui</span><b>{html_escape((o['updated_at'] or '')[:16].replace('T',' '))} WIB</b></div>
 </div>
</div>
<div class="card"><h2>Tahapan produksi</h2><ul class="timeline">{''.join(steps)}</ul></div>
{photos_html}
<div class="card"><h2>Informasi</h2>
 <p class="tiny muted" style="margin:0">Halaman ini diperbarui otomatis setiap 60 detik
 dan setiap kali dibuka. Jika ada pertanyaan, hubungi {html_escape(s.get('name') or 'Rofi Jaya')}
 melalui WhatsApp.</p></div>
"""
    return public_page(
        f"Tracking {o['number']} · Rofi Jaya", body, o["number"],
        refresh_seconds=60)


@app.get("/api/v2/state")
@authenticated
def v2_state():
    with connect() as c:
        rows = c.execute("SELECT * FROM orders ORDER BY number DESC").fetchall()
        orders = [serialize_v2(c, r) for r in rows]
        s = settings(c)
        base = public_base_url()
        for o in orders:
            o["urls"] = order_urls(o["id"], o["number"], o["tracking_token"])
    return jsonify(
        csrf=session["csrf"], settings=s, orders=orders,
        today=_today_wib(), stages=[[k, STAGE_LABELS[k]] for k in STAGE_KEYS],
        checklist=CHECKLIST_DEFAULT, methods=METHODS, handover=HANDOVER,
        garments=s.get("garments", []), materials=s.get("materials", []),
        fonnte_configured=bool(fonnte_token()), base_url=base,
        wa_configured=bool(s.get("wa")),
    )


def _validate_items(payload):
    require(isinstance(payload, list) and 1 <= len(payload) <= 20,
            "Pesanan harus berisi 1–20 item.")
    items = []
    for raw in payload:
        require(isinstance(raw, dict), "Data item tidak valid.")
        garment = text(raw.get("garment", ""), 150)
        require(garment, "Jenis pakaian setiap item wajib diisi.")
        qty = _num(raw.get("qty"), 1, 1000000, "Jumlah pcs")
        price = _num(raw.get("price"), 0, 10**11, "Harga per pcs")
        sizes = raw.get("sizes") or []
        require(isinstance(sizes, list) and len(sizes) <= 30,
                "Rincian ukuran tidak valid.")
        clean_sizes = []
        total_sizes = 0
        for s in sizes:
            require(isinstance(s, dict), "Rincian ukuran tidak valid.")
            label = text(s.get("label", ""), 20)
            require(label, "Nama ukuran wajib diisi.")
            n = _num(s.get("qty"), 0, 1000000, "Jumlah ukuran")
            if n:
                clean_sizes.append({"label": label.upper(), "qty": n})
                total_sizes += n
        if clean_sizes:
            require(total_sizes == qty,
                    f"Total rincian ukuran item {garment} ({total_sizes}) harus sama dengan jumlah pcs ({qty}).")
        items.append({
            "name": text(raw.get("name", ""), 150) or garment,
            "garment": garment,
            "material": text(raw.get("material", ""), 150),
            "color": text(raw.get("color", ""), 100),
            "design": text(raw.get("design", ""), 3000),
            "printing": text(raw.get("printing", ""), 300),
            "note": text(raw.get("note", ""), 2000),
            "price": price, "qty": qty, "sizes": clean_sizes,
            "subtotal": price * qty,
        })
    return items


def _validate_order_payload(d):
    require(isinstance(d, dict), "Formulir pesanan tidak valid.")
    customer = text(d.get("customer", ""), 150)
    require(customer, "Nama konsumen wajib diisi.")
    wa = normalize_wa(d.get("wa", ""))
    deal = _date(d.get("deal"), "Tanggal kesepakatan")
    require(deal <= _today_wib(), "Tanggal kesepakatan tidak boleh di masa depan.")
    target = _date(d.get("target"), "Estimasi selesai")
    require(target >= deal, "Estimasi selesai tidak boleh sebelum tanggal kesepakatan.")
    target_payment = _date(d.get("target_payment", ""), "Target pelunasan", optional=True)
    if target_payment:
        require(target_payment >= deal,
                "Target pelunasan tidak boleh sebelum tanggal kesepakatan.")
    items = _validate_items(d.get("items"))
    discount = _num(d.get("discount"), 0, 10**12, "Diskon")
    extra = _num(d.get("extra"), 0, 10**12, "Biaya tambahan")
    base, total = _totals(items, discount, extra)
    dp = _num(d.get("dp"), 0, 10**12, "DP")
    require(dp <= total, "DP tidak boleh melebihi total pesanan.")
    return {
        "dp": dp,
        "dp_date": _date(d.get("dp_date", "") or deal, "Tanggal DP"),
        "dp_method": text(d.get("dp_method", "") or "Tunai/Transfer", 60),
        "dp_note": text(d.get("dp_note", ""), 500),
        "customer": customer, "wa": wa,
        "company": text(d.get("company", ""), 200),
        "address": text(d.get("address", ""), 1500),
        "customer_note": text(d.get("customer_note", ""), 2000),
        "agreement_note": text(d.get("agreement_note", ""), 3000),
        "deal": deal, "target": target, "target_payment": target_payment,
        "work_start": _date(d.get("work_start", ""), "Rencana mulai", optional=True),
        "items": items, "discount": discount, "extra": extra,
        "base": base, "total": total,
    }


def _write_items(c, order_id, items):
    c.execute("DELETE FROM order_items WHERE order_id=%s", (order_id,))
    stamp = now()
    for pos, it in enumerate(items):
        item_id = uuid.uuid4().hex
        c.execute(
            "INSERT INTO order_items(id,order_id,position,name,garment,material,"
            "color,design,printing,note,price,qty,created) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (item_id, order_id, pos, it["name"], it["garment"], it["material"],
             it["color"], it["design"], it["printing"], it["note"],
             it["price"], it["qty"], stamp)
        )
        for s in it["sizes"]:
            c.execute(
                "INSERT INTO size_breakdowns(id,item_id,label,qty) VALUES(%s,%s,%s,%s)",
                (uuid.uuid4().hex, item_id, s["label"], s["qty"])
            )


def _init_stages(c, order_id, target):
    for key in STAGE_KEYS:
        c.execute(
            "INSERT INTO production_stages(id,order_id,stage_key,label,state,"
            "target_date) VALUES(%s,%s,%s,%s,'pending',%s) ON CONFLICT DO NOTHING",
            (uuid.uuid4().hex, order_id, key, STAGE_LABELS[key],
             target if key != "serah" else "")
        )
    for pos, label in enumerate(CHECKLIST_DEFAULT):
        c.execute(
            "INSERT INTO production_checklist_items(id,order_id,position,label,done) "
            "VALUES(%s,%s,%s,%s,0) ON CONFLICT DO NOTHING",
            (uuid.uuid4().hex, order_id, pos, label)
        )


def _create_order_internal(c, d):
    """Buat pesanan di dalam satu koneksi. Kembalikan (id, number, token).

    Dipakai oleh route HTTP dan bot Telegram agar aturan pembuatan pesanan
    hanya ada di satu tempat.
    """
    s = settings(c)
    prefix = re.sub(r"[^A-Z0-9]", "", (s.get("prefix") or "RJ").upper())[:8] or "RJ"
    key = prefix + "-" + datetime.now(WIB).strftime("%Y%m")
    seq = c.execute(
        "INSERT INTO counters(key,value) VALUES(%s,1) "
        "ON CONFLICT(key) DO UPDATE SET value = counters.value + 1 "
        "RETURNING value", (key,)
    ).fetchone()["value"]
    number = f"{key}-{seq:04d}"
    ident = uuid.uuid4().hex
    token = _mig.new_token()
    stamp = now()
    dp = d["dp"]
    _customer_row(c, d["customer"], d["wa"], d["company"], d["address"])
    legacy = {
        "created": stamp, "life": "active", "final_label": "",
        "wa": d["wa"], "company": d["company"], "address": d["address"],
        "customer_note": d["customer_note"],
        "agreement_note": d["agreement_note"],
        "work_start": d["work_start"], "target_payment": d["target_payment"],
        "discount": d["discount"], "extra": d["extra"],
        "garment": d["items"][0]["garment"],
        "special": d["agreement_note"], "shipping": None, "received": "",
        "ready_at": "", "history": [],
        "qty": sum(i["qty"] for i in d["items"]),
        "sizes": {s_["label"]: s_["qty"] for s_ in d["items"][0]["sizes"]},
        "total": d["total"], "deal": d["deal"], "target": d["target"],
        "material": d["items"][0]["material"],
        "color": d["items"][0]["color"],
        "spec": d["items"][0]["design"],
    }
    c.execute(
        "INSERT INTO orders(id,number,version,data,customer_name,agreed_date,"
        "tracking_token,total,updated_at) "
        "VALUES(%s,%s,1,%s,%s,%s,%s,%s,%s)",
        (ident, number, json.dumps(legacy), d["customer"], d["deal"],
         token, d["total"], stamp)
    )
    c.execute("UPDATE orders SET target=%s WHERE id=%s", (d["target"], ident))
    _write_items(c, ident, d["items"])
    _init_stages(c, ident, d["target"])
    _log(c, ident, f"Pesanan {number} dibuat dari kesepakatan tanggal {d['deal']}",
         {"total": d["total"]}, visible=True)
    if dp:
        c.execute(
            "INSERT INTO payments(id,order_id,amount,date,method,note,reference,"
            "kind,recorded_at) VALUES(%s,%s,%s,%s,%s,%s,%s,'DP',%s)",
            (uuid.uuid4().hex, ident, dp,
             d["dp_date"], d["dp_method"], d["dp_note"], "", stamp)
        )
        _log(c, ident, "DP diterima", {"jumlah": dp}, visible=True)
    return ident, number, token


@app.post("/api/v2/orders")
@authenticated
def v2_create_order():
    d = _validate_order_payload(request.get_json())
    with connect() as c:
        ident, number, token = _create_order_internal(c, d)
    return jsonify(id=ident, number=number, urls=order_urls(ident, number, token))


@app.get("/api/v2/orders/<ident>")
@authenticated
def v2_order(ident):
    with connect() as c:
        o = load_order(c, ident)
        require(o is not None, "Pesanan tidak ditemukan.")
        photos = c.execute(
            "SELECT id,stage,caption,uploaded,remote_url FROM photos WHERE order_id=%s "
            "ORDER BY uploaded", (ident,)
        ).fetchall()
        o["photos"] = [dict(x) for x in photos]
    o["urls"] = order_urls(ident, o["number"], o["tracking_token"])
    return jsonify(order=o)


@app.post("/api/v2/orders/<ident>/edit")
@authenticated
def v2_edit_order(ident):
    d = _validate_order_payload(request.get_json())
    reason = text((request.get_json() or {}).get("reason", ""), 2000)
    require(reason, "Alasan revisi wajib diisi.")
    with connect() as c:
        o = load_order(c, ident)
        require(o is not None, "Pesanan tidak ditemukan.")
        require(o["life"] != "cancelled", "Pesanan dibatalkan tidak dapat direvisi.")
        require(not o["received"], "Pesanan sudah diserahkan; buat pesanan baru untuk perubahan.")
        require(d["total"] >= o["paid"],
                "Total baru tidak boleh lebih kecil dari pembayaran yang sudah diterima.")
        before = {"total": o["total"], "target": o["target"], "qty": o["qty"]}
        c.execute(
            "UPDATE orders SET customer_name=%s, agreed_date=%s, total=%s, "
            "target=%s, version=version+1, updated_at=%s WHERE id=%s",
            (d["customer"], d["deal"], d["total"], d["target"], now(), ident)
        )
        legacy = json.loads(c.execute("SELECT data FROM orders WHERE id=%s",
                                      (ident,)).fetchone()["data"])
        legacy.update({
            "wa": d["wa"], "company": d["company"], "address": d["address"],
            "customer_note": d["customer_note"],
            "agreement_note": d["agreement_note"], "special": d["agreement_note"],
            "work_start": d["work_start"], "target_payment": d["target_payment"],
            "discount": d["discount"], "extra": d["extra"],
            "garment": d["items"][0]["garment"],
        })
        c.execute("UPDATE orders SET data=%s WHERE id=%s", (json.dumps(legacy), ident))
        _write_items(c, ident, d["items"])
        _customer_row(c, d["customer"], d["wa"], d["company"], d["address"])
        _log(c, ident, "Kesepakatan direvisi", {
            "alasan": reason, "sebelum": before,
            "sesudah": {"total": d["total"], "target": d["target"],
                        "qty": sum(i["qty"] for i in d["items"])}
        })
    return jsonify(ok=True)


def _stage_action_internal(c, ident, d):
    """Jalankan aksi tahap dalam satu koneksi (dipakai route & bot)."""
    action = d.get("action")
    key = text(d.get("stage", ""), 20)
    require(key in STAGE_KEYS, "Tahap tidak valid.")
    o = load_order(c, ident)
    require(o is not None, "Pesanan tidak ditemukan.")
    require(o["life"] == "active", "Pesanan tidak sedang aktif.")
    stages = {s["key"]: s for s in o["stages"]}
    s = stages[key]
    idx = STAGE_KEYS.index(key)

    def prev_done():
        return idx == 0 or stages[STAGE_KEYS[idx - 1]]["state"] == "done"

    if action == "start":
        require(s["state"] == "pending", "Tahap ini sudah dimulai.")
        require(prev_done(), "Selesaikan tahap sebelumnya terlebih dahulu.")
        start = _date(d.get("start") or _today_wib(), "Tanggal mulai")
        require(start <= _today_wib(), "Tanggal mulai tidak boleh di masa depan.")
        require(start >= o["deal"], "Tanggal mulai tidak boleh sebelum kesepakatan.")
        target = _date(d.get("target", ""), "Target tahap", optional=True)
        if target:
            require(target >= start, "Target tahap tidak boleh sebelum tanggal mulai.")
        c.execute(
            "UPDATE production_stages SET state='running', start_date=%s, "
            "started_at=%s, target_date=%s, note=%s WHERE order_id=%s AND stage_key=%s",
            (start, now(), target, text(d.get("note", ""), 3000), ident, key)
        )
        _log(c, ident, f"Tahap {STAGE_LABELS[key]} dimulai",
             {"tanggal": start, "target": target}, visible=True)
        if key == "finishing":
            _log(c, ident, "Checklist finishing dapat dicentang", visible=False)
    elif action == "finish":
        require(s["state"] == "running", "Mulai tahap ini terlebih dahulu.")
        if key == "finishing":
            pending = [x["label"] for x in o["checklist"] if not x["done"]]
            require(not pending,
                    "Checklist finishing belum lengkap: " + "; ".join(pending))
        if key == "potong":
            require(prev_done(), "Tahap sebelumnya belum selesai.")
        stamp = now()
        c.execute(
            "UPDATE production_stages SET state='done', finished_at=%s "
            "WHERE order_id=%s AND stage_key=%s", (stamp, ident, key)
        )
        if key == "finishing":
            legacy = json.loads(c.execute("SELECT data FROM orders WHERE id=%s",
                                          (ident,)).fetchone()["data"])
            legacy["ready_at"] = stamp
            c.execute("UPDATE orders SET data=%s WHERE id=%s",
                      (json.dumps(legacy), ident))
            _log(c, ident, "Finishing selesai — pesanan siap diserahkan",
                 {"waktu": stamp}, visible=True)
        else:
            _log(c, ident, f"Tahap {STAGE_LABELS[key]} selesai",
                 {"waktu": stamp}, visible=True)
    elif action == "reopen":
        reason = text(d.get("reason", ""), 2000)
        require(reason, "Alasan membuka kembali tahap wajib diisi.")
        require(s["state"] == "done", "Tahap ini belum selesai.")
        if key != "serah":
            later = [STAGE_KEYS[i] for i in range(idx + 1, len(STAGE_KEYS))
                     if stages[STAGE_KEYS[i]]["state"] != "pending"]
            require(not later,
                    "Buka kembali tahap setelahnya lebih dulu (urutan: "
                    + ", ".join(STAGE_LABELS[x] for x in reversed(later)) + ").")
        c.execute(
            "UPDATE production_stages SET state='running', finished_at='' "
            "WHERE order_id=%s AND stage_key=%s", (ident, key)
        )
        _log(c, ident, f"Tahap {STAGE_LABELS[key]} dibuka kembali", {"alasan": reason},
             visible=False)
    elif action == "note":
        c.execute(
            "UPDATE production_stages SET note=%s, target_date=%s "
            "WHERE order_id=%s AND stage_key=%s",
            (text(d.get("note", ""), 3000),
             _date(d.get("target", ""), "Target tahap", optional=True) or s["target"],
             ident, key)
        )
        _log(c, ident, f"Catatan tahap {STAGE_LABELS[key]} diperbarui")
    else:
        raise ValidationError("Aksi tahap tidak dikenali.")
    _bump(c, ident)


@app.post("/api/v2/orders/<ident>/stage")
@authenticated
def v2_stage(ident):
    """Aksi tahap: start, finish, reopen, note, target."""
    d = request.get_json() or {}
    with connect() as c:
        _stage_action_internal(c, ident, d)
    return jsonify(ok=True)


def _checklist_toggle_internal(c, ident, item):
    """Toggle satu item checklist (dipakai route & bot). Kembalikan (done, finished, total)."""
    o = load_order(c, ident)
    require(o is not None, "Pesanan tidak ditemukan.")
    require(o["life"] == "active", "Pesanan tidak sedang aktif.")
    row = c.execute(
        "SELECT * FROM production_checklist_items WHERE order_id=%s AND id=%s",
        (ident, item)
    ).fetchone()
    require(row is not None, "Item checklist tidak ditemukan.")
    done = 0 if row["done"] else 1
    c.execute(
        "UPDATE production_checklist_items SET done=%s, done_at=%s WHERE id=%s",
        (done, now() if done else "", item)
    )
    total = c.execute(
        "SELECT COUNT(*) AS n FROM production_checklist_items WHERE order_id=%s",
        (ident,)
    ).fetchone()["n"]
    finished = c.execute(
        "SELECT COUNT(*) AS n FROM production_checklist_items "
        "WHERE order_id=%s AND done=1", (ident,)
    ).fetchone()["n"]
    _bump(c, ident)
    return done, finished, total


@app.post("/api/v2/orders/<ident>/checklist")
@authenticated
def v2_checklist(ident):
    d = request.get_json() or {}
    item = text(d.get("item", ""), 40)
    with connect() as c:
        done, finished, total = _checklist_toggle_internal(c, ident, item)
    return jsonify(ok=True, done=finished, total=total)


@app.post("/api/v2/orders/<ident>/payment")
@authenticated
def v2_payment(ident):
    d = request.get_json() or {}
    with connect() as c:
        o = load_order(c, ident)
        require(o is not None, "Pesanan tidak ditemukan.")
        require(o["life"] != "cancelled", "Pesanan dibatalkan tidak menerima pembayaran.")
        amount = _num(d.get("amount"), 1, 10**12, "Nominal")
        require(amount <= max(o["remaining"], 0),
                f"Nominal melebihi sisa tagihan ({format_rupiah(o['remaining'])}).")
        date = _date(d.get("date") or _today_wib(), "Tanggal pembayaran")
        require(o["deal"] <= date <= _today_wib(),
                "Tanggal pembayaran harus antara tanggal kesepakatan dan hari ini.")
        method = text(d.get("method", ""), 60)
        require(method in METHODS, "Metode pembayaran tidak valid.")
        pid = uuid.uuid4().hex
        c.execute(
            "INSERT INTO payments(id,order_id,amount,date,method,note,reference,kind,"
            "recorded_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (pid, ident, amount, date, method, text(d.get("note", ""), 1000),
             text(d.get("reference", ""), 120),
             "Pelunasan" if amount == o["remaining"] else "Pembayaran", now())
        )
        _log(c, ident, "Pembayaran diterima", {
            "nominal": amount, "tanggal": date, "metode": method}, visible=True)
        _bump(c, ident)
        after = load_order(c, ident)
    return jsonify(ok=True, id=pid, remaining=after["remaining"],
                   payment_status=after["payment_status"])


@app.post("/api/v2/orders/<ident>/payment/<pid>/void")
@authenticated
def v2_payment_void(ident, pid):
    d = request.get_json() or {}
    reason = text(d.get("reason", ""), 1000)
    require(reason, "Alasan koreksi wajib diisi.")
    with connect() as c:
        o = load_order(c, ident)
        require(o is not None, "Pesanan tidak ditemukan.")
        row = c.execute(
            "SELECT * FROM payments WHERE id=%s AND order_id=%s", (pid, ident)
        ).fetchone()
        require(row is not None, "Pembayaran tidak ditemukan.")
        require(not row["voided"], "Pembayaran ini sudah dikoreksi.")
        c.execute(
            "UPDATE payments SET voided=1, void_reason=%s, void_at=%s WHERE id=%s",
            (reason, now(), pid)
        )
        _log(c, ident, "Pembayaran dikoreksi (tidak dihapus)",
             {"nominal": int(row["amount"]), "tanggal": row["date"], "alasan": reason},
             visible=False)
        _bump(c, ident)
    return jsonify(ok=True)


@app.post("/api/v2/orders/<ident>/handover")
@authenticated
def v2_handover(ident):
    d = request.get_json() or {}
    with connect() as c:
        o = load_order(c, ident)
        require(o is not None, "Pesanan tidak ditemukan.")
        require(o["life"] in ("active", "unpaid"), "Status pesanan tidak mengizinkan penyerahan.")
        stages = {s["key"]: s for s in o["stages"]}
        require(stages["finishing"]["state"] == "done",
                "Selesaikan finishing sebelum mencatat penyerahan.")
        method = text(d.get("method", ""), 60)
        require(method in HANDOVER, "Metode penyerahan tidak valid.")
        date = _date(d.get("date") or _today_wib(), "Tanggal penyerahan")
        require(date <= _today_wib(), "Tanggal penyerahan tidak boleh di masa depan.")
        legacy = json.loads(c.execute("SELECT data FROM orders WHERE id=%s",
                                      (ident,)).fetchone()["data"])
        shipping = {
            "method": method, "courier": text(d.get("courier", ""), 150),
            "tracking": text(d.get("tracking", ""), 150),
            "date": date, "note": text(d.get("note", ""), 1000),
            "recorded_at": now(),
        }
        legacy["shipping"] = shipping
        legacy["received"] = date
        c.execute("UPDATE orders SET data=%s WHERE id=%s", (json.dumps(legacy), ident))
        c.execute(
            "UPDATE production_stages SET state='done', start_date=%s, started_at=%s, "
            "finished_at=%s, note=%s WHERE order_id=%s AND stage_key='serah'",
            (date, now(), now(), f"{method} · {date}", ident)
        )
        _log(c, ident, f"Pesanan diserahkan melalui {method}", shipping, visible=True)
        _bump(c, ident)
    return jsonify(ok=True)


@app.post("/api/v2/orders/<ident>/life")
@authenticated
def v2_life(ident):
    d = request.get_json() or {}
    target = text(d.get("life", ""), 20)
    reason = text(d.get("reason", ""), 2000)
    require(reason, "Alasan wajib diisi.")
    require(target in ("active", "paused", "cancelled", "done", "archived"),
            "Status tidak valid.")
    with connect() as c:
        o = load_order(c, ident)
        require(o is not None, "Pesanan tidak ditemukan.")
        if target == "done":
            require(o["received"], "Barang belum dicatat diserahkan.")
            require(o["remaining"] == 0, "Masih ada sisa pembayaran.")
        if target == "archived":
            require(o["life"] in ("done", "cancelled"),
                    "Hanya pesanan selesai/dibatalkan yang bisa diarsipkan.")
        c.execute("UPDATE orders SET life=%s, version=version+1, updated_at=%s "
                  "WHERE id=%s", (target, now(), ident))
        legacy = json.loads(c.execute("SELECT data FROM orders WHERE id=%s",
                                      (ident,)).fetchone()["data"])
        labels = {"active": "", "paused": "Ditunda", "cancelled": "Dibatalkan",
                  "done": "Selesai", "archived": "Diarsipkan"}
        legacy["final_label"] = labels[target]
        c.execute("UPDATE orders SET data=%s WHERE id=%s", (json.dumps(legacy), ident))
        _log(c, ident, f"Status pesanan diubah: {labels[target] or 'Aktif'}",
             {"alasan": reason}, visible=True)
    return jsonify(ok=True)


@app.post("/api/v2/orders/<ident>/wa")
@authenticated
def v2_wa(ident):
    """Susun pesan WhatsApp (nota atau tracking) — tidak mengirim otomatis."""
    d = request.get_json() or {}
    kind = text(d.get("kind", "nota"), 20)
    require(kind in ("nota", "tracking", "progres"), "Jenis pesan tidak valid.")
    with connect() as c:
        o = load_order(c, ident)
        require(o is not None, "Pesanan tidak ditemukan.")
        s = settings(c)
    urls = order_urls(o["id"], o["number"], o["tracking_token"])
    usaha = s.get("name") or "Rofi Jaya"
    if kind == "nota":
        msg = (
            f"Halo {o['customer']}, berikut Nota Pesanan dari {usaha}.\n\n"
            f"Nomor Nota: {o['number']}\n"
            f"Total Pesanan: {format_rupiah(o['total'])}\n"
            f"DP/Pembayaran: {format_rupiah(o['paid'])}\n"
            f"Sisa Pembayaran: {format_rupiah(o['remaining'])}\n"
            f"Estimasi Selesai: {o['target']}\n\n"
            f"Nota digital:\n{urls['nota']}\n\n"
            f"Terima kasih telah mempercayakan pesanan Anda kepada {usaha}."
        )
    elif kind == "tracking":
        msg = (
            f"Halo {o['customer']}, pesanan Anda sudah tercatat di {usaha}.\n\n"
            f"Anda dapat memantau progres produksi kapan saja melalui link berikut:\n"
            f"{urls['tracking']}\n\n"
            f"Status produksi akan diperbarui oleh tim {usaha} sesuai perkembangan "
            f"pengerjaan. Terima kasih."
        )
    else:
        done = [x["label"] for x in o["stages"] if x["state"] == "done"]
        msg = (
            f"Halo {o['customer']}, berikut progres pesanan {o['number']} di {usaha}.\n\n"
            f"Tahap saat ini: {o['status']}\n"
            f"Sudah selesai: {', '.join(done) or 'belum ada'}\n"
            f"Estimasi selesai: {o['target']}\n"
            f"Sisa pembayaran: {format_rupiah(o['remaining'])}\n\n"
            f"Pantau progres: {urls['tracking']}\n\n"
            f"Terima kasih."
        )
    extra = text(d.get("extra", ""), 2000)
    if extra:
        msg += "\n\n" + extra
    return jsonify(message=msg, url=_wa_url(o["wa"], msg), wa=o["wa"], **urls)

@app.post("/api/v2/orders/<ident>/send-wa")
@authenticated
def v2_send_wa(ident):
    """Kirim pesan WhatsApp OTOMATIS via Fonnte."""
    d = request.get_json() or {}
    kind = text(d.get("kind", "nota"), 20)
    require(kind in ("nota", "tracking", "progres"), "Jenis pesan tidak valid.")
    
    with connect() as c:
        o = load_order(c, ident)
        require(o is not None, "Pesanan tidak ditemukan.")
        s = settings(c)
        
    urls = order_urls(o["id"], o["number"], o["tracking_token"])
    usaha = s.get("name") or "Rofi Jaya"
    
    # Susun pesan
    if kind == "nota":
        msg = (
            f"Halo {o['customer']}, berikut Nota Pesanan dari {usaha}.\n\n"
            f"Nomor Nota: {o['number']}\n"
            f"Total Pesanan: {format_rupiah(o['total'])}\n"
            f"Sisa Pembayaran: {format_rupiah(o['remaining'])}\n"
            f"Estimasi Selesai: {o['target']}\n\n"
            f"Nota digital:\n{urls['nota']}\n\n"
            f"Terima kasih."
        )
    elif kind == "tracking":
        msg = (
            f"Halo {o['customer']}, pesanan Anda di {usaha}.\n\n"
            f"Pantau progres produksi kapan saja melalui link berikut:\n"
            f"{urls['tracking']}\n\n"
            f"Terima kasih."
        )
    else:
        done = [x["label"] for x in o["stages"] if x["state"] == "done"]
        msg = (
            f"Halo {o['customer']}, berikut progres pesanan {o['number']} di {usaha}.\n\n"
            f"Status: {o['status']}\n"
            f"Sudah selesai: {', '.join(done) or 'belum ada'}\n"
            f"Sisa pembayaran: {format_rupiah(o['remaining'])}\n\n"
            f"Pantau progres: {urls['tracking']}\n\n"
            f"Terima kasih."
        )
        
    extra = text(d.get("extra", ""), 2000)
    if extra:
        msg += "\n\n" + extra
        
    # Kirim via Fonnte
    ok, pesan = fonnte_send(o["wa"], msg)
    
    if not ok:
        return jsonify(error=f"Gagal kirim WA: {pesan}"), 500
        
    return jsonify(ok=True, message="Pesan berhasil dikirim via Fonnte.")


def _upload_photo_internal(ident, stage, caption, image_data):
    """Upload foto base64 ke ImageKit lalu simpan remote_url (dipakai route & bot)."""
    import os
    ik_private = os.getenv("IMAGEKIT_PRIVATE_KEY", "").strip()
    ik_endpoint = os.getenv("IMAGEKIT_URL_ENDPOINT", "").strip().rstrip("/")
    require(ik_private and ik_endpoint, "Konfigurasi ImageKit belum diset di .env.")
    require(image_data.startswith("data:image/"), "Format foto tidak valid.")
    header, b64_str = image_data.split(",", 1)
    raw_img = base64.b64decode(b64_str)
    require(len(raw_img) <= 5 * 1024 * 1024, "Foto maksimal 5MB.")
    import uuid as _uuid
    file_name = f"progres_{ident}_{stage}_{_uuid.uuid4().hex[:8]}.jpg"
    boundary = "----WebKitFormBoundary" + _uuid.uuid4().hex
    body = []
    body.append(f"--{boundary}".encode())
    body.append(f'Content-Disposition: form-data; name="file"; filename="{file_name}"'.encode())
    body.append(b"Content-Type: image/jpeg\r\n")
    body.append(raw_img)
    body.append(f"--{boundary}".encode())
    body.append(b'Content-Disposition: form-data; name="fileName"\r\n')
    body.append(file_name.encode())
    body.append(f"--{boundary}--".encode())
    payload = b"\r\n".join(body)
    req = urllib.request.Request("https://upload.imagekit.io/api/v1/files/upload", data=payload)
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{ik_private}:".encode()).decode())
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            res_data = _json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode()
        raise ValidationError(f"Gagal upload ke ImageKit: {err_msg}")
    public_url = res_data.get("url")
    require(public_url, "ImageKit tidak mengembalikan URL.")
    photo_id = _uuid.uuid4().hex
    with connect() as c:
        o = load_order(c, ident)
        require(o is not None, "Pesanan tidak ditemukan.")
        c.execute(
            "INSERT INTO photos(id, order_id, stage, caption, uploaded, mime, data, remote_url, remote_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (photo_id, ident, stage, caption, now(), "image/jpeg", b"", public_url, res_data.get("fileId", ""))
        )
        _log(c, ident, f"Foto {stage} diunggah", {"url": public_url}, visible=True)
        _bump(c, ident)
    return public_url


@app.post("/api/v2/orders/<ident>/upload-photo")
@authenticated
def v2_upload_photo(ident):
    """Upload foto ke ImageKit, simpan URL ke database."""
    d = request.get_json() or {}
    stage = text(d.get("stage", ""), 50)
    caption = text(d.get("caption", ""), 200)
    image_data = d.get("data", "")  # format: "data:image/jpeg;base64,..."
    require(stage in ["potong", "jahit", "finishing", "serah", "umum"], "Tahap tidak valid.")
    require(image_data.startswith("data:image/"), "Format foto tidak valid.")
    public_url = _upload_photo_internal(ident, stage, caption, image_data)
    return jsonify(ok=True, url=public_url)


# -------------------------- Boot v2 --------------------------
# Migrasi dijalankan sekali saat modul dimuat agar tabel baru tersedia
# sebelum route mana pun melayani permintaan. Kalau database belum
# dikonfigurasi, migrasi dilewati dan error baru muncul saat dipakai.
def _boot_migrate():
    """Migrasi + backfill. Dijalankan lagi pada permintaan pertama.

    Saat modul diimpor, tabel dasar (`orders`) mungkin belum dibuat
    karena `initialize()` baru dipanggil di __main__. Kegagalan pertama
    diabaikan diam-diam; hasil sebenarnya dilaporkan saat server siap.
    """
    global v2_ready
    migrate_v2()
    v2_ready = True


v2_ready = False
try:
    migrate_v2()
    v2_ready = True
except Exception:  # noqa: BLE001  (tabel dasar belum ada)
    pass


@app.before_request
def _ensure_v2_schema():
    if not v2_ready:
        _boot_migrate()