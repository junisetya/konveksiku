# -*- coding: utf-8 -*-
"""Bot Telegram (menu tombol) untuk Rofi Konveksi.

Desain:
- Semua perintah memakai TOMBOL inline (bukan ketik /...).
- Nota: cukup 1 baris isian, lalu ada tombol Cek Ulang / Kirim / Batal.
- Tahap & Foto: pemilihan via tombol; hanya data isian (catatan/foto/
  nomor pesanan manual) yang diketik.

Modul memakai fungsi internal rofi_api_v2 (buat pesanan, tahap, upload
ImageKit). Webhook didaftarkan lewat setup(app).
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date as _date_today
from datetime import timedelta as _timedelta

from app import (
    connect, settings, normalize_wa, format_rupiah,
    fonnte_send, fonnte_device, ValidationError,
)
from rofi_api_v2 import (
    _validate_order_payload,
    _create_order_internal,
    _stage_action_internal,
    _upload_photo_internal,
    _checklist_toggle_internal,
    order_urls,
    STAGE_KEYS,
    STAGE_LABELS,
)

# ---------------------------------------------------------------------------
# Konfigurasi & helper Telegram
# ---------------------------------------------------------------------------

def _env(name, default=""):
    return os.getenv(name, default).strip()

TOKEN = _env("TELEGRAM_TOKEN")
API_BASE = _env("TELEGRAM_API_BASE", "https://api.telegram.org")
ALLOWED = {x.strip() for x in _env("TELEGRAM_ALLOWED_IDS").split(",") if x.strip()}
WEBHOOK_SECRET = _env("TELEGRAM_WEBHOOK_SECRET")

WIZARD_TTL = 60 * 30  # 30 menit
MAX_ORDERS_MENU = 8


def _telegram(method, payload=None):
    if not TOKEN:
        return {"ok": False, "description": "TELEGRAM_TOKEN belum diset."}
    url = f"{API_BASE}/bot{TOKEN}/{method}"
    req = urllib.request.Request(url, data=json.dumps(payload or {}).encode(),
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "description": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "description": str(e)}


def send_message(chat_id, text, keyboard=None):
    if not text:
        return
    payload = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    _telegram("sendMessage", payload)


def _order_by_number(number):
    with connect() as c:
        row = c.execute(
            "SELECT id, number, tracking_token FROM orders WHERE number=%s",
            (number.strip(),),
        ).fetchone()
        return dict(row) if row else None


def _stage_label(key):
    return STAGE_LABELS.get(key, key)


# ---------------------------------------------------------------------------
# Keyboard (tombol)
# ---------------------------------------------------------------------------

def main_menu_keyboard():
    return [
        [{"text": "📝 Nota", "callback_data": "nota"},
         {"text": "🔄 Tahap", "callback_data": "tahap"}],
        [{"text": "📷 Foto", "callback_data": "foto"},
         {"text": "ℹ️ Status", "callback_data": "status"}],
        [{"text": "❓ Bantuan", "callback_data": "bantuan"},
         {"text": "🚫 Batal", "callback_data": "batal"}],
    ]


def _tahap_act_keyboard():
    return [
        [{"text": "▶️ Mulai", "callback_data": "tahap_mulai"},
         {"text": "✅ Selesai", "callback_data": "tahap_selesai"}],
        [{"text": "📝 Catatan", "callback_data": "tahap_catatan"},
         {"text": "↩️ Ulang", "callback_data": "tahap_ulang"}],
        [{"text": "🏠 Menu", "callback_data": "menu"}],
    ]


def _stage_keyboard(prefix, extra_back="tahap"):
    rows = [
        [{"text": "✂️ Potong", "callback_data": prefix + "_potong"},
         {"text": "🧵 Jahit", "callback_data": prefix + "_jahit"}],
        [{"text": "🎨 Finishing", "callback_data": prefix + "_finishing"},
         {"text": "📦 Serah", "callback_data": prefix + "_serah"}],
    ]
    if prefix == "foto":
        rows.append([{"text": "🟰 Umum", "callback_data": "foto_umum"}])
    rows.append([{"text": "↩️ Kembali", "callback_data": extra_back}])
    return rows


def _orders_keyboard(orders, back="menu"):
    rows = []
    for i in range(0, len(orders), 2):
        row = [{"text": o, "callback_data": "order_" + o} for o in orders[i:i + 2]]
        rows.append(row)
    rows.append([{"text": "⌨️ Ketik nomor", "callback_data": "order_manual"}])
    rows.append([{"text": "↩️ Kembali", "callback_data": back}])
    return rows


def _nota_confirm_keyboard():
    return [
        [{"text": "✅ Kirim Nota", "callback_data": "kirim_nota"}],
        [{"text": "✏️ Perbaiki", "callback_data": "perbaiki_nota"},
         {"text": "🚫 Batal", "callback_data": "batal"}],
    ]


def _recent_orders(limit=MAX_ORDERS_MENU):
    with connect() as c:
        rows = c.execute(
            "SELECT number FROM orders ORDER BY number DESC LIMIT "
            + str(int(limit))).fetchall()
    return [r["number"] for r in rows]


def _checklist_items(order_id):
    with connect() as c:
        rows = c.execute(
            "SELECT id, label, done FROM production_checklist_items "
            "WHERE order_id=%s ORDER BY position", (order_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def _checklist_keyboard(items):
    rows = []
    for it in items:
        mark = "☑️" if it["done"] else "⬜️"
        rows.append([{"text": f"{mark} {it['label']}",
                     "callback_data": "cl_toggle_" + it["id"]}])
    rows.append([{"text": "✅ Selesaikan Finishing", "callback_data": "cl_finish"}])
    rows.append([{"text": "🏠 Menu", "callback_data": "menu"}])
    return rows


def _start_checklist(chat_id, number):
    order = _order_by_number(number)
    if not order:
        return f"❌ Pesanan {number} tidak ditemukan.", _menu_kb()
    _set_state(chat_id, "checklist",
               {"number": number, "order_id": order["id"]})
    items = _checklist_items(order["id"])
    return "✅ Finishing — centang checklist:", _checklist_keyboard(items)


# ---------------------------------------------------------------------------
# State wizard (memori, TTL)
# ---------------------------------------------------------------------------

WIZARD = {}


def _state(chat_id):
    st = WIZARD.get(chat_id)
    if not st:
        return None
    if st.get("expires", 0) < time.time():
        WIZARD.pop(chat_id, None)
        return None
    return st


def _set_state(chat_id, flow, data=None):
    WIZARD[chat_id] = {
        "flow": flow, "data": data or {}, "expires": time.time() + WIZARD_TTL,
    }


def _clear_state(chat_id):
    WIZARD.pop(chat_id, None)


# ---------------------------------------------------------------------------
# Nota — satu baris isian + konfirmasi tombol
# ---------------------------------------------------------------------------

NOTA_HELP = (
    "📝 KIRIM 1 PESAN berisi data nota, format:\n"
    "nama=…; wa=…; model=…; harga=…; ukuran=M=4,L=6; dp=…\n\n"
    "Contoh:\n"
    "nama=Budi Santoso; wa=081234567890; model=Batik; "
    "ukuran=M=4,L=6; harga=175000; dp=300000\n\n"
    "Opsional: company=…; alamat=…; bahan=…; warna=…; desain=…; "
    "qty=…; target=YYYY-MM-DD; metode=…\n"
    "Kalau tanpa ukuran, isi qty=… (default 1)."
)


def _parse_sizes(raw):
    """'M=4,L=6' -> [{'label':'M','qty':4}, ...]; kosong -> []."""
    if raw.strip() in ("", "-"):
        return []
    out = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^\s*([A-Za-z0-9]+)\s*=\s*(\d+)\s*$", part)
        if not m:
            raise ValidationError(f"Format ukuran salah: '{part}' (contoh M=4,L=6)")
        out.append({"label": m.group(1).upper(), "qty": int(m.group(2))})
    return out


def _to_int(value, label):
    """Ambil angka dari input (toleransi 175.000 / 175,000)."""
    m = re.search(r"\d+", str(value).replace(".", "").replace(",", ""))
    if not m:
        raise ValidationError(f"{label} harus angka.")
    return int(m.group(0))


def parse_nota_line(text):
    text = text.strip()
    if text.lower().startswith("/nota"):
        text = text[len("/nota"):].strip()
    if not text:
        raise ValidationError("Isian nota kosong.")
    raw = {}
    for part in text.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            raw[k.strip().lower()] = v.strip()
        else:
            raise ValidationError(
                f"Bagian '{part}' harus berbentuk kunci=nilai (mis. nama=Budi).")

    missing = []
    for k, label in (("nama", "nama"), ("wa", "wa"), ("model", "model"),
                     ("harga", "harga")):
        if not raw.get(k):
            missing.append(label)
    if missing:
        raise ValidationError("Kurang: " + ", ".join(missing) + ".")

    customer = raw["nama"]
    wa = normalize_wa(raw["wa"])
    garment = raw["model"]
    price = _to_int(raw["harga"], "Harga")
    sizes = _parse_sizes(raw.get("ukuran", "") or raw.get("sizes", ""))
    qty = _to_int(raw.get("qty") or "0", "Jumlah") if raw.get("qty") else 0
    total_sizes = sum(s["qty"] for s in sizes)
    if sizes and not qty:
        qty = total_sizes
    if not qty:
        qty = 1
    if sizes and total_sizes != qty:
        raise ValidationError(
            f"Total ukuran ({total_sizes}) tidak sama dengan qty ({qty}).")
    if qty > 1000000 or price > 10**11:
        raise ValidationError("Nilai qty/harga di luar batas.")

    today = _date_today.today()
    deal = raw.get("deal") or today.isoformat()
    target = raw.get("target") or (today + _timedelta(days=14)).isoformat()
    dp = _to_int(raw.get("dp") or "0", "DP") if raw.get("dp") else 0
    return {
        "customer": customer, "wa": wa,
        "company": raw.get("company", ""),
        "address": raw.get("alamat", ""),
        "garment": garment, "qty": qty, "price": price, "sizes": sizes,
        "material": raw.get("bahan", ""),
        "color": raw.get("warna", ""),
        "design": raw.get("desain", ""),
        "deal": deal, "target": target,
        "target_payment": raw.get("targetpembayaran", ""),
        "dp": dp, "dp_method": raw.get("metode", "Tunai"),
        "agreement_note": raw.get("catatan", ""),
    }


def _draft_payload(d):
    return {
        "customer": d["customer"], "wa": d["wa"],
        "company": d["company"], "address": d["address"],
        "deal": d["deal"], "target": d["target"],
        "target_payment": d["target_payment"],
        "work_start": "", "customer_note": "",
        "agreement_note": d["agreement_note"],
        "dp": d["dp"], "dp_method": d["dp_method"],
        "dp_date": d["deal"], "dp_note": "",
        "discount": 0, "extra": 0,
        "items": [{
            "garment": d["garment"], "name": d["garment"],
            "qty": d["qty"], "price": d["price"],
            "sizes": d["sizes"], "material": d["material"],
            "color": d["color"], "design": d["design"],
            "printing": "", "note": "",
        }],
    }


def _nota_summary(d):
    total = d["price"] * d["qty"]
    dp = d["dp"]
    sizes = ", ".join(f"{s['label']}={s['qty']}" for s in d["sizes"]) or "—"
    lines = [
        "📋 CEK ULANG NOTA:",
        f"• Konsumen: {d['customer']}",
        f"• WA: {d['wa']}",
        f"• Model: {d['garment']} ({d['qty']} pcs)",
        f"• Ukuran: {sizes}",
        f"• Harga/pcs: {format_rupiah(d['price'])}",
        f"• Total: {format_rupiah(total)}",
        f"• DP: {format_rupiah(dp)} · Sisa: {format_rupiah(total - dp)}",
        f"• Deal: {d['deal']} · Target: {d['target']}",
    ]
    if d.get("company"):
        lines.append(f"• Instansi: {d['company']}")
    if d.get("address"):
        lines.append(f"• Alamat: {d['address']}")
    return "\n".join(lines)


def _confirm_nota_draft(chat_id, d):
    try:
        valid = _validate_order_payload(_draft_payload(d))
    except ValidationError as e:
        return f"❌ Data tidak valid: {e}", _nota_confirm_keyboard()
    with connect() as c:
        s = settings(c)
        ident, number, token = _create_order_internal(c, valid)
    urls = order_urls(ident, number, token)
    usaha = s.get("name") or "Rofi Jaya"
    msg = (
        f"Halo {valid['customer']}, berikut Nota Pesanan dari {usaha}.\n\n"
        f"Nomor Nota: {number}\n"
        f"Total Pesanan: {format_rupiah(valid['total'])}\n"
        f"Sisa Pembayaran: {format_rupiah(valid['total'] - valid['dp'])}\n"
        f"Estimasi Selesai: {valid['target']}\n\n"
        f"Nota digital:\n{urls['nota']}\n\n"
        "Terima kasih."
    )
    ok, pesan = fonnte_send(valid["wa"], msg)
    wa_line = (f"✅ WhatsApp terkirim ke {valid['wa']}."
               if ok else f"⚠️ WhatsApp GAGAL: {pesan}")
    return (
        f"✅ Nota {number} dibuat.\n"
        f"• Nota : {urls['nota']}\n"
        f"• Tracking : {urls['tracking']}\n"
        f"• {wa_line}"
    ), main_menu_keyboard()


# ---------------------------------------------------------------------------
# Tahap & Foto (pilih via tombol)
# ---------------------------------------------------------------------------

ACTION_LABEL = {"start": "dimulai", "finish": "diselesaikan",
                "note": "dicatat", "reopen": "dibuka ulang"}


def execute_stage(chat_id, number, act, stage):
    act = {"mulai": "start", "selesai": "finish",
           "catatan": "note", "ulang": "reopen"}.get(act, act)
    order = _order_by_number(number)
    if not order:
        return f"❌ Pesanan {number} tidak ditemukan.", _menu_kb()
    if act == "start":
        d = {"action": "start", "stage": stage,
             "start": _date_today.today().isoformat(), "note": ""}
    elif act == "finish":
        d = {"action": "finish", "stage": stage}
    elif act == "note":
        d = {"action": "note", "stage": stage, "note": ""}
    else:
        d = {"action": "reopen", "stage": stage,
             "reason": "Dibuka ulang lewat Telegram"}
    try:
        with connect() as c:
            _stage_action_internal(c, order["id"], d)
    except ValidationError as e:
        return f"❌ {e}", _menu_kb()
    urls = order_urls(order["id"], order["number"], order["tracking_token"])
    label = ACTION_LABEL.get(act, act)
    return (
        f"✅ Tahap {_stage_label(stage)} {label} untuk {order['number']}.\n"
        f"• Tracking : {urls['tracking']}"
    ), _menu_kb()


def upload_photo(chat_id, msg, order_number, stage):
    order = _order_by_number(order_number)
    if not order:
        return "❌ Pesanan tidak ditemukan.", _menu_kb()
    photos = msg.get("photo") or []
    if not photos:
        return "Kirim foto (format foto Telegram).", None
    file_id = photos[-1]["file_id"]
    info = _telegram("getFile", {"file_id": file_id})
    file_path = (info.get("result") or {}).get("file_path")
    if not file_path:
        return "❌ Gagal mengambil file foto dari Telegram.", _menu_kb()
    file_path = str(file_path).lstrip("/")
    quoted = urllib.parse.quote(file_path, safe="/")
    candidates = [f"{API_BASE}/bot{TOKEN}/" + quoted,
                  "https://api.telegram.org/file/bot" + TOKEN + "/" + quoted]
    raw = None
    last_err = None
    for attempt in range(2):
        for url in candidates:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "RofiBot/1.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read()
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:140]
                last_err = f"HTTP {e.code}: {detail}"
                time.sleep(0.8)
            except Exception as e:  # noqa: BLE001
                last_err = str(e)
                break
        if raw is not None:
            break
    if raw is None:
        return (f"❌ Gagal mengunduh foto ({last_err}).\n"
                f"file: {file_path}\nCoba kirim ulang foto."), _menu_kb()
    if len(raw) > 5 * 1024 * 1024:
        return "❌ Foto maksimal 5MB.", _menu_kb()
    data_uri = "data:image/jpeg;base64," + base64.b64encode(raw).decode()
    caption = (msg.get("caption") or "").strip()[:200]
    try:
        url_ik = _upload_photo_internal(order["id"], stage, caption, data_uri)
    except ValidationError as e:
        return f"❌ {e}", _menu_kb()
    urls = order_urls(order["id"], order["number"], order["tracking_token"])
    return (
        f"✅ Foto {_stage_label(stage)} diunggah untuk {order['number']}.\n"
        f"• Foto : {url_ik}\n"
        f"• Tracking : {urls['tracking']}"
    ), _menu_kb()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def _status():
    info, pesan = fonnte_device()
    lines = []
    if info is None:
        lines.append(f"Fonnte: {pesan}")
    else:
        lines.append(f"Device Fonnte: {info.get('device')} ({info.get('name')})")
        lines.append("Status: " + ("terhubung" if info.get("device_status") == "connect" else "terputus"))
        lines.append(f"Paket: {info.get('package')} · Kuota: {info.get('quota')} · "
                     f"Berlaku: {info.get('expired')}")
    with connect() as c:
        total = c.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
    lines.append(f"Total pesanan tersimpan: {total}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Router callback (tombol)
# ---------------------------------------------------------------------------

def _menu_kb():
    return main_menu_keyboard()


HELP = (
    "🤖 Rofi Konveksi — Bot Telegram\n"
    "Semua aksi memakai TOMBOL di bawah, atau ketik perintah /…\n"
    "📝 Nota — 1 baris isian + cek ulang sebelum kirim\n"
    "🔄 Tahap — mulai/selesai/catatan/ulang via tombol\n"
    "📷 Foto — upload foto ke ImageKit via tombol\n"
    "ℹ️ Status — status Fonnte & pesanan\n"
    "🚫 Batal — batalkan proses yang berjalan"
)


def _handle_callback(chat_id, data):
    st = _state(chat_id)
    if data == "menu":
        _set_state(chat_id, "idle")
        return "🏠 Menu utama:", _menu_kb()
    if data == "bantuan":
        return HELP, _menu_kb()
    if data == "batal":
        _clear_state(chat_id)
        return "Wizard dibatalkan.", _menu_kb()
    if data == "status":
        return _status(), _menu_kb()
    if data == "nota":
        _set_state(chat_id, "nota_draft", {"draft": None})
        return NOTA_HELP, None
    if data == "tahap":
        _set_state(chat_id, "tahap_act")
        return "Pilih aksi tahap:", _tahap_act_keyboard()
    if data == "foto":
        _set_state(chat_id, "foto_stage")
        return "Foto untuk tahap mana?", _stage_keyboard("foto")

    if data.startswith("tahap_"):
        key = data.split("_", 1)[1]
        if key in ("mulai", "selesai", "catatan", "ulang"):
            _set_state(chat_id, "tahap_stage", {"act": key})
            return "Pilih tahap:", _stage_keyboard("tahap")
        if key in STAGE_KEYS and st and st.get("flow") == "tahap_stage":
            act = st.get("data", {}).get("act")
            _set_state(chat_id, "order_pick",
                       {"kind": "tahap", "act": act, "stage": key})
            orders = _recent_orders()
            if orders:
                return "Pilih pesanan:", _orders_keyboard(orders)
            return "Belum ada pesanan. Ketik nomor pesanan:", None

    if data.startswith("foto_"):
        stage = data.split("_", 1)[1]
        if stage in STAGE_KEYS or stage == "umum":
            _set_state(chat_id, "order_pick", {"kind": "foto", "stage": stage})
            orders = _recent_orders()
            if orders:
                return "Pilih pesanan:", _orders_keyboard(orders)
            return "Belum ada pesanan. Ketik nomor pesanan:", None

    if data == "kirim_nota":
        if (not st or st.get("flow") != "nota_draft"
                or not st.get("data", {}).get("draft")):
            return "Tidak ada draft nota. Klik 📝 Nota dulu.", _menu_kb()
        text, kb = _confirm_nota_draft(chat_id, st["data"]["draft"])
        _clear_state(chat_id)
        return text, kb

    if data == "perbaiki_nota":
        _set_state(chat_id, "nota_draft", {"draft": None})
        return "✏️ Kirim ulang isian nota:\n\n" + NOTA_HELP, None

    if data == "order_manual":
        if not st:
            return "Sesi kedaluwarsa. Mulai dari menu.", _menu_kb()
        _set_state(chat_id, "order_manual", st.get("data", {}))
        return "Ketik nomor pesanan (contoh KVK-202610-0003):", None

    if data.startswith("order_"):
        number = data[len("order_"):]
        meta = st.get("data", {}) if st else {}
        kind = meta.get("kind")
        if not kind:
            return "Sesi kedaluwarsa. Mulai dari menu.", _menu_kb()
        if kind == "tahap":
            act = meta.get("act")
            stage = meta.get("stage")
            if act == "catatan":
                _set_state(chat_id, "tahap_catatan",
                           {"number": number, "stage": stage})
                return ("📝 Ketik catatan untuk tahap "
                        + _stage_label(stage) + ":", None)
            if act == "selesai" and stage == "finishing":
                return _start_checklist(chat_id, number)
            return execute_stage(chat_id, number, act, stage)
        _set_state(chat_id, "foto_wait",
                   {"number": number, "stage": meta.get("stage")})
        return "📷 Kirim foto sekarang (maks 5MB):", None

    if data.startswith("cl_toggle_"):
        item = data[len("cl_toggle_"):]
        if not st or st.get("flow") != "checklist":
            return "Sesi checklist kedaluwarsa.", _menu_kb()
        order_id = st["data"].get("order_id")
        try:
            with connect() as c:
                _checklist_toggle_internal(c, order_id, item)
        except ValidationError as e:
            return f"❌ {e}", _menu_kb()
        items = _checklist_items(order_id)
        return "Checklist finishing diperbarui:", _checklist_keyboard(items)

    if data == "cl_finish":
        if not st or st.get("flow") != "checklist":
            return "Sesi checklist kedaluwarsa.", _menu_kb()
        order_id = st["data"].get("order_id")
        items = _checklist_items(order_id)
        pending = [it["label"] for it in items if not it["done"]]
        if pending:
            return ("❌ Checklist belum lengkap: " + "; ".join(pending),
                    _checklist_keyboard(items))
        text, kb = execute_stage(chat_id, st["data"].get("number", ""),
                                 "selesai", "finishing")
        _clear_state(chat_id)
        return text, kb

    return "Tombol tidak dikenal.", _menu_kb()


# ---------------------------------------------------------------------------
# Dispatcher update (pesan & callback)
# ---------------------------------------------------------------------------

def handle_update(update):
    out = []
    base = update or {}

    cbq = base.get("callback_query")
    if cbq:
        chat_id = cbq.get("message", {}).get("chat", {}).get("id")
        if chat_id is None or str(chat_id) not in ALLOWED:
            return []
        _telegram("answerCallbackQuery", {"callback_query_id": cbq.get("id")})
        res = _handle_callback(chat_id, str(cbq.get("data") or ""))
        if res:
            out.append((chat_id, res[0], res[1]))
        return out

    msg = base.get("message")
    if not msg:
        return []
    chat_id = msg.get("chat", {}).get("id")
    if chat_id is None or str(chat_id) not in ALLOWED:
        return []
    text = (msg.get("text") or "").strip()
    st = _state(chat_id)

    # Input foto (flow foto_wait)
    if st and st.get("flow") == "foto_wait" and msg.get("photo"):
        text_r, kb = upload_photo(
            chat_id, msg, st["data"].get("number", ""), st["data"].get("stage", ""))
        _clear_state(chat_id)
        return [(chat_id, text_r, kb)]

    # Nota: satu baris isian (auto-detect juga walau belum klik Nota)
    nota_auto = (not st and "nama=" in text and "wa=" in text
                 and "model=" in text)
    if text and ((st and st.get("flow") == "nota_draft") or nota_auto):
        try:
            draft = parse_nota_line(text)
            _validate_order_payload(_draft_payload(draft))
        except (ValidationError, ValueError, TypeError) as e:
            return [(chat_id, f"❌ {e}\n\n{NOTA_HELP}", None)]
        if st is None:
            _set_state(chat_id, "nota_draft", {"draft": draft})
        else:
            st["data"]["draft"] = draft
        return [(chat_id, _nota_summary(draft), _nota_confirm_keyboard())]

    # Ketik nomor pesanan manual
    if st and st.get("flow") == "order_manual" and text:
        meta = st.get("data", {})
        kind = meta.get("kind")
        if kind == "tahap":
            act = meta.get("act")
            stage = meta.get("stage")
            if act == "catatan":
                _set_state(chat_id, "tahap_catatan",
                           {"number": text.strip(), "stage": stage})
                return [(chat_id, "Ketik catatan:", None)]
            if act == "selesai" and stage == "finishing":
                return [(chat_id, *_start_checklist(chat_id, text.strip()))]
            return [(chat_id, *execute_stage(chat_id, text, act, stage))]
        _set_state(chat_id, "foto_wait",
                   {"number": text.strip(), "stage": meta.get("stage")})
        return [(chat_id, "📷 Kirim foto sekarang (maks 5MB):", None)]

    # Catatan tahap (alur tombol)
    if st and st.get("flow") == "tahap_catatan" and text:
        number = st["data"].get("number", "")
        stage = st["data"].get("stage", "")
        order = _order_by_number(number)
        if not order:
            _clear_state(chat_id)
            return [(chat_id, f"❌ Pesanan {number} tidak ditemukan.", _menu_kb())]
        try:
            with connect() as c:
                _stage_action_internal(c, order["id"],
                                       {"action": "note", "stage": stage,
                                        "note": text[:3000]})
        except ValidationError as e:
            _clear_state(chat_id)
            return [(chat_id, f"❌ {e}", _menu_kb())]
        urls = order_urls(order["id"], order["number"], order["tracking_token"])
        _clear_state(chat_id)
        return [(chat_id,
                 f"✅ Catatan tahap {_stage_label(stage)} tersimpan untuk "
                 f"{order['number']}.\n• Tracking : {urls['tracking']}",
                 _menu_kb())]

    if not text:
        return []

    low = text.lower()
    if low in ("/start", "/bantuan"):
        return [(chat_id, HELP, _menu_kb())]
    if low == "/batal":
        _clear_state(chat_id)
        return [(chat_id, "Wizard dibatalkan.", _menu_kb())]
    if low == "/nota":
        _set_state(chat_id, "nota_draft", {"draft": None})
        return [(chat_id, NOTA_HELP, None)]
    if low == "/tahap":
        _set_state(chat_id, "tahap_act")
        return [(chat_id, "Pilih aksi tahap:", _tahap_act_keyboard())]
    if low == "/foto":
        _set_state(chat_id, "foto_stage")
        return [(chat_id, "Foto untuk tahap mana?", _stage_keyboard("foto"))]
    if low == "/status":
        return [(chat_id, _status(), _menu_kb())]
    return [(chat_id, "Perintah tidak dikenal. Gunakan tombol.", _menu_kb())]


# ---------------------------------------------------------------------------
# Route webhook
# ---------------------------------------------------------------------------

def setup(app_obj):
    from flask import request

    @app_obj.post("/telegram/webhook")
    def telegram_webhook():
        if WEBHOOK_SECRET and (
            request.headers.get("X-Telegram-Bot-Api-Secret-Token", "") != WEBHOOK_SECRET
        ):
            return "", 403
        upd = request.get_json(silent=True) or {}
        try:
            for cid, txt, kb in handle_update(upd):
                send_message(cid, txt, keyboard=kb)
        except Exception as exc:  # noqa: BLE001
            app_obj.logger.exception("Telegram webhook error: %s", exc)
        return "ok"
