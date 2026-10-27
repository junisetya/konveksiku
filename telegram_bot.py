# -*- coding: utf-8 -*-
"""Bot Telegram (wizard) untuk Rofi Konveksi.

Modul ini TIDAK mengubah perilaku API yang ada; ia memakai fungsi internal
dari `rofi_api_v2` untuk membuat pesanan, memperbarui tahap, dan upload foto
ke ImageKit. Route webhook didaftarkan lewat `setup(app)`.

Keamanan:
- Hanya `chat_id` dalam TELEGRAM_ALLOWED_IDS yang dilayani.
- Opsional header `X-Telegram-Bot-Api-Secret-Token` dicocokkan dengan
  TELEGRAM_WEBHOOK_SECRET (diset saat setWebhook).
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date as _date_today

from app import (
    connect, settings, normalize_wa, format_rupiah,
    fonnte_send, fonnte_device, ValidationError,
)
from rofi_api_v2 import (
    _validate_order_payload,
    _create_order_internal,
    _stage_action_internal,
    _upload_photo_internal,
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

WIZARD_TTL = 60 * 15  # 15 menit


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


def send_message(chat_id, text):
    if text:
        _telegram("sendMessage", {"chat_id": chat_id, "text": text})


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
# State wizard (dalam memori, ber-TTL)
# ---------------------------------------------------------------------------

WIZARD = {}


def _now():
    return time.time()


def _state(chat_id):
    st = WIZARD.get(chat_id)
    if not st:
        return None
    if st.get("expires", 0) < _now():
        WIZARD.pop(chat_id, None)
        return None
    return st


def _set_state(chat_id, flow, step=0, data=None, items=None, cur=None,
               waiting=None):
    WIZARD[chat_id] = {
        "flow": flow, "step": step, "data": data or {},
        "items": items or [], "cur": cur or {}, "waiting": waiting,
        "expires": _now() + WIZARD_TTL,
    }


def _clear_state(chat_id):
    WIZARD.pop(chat_id, None)


# ---------------------------------------------------------------------------
# Wizard buat nota
# ---------------------------------------------------------------------------

NOTA_PROMPTS = {
    "customer": "1/19 · Siapa nama konsumen?",
    "wa": "2/19 · Nomor WhatsApp konsumen? (mis. 081234567890)",
    "company": "3/19 · Instansi/perusahaan? (ketik - jika kosong)",
    "address": "4/19 · Alamat / catatan pengiriman? (-)",
    "item_garment": "5/19 · Model pakaian item ke-{n}?",
    "item_qty": "6/19 · Jumlah pcs untuk item ke-{n}?",
    "item_price": "7/19 · Harga per pcs (Rp)?",
    "item_sizes": "8/19 · Ukuran (format M=4, L=6) atau - ?",
    "item_material": "9/19 · Bahan? (-)",
    "item_color": "10/19 · Warna? (-)",
    "item_design": "11/19 · Spesifikasi/desain? (-)",
    "more_items": "12/19 · Tambah item lagi? (ya/tidak)",
    "dp": "13/19 · DP diterima (Rp)? (0 jika belum)",
    "dp_method": "14/19 · Metode DP? (default Tunai)",
    "deal": "15/19 · Tanggal kesepakatan? (default hari ini)",
    "target": "16/19 · Estimasi selesai (YYYY-MM-DD)?",
    "target_payment": "17/19 · Target pelunasan? (-)",
    "agreement_note": "18/19 · Catatan kesepakatan (tampil di nota)? (-)",
    "confirm": "19/19 · Konfirmasi (ya / ulangi / batal)",
}


def _parse_sizes(raw):
    """'M=4,L=6' -> [{'label':'M','qty':4}, ...]; '-' -> []."""
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


def _date_or_today(raw):
    raw = raw.strip()
    if raw in ("", "-"):
        raw = _date_today.today().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise ValidationError("Tanggal harus berformat YYYY-MM-DD")
    return raw


def _nota_prompt(key, item_number=1):
    tpl = NOTA_PROMPTS.get(key, "")
    return tpl.format(n=item_number) if "{n}" in tpl else tpl


def _confirm_nota(chat_id, data, items):
    payload = {
        "customer": data.get("customer", ""),
        "wa": data.get("wa", ""),
        "company": data.get("company", ""),
        "address": data.get("address", ""),
        "deal": data.get("deal", ""),
        "target": data.get("target", ""),
        "target_payment": data.get("target_payment", ""),
        "work_start": "",
        "customer_note": "",
        "agreement_note": data.get("agreement_note", ""),
        "dp": int(data.get("dp") or 0),
        "dp_method": data.get("dp_method", "Tunai"),
        "dp_date": data.get("deal", ""),
        "dp_note": "",
        "discount": 0,
        "extra": 0,
        "items": items,
    }
    try:
        valid = _validate_order_payload(payload)
    except ValidationError as e:
        _clear_state(chat_id)
        return f"❌ Data tidak valid: {e}\nKetik /nota untuk mengulang."

    with connect() as c:
        s = settings(c)
        ident, number, token = _create_order_internal(c, valid)
    urls = order_urls(ident, number, token)
    usaha = s.get("name") or "Rofi Jaya"
    total = valid["total"]
    remaining = total - valid["dp"]
    msg = (
        f"Halo {valid['customer']}, berikut Nota Pesanan dari {usaha}.\n\n"
        f"Nomor Nota: {number}\n"
        f"Total Pesanan: {format_rupiah(total)}\n"
        f"Sisa Pembayaran: {format_rupiah(remaining)}\n"
        f"Estimasi Selesai: {valid['target']}\n\n"
        f"Nota digital:\n{urls['nota']}\n\n"
        "Terima kasih."
    )
    ok, pesan = fonnte_send(valid["wa"], msg)
    _clear_state(chat_id)
    wa_line = (f"✅ WhatsApp terkirim ke {valid['wa']}."
               if ok else f"⚠️ WhatsApp GAGAL: {pesan}")
    return (
        f"✅ Nota {number} dibuat.\n"
        f"• Nota : {urls['nota']}\n"
        f"• Tracking : {urls['tracking']}\n"
        f"• {wa_line}"
    )


def _handle_nota(chat_id, text):
    st = _state(chat_id)
    step = st["step"]
    data = st["data"]
    items = st["items"]
    cur = st["cur"]

    try:
        if step == 0:
            if not text:
                raise ValidationError("Nama konsumen wajib diisi.")
            data["customer"] = text[:150]
        elif step == 1:
            data["wa"] = normalize_wa(text)
        elif step == 2:
            data["company"] = "" if text == "-" else text[:200]
        elif step == 3:
            data["address"] = "" if text == "-" else text[:1500]
        elif step == 4:
            if not text:
                raise ValidationError("Model pakaian wajib diisi.")
            cur["garment"] = text[:150]
            cur["name"] = text[:150]
        elif step == 5:
            if not re.fullmatch(r"\d+", text):
                raise ValidationError("Jumlah pcs harus angka.")
            cur["qty"] = int(text)
        elif step == 6:
            if not re.fullmatch(r"\d+", text):
                raise ValidationError("Harga harus angka.")
            cur["price"] = int(text)
        elif step == 7:
            cur["sizes"] = _parse_sizes(text)
        elif step == 8:
            cur["material"] = "" if text == "-" else text[:150]
        elif step == 9:
            cur["color"] = "" if text == "-" else text[:100]
        elif step == 10:
            cur["design"] = "" if text == "-" else text[:3000]
        elif step == 11:
            low = text.lower()
            if low not in ("ya", "tidak"):
                raise ValidationError("Jawab: ya / tidak")
            items.append(dict(cur))
            cur.clear()
            if low == "ya":
                _set_state(chat_id, "nota", step=4, data=data,
                           items=items, cur=cur)
                return _nota_prompt("item_garment", len(items) + 1)
        elif step == 12:
            if not re.fullmatch(r"\d+", text):
                raise ValidationError("DP harus angka.")
            data["dp"] = int(text)
        elif step == 13:
            data["dp_method"] = "Tunai" if text == "-" else text[:60]
        elif step == 14:
            data["deal"] = _date_or_today(text)
        elif step == 15:
            t = text.strip()
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
                raise ValidationError("Format tanggal YYYY-MM-DD")
            data["target"] = t
        elif step == 16:
            data["target_payment"] = "" if text == "-" else text.strip()
        elif step == 17:
            data["agreement_note"] = "" if text == "-" else text[:3000]
        elif step == 18:
            low = text.lower()
            if low == "batal":
                _clear_state(chat_id)
                return "Wizard dibatalkan."
            if low == "ulangi":
                _set_state(chat_id, "nota", step=0, data={}, items=[], cur={})
                return _nota_prompt("customer")
            if low != "ya":
                return "Jawab: ya / ulangi / batal"
            return _confirm_nota(chat_id, data, items)
    except ValidationError as e:
        return f"❌ {e}\nCoba lagi."

    st["step"] += 1
    _set_state(chat_id, "nota", step=st["step"], data=data,
               items=items, cur=cur)
    n = len(items) + 1
    key = "confirm" if st["step"] == 18 else (
        "item_garment" if 4 <= st["step"] <= 10 else "?")
    if key == "?":
        keys = ["customer", "wa", "company", "address", "item_garment",
                "item_qty", "item_price", "item_sizes", "item_material",
                "item_color", "item_design", "more_items", "dp", "dp_method",
                "deal", "target", "target_payment", "agreement_note", "confirm"]
        key = keys[st["step"]] if st["step"] < len(keys) else "confirm"
    return _nota_prompt(key, n)


# ---------------------------------------------------------------------------
# Update tahap
# ---------------------------------------------------------------------------

ACTION_ALIAS = {
    "mulai": "start", "selesai": "finish",
    "catatan": "note", "ulang": "reopen",
}


def _run_stage(chat_id, action, key, note):
    st = _state(chat_id)
    number = (st.get("data") or {}).get("number", "")
    order = _order_by_number(number)
    if not order:
        _clear_state(chat_id)
        return f"❌ Pesanan {number or ''} tidak ditemukan."
    oid = order["id"]
    if action == "start":
        d = {"action": "start", "stage": key,
             "start": _date_today.today().isoformat(), "note": note}
    elif action == "finish":
        d = {"action": "finish", "stage": key}
    elif action == "note":
        d = {"action": "note", "stage": key, "note": note}
    else:
        d = {"action": "reopen", "stage": key,
             "reason": note or "Dibuka ulang lewat Telegram"}
    try:
        with connect() as c:
            _stage_action_internal(c, oid, d)
    except ValidationError as e:
        _clear_state(chat_id)
        return f"❌ {e}"
    urls = order_urls(oid, order["number"], order["tracking_token"])
    _clear_state(chat_id)
    action_label = {"start": "dimulai", "finish": "diselesaikan",
                    "note": "dicatat", "reopen": "dibuka ulang"}.get(action, action)
    return (
        f"✅ Tahap {_stage_label(key)} {action_label} untuk {order['number']}.\n"
        f"• Tracking : {urls['tracking']}"
    )


def _handle_tahap(chat_id, text):
    rest = text[len("/tahap"):].strip()
    if not rest:
        _set_state(chat_id, "tahap", waiting="stage_action")
        return ("Kirim: <aksi> <kode tahap> [catatan]\n"
                "Contoh: mulai potong dibuka hari ini\n"
                "Aksi: mulai / selesai / catatan / ulang\n"
                "Kode: " + ", ".join(STAGE_KEYS))
    parts = rest.split(None, 2)
    action = ACTION_ALIAS.get(parts[0])
    if not action:
        return "Aksi tidak dikenal. Gunakan: mulai / selesai / catatan / ulang"
    if len(parts) < 2:
        return "Format: /tahap <aksi> <kode tahap> [catatan]"
    key = parts[1]
    if key not in STAGE_KEYS:
        return f"Kode tahap tidak valid. Pilih: {', '.join(STAGE_KEYS)}"
    note = parts[2] if len(parts) > 2 else ""
    _set_state(chat_id, "tahap", waiting="order_number",
               data={"action": action, "key": key, "note": note})
    return "Nomor pesanan? (contoh KVK-202610-0003)"


# ---------------------------------------------------------------------------
# Upload foto
# ---------------------------------------------------------------------------

def _handle_photo_file(chat_id, msg):
    st = _state(chat_id)
    data = st.get("data") or {}
    order = _order_by_number(data.get("number", ""))
    if not order:
        _clear_state(chat_id)
        return "❌ Pesanan tidak ditemukan. Ulangi /foto"
    photos = msg.get("photo") or []
    if not photos:
        return "Tidak ada foto di pesan ini. Kirim foto."
    file_id = photos[-1]["file_id"]
    info = _telegram("getFile", {"file_id": file_id})
    file_path = (info.get("result") or {}).get("file_path")
    if not file_path:
        _clear_state(chat_id)
        return "❌ Gagal mengambil file foto dari Telegram."
    try:
        url = f"{API_BASE}/bot{TOKEN}/{file_path}"
        with urllib.request.urlopen(url, timeout=30) as resp:
            raw = resp.read()
    except Exception as e:  # noqa: BLE001
        _clear_state(chat_id)
        return f"❌ Gagal mengunduh foto: {e}"
    if len(raw) > 5 * 1024 * 1024:
        _clear_state(chat_id)
        return "❌ Foto maksimal 5MB."
    data_uri = "data:image/jpeg;base64," + base64.b64encode(raw).decode()
    stage = data.get("stage", "")
    caption = (msg.get("caption") or "").strip()[:200]
    try:
        url_ik = _upload_photo_internal(order["id"], stage, caption, data_uri)
    except ValidationError as e:
        _clear_state(chat_id)
        return f"❌ {e}"
    urls = order_urls(order["id"], order["number"], order["tracking_token"])
    _clear_state(chat_id)
    return (
        f"✅ Foto {_stage_label(stage)} diunggah untuk {order['number']}.\n"
        f"• Foto ImageKit : {url_ik}\n"
        f"• Tracking : {urls['tracking']}"
    )


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def _status():
    info, pesan = fonnte_device()
    lines = []
    if info is None:
        lines.append(f"Fonnte: {pesan}")
    else:
        lines.append(f"Device Fonnte: {info.get('device')} "
                     f"({info.get('name')})")
        lines.append("Status: "
                     + ("terhubung" if info.get("device_status") == "connect"
                        else "terputus"))
        lines.append(f"Paket: {info.get('package')} · Kuota: {info.get('quota')} · "
                     f"Berlaku: {info.get('expired')}")
    with connect() as c:
        total = c.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
    lines.append(f"Total pesanan tersimpan: {total}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

HELP = (
    "🤖 Rofi Konveksi — Bot Telegram\n"
    "/nota — wizard buat nota & kirim ke WhatsApp konsumen\n"
    "/tahap <aksi> <kode> [catatan] — mulai/selesai/catatan/ulang\n"
    "/foto — upload foto tahap (ImageKit) → muncul di link tracking\n"
    "/status — status Fonnte & pesanan\n"
    "/batal — batalkan wizard yang berjalan\n"
    "/bantuan — perintah ini"
)


def _handle_waiting(chat_id, text):
    st = _state(chat_id)
    waiting = st.get("waiting")
    if waiting == "stage_action":
        if text.lower() in ("batal", "/batal"):
            _clear_state(chat_id)
            return "Dibatalkan."
        parts = text.split(None, 2)
        action = ACTION_ALIAS.get(parts[0]) if parts else None
        if not action:
            return "Aksi tidak dikenal. Gunakan: mulai / selesai / catatan / ulang"
        if len(parts) < 2 or parts[1] not in STAGE_KEYS:
            return f"Kode tahap tidak valid. Pilih: {', '.join(STAGE_KEYS)}"
        note = parts[2] if len(parts) > 2 else ""
        _set_state(chat_id, "tahap", waiting="order_number",
                   data={"action": action, "key": parts[1], "note": note})
        return "Nomor pesanan? (contoh KVK-202610-0003)"
    if waiting == "order_number":
        st["data"]["number"] = text.strip()
        return _run_stage(chat_id, st["data"]["action"],
                          st["data"]["key"], st["data"].get("note", ""))
    if waiting == "photo_stage":
        key = text.strip()
        if key not in STAGE_KEYS and key != "umum":
            return "Kode tahap tidak valid. Pilih: potong/jahit/finishing/serah/umum"
        _set_state(chat_id, "foto", waiting="photo_order",
                   data={"stage": key})
        return "Nomor pesanan? (contoh KVK-202610-0003)"
    if waiting == "photo_order":
        _set_state(chat_id, "foto", waiting="photo_file",
                   data={"stage": st.get("data", {}).get("stage", ""),
                         "number": text.strip()})
        return "Kirim foto sekarang (maks 5MB)."
    if waiting == "photo_file":
        return "Kirim foto sekarang (maks 5MB)."
    return "Ketik /batal untuk membatalkan."


def handle_update(update):
    msg = (update or {}).get("message")
    if not msg:
        return []
    chat_id = msg.get("chat", {}).get("id")
    if chat_id is None or str(chat_id) not in ALLOWED:
        return []
    text = (msg.get("text") or "").strip()
    st = _state(chat_id)

    if st and st.get("waiting") == "photo_file" and msg.get("photo"):
        return [(chat_id, _handle_photo_file(chat_id, msg))]
    if text.startswith("/"):
        pass  # perintah eksplisit menang atas state apa pun
    elif st and st.get("waiting") and text:
        return [(chat_id, _handle_waiting(chat_id, text))]
    elif st and st.get("flow") == "nota":
        return [(chat_id, _handle_nota(chat_id, text))]

    if not text:
        return [(chat_id, "Silakan kirim perintah. /bantuan")]

    low = text.lower()
    if low in ("/start", "/bantuan"):
        return [(chat_id, HELP)]
    if low == "/nota":
        _set_state(chat_id, "nota", step=0)
        return [(chat_id, _nota_prompt("customer"))]
    if low.startswith("/tahap"):
        return [(chat_id, _handle_tahap(chat_id, text))]
    if low == "/foto":
        _set_state(chat_id, "foto", waiting="photo_stage")
        return [(chat_id, "Untuk tahap mana? (potong/jahit/finishing/serah/umum)")]
    if low == "/status":
        return [(chat_id, _status())]
    if low == "/batal":
        _clear_state(chat_id)
        return [(chat_id, "Wizard dibatalkan.")]
    return [(chat_id, "Perintah tidak dikenal. /bantuan")]


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
            for cid, txt in handle_update(upd):
                send_message(cid, txt)
        except Exception as exc:  # noqa: BLE001
            app_obj.logger.exception("Telegram webhook error: %s", exc)
        return "ok"
