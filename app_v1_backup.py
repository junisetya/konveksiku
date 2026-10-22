import os
import re
import io
import json
import uuid
import base64
import secrets
import psycopg2
import psycopg2.extras
import psycopg2.pool
import threading
import time
import sys
import contextlib
import urllib.request
import urllib.error
import urllib.parse
from html import escape as html_escape
from pathlib import Path
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlparse, parse_qs

from flask import (
    Flask, request, session, jsonify, Response, g,
    send_file
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from PIL import Image, ImageDraw, UnidentifiedImageError

# -------------------------- Konfigurasi --------------------------

def load_env_file(path):
    """Muat KEY=VALUE dari file .env bila ada.

    Nilai yang sudah ada di environment selalu menang, supaya rahasia dari
    `fly secrets` di produksi tidak tertimpa file .env lokal. Baris kosong,
    baris berkomentar (#), dan baris tanpa "=" dilewati.
    """
    try:
        isi = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for baris in isi:
        baris = baris.strip()
        if not baris or baris.startswith("#") or "=" not in baris:
            continue
        nama, nilai = baris.split("=", 1)
        nama = nama.strip()
        if nama and nama not in os.environ:
            os.environ[nama] = nilai.strip().strip('"').strip("'")


load_env_file(Path(__file__).resolve().parent / ".env")

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(mode=0o700, exist_ok=True)
SECRET_FILE = DATA / "session-secret"

# Deteksi lingkungan produksi (Fly.io, Render, Railway, Heroku).
PAAS = any(os.getenv(v) for v in (
    "FLY_APP_NAME", "RENDER_SERVICE_ID", "RAILWAY_ENVIRONMENT",
    "HEROKU_APP_NAME", "DYNO",
))


def truthy(value, default=None):
    """Nilai boolean dari environment. 'auto' dipakai untuk COOKIE_SECURE."""
    if value is None:
        return default
    v = str(value).strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


def secure_cookie_default():
    """Cookie session ditandai Secure bila situs dijalankan via HTTPS."""
    setting = truthy(os.getenv("COOKIE_SECURE"), None)
    if setting is not None:
        return setting
    origin = os.getenv("APP_ORIGIN", "").strip()
    if origin.lower().startswith("https://"):
        return True
    return PAAS


def load_secret_key():
    """Kunci penanda tangan sesi.

    Produksi wajib memakai SECRET_KEY dari environment (rotasi mudah dan
    tidak pernah ikut masuk repository). Lokal boleh memakai file
    data/session-secret yang dibuat otomatis.
    """
    env = os.getenv("SECRET_KEY", "").strip()
    if env:
        if len(env) < 32:
            raise SystemExit(
                "SECRET_KEY terlalu pendek (minimal 32 karakter)."
            )
        return env
    if SECRET_FILE.exists():
        key = SECRET_FILE.read_text().strip()
        if len(key) >= 32:
            if PAAS:
                print("PERINGATAN: SECRET_KEY belum diset. Kunci sesi "
                      "hanya bertahan selama satu siklus container, jadi "
                      "Anda akan diminta login ulang setelah deploy. "
                      "Set SECRET_KEY lewat `fly secrets set`.")
            return key
    key = secrets.token_hex(48)
    SECRET_FILE.write_text(key)
    try:
        SECRET_FILE.chmod(0o600)
    except OSError:
        pass
    print("PERINGATAN: data/session-secret dibuat otomatis. Untuk "
          "produksi, set SECRET_KEY lewat `fly secrets set SECRET_KEY=...`.")
    return key


app = Flask(__name__)
app.secret_key = load_secret_key()
app.config.update(
    MAX_CONTENT_LENGTH=int(os.getenv("MAX_UPLOAD_MB", "9")) * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=secure_cookie_default(),
    SESSION_COOKIE_NAME=os.getenv("SESSION_COOKIE_NAME", "rofi_session"),
    PERMANENT_SESSION_LIFETIME=timedelta(
        hours=int(os.getenv("SESSION_HOURS", "8"))
    ),
)

# Di belakang reverse proxy (Fly.io, Render) alamat skema dan IP asli
# datang lewat header X-Forwarded-*.
if truthy(os.getenv("TRUST_PROXY"), PAAS):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

WIB = timezone(timedelta(hours=7))
QC_ITEMS = [
    "Sisa benang dibersihkan",
    "Kualitas jahitan diperiksa",
    "Ukuran dan model diperiksa",
    "Jumlah setiap ukuran diperiksa",
    "Noda dan kerusakan diperiksa",
    "Pakaian disetrika",
    "Pakaian dilipat",
    "Packing selesai",
]
STAGES = ["Potong Bahan", "Jahit", "Finishing & QC"]
STAGE_TEMPLATE = {"Potong Bahan": "potong", "Jahit": "jahit",
                  "Finishing & QC": "finishing"}
ISSUE_CATEGORIES = [
    "Revisi model", "Perubahan ukuran", "Perubahan jumlah",
    "Kekurangan bahan", "Barang cacat", "Permintaan konsumen", "Lainnya"
]
TEMPLATES = {
    "potong": "Halo Bapak/Ibu {nama}, berikut progres pesanan Anda.\n\n"
              "{ringkasan}\n\nSaat ini proses pemotongan bahan sedang dikerjakan."
              "\n\nTerima kasih atas kepercayaannya kepada {usaha}.",
    "jahit": "Halo Bapak/Ibu {nama}, berikut progres pesanan Anda.\n\n"
             "{ringkasan}\n\nPesanan sedang dalam proses jahit."
             "\n\nTerima kasih atas kepercayaannya kepada {usaha}.",
    "finishing": "Halo Bapak/Ibu {nama}, berikut progres pesanan Anda.\n\n"
                 "{ringkasan}\n\nPesanan sedang melalui finishing dan pemeriksaan kualitas."
                 "\n\nTerima kasih atas kepercayaannya kepada {usaha}.",
    "siap": "Halo Bapak/Ibu {nama}, pesanan Anda telah siap dikirim.\n\n"
            "{ringkasan}\n\nSisa pembayaran: {sisa}."
            "\nMohon konfirmasi pengiriman dan pelunasan sesuai kesepakatan."
            "\n\nTerima kasih.",
    "bayar": "Halo Bapak/Ibu {nama}, kami ingin mengingatkan pembayaran pesanan "
             "{nomor}.\n\nHarga kesepakatan: {total}\nPembayaran diterima: {dibayar}"
             "\nSisa pembayaran: {sisa}\n\nTerima kasih atas kerja samanya.",
    "kirim": "Halo Bapak/Ibu {nama}, berikut informasi pengiriman pesanan "
             "{nomor}.\n\nMetode: {metode}\nKurir: {kurir}\nResi: {resi}"
             "\nTanggal kirim: {tanggal_kirim}\nEstimasi tiba: {tiba}"
             "\n\nTerima kasih.",
    "terima": "Halo Bapak/Ibu {nama}, pesanan {nomor} telah dicatat diterima pada "
              "{diterima}.\n\nTerima kasih telah mempercayakan pesanan kepada "
              "{usaha}. Sisa pembayaran tercatat: {sisa}.",
}
DEFAULT_SETTINGS = {
    "name": "Rofi Jaya",
    "wa": "",
    "address": "",
    "prefix": "KVK",
    "default_days": 14,
    "currency": "IDR",
    "logo": "",
    "auto_notify": True,
    "gallery_link": True,
    "notify_provider": "fonnte",
    "garments": [
        "Baju batik", "Jersey", "Baju koko", "Seragam komunitas",
        "Seragam sekolah", "Seragam kerja", "Kaos", "Kemeja",
        "Jaket", "Celana", "Pakaian custom"
    ],
    "materials": ["Katun", "Katun combed", "Drill", "Dri-fit", "Poliester"],
    "templates": TEMPLATES,
}

def now():
    return datetime.now(WIB).isoformat(timespec="seconds")

def today():
    return datetime.now(WIB).date().isoformat()

# -------------------------- Koneksi Database --------------------------

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

POOL = None
POOL_LOCK = threading.Lock()


def database_config():
    """Opsi koneksi psycopg2 yang aman untuk Supabase/PostgreSQL terkelola."""
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL belum diisi. Set DATABASE_URL "
            "postgres://user:password@host:5432/dbname"
        )
    parsed = urlparse(DATABASE_URL)
    opts = {}
    # Supabase mewajibkan TLS; parameter dari URL tetap dihormati.
    query = parse_qs(parsed.query)
    for key in ("sslmode", "sslrootcert", "sslcert", "sslkey",
                "connect_timeout", "application_name"):
        if query.get(key):
            opts[key] = query[key][0]
    opts.setdefault("sslmode", "require")
    opts.setdefault("connect_timeout", "10")
    opts.setdefault("application_name", "rofi-jaya")
    return opts


def get_pool():
    """Pool koneksi. Dibuat sekali lalu dipakai bersama oleh semua request."""
    global POOL
    if POOL is None:
        with POOL_LOCK:
            if POOL is None:
                POOL = psycopg2.pool.ThreadedConnectionPool(
                    1, int(os.getenv("DB_POOL_MAX", "10")),
                    dsn=DATABASE_URL, **database_config()
                )
    return POOL


class DBWrapper:
    """Pembungkus cursor psycopg2. Koneksi dimiliki pool, bukan wrapper."""

    def __init__(self, conn):
        self.conn = conn
        self.cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    def execute(self, query, params=None):
        self.cursor.execute(query, params)
        return self.cursor
    def executemany(self, query, params):
        self.cursor.executemany(query, params)
    def executescript(self, script):
        self.cursor.execute(script)
    def commit(self):
        self.conn.commit()
    def rollback(self):
        self.conn.rollback()
    def close_cursor(self):
        with contextlib.suppress(Exception):
            self.cursor.close()


@contextlib.contextmanager
def connect():
    """Pinjam satu koneksi dari pool; selalu dikembalikan, even saat error."""
    pool = get_pool()
    conn = pool.getconn()
    wrapper = DBWrapper(conn)
    broken = False
    try:
        try:
            yield wrapper
        except Exception:
            # Rollback dulu; kalau rollback sendiri gagal, koneksi rusak
            # dan tidak boleh dikembalikan ke pool.
            try:
                conn.rollback()
            except Exception:
                broken = True
            raise
        else:
            with contextlib.suppress(Exception):
                conn.commit()
    finally:
        wrapper.close_cursor()
        with contextlib.suppress(Exception):
            pool.putconn(conn, close=broken)


def initialize():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS owner(
            id INTEGER PRIMARY KEY,
            password_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings(
            id INTEGER PRIMARY KEY,
            data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS counters(
            key TEXT PRIMARY KEY,
            value INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS orders(
            id TEXT PRIMARY KEY,
            number TEXT UNIQUE NOT NULL,
            version INTEGER NOT NULL,
            data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS photos(
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL REFERENCES orders(id),
            stage TEXT NOT NULL,
            caption TEXT NOT NULL,
            uploaded TEXT NOT NULL,
            mime TEXT NOT NULL,
            data BYTEA NOT NULL,
            remote_url TEXT NOT NULL DEFAULT '',
            remote_id TEXT NOT NULL DEFAULT ''
        );
        -- Database lama mungkin belum punya kolom ini; tambahkan tanpa
        -- menghapus data yang sudah ada.
        ALTER TABLE photos ADD COLUMN IF NOT EXISTS
            remote_url TEXT NOT NULL DEFAULT '';
        ALTER TABLE photos ADD COLUMN IF NOT EXISTS
            remote_id TEXT NOT NULL DEFAULT '';
        CREATE TABLE IF NOT EXISTS payment_keys(
            order_id TEXT NOT NULL REFERENCES orders(id),
            token TEXT NOT NULL,
            PRIMARY KEY(order_id, token)
        );
    """)
        if not c.execute("SELECT 1 FROM settings").fetchone():
            c.execute("INSERT INTO settings VALUES(1,%s)",
                      (json.dumps(DEFAULT_SETTINGS),))
        if not c.execute("SELECT 1 FROM owner").fetchone():
            password = os.getenv("OWNER_PASSWORD", "")
            if not password:
                if not sys.stdin.isatty():
                    raise SystemExit(
                        "OWNER_PASSWORD belum diisi. Set OWNER_PASSWORD "
                        "minimal 12 karakter (contoh: fly secrets set "
                        "OWNER_PASSWORD=...) sebelum menjalankan aplikasi."
                    )
                import getpass
                print("\nBuat kata sandi owner, minimal 12 karakter.")
                password = getpass.getpass("Kata sandi: ")
                repeat = getpass.getpass("Ulangi kata sandi: ")
                if password != repeat:
                    raise SystemExit("Kata sandi tidak sama.")
            if len(password) < 12:
                raise SystemExit("Kata sandi minimal 12 karakter.")
            c.execute("INSERT INTO owner VALUES(1,%s)",
                      (generate_password_hash(password),))
            print("Kata sandi owner dibuat.")


class ValidationError(Exception):
    pass

def require(condition, message):
    if not condition:
        raise ValidationError(message)

def text(value, limit=2000):
    require(isinstance(value, str), "Format teks tidak valid.")
    value = value.strip()
    require(len(value) <= limit, f"Teks maksimal {limit} karakter.")
    return value

def integer(value, minimum=0, maximum=10**12):
    require(not isinstance(value, bool), "Angka tidak valid.")
    require(re.fullmatch(r"\d+", str(value or "0")) is not None,
            "Gunakan bilangan bulat nonnegatif.")
    n = int(value or 0)
    require(minimum <= n <= maximum, "Angka di luar batas yang diizinkan.")
    return n

def date_value(value, optional=False):
    if optional and not value:
        return ""
    require(isinstance(value, str), "Tanggal tidak valid.")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValidationError("Tanggal harus berformat YYYY-MM-DD.")
    return value

def normalize_wa(value):
    n = re.sub(r"[\s()+.-]", "", text(value, 30))
    if n.startswith("0"):
        n = "62" + n[1:]
    elif n.startswith("8"):
        n = "62" + n
    require(re.fullmatch(r"[1-9]\d{7,14}", n) is not None,
            "Nomor WhatsApp tidak valid. Gunakan 08… atau kode negara.")
    return n

def settings(c):
    """Pengaturan usaha, digabung dengan default agar kunci baru tetap ada."""
    stored = json.loads(c.execute(
        "SELECT data FROM settings WHERE id=1"
    ).fetchone()["data"])
    merged = dict(DEFAULT_SETTINGS)
    merged.update(stored)
    templates = dict(DEFAULT_SETTINGS["templates"])
    templates.update(stored.get("templates") or {})
    merged["templates"] = templates
    return merged

# -------------------------- Galeri & Notifikasi WhatsApp --------------------------

# Token galeri berlaku 90 hari. Foto produksi biasanya dilihat owner
# dan konsumen dalam waktu jauh lebih singkat.
GALLERY_TTL = timedelta(days=int(os.getenv("GALLERY_TTL_DAYS", "90")))
GALLERY_SALT = "rofi-gallery-v1"

gallery_signer = URLSafeTimedSerializer(
    app.secret_key, salt=GALLERY_SALT, signer_kwargs={"key_derivation": "hmac"})


def public_base_url():
    """Alamat publik aplikasi, dipakai untuk link galeri dan foto."""
    origin = os.getenv("APP_ORIGIN", "").strip().rstrip("/")
    if origin:
        return origin
    base = request.host_url.rstrip("/")
    if PAAS and base.startswith("http://"):
        base = "https://" + base[len("http://"):]
    return base


def sign_gallery(order_id, stage=""):
    """Token bertanda tangan untuk akses galeri publik satu pesanan."""
    return gallery_signer.dumps({"o": order_id, "s": stage or ""})


def read_gallery(token, max_age=None):
    """Baca token galeri. Mengembalikan dict atau None kalau tidak valid."""
    try:
        payload = gallery_signer.loads(
            token, max_age=int((max_age or GALLERY_TTL).total_seconds()))
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict) or "o" not in payload:
        return None
    return payload


def gallery_url(order_id, stage=""):
    return f"{public_base_url()}/g/{sign_gallery(order_id, stage)}"


def photo_public_url(order_id, photo_id, stage=""):
    token = sign_gallery(order_id, stage)
    return f"{public_base_url()}/g/{token}/p/{photo_id}"


def format_rupiah(value):
    return "Rp" + f"{int(value):,}".replace(",", ".")


def order_summary(o):
    """Ringkasan pesanan yang aman dikirim ke konsumen."""
    lines = [
        f"No. Pesanan: {o['number']}",
        f"Jenis: {o['garment']}",
        f"Jumlah: {o['qty']} pcs",
    ]
    if o.get("material"):
        lines.append(f"Bahan: {o['material']}")
    if o.get("color"):
        lines.append(f"Warna: {o['color']}")
    if o.get("target"):
        lines.append(f"Estimasi selesai: {o['target']}")
    return "\n".join(lines)


def render_message(template, o, ringkasan, usaha, extra=""):
    """Isi template pesan dengan data pesanan."""
    values = {
        "nama": o["customer"], "nomor": o["number"], "jenis": o["garment"],
        "jumlah": f"{o['qty']} pcs", "status": production_status(o),
        "estimasi": o.get("target", ""), "usaha": usaha,
        "ringkasan": ringkasan, "total": format_rupiah(o["total"]),
        "dibayar": format_rupiah(paid(o)),
        "sisa": format_rupiah(remaining(o)), "metode": "", "kurir": "",
        "resi": "", "tanggal_kirim": "", "tiba": "",
        "diterima": o.get("received", ""),
    }
    text = re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)),
                  template or "")
    if extra:
        text += "\n\n" + extra.strip()
    return text


def fonnte_token():
    return os.getenv("FONNTE_TOKEN", "").strip()


def fonnte_requests(target, message, image_urls=None):
    """Bentuk daftar permintaan POST untuk endpoint /send Fonnte.

    Fonnte hanya menerima satu lampiran per permintaan (field "url") dan
    tidak punya field untuk beberapa gambar sekaligus. Jadi beberapa foto
    dikirim sebagai beberapa permintaan berurutan: permintaan pertama
    membawa pesan + foto pertama, sisanya hanya foto. `delay` membuat
    Fonnte memberi jeda antar kiriman.

    Terpisah dari pemanggilan jaringan supaya aturannya bisa diuji.
    """
    fields = {"target": target, "message": message}
    urls = [u for u in (image_urls or []) if u]
    mode = os.getenv("FONNTE_IMAGE_MODE", "comma").strip().lower()
    max_images = int(os.getenv("FONNTE_MAX_IMAGES", "3"))
    if not urls or mode == "none":
        return [fields]
    picked = urls[:max_images]
    delay = os.getenv("FONNTE_DELAY", "2")
    if mode == "single":
        return [dict(fields, url=picked[0], delay=delay)]
    # Fonnte menolak permintaan dengan "message" kosong ("message cannot
    # empty"), jadi tiap foto lanjutan tetap membawa keterangan singkat.
    # Dikosongkan pun tetap diberi teks cadangan supaya kiriman tidak gagal.
    lanjutan = os.getenv("FONNTE_FOLLOWUP_TEXT", "").strip() or \
        "Foto tambahan untuk pesanan ini."
    requests_ = [dict(fields, url=picked[0])]
    requests_ += [
        {"target": target, "message": lanjutan, "url": u, "delay": delay}
        for u in picked[1:]
    ]
    return requests_


def fonnte_device():
    """Info device Fonnte: status koneksi, paket, dan sisa kuota.

    Mengembalikan (info: dict | None, pesan: str). Tidak melempar exception
    supaya kegagalan cek kuota tidak mengganggu halaman Pengaturan.
    """
    token = fonnte_token()
    if not token:
        return None, "Token Fonnte belum diisi (set FONNTE_TOKEN)."
    url = os.getenv("FONNTE_DEVICE_URL",
                    "https://api.fonnte.com/device").strip()
    req = urllib.request.Request(url, data=b"", method="POST")
    req.add_header("Authorization", token)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return None, f"Fonnte menolak permintaan (HTTP {e.code})."
    except (urllib.error.URLError, OSError) as e:
        return None, f"Tidak bisa menghubungi Fonnte: {e}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, "Respons Fonnte tidak dikenali."
    if not isinstance(data, dict) or not data.get("status"):
        alasan = ""
        if isinstance(data, dict):
            alasan = data.get("reason") or data.get("detail") or ""
        return None, f"Fonnte: {alasan or 'token tidak valid.'}"
    return data, "OK"


def _fonnte_post(url, token, fields):
    """Kirim satu permintaan ke Fonnte. Mengembalikan (berhasil, pesan)."""
    body = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", token)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        return False, f"Fonnte menolak permintaan (HTTP {e.code}). {detail}"
    except (urllib.error.URLError, OSError) as e:
        return False, f"Tidak bisa menghubungi Fonnte: {e}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False, f"Respons Fonnte tidak dikenali: {raw[:200]}"
    # Fonnte membalas objek {"status": bool, ...}. Sebagian endpoint membalas
    # larik kosong kalau tidak ada error, jadi jangan diasumsikan objek.
    if isinstance(data, list):
        if not data:
            return True, "Pesan dikirim."
        data = data[0] if isinstance(data[0], dict) else {}
    if not isinstance(data, dict):
        return False, f"Respons Fonnte tidak dikenali: {raw[:200]}"
    if data.get("status"):
        return True, data.get("detail") or "Pesan dikirim."
    reason = data.get("reason") or data.get("detail") or "Tidak diketahui."
    return False, f"Fonnte: {reason}"


def fonnte_send(target, message, image_urls=None):
    """Kirim pesan WhatsApp lewat Fonnte.

    Mengembalikan (berhasil: bool, pesan: str). Tidak pernah melempar
    exception supaya kegagalan notifikasi tidak membatalkan aksi utama.

    Foto dilampirkan sebagai tautan. Kalau lampiran ditolak Fonnte, pesan
    teks dikirim ulang tanpa lampiran — isinya tetap memuat tautan galeri,
    jadi konsumen masih bisa melihat foto.
    """
    token = fonnte_token()
    if not token:
        return False, "Token Fonnte belum diisi (set FONNTE_TOKEN)."
    url = os.getenv("FONNTE_API_URL",
                    "https://api.fonnte.com/send").strip()
    requests_ = fonnte_requests(target, message, image_urls)
    terkirim = 0
    for i, fields in enumerate(requests_):
        ok, pesan = _fonnte_post(url, token, fields)
        if ok:
            terkirim += 1
            continue
        if i == 0 and fields.get("url"):
            # Lampiran pertama ditolak: kirim ulang pesannya tanpa foto
            # supaya konsumen tetap menerima kabar progres.
            tanpa_foto = {k: v for k, v in fields.items() if k != "url"}
            ok2, pesan2 = _fonnte_post(url, token, tanpa_foto)
            if ok2:
                return True, ("Pesan terkirim tanpa lampiran foto: " + pesan)
            return False, pesan2
        # Foto lanjutan gagal: pesan utama sudah sampai, jadi ini bukan
        # kegagalan total.
        if terkirim:
            sisa = len(requests_) - terkirim
            return True, (f"Pesan terkirim; {sisa} foto gagal dilampirkan: "
                          f"{pesan}")
        return False, pesan
    return True, "Pesan dikirim."


def notify_stage_started(c, o, stage, note="", with_photos=True,
                         require_enabled=True):
    """Kirim pembaruan tahap + foto ke konsumen.

    Mengembalikan (berhasil: bool, pesan: str). Tidak melempar exception:
    kegagalan notifikasi tidak boleh membatalkan penyimpanan tahap.
    """
    s = settings(c)
    if require_enabled and not s.get("auto_notify"):
        return False, "Notifikasi otomatis dimatikan di Pengaturan."
    if not o.get("wa"):
        return False, "Nomor WhatsApp konsumen belum terisi."
    if not fonnte_token():
        return False, "Token Fonnte belum diisi (set FONNTE_TOKEN)."

    photos = c.execute(
        "SELECT id,caption,uploaded FROM photos WHERE order_id=%s AND stage=%s "
        "ORDER BY uploaded", (o["id"], stage)
    ).fetchall() if with_photos else []

    ringkasan = order_summary(o)
    extra_parts = []
    if note:
        extra_parts.append(f"Catatan pengerjaan:\n{note.strip()}")
    if s.get("gallery_link", True):
        if photos:
            extra_parts.append(
                f"Foto produksi {stage}:\n{gallery_url(o['id'], stage)}")
            extra_parts.append(
                f"(Semua foto pesanan {o['number']}: {gallery_url(o['id'], '')})")
        else:
            extra_parts.append(
                f"(Semua foto pesanan {o['number']}: {gallery_url(o['id'], '')})")
    template_key = STAGE_TEMPLATE.get(stage, "potong")
    template = (s.get("templates") or {}).get(template_key, "")
    if not template:
        template = ("Halo Bapak/Ibu {nama}, berikut progres pesanan Anda.\n\n"
                    "{ringkasan}")
    message = render_message(template, o, ringkasan, s.get("name", ""),
                              "\n\n".join(extra_parts))
    image_urls = [
        photo_public_url(o["id"], p["id"], stage) for p in photos
    ]
    return fonnte_send(o["wa"], message, image_urls)


def paid(o):
    return sum(p["amount"] for p in o["payments"])

def remaining(o):
    return o["total"] - paid(o)

def payment_status(o):
    if remaining(o) == 0:
        return "Lunas"
    if not o["payments"]:
        return "Belum Bayar"
    if len(o["payments"]) == 1 and o["payments"][0]["kind"] == "DP":
        return "DP Dibayar"
    return "Cicilan"

def production_status(o):
    if o["life"] == "done":
        return "Selesai"
    if o["received"]:
        return "Barang Diterima"
    if o["shipping"]:
        return "Dikirim"
    for i, s in enumerate(o["stages"]):
        if s["state"] == "running":
            return STAGES[i]
    if all(s["state"] == "done" for s in o["stages"]):
        return "Siap Kirim"
    if o["stages"][1]["state"] == "done":
        return "Menunggu Finishing"
    if o["stages"][0]["state"] == "done":
        return "Menunggu Jahit"
    return "Pesanan Baru"

def activity(o, message, detail=None):
    o["history"].append({
        "at": now(), "message": message, "detail": detail
    })

def blocked(o):
    return any(i["blocking"] and i["status"] != "Selesai"
               for i in o["issues"])

def order_from_row(row):
    """Buat dict pesanan dari baris database, lengkap dengan id dan number.

    Kolom `id` dan `number` disimpan terpisah dari JSON `data` supaya bisa
    diubah tanpa menulis ulang blob. Semua pemanggil wajib memuat pesanan
    lewat fungsi ini: kalau tidak, o["id"] atau o["number"] tidak ada dan
    pengiriman pesan WhatsApp ikut gagal.
    """
    o = json.loads(row["data"])
    for key in ("id", "number"):
        if key in row.keys():
            # Kolom tabel yang jadi acuan. Isi blob bisa saja masih memuat
            # nilai lama dari backup sebelum kolom ini dipisah.
            o[key] = row[key]
    return o


def order_data(o):
    """Buat isi JSON pesanan tanpa field turunan dari kolom tabel.

    `id` dan `number` milik kolom tabel, bukan isi pesanan. Kalau ikut
    disimpan, nilai lamanya bisa tertinggal di blob setelah kolomnya berubah.
    """
    return json.dumps({k: v for k, v in o.items() if k not in ("id", "number")})

def serialize(c, row, photos_by_order=None):
    o = order_from_row(row)
    o["version"] = row["version"]
    o["paid"] = paid(o)
    o["remaining"] = remaining(o)
    o["payment_status"] = payment_status(o)
    o["status"] = production_status(o)
    stage_late = any(
        s["state"] == "running" and s["estimate"] and s["estimate"] < today()
        for s in o["stages"]
    )
    o["late"] = o["life"] == "active" and (
        stage_late or (
            o["target"] < today() and
            not all(s["state"] == "done" for s in o["stages"])
        )
    )
    if photos_by_order is not None:
        o["photos"] = photos_by_order.get(o["id"], [])
    else:
        o["photos"] = [
            dict(x) for x in c.execute(
                "SELECT id,stage,caption,uploaded FROM photos "
                "WHERE order_id=%s ORDER BY uploaded",
                (o["id"],)
            )
        ]
    return o


def photos_index(c, order_ids):
    """Ambil metadata foto untuk banyak pesanan sekaligus (hindari N+1)."""
    index = {oid: [] for oid in order_ids}
    if not order_ids:
        return index
    rows = c.execute(
        "SELECT order_id,id,stage,caption,uploaded FROM photos "
        "WHERE order_id = ANY(%s) ORDER BY uploaded",
        (list(order_ids),)
    ).fetchall()
    for row in rows:
        index.setdefault(row["order_id"], []).append({
            "id": row["id"], "stage": row["stage"],
            "caption": row["caption"], "uploaded": row["uploaded"],
        })
    return index

def validate_order(d):
    require(isinstance(d, dict), "Form pesanan tidak valid.")
    result = {}
    limits = {
        "customer": 150, "address": 1500, "customer_note": 2000,
        "garment": 150, "spec": 3000, "material": 150,
        "color": 100, "special": 3000,
    }
    for k, limit in limits.items():
        result[k] = text(d.get(k, ""), limit)
    for k in ("customer", "garment", "material"):
        require(result[k], "Nama konsumen, jenis pakaian, dan bahan wajib diisi.")
    result["wa"] = normalize_wa(d.get("wa", ""))
    result["deal"] = date_value(d.get("deal"))
    result["work_start"] = date_value(d.get("work_start"), True)
    result["target"] = date_value(d.get("target"))
    require(result["target"] >= result["deal"],
            "Target selesai tidak boleh sebelum tanggal deal.")
    if result["work_start"]:
        require(result["work_start"] >= result["deal"],
                "Tanggal mulai tidak boleh sebelum tanggal deal.")
    result["qty"] = integer(d.get("qty"), 1, 1000000)
    result["total"] = integer(d.get("total"))
    sizes = d.get("sizes", {})
    require(isinstance(sizes, dict) and len(sizes) <= 50,
            "Rincian ukuran tidak valid.")
    result["sizes"] = {}
    for k, v in sizes.items():
        key = text(k, 40)
        require(key, "Nama ukuran wajib diisi.")
        result["sizes"][key] = integer(v, 0, 1000000)
    if sizes:
        require(sum(result["sizes"].values()) == result["qty"],
                "Total rincian ukuran harus sama dengan jumlah pesanan.")
    return result

def image_data(value):
    require(isinstance(value, str) and "," in value,
            "File foto tidak valid.")
    try:
        raw = base64.b64decode(value.split(",", 1)[1], validate=True)
    except Exception:
        raise ValidationError("File foto tidak valid.")
    require(0 < len(raw) <= 5 * 1024 * 1024, "Foto maksimal 5 MB.")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            require(im.format in ("JPEG", "PNG", "WEBP"),
                    "Format foto harus JPEG, PNG, atau WebP.")
            require(im.width * im.height <= 25000000,
                    "Resolusi foto maksimal 25 megapiksel.")
            im.load()
            im = im.convert("RGB")
            im.thumbnail((2400, 2400))
            out = io.BytesIO()
            im.save(out, "JPEG", quality=88)
            return out.getvalue()
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError,
            Image.DecompressionBombError):
        raise ValidationError("Foto rusak atau format tidak didukung.")

def authenticated(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("owner"):
            return jsonify(error="Silakan masuk sebagai owner."), 401
        return f(*args, **kwargs)
    return wrapped


def allowed_origins():
    """Asal yang boleh mengirim request tulis.

    APP_ORIGIN diset eksplisit di produksi. Kalau kosong, memakai host
    dari request (ProxyFix sudah memperbaiki skema/host di belakang proxy).
    """
    configured = os.getenv("APP_ORIGIN", "").strip()
    if configured:
        return {o.rstrip("/") for o in configured.split(",") if o.strip()}
    return {request.host_url.rstrip("/")}


def origin_allowed(origin):
    origin = (origin or "").rstrip("/")
    if not origin:
        return True  # permintaan tanpa Origin (mis. curl/uji otomatis)
    return origin in allowed_origins()


@app.before_request
def protect_request():
    if request.path.startswith("/api/") and request.method != "GET":
        if not origin_allowed(request.headers.get("Origin")):
            return jsonify(error="Asal permintaan tidak diizinkan."), 403
        if not request.is_json:
            return jsonify(error="Permintaan harus menggunakan JSON."), 415
        if request.path != "/api/login":
            if not session.get("owner"):
                return jsonify(error="Sesi berakhir. Silakan masuk."), 401
            token = request.headers.get("X-CSRF-Token", "")
            if not token or not secrets.compare_digest(
                token, session.get("csrf", "")
            ):
                return jsonify(error="Token keamanan tidak valid. Muat ulang."), 403
    # Halaman & aset boleh di-cache sebentar; API tidak boleh.
    if request.path.startswith("/api/"):
        g.no_store = True


@app.after_request
def secure_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "connect-src 'self'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self';"
    )
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    if getattr(g, "no_store", False) or request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    else:
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.errorhandler(ValidationError)
def validation_error(e):
    return jsonify(error=str(e)), 400


@app.errorhandler(HTTPException)
def http_error(e):
    if request.path.startswith("/api/"):
        messages = {
            404: "Data tidak ditemukan.",
            405: "Metode permintaan tidak diizinkan.",
            413: "Ukuran unggahan terlalu besar.",
            415: "Permintaan harus menggunakan JSON.",
            429: "Terlalu banyak permintaan. Tunggu sebentar lalu coba lagi.",
        }
        return jsonify(error=messages.get(e.code, f"Permintaan gagal ({e.code}).")), e.code
    return e


@app.errorhandler(Exception)
def unexpected_error(e):
    app.logger.exception("Kesalahan aplikasi")
    if isinstance(e, psycopg2.Error):
        hint = "Koneksi ke database terputus. Coba lagi dalam beberapa saat."
    else:
        hint = "Terjadi kesalahan di server. Silakan coba lagi."
    return jsonify(error=hint), 500

login_attempts = []
login_lock = threading.Lock()

@app.post("/api/login")
def login():
    with login_lock:
        cutoff = time.time() - 300
        login_attempts[:] = [t for t in login_attempts if t > cutoff]
        if len(login_attempts) >= 10:
            return jsonify(error="Terlalu banyak percobaan. Tunggu 5 menit."), 429
        login_attempts.append(time.time())
    d = request.get_json()
    require(isinstance(d, dict), "Permintaan tidak valid.")
    password = text(d.get("password", ""), 500)
    with connect() as c:
        row = c.execute("SELECT password_hash FROM owner WHERE id=1").fetchone()
    if not check_password_hash(row["password_hash"], password):
        return jsonify(error="Kata sandi tidak sesuai."), 401
    with login_lock:
        login_attempts.clear()
    session.clear()
    session["owner"] = True
    session["csrf"] = secrets.token_hex(32)
    session.permanent = True
    return jsonify(csrf=session["csrf"])

@app.post("/api/logout")
@authenticated
def logout():
    session.clear()
    return jsonify(ok=True)

@app.get("/api/state")
@authenticated
def state():
    with connect() as c:
        rows = c.execute("SELECT * FROM orders ORDER BY number DESC").fetchall()
        index = photos_index(c, [r["id"] for r in rows])
        return jsonify(
            csrf=session["csrf"],
            settings=settings(c),
            orders=[serialize(c, r, index) for r in rows],
            today=today(),
            qc_items=QC_ITEMS,
            categories=ISSUE_CATEGORIES,
            fonnte_configured=bool(fonnte_token()),
        )

@app.post("/api/settings")
@authenticated
def save_settings():
    d = request.get_json()
    require(isinstance(d, dict), "Pengaturan tidak valid.")
    with connect() as c:
        s = settings(c)
        s["name"] = text(d.get("name", ""), 150)
        require(s["name"], "Nama usaha wajib diisi.")
        s["wa"] = normalize_wa(d["wa"]) if d.get("wa") else ""
        s["address"] = text(d.get("address", ""), 1500)
        s["prefix"] = text(d.get("prefix", ""), 12).upper()
        require(re.fullmatch(r"[A-Z0-9]{2,12}", s["prefix"]) is not None,
                "Awalan nomor harus 2–12 huruf/angka.")
        s["default_days"] = integer(d.get("default_days"), 1, 365)
        s["auto_notify"] = bool(d.get("auto_notify", s.get("auto_notify")))
        s["gallery_link"] = bool(d.get("gallery_link", s.get("gallery_link")))
        for k in ("garments", "materials"):
            values = d.get(k)
            require(isinstance(values, list) and 1 <= len(values) <= 200,
                    "Daftar pakaian/bahan harus berisi 1–200 item.")
            s[k] = list(dict.fromkeys(
                text(v, 150) for v in values if text(v, 150)
            ))
            require(s[k], "Daftar tidak boleh kosong.")
        templates = d.get("templates", {})
        require(isinstance(templates, dict), "Template tidak valid.")
        for k in TEMPLATES:
            s["templates"][k] = text(templates.get(k, ""), 5000)
            require(s["templates"][k], "Template pesan tidak boleh kosong.")
        if d.get("logo"):
            s["logo"] = "data:image/jpeg;base64," + base64.b64encode(
                image_data(d["logo"])
            ).decode()
        if d.get("remove_logo"):
            s["logo"] = ""
        c.execute("UPDATE settings SET data=%s WHERE id=1", (json.dumps(s),))
    return jsonify(ok=True)


@app.get("/api/notify/status")
@authenticated
def notify_status():
    """Status konfigurasi notifikasi WhatsApp (untuk ditampilkan di UI)."""
    with connect() as c:
        s = settings(c)
    return jsonify(
        auto_notify=bool(s.get("auto_notify")),
        gallery_link=bool(s.get("gallery_link", True)),
        fonnte_configured=bool(fonnte_token()),
        base_url=public_base_url(),
        ttl_days=GALLERY_TTL.days,
    )


@app.get("/api/notify/device")
@authenticated
def notify_device():
    """Status device Fonnte: nomor terhubung, paket, sisa kuota."""
    info, pesan = fonnte_device()
    if info is None:
        return jsonify(ok=False, message=pesan)
    return jsonify(
        ok=True,
        device=info.get("device", ""),
        name=info.get("name", ""),
        connected=info.get("device_status") == "connect",
        package=info.get("package", ""),
        quota=info.get("quota", ""),
        expired=info.get("expired", ""),
    )


@app.post("/api/notify/test")
@authenticated
def notify_test():
    """Kirim pesan uji ke nomor owner (untuk memastikan Fonnte terhubung)."""
    d = request.get_json(silent=True) or {}
    require(isinstance(d, dict), "Permintaan tidak valid.")
    with connect() as c:
        s = settings(c)
    target = normalize_wa(d.get("target", "")) if d.get("target") else s.get("wa")
    require(target, "Isi nomor WhatsApp tujuan (milik Anda sendiri).")
    message = (
        f"{s.get('name', 'Rofi Jaya')}: ini pesan uji. Notifikasi WhatsApp "
        "untuk progres produksi sudah terhubung."
    )
    ok, pesan = fonnte_send(target, message)
    return jsonify(ok=ok, message=pesan)


@app.post("/api/notify/stage")
@authenticated
def notify_stage_manual():
    """Kirim ulang pembaruan tahap + foto ke konsumen secara manual."""
    d = request.get_json()
    require(isinstance(d, dict), "Permintaan tidak valid.")
    ident = text(d.get("id", ""), 64)
    stage = text(d.get("stage", ""), 100)
    require(stage in STAGES, "Tahap tidak valid.")
    with connect() as c:
        row = c.execute("SELECT id,number,data FROM orders WHERE id=%s",
                        (ident,)).fetchone()
        require(row is not None, "Pesanan tidak ditemukan.")
        o = order_from_row(row)
        ok, pesan = notify_stage_started(c, o, stage, d.get("note", ""),
                                         bool(d.get("with_photos", True)),
                                         require_enabled=False)
        o["notified"] = {"at": now(), "stage": stage, "ok": ok, "message": pesan}
        activity(o, "Pembaruan WhatsApp dikirim ke konsumen" if ok
                 else "Pembaruan WhatsApp gagal dikirim",
                 {"tahap": stage, "hasil": pesan})
        c.execute(
            "UPDATE orders SET data=%s,version=version+1 WHERE id=%s",
            (order_data(o), ident)
        )
    return jsonify(ok=ok, message=pesan)


@app.post("/api/notify/message")
@authenticated
def notify_message():
    """Kirim pesan WhatsApp ke konsumen memakai template yang dipilih."""
    d = request.get_json()
    require(isinstance(d, dict), "Permintaan tidak valid.")
    ident = text(d.get("id", ""), 64)
    kind = text(d.get("kind", ""), 40)
    extra = text(d.get("extra", ""), 2000)
    require(kind in TEMPLATES, "Jenis pesan tidak valid.")
    with connect() as c:
        row = c.execute("SELECT id,number,data FROM orders WHERE id=%s",
                        (ident,)).fetchone()
        require(row is not None, "Pesanan tidak ditemukan.")
        o = order_from_row(row)
        s = settings(c)
        require(o.get("wa"), "Nomor WhatsApp konsumen belum terisi.")
        message = render_message(
            (s.get("templates") or {}).get(kind, ""), o, order_summary(o),
            s.get("name", ""), extra)
        ok, pesan = fonnte_send(o["wa"], message)
    return jsonify(ok=ok, message=pesan), (200 if ok else 502)


@app.get("/api/gallery-link/<ident>")
@authenticated
def gallery_link(ident):
    """Buat tautan galeri publik untuk satu pesanan."""
    with connect() as c:
        row = c.execute("SELECT id,number,data FROM orders WHERE id=%s",
                        (ident,)).fetchone()
        require(row is not None, "Pesanan tidak ditemukan.")
    return jsonify(url=gallery_url(ident, ""), expires_days=GALLERY_TTL.days)


@app.post("/api/password")
@authenticated
def change_password():
    d = request.get_json()
    old = text(d.get("old", ""), 500)
    new = text(d.get("new", ""), 500)
    require(len(new) >= 12, "Kata sandi baru minimal 12 karakter.")
    with connect() as c:
        row = c.execute("SELECT password_hash FROM owner WHERE id=1").fetchone()
        require(check_password_hash(row["password_hash"], old),
                "Kata sandi lama tidak sesuai.")
        c.execute("UPDATE owner SET password_hash=%s WHERE id=1",
                  (generate_password_hash(new),))
    session.clear()
    return jsonify(ok=True)

@app.post("/api/orders")
@authenticated
def create_order():
    d = request.get_json()
    o = validate_order(d)
    dp = integer(d.get("dp"))
    require(dp <= o["total"], "DP tidak boleh melebihi harga kesepakatan.")
    o.update({
        "created": now(), "life": "active", "final_label": "",
        "stages": [
            {"state": "pending", "start": "", "estimate": "",
             "finished": "", "note": ""}
            for _ in STAGES
        ],
        "checklist": [False] * len(QC_ITEMS),
        "qc": {"inspected": 0, "good": 0, "bad": 0,
               "missing": o["qty"], "defect": "", "correction": "",
               "approval": ""},
        "issues": [], "payments": [], "shipping": None,
        "received": "", "history": [],
    })
    if dp:
        o["payments"].append({
            "id": uuid.uuid4().hex, "amount": dp, "date": o["deal"],
            "note": "DP awal saat kesepakatan", "kind": "DP", "at": now()
        })
    activity(o, "Pesanan dibuat; seluruh tahap produksi belum dimulai.")
    if dp:
        activity(o, "DP diterima", {"jumlah": dp, "tanggal": o["deal"]})
    ident = uuid.uuid4().hex
    with connect() as c:
        s = settings(c)
        key = s["prefix"] + "-" + datetime.now(WIB).strftime("%Y%m")
        # Penomoran atomik: dua request bersamaan tidak bisa mendapat
        # nomor urut yang sama.
        seq = c.execute(
            "INSERT INTO counters(key,value) VALUES(%s,1) "
            "ON CONFLICT(key) DO UPDATE SET value = counters.value + 1 "
            "RETURNING value",
            (key,)
        ).fetchone()["value"]
        number = f"{key}-{seq:04d}"
        c.execute("INSERT INTO orders VALUES(%s,%s,1,%s)",
                  (ident, number, order_data(o)))
    return jsonify(id=ident, number=number)

@app.post("/api/orders/<ident>/action")
@authenticated
def order_action(ident):
    d = request.get_json()
    require(isinstance(d, dict), "Permintaan tidak valid.")
    action = d.get("action")
    # Kirim pembaruan WhatsApp + foto hanya untuk aksi "start" (Mulai Tahap)
    # dan hanya bila owner mencentang opsi tersebut.
    notify = action == "start" and bool(d.get("notify"))
    notify_result = None
    with connect() as c:
        row = c.execute("SELECT id,number,version,data FROM orders WHERE id=%s",
                        (ident,)).fetchone()
        require(row is not None, "Pesanan tidak ditemukan.")

        # Idempotensi: retry pembayaran yang sama tidak membuat transaksi baru.
        if action == "pay":
            token = text(d.get("token", ""), 100)
            require(len(token) >= 16, "ID transaksi pembayaran tidak valid.")
            if c.execute(
                "SELECT 1 FROM payment_keys WHERE order_id=%s AND token=%s",
                (ident, token)
            ).fetchone():
                return jsonify(ok=True, duplicate=True)

        if integer(d.get("version")) != row["version"]:
            return jsonify(
                error="Data berubah pada tab/perangkat lain. Tutup form dan muat ulang."
            ), 409

        o = order_from_row(row)
        active_only = {
            "edit", "start", "stage", "finish", "checklist", "qc",
            "issue_add", "ship", "receive", "complete"
        }
        if action in active_only:
            require(o["life"] == "active", "Aktifkan kembali pesanan sebelum mengubahnya.")
        if action in {"pay", "photo_add", "photo_delete", "issue_update"}:
            require(o["life"] in ("active", "paused", "unpaid"),
                    "Pesanan ini hanya dapat dibaca.")

        if action == "edit":
            require(not o["shipping"], "Kesepakatan tidak dapat diubah setelah pengiriman.")
            changed = validate_order(d.get("order"))
            require(changed["total"] >= paid(o),
                    "Harga baru tidak boleh di bawah pembayaran yang sudah diterima.")
            reason = text(d.get("reason", ""), 2000)
            require(reason, "Alasan revisi wajib diisi.")
            differences = {
                k: {"lama": o.get(k), "baru": v}
                for k, v in changed.items() if o.get(k) != v
            }
            if any(o["checklist"]) or any(
                s["state"] == "done" for s in o["stages"][2:]
            ):
                require(changed["qty"] == o["qty"],
                        "Jumlah tidak dapat diubah setelah QC dimulai.")
            o.update(changed)
            activity(o, "Kesepakatan direvisi", {
                "alasan": reason, "perubahan": differences
            })

        elif action in ("start", "stage", "finish"):
            i = integer(d.get("stage"), 0, 2)
            s = o["stages"][i]
            if action == "start":
                require(s["state"] == "pending", "Tahap sudah dimulai.")
                require(i == 0 or o["stages"][i - 1]["state"] == "done",
                        "Selesaikan tahap sebelumnya terlebih dahulu.")
                start = date_value(d.get("start"))
                estimate = date_value(d.get("estimate"))
                require(start >= o["deal"] and start <= today(),
                        "Tanggal mulai harus antara tanggal deal dan hari ini.")
                if i:
                    require(start >= o["stages"][i - 1]["finished"][:10],
                            "Tanggal mulai tidak boleh sebelum tahap sebelumnya selesai.")
                require(estimate >= start, "Estimasi tidak boleh sebelum tanggal mulai.")
                s.update(state="running", start=start, estimate=estimate,
                         note=text(d.get("note", ""), 3000))
                activity(o, f"{STAGES[i]} dimulai", dict(s))
            elif action == "stage":
                require(s["state"] == "running", "Tahap belum berjalan.")
                estimate = date_value(d.get("estimate"))
                require(estimate >= s["start"], "Estimasi tidak valid.")
                old = dict(s)
                s["estimate"] = estimate
                s["note"] = text(d.get("note", ""), 3000)
                activity(o, f"Catatan/estimasi {STAGES[i]} diperbarui",
                         {"lama": old, "baru": dict(s)})
            else:
                require(s["state"] == "running", "Tahap belum dimulai.")
                if i == 2:
                    require(all(o["checklist"]), "Selesaikan seluruh checklist finishing.")
                    require(not blocked(o),
                            "Selesaikan kendala yang menghalangi pengiriman.")
                    q = o["qc"]
                    issues_qc = (
                        q["inspected"] != o["qty"] or
                        q["good"] != o["qty"] or q["bad"] > 0
                    )
                    require(not issues_qc or bool(q["approval"]),
                            "QC masih memiliki cacat/kekurangan. "
                            "Perbaiki atau isi persetujuan pengecualian owner.")
                s["state"] = "done"
                s["finished"] = now()
                activity(o, f"{STAGES[i]} diselesaikan oleh owner", dict(s))
                if i == 2:
                    o["ready_at"] = now()
                    activity(o, "Pesanan siap kirim")

        elif action == "checklist":
            require(o["stages"][2]["state"] == "running",
                    "Mulai finishing terlebih dahulu.")
            values = d.get("values")
            require(isinstance(values, list) and len(values) == len(QC_ITEMS)
                    and all(type(x) is bool for x in values),
                    "Checklist tidak valid.")
            o["checklist"] = values
            activity(o, "Checklist finishing disimpan", values)

        elif action == "qc":
            require(o["stages"][2]["state"] == "running",
                    "QC hanya dapat diperbarui saat finishing berjalan.")
            inspected = integer(d.get("inspected"), 0, o["qty"])
            good = integer(d.get("good"), 0, inspected)
            bad = integer(d.get("bad"), 0, inspected)
            require(good + bad == inspected,
                    "Jumlah baik + cacat harus sama dengan jumlah diperiksa.")
            defect = text(d.get("defect", ""), 3000)
            correction = text(d.get("correction", ""), 3000)
            approval = text(d.get("approval", ""), 3000)
            if bad or inspected < o["qty"]:
                require(defect, "Jelaskan cacat atau kekurangan.")
            q = {
                "inspected": inspected, "good": good, "bad": bad,
                "missing": o["qty"] - inspected, "defect": defect,
                "correction": correction, "approval": approval
            }
            activity(o, "Pemeriksaan kualitas dicatat",
                     {"lama": o["qc"], "baru": q})
            o["qc"] = q

        elif action == "issue_add":
            category = text(d.get("category", ""), 100)
            require(category in ISSUE_CATEGORIES, "Kategori tidak valid.")
            description = text(d.get("description", ""), 3000)
            require(description, "Deskripsi kendala wajib diisi.")
            issue = {
                "id": uuid.uuid4().hex, "at": now(), "category": category,
                "description": description,
                "action": text(d.get("followup", ""), 3000),
                "blocking": bool(d.get("blocking")),
                "status": "Baru", "resolution": ""
            }
            o["issues"].append(issue)
            activity(o, "Revisi/kendala dicatat", dict(issue))

        elif action == "issue_update":
            issue = next((x for x in o["issues"] if x["id"] == d.get("issue")), None)
            require(issue is not None, "Kendala tidak ditemukan.")
            status = d.get("status")
            require(status in ("Baru", "Sedang ditangani", "Selesai"),
                    "Status kendala tidak valid.")
            resolution = text(d.get("resolution", ""), 3000)
            if status == "Selesai":
                require(resolution, "Catatan penyelesaian wajib diisi.")
            old = dict(issue)
            issue.update(status=status, resolution=resolution, updated=now())
            activity(o, "Kendala diperbarui", {"lama": old, "baru": dict(issue)})

        elif action == "pay":
            amount = integer(d.get("amount"), 1)
            require(amount <= remaining(o),
                    "Pembayaran melebihi sisa tagihan.")
            date = date_value(d.get("date"))
            require(o["deal"] <= date <= today(),
                    "Tanggal pembayaran harus antara tanggal deal dan hari ini.")
            p = {
                "id": uuid.uuid4().hex, "amount": amount, "date": date,
                "note": text(d.get("note", ""), 2000),
                "kind": "Pembayaran", "at": now()
            }
            o["payments"].append(p)
            c.execute("INSERT INTO payment_keys VALUES(%s,%s)", (ident, token))
            activity(o, "Pembayaran diterima", p)

        elif action == "photo_add":
            stage = text(d.get("stage", ""), 100)
            allowed = ["Potong Bahan", "Jahit", "Finishing & QC", "Packing"]
            allowed += ["Kendala:" + x["id"] for x in o["issues"]]
            require(stage in allowed, "Kelompok foto tidak valid.")
            caption = text(d.get("caption", ""), 1000)
            raw = image_data(d.get("data"))
            photo_id = uuid.uuid4().hex
            c.execute("INSERT INTO photos VALUES(%s,%s,%s,%s,%s,%s,%s)", (
                photo_id, ident, stage, caption, now(), "image/jpeg", raw
            ))
            activity(o, "Foto ditambahkan", {
                "id": photo_id, "tahap": stage, "keterangan": caption
            })

        elif action == "photo_delete":
            photo = c.execute(
                "SELECT id,stage,caption FROM photos WHERE id=%s AND order_id=%s",
                (d.get("photo"), ident)
            ).fetchone()
            require(photo is not None, "Foto tidak ditemukan.")
            activity(o, "Foto dihapus oleh owner", dict(photo))
            c.execute("DELETE FROM photos WHERE id=%s", (photo["id"],))

        elif action == "ship":
            require(all(s["state"] == "done" for s in o["stages"]),
                    "Finishing belum selesai.")
            require(not o["received"], "Barang sudah diterima.")
            require(not blocked(o), "Masih ada kendala yang menghalangi pengiriman.")
            method = d.get("method")
            require(method in ("Kurir", "Ekspedisi", "Diambil langsung"),
                    "Metode pengiriman tidak valid.")
            shipping_date = date_value(d.get("date"))
            eta = date_value(d.get("eta"))
            require(o["ready_at"][:10] <= shipping_date <= today(),
                    "Tanggal kirim harus antara tanggal siap kirim dan hari ini.")
            require(eta >= shipping_date, "Estimasi tiba tidak boleh sebelum tanggal kirim.")
            count = integer(d.get("qty"), 1, o["qty"])
            note = text(d.get("note", ""), 2000)
            if count < o["qty"]:
                require(note, "Pengiriman kurang dari pesanan membutuhkan alasan.")
            sh = {
                "method": method, "courier": text(d.get("courier", ""), 150),
                "tracking": text(d.get("tracking", ""), 150),
                "packages": integer(d.get("packages"), 1, 1000000),
                "qty": count, "date": shipping_date, "eta": eta, "note": note
            }
            activity(o, "Informasi pengiriman dicatat/diperbarui",
                     {"lama": o["shipping"], "baru": sh})
            o["shipping"] = sh

        elif action == "receive":
            require(o["shipping"] is not None, "Catat pengiriman/serah terima dahulu.")
            require(not o["received"], "Penerimaan sudah dicatat.")
            received = date_value(d.get("date"))
            require(o["shipping"]["date"] <= received <= today(),
                    "Tanggal terima harus antara tanggal kirim dan hari ini.")
            o["received"] = received
            activity(o, "Barang diterima/diserahterimakan", {"tanggal": received})

        elif action == "complete":
            require(o["received"], "Barang belum dicatat diterima.")
            require(not blocked(o), "Masih ada kendala yang menghalangi penyelesaian.")
            require(remaining(o) == 0, "Masih ada sisa pembayaran.")
            o["life"] = "done"
            o["final_label"] = "Selesai dan Lunas"
            activity(o, "Pesanan selesai dan lunas")

        elif action == "life":
            target = d.get("life")
            reason = text(d.get("reason", ""), 2000)
            require(reason, "Alasan perubahan wajib diisi.")
            if target == "paused":
                require(o["life"] == "active", "Pesanan tidak sedang aktif.")
                o["life"] = "paused"
                o["final_label"] = "Ditunda"
            elif target == "active":
                require(o["life"] in ("paused", "unpaid"),
                        "Hanya pesanan ditunda/belum lunas yang dapat diaktifkan.")
                o["life"] = "active"
                o["final_label"] = ""
            elif target == "cancelled":
                require(o["life"] in ("active", "paused"),
                        "Pesanan tidak dapat dibatalkan.")
                o["life"] = "cancelled"
                o["final_label"] = "Dibatalkan"
            elif target == "unpaid":
                require(o["life"] == "active" and o["received"] and remaining(o) > 0,
                        "Pengecualian hanya untuk barang diterima tetapi belum lunas.")
                require(not blocked(o), "Masih ada kendala penghalang.")
                o["life"] = "unpaid"
                o["final_label"] = "Selesai tetapi Belum Lunas"
            elif target == "archived":
                require(o["life"] in ("done", "cancelled"),
                        "Hanya pesanan selesai/dibatalkan yang dapat diarsipkan.")
                o["archived_from"] = o["final_label"]
                o["life"] = "archived"
                o["final_label"] = "Diarsipkan"
            else:
                raise ValidationError("Perubahan status tidak valid.")
            activity(o, "Status administrasi diubah", {
                "status": o["final_label"] or "Aktif", "alasan": reason
            })

        else:
            raise ValidationError("Tindakan tidak dikenali.")

        c.execute(
            "UPDATE orders SET data=%s,version=version+1 WHERE id=%s",
            (order_data(o), ident)
        )

        # Notifikasi WhatsApp otomatis + foto (opsional, tidak membatalkan
        # penyimpanan kalau gagal).
        if notify:
            # Centang di dialog sudah menjadi pilihan owner untuk tahap ini,
            # jadi sakelar global tidak menghalangi pengiriman.
            ok, pesan = notify_stage_started(
                c, o, STAGES[i], o["stages"][i].get("note", ""),
                require_enabled=False)
            notify_result = {"ok": ok, "message": pesan}
            o["notified"] = {
                "at": now(), "stage": STAGES[i], "ok": ok, "message": pesan
            }
            activity(o, "Pembaruan WhatsApp dikirim ke konsumen" if ok
                     else "Pembaruan WhatsApp gagal dikirim",
                     {"tahap": STAGES[i], "hasil": pesan})
            c.execute(
                "UPDATE orders SET data=%s,version=version+1 WHERE id=%s",
                (order_data(o), ident)
            )
    return jsonify(ok=True, notified=notify_result)


@app.get("/api/photos/<ident>")
@authenticated
def photo(ident):
    with connect() as c:
        row = c.execute(
            "SELECT data,mime FROM photos WHERE id=%s", (ident,)
        ).fetchone()
    if not row:
        return jsonify(error="Foto tidak ditemukan."), 404
    return send_file(
        io.BytesIO(bytes(row["data"])), mimetype=row["mime"],
        as_attachment=request.args.get("download") == "1",
        download_name=f"progres-{ident[:8]}.jpg"
    )


# -------------------------- Galeri publik --------------------------

GALLERY_CSS = """
:root{--green:#143e35;--accent:#c9a66b;--bg:#f5f6f3;--line:#e4e8e3;
--muted:#6d7a72}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:#1c2622;
font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{background:var(--green);color:#fff;padding:26px 18px}
header .wrap,main{max-width:860px;margin:0 auto}
header h1{margin:0 0 6px;font-size:20px}
header p{margin:0;opacity:.82;font-size:14px}
main{padding:22px 18px 60px}
.card{background:#fff;border:1px solid var(--line);border-radius:14px;
padding:18px;margin-bottom:20px}
.card h2{margin:0 0 12px;font-size:15px;letter-spacing:.04em;
text-transform:uppercase;color:var(--muted)}
.kv{display:grid;grid-template-columns:150px 1fr;gap:6px 14px;font-size:14px}
.kv span{color:var(--muted)}
.kv b{font-weight:600}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));
gap:14px}
figure{margin:0;background:var(--bg);border-radius:12px;overflow:hidden;
border:1px solid var(--line)}
figure img{width:100%;display:block;aspect-ratio:3/4;object-fit:cover}
figcaption{padding:9px 11px;font-size:12.5px;color:var(--muted)}
figcaption b{display:block;color:#1c2622;font-weight:600;font-size:13px}
.empty{padding:28px;text-align:center;color:var(--muted)}
footer{text-align:center;color:var(--muted);font-size:12.5px;padding:0 18px 40px}
@media(max-width:600px){.kv{grid-template-columns:1fr}}
"""


def gallery_page(title, body):
    return Response(
        "<!doctype html><html lang=\"id\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{html_escape(title)}</title>"
        "<style>" + GALLERY_CSS + "</style></head><body>"
        f"<header><div class=\"wrap\"><h1>{html_escape(title)}</h1>"
        "<p> Dokumentasi produksi pesanan</p></div></header>"
        f"<main>{body}</main>"
        "<footer>Foto ini dikirim untuk keperluan informasi progres pesanan.</footer>"
        "</body></html>",
        mimetype="text/html")


@app.get("/g/<token>")
def public_gallery(token):
    """Galeri foto publik untuk satu pesanan.

    Token bersifat bertanda tangan dan berlaku terbatas waktu, jadi tautan
    hanya bisa dibuka oleh penerima tautan.
    """
    payload = read_gallery(token)
    if not payload:
        return gallery_page(
            "Tautan tidak berlaku",
            '<div class="card"><div class="empty">Tautan foto ini sudah tidak '
            'berlaku atau rusak.<br>Minta tautan baru kepada usaha.</div></div>'
        ), 404
    order_id = payload["o"]
    stage = payload.get("s") or ""
    with connect() as c:
        row = c.execute(
            "SELECT id,number,data FROM orders WHERE id=%s", (order_id,)
        ).fetchone()
        if not row:
            return gallery_page(
                "Pesanan tidak ditemukan",
                '<div class="card"><div class="empty">Data pesanan tidak '
                'ditemukan.</div></div>'), 404
        o = order_from_row(row)
        s = settings(c)
        if stage:
            rows = c.execute(
                "SELECT id,stage,caption,uploaded FROM photos "
                "WHERE order_id=%s AND stage=%s ORDER BY uploaded",
                (order_id, stage)
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT id,stage,caption,uploaded FROM photos "
                "WHERE order_id=%s ORDER BY uploaded",
                (order_id,)
            ).fetchall()

    usaha = s.get("name", "")
    ringkasan = [
        ("No. Pesanan", o["number"]),
        ("Jenis pakaian", o["garment"]),
        ("Jumlah", f"{o['qty']} pcs"),
    ]
    if o.get("material"):
        ringkasan.append(("Bahan", o["material"]))
    if o.get("color"):
        ringkasan.append(("Warna", o["color"]))
    ringkasan.append(("Tahap", stage or "Semua tahap"))
    ringkasan.append(("Estimasi selesai", o.get("target", "") or "—"))

    if rows:
        groups = []
        for r in rows:
            if not groups or groups[-1][0] != r["stage"]:
                groups.append((r["stage"], []))
            groups[-1][1].append(r)
        parts = []
        for group_stage, items in groups:
            figures = "".join(
                '<figure><a href="/g/%s/p/%s" target="_blank" rel="noopener">'
                '<img loading="lazy" src="/g/%s/p/%s" alt="%s"></a>'
                "<figcaption><b>%s</b>%s</figcaption></figure>" % (
                    html_escape(token), html_escape(r["id"]),
                    html_escape(token), html_escape(r["id"]),
                    html_escape(r["caption"] or group_stage),
                    html_escape(group_stage),
                    html_escape(r["caption"] or ""))
                for r in items
            )
            parts.append(
                '<div class="card"><h2>%s</h2><div class="gallery">%s</div></div>'
                % (html_escape(group_stage), figures)
            )
        photos_html = "".join(parts)
    else:
        photos_html = ('<div class="card"><div class="empty">Belum ada foto '
                       'untuk tahap ini.</div></div>')

    body = (
        '<div class="card"><h2>Ringkasan pesanan</h2><div class="kv">'
        + "".join(f"<span>{html_escape(k)}</span><b>{html_escape(v)}</b>"
                  for k, v in ringkasan)
        + "</div></div>" + photos_html
    )
    title = f"Progres Pesanan {o['number']} · {usaha}"
    return gallery_page(title, body)


@app.get("/g/<token>/p/<photo_id>")
def public_photo(token, photo_id):
    """Satu foto dari galeri publik (token wajib, tanpa login)."""
    payload = read_gallery(token)
    if not payload:
        return Response(status=404)
    order_id = payload["o"]
    stage = payload.get("s") or ""
    with connect() as c:
        if stage:
            row = c.execute(
                "SELECT data,mime FROM photos WHERE id=%s AND order_id=%s "
                "AND stage=%s", (photo_id, order_id, stage)
            ).fetchone()
        else:
            row = c.execute(
                "SELECT data,mime FROM photos WHERE id=%s AND order_id=%s",
                (photo_id, order_id)
            ).fetchone()
    if not row:
        return Response(status=404)
    response = send_file(
        io.BytesIO(bytes(row["data"])), mimetype=row["mime"]
    )
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


BACKUP_TABLES = (
    ("owner", "SELECT id,password_hash FROM owner"),
    ("settings", "SELECT id,data FROM settings"),
    ("counters", "SELECT key,value FROM counters"),
    ("orders", "SELECT id,number,version,data FROM orders ORDER BY number"),
    ("photos",
     "SELECT id,order_id,stage,caption,uploaded,mime,data FROM photos "
     "ORDER BY uploaded"),
    ("payment_keys", "SELECT order_id,token FROM payment_keys"),
)


@app.get("/api/backup")
@authenticated
def backup():
    """Unduh salinan data.

    Foto ikut disertakan sebagai base64. Agar tidak kehabisan memori,
    file dikirim secara bertahap (streaming), bukan seluruhnya dirakit
    di memory. Foto bisa dimatikan lewat ?photos=0 untuk backup ringan.
    """
    include_photos = request.args.get("photos", "1") != "0"
    pool = get_pool()
    conn = pool.getconn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def generate():
        # Koneksi harus tetap hidup selama file dikirim.
        try:
            yield ('{"backup": {"app": "rofi-jaya", "format": 2, '
                   '"created": "%s", "photos": %s}, "tables": {' % (
                       now(), "true" if include_photos else "false"))
            first_table = True
            for name, query in BACKUP_TABLES:
                if not include_photos and name == "photos":
                    continue
                if not first_table:
                    yield ","
                first_table = False
                yield '"%s": [' % name
                cur.execute(query)
                first_row = True
                while True:
                    rows = cur.fetchmany(100)
                    if not rows:
                        break
                    for row in rows:
                        item = dict(row)
                        if name == "photos":
                            raw = item.get("data")
                            item["data"] = (
                                base64.b64encode(bytes(raw)).decode("ascii")
                                if raw else ""
                            )
                        if not first_row:
                            yield ","
                        first_row = False
                        yield json.dumps(item, default=str)
                yield "]"
            yield "}}"
        finally:
            with contextlib.suppress(Exception):
                cur.close()
            with contextlib.suppress(Exception):
                pool.putconn(conn)

    filename = f"backup-rofi-jaya-{today()}.json"
    return Response(
        generate(), mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/backup/restore")
@authenticated
def restore_backup():
    """Pulihkan database dari file backup JSON milik owner.

    Data yang ada akan diganti. Wuajib dicek ulang oleh owner.
    """
    # Backup dengan foto bisa berukuran besar; longgarkan batas unggahan
    # khusus endpoint ini.
    request.max_content_length = int(
        os.getenv("MAX_RESTORE_MB", "200")) * 1024 * 1024
    d = request.get_json()
    require(isinstance(d, dict), "Permintaan tidak valid.")
    confirm = text(d.get("confirm", ""), 50)
    require(confirm == "GANTI SEMUA DATA",
            "Ketik GANTI SEMUA DATA untuk mengonfirmasi pemulihan.")
    tables = d.get("tables")
    require(isinstance(tables, dict), "Isi backup tidak valid.")
    orders = tables.get("orders")
    require(isinstance(orders, list), "Isi backup tidak memuat pesanan.")
    require(len(orders) <= 100000, "Backup terlalu besar untuk dipulihkan.")
    photos = tables.get("photos") or []
    require(isinstance(photos, list), "Isi backup tidak valid.")
    require(all(isinstance(r, dict) for r in orders),
            "Isi backup tidak valid.")

    def _field(row, key, default="", limit=200):
        value = row.get(key, default)
        return str(value if value is not None else default)[:limit]

    def _version(row):
        try:
            return max(1, int(row.get("version", 1)))
        except (TypeError, ValueError):
            return 1

    with connect() as c:
        # Pesanan dulu, lalu foto (ada foreign key ke orders).
        c.execute("DELETE FROM photos")
        c.execute("DELETE FROM payment_keys")
        c.execute("DELETE FROM orders")
        for row in orders:
            data = row.get("data")
            c.execute(
                "INSERT INTO orders(id,number,version,data) VALUES(%s,%s,%s,%s)",
                (_field(row, "id", "", 64),
                 _field(row, "number", "", 64),
                 _version(row),
                 data if isinstance(data, str) else "{}")
            )
        for row in photos:
            if not isinstance(row, dict):
                continue
            raw = row.get("data")
            try:
                blob = base64.b64decode(raw, validate=True) if raw else b""
            except Exception:
                blob = b""
            c.execute(
                "INSERT INTO photos(id,order_id,stage,caption,uploaded,mime,data)"
                " VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (_field(row, "id", "", 64),
                 _field(row, "order_id", "", 64),
                 _field(row, "stage", "", 100),
                 _field(row, "caption", "", 1000),
                 _field(row, "uploaded", "", 40),
                 _field(row, "mime", "image/jpeg", 60),
                 psycopg2.Binary(blob))
            )
        for row in (tables.get("payment_keys") or []):
            if not isinstance(row, dict):
                continue
            c.execute(
                "INSERT INTO payment_keys(order_id,token) VALUES(%s,%s) "
                "ON CONFLICT DO NOTHING",
                (_field(row, "order_id", "", 64), _field(row, "token", "", 100))
            )
        for row in (tables.get("counters") or []):
            if not isinstance(row, dict):
                continue
            try:
                value = int(row.get("value", 0))
            except (TypeError, ValueError):
                continue
            c.execute(
                "INSERT INTO counters(key,value) VALUES(%s,%s) "
                "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                (_field(row, "key", "", 64), value)
            )
        # Pengaturan & owner tidak ditimpa agar sesi login tidak putus.
    return jsonify(ok=True, orders=len(orders), photos=len(photos))


@app.get("/api/healthz")
def healthz():
    """Cek kesehatan untuk platform (tanpa perlu login)."""
    try:
        with connect() as c:
            c.execute("SELECT 1 FROM settings LIMIT 1").fetchone()
        return jsonify(status="ok", database="ok", time=now())
    except Exception as e:  # noqa: BLE001
        app.logger.warning("Health check gagal: %r", e)
        return jsonify(status="degraded", database="error", time=now()), 503

# -------------------------- Antarmuka --------------------------
# (Bagian HTML dan Javascript tetap SAMA, tidak ada yang diubah)

HTML = r"""<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#143e35">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>Rofi Jaya — Manajemen Pesanan & Produksi</title>
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/icon-192.png">
<style>
:root{--green:#143e35;--accent:#c9a66b;--bg:#f5f6f3;--line:#e4e8e3;
--text:#20372f;--muted:#718078;--red:#b43f3f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:14px/1.55 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
button,input,select,textarea{font:inherit}
button,.button{border:1px solid var(--line);background:#fff;color:var(--text);
padding:10px 15px;border-radius:9px;cursor:pointer;text-decoration:none;
display:inline-flex;align-items:center;justify-content:center;gap:6px;font-weight:600}
button:hover,.button:hover{filter:brightness(.97)}
button:disabled{opacity:.5;cursor:wait}
.primary{background:var(--green);color:white;border-color:var(--green)}
.danger{color:var(--red);border-color:#efcccc}
.wa{background:#e9f6ed;color:#21603c}
.small{padding:6px 10px;font-size:12px}
input,select,textarea{width:100%;padding:11px;border:1px solid #d9dfda;
border-radius:8px;background:white;color:var(--text)}
textarea{min-height:90px;resize:vertical}
input[type=checkbox]{width:18px;height:18px;accent-color:var(--green)}
input:focus,select:focus,textarea:focus{outline:2px solid #b4d0c3;outline-offset:1px}
label{display:block;font-size:12px;font-weight:650;margin:0 0 6px}
h1,h2,h3,p{margin-top:0}h1{font-size:28px;letter-spacing:-.7px;margin-bottom:5px}
h2{font-size:19px}h3{font-size:15px}
.muted{color:var(--muted)}.tiny{font-size:12px}.wrap{white-space:pre-wrap;overflow-wrap:anywhere}
.sidebar{position:fixed;inset:0 auto 0 0;width:238px;background:var(--green);
color:white;padding:30px 18px;display:flex;flex-direction:column;z-index:10}
.brand{display:flex;gap:12px;align-items:center;padding:0 10px 28px}
.monogram{width:43px;height:43px;border-radius:12px;background:var(--accent);
color:#173c31;display:grid;place-items:center;font-weight:850;letter-spacing:-2px;
font-size:21px;flex-shrink:0}
.brand strong{font-size:21px;display:block}.brand span{font-size:10px;color:#bfd0c7}
.nav{display:flex;flex-direction:column;gap:5px}
.nav button{background:none;border:0;color:#bed0c8;justify-content:flex-start;
padding:12px 15px;font-weight:500}
.nav button.active{background:#2d554b;color:white}
.nav button span{width:23px;font-size:17px}
.sidebar-bottom{margin-top:auto;border-top:1px solid #386054;padding:20px 10px 0}
.main{margin-left:238px;min-height:100vh}
.topbar{height:76px;background:#fff;border-bottom:1px solid var(--line);
padding:0 34px;display:flex;align-items:center;justify-content:space-between;gap:15px}
.content{max-width:1500px;margin:auto;padding:30px 34px 70px}
.head{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:24px}
.eyebrow{font-size:11px;letter-spacing:1.8px;font-weight:700;color:#7c8c81;margin-bottom:8px}
.card{background:white;border:1px solid var(--line);border-radius:13px;padding:22px;
margin-bottom:20px;box-shadow:0 3px 8px #203b2c03}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}
.stats .card{margin-bottom:0;padding:19px}.stat-number{font-size:30px;font-weight:750;margin:11px 0 2px}
.stat-icon{float:right;background:#edf2ed;border-radius:9px;padding:5px 9px;color:#4c7763}
.two{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.three{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.full{grid-column:1/-1}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.spread{justify-content:space-between}.stack{display:grid;gap:16px}
.notice{background:#f8f5eb;border:1px solid #eee4c7;color:#7a6537;
padding:13px 16px;border-radius:9px;margin:16px 0}
.info{background:#edf5f1;border-color:#dceae2;color:#3b6552}
.error{background:#fff0ed;border-color:#efd3cb;color:#a34231}
.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;text-align:left}
th{font-size:11px;letter-spacing:.4px;color:#7c8b82;background:#f8faf7;font-weight:600}
th,td{padding:15px 13px;border-bottom:1px solid #edf0eb;white-space:nowrap}
td{font-size:13px}tbody tr:hover{background:#fbfcf9}
td strong{font-weight:650}.link{color:var(--green);cursor:pointer;background:none;border:0;padding:0}
.badge{display:inline-block;padding:4px 9px;border-radius:6px;font-size:11px;
font-weight:650;background:#edf1ed;color:#62746b;white-space:nowrap}
.b-green{background:#e6f3e9;color:#34734b}.b-blue{background:#eaf1fc;color:#4b71a4}
.b-orange{background:#fbf0df;color:#a2762e}.b-red{background:#fbe9e6;color:#ad5242}
.b-purple{background:#f0eafa;color:#8061a4}
.filters{display:flex;gap:10px;flex-wrap:wrap;margin:20px 0}
.filters input{flex:2;min-width:180px}.filters select{flex:1;min-width:140px}
.empty{text-align:center;padding:50px 20px;color:var(--muted)}
.empty strong{display:block;color:var(--text);font-size:18px;margin-bottom:8px}
.tabs{display:flex;gap:7px;overflow:auto;padding:0 0 14px;margin-bottom:10px}
.tabs button{white-space:nowrap;background:transparent;border:0;font-size:13px}
.tabs button.active{background:var(--green);color:white}
.timeline{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:22px}
.step{padding:16px;border:1px solid var(--line);border-radius:10px;background:#fafbf8}
.step.done{background:#eaf4ee;border-color:#d5e6db}
.step.running{border-color:#7ba58e;background:#f3f8f4}
.step strong{display:block;margin:5px 0}
.dot{display:inline-grid;place-items:center;border-radius:50%;width:27px;height:27px;
background:#e2e9e2;color:#657b6c;font-weight:700}
.done .dot,.running .dot{background:var(--green);color:#fff}
.kv{display:grid;grid-template-columns:150px 1fr;gap:10px;font-size:13px}
.kv>span{color:var(--muted)}.kv>b{font-weight:550;white-space:pre-wrap;overflow-wrap:anywhere}
.check{display:flex;gap:10px;align-items:center;font-size:13px;font-weight:500;margin:12px 0}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:16px}
.photo{border:1px solid var(--line);border-radius:10px;overflow:hidden}
.photo img{width:100%;height:170px;object-fit:cover;display:block}
.photo-body{padding:12px}.history{border-left:2px solid #dde7de;padding-left:20px;margin-left:8px}
.history-item{position:relative;padding:0 0 22px}
.history-item:before{content:"";width:9px;height:9px;background:#8ca792;border-radius:50%;
position:absolute;left:-25px;top:6px}
details{margin:8px 0}summary{cursor:pointer;color:#64806d;font-size:12px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8f4;padding:12px;border-radius:8px;font-size:11px}
dialog{border:1px solid var(--line);border-radius:16px;padding:0;width:min(720px,95vw);
max-height:92vh;color:var(--text);box-shadow:0 30px 90px #102f3033}
dialog::backdrop{background:#0c211c88;backdrop-filter:blur(2px)}
.dialog-head{padding:20px 24px;border-bottom:1px solid var(--line);display:flex;
align-items:center;justify-content:space-between}
.dialog-head h2{margin:0}.dialog-body{padding:24px;overflow:auto}
.dialog-actions{display:flex;justify-content:flex-end;gap:9px;margin-top:22px;flex-wrap:wrap}
#toast{position:fixed;bottom:25px;left:50%;transform:translateX(-50%);
background:#173e33;color:white;padding:13px 22px;border-radius:10px;z-index:100;
max-width:90vw;display:none;box-shadow:0 8px 35px #0002}
#toast.bad{background:#9c3d30}
.login{max-width:430px;margin:12vh auto;padding:30px}
.login .monogram{margin-bottom:22px}.login input{margin:8px 0 20px}
.mobile-menu{display:none}.logo{width:42px;height:42px;border-radius:10px;object-fit:cover}
#print-area{display:none}
@media(min-width:1600px){.content{padding-top:40px}}
@media(max-width:1150px){.sidebar{width:210px}.main{margin-left:210px}
.content{padding:25px}.grid{grid-template-columns:repeat(2,1fr)}.two{grid-template-columns:1fr}}
@media(max-width:760px){.sidebar{transform:translateX(-100%);width:250px;transition:transform .15s}
.sidebar.open{transform:none;box-shadow:0 0 0 100vw #0b221a88}
.main{margin-left:0}.mobile-menu{display:inline-flex}.topbar{height:65px;padding:0 16px}
.content{padding:22px 16px 45px}.head{align-items:flex-start}.head h1{font-size:23px}
.head>.primary{font-size:12px;padding:10px;white-space:nowrap}
.grid{gap:10px}.stats .card{padding:14px}.stat-number{font-size:26px}
.card{padding:17px}.form-grid,.three{grid-template-columns:1fr}
.timeline{grid-template-columns:repeat(2,1fr)}.kv{grid-template-columns:120px 1fr}
.topbar .date-text{display:none}.dialog-body{padding:18px}.login{margin:8vh 16px}
}
@media print{body{background:white;color:black}#app,dialog,#toast{display:none!important}
#print-area{display:block;padding:24px;font-size:12px}
#print-area table{margin:20px 0}#print-area h1{font-size:25px}
#print-area .card{box-shadow:none;border:0;padding:0}
@page{size:A4;margin:15mm}}
</style>
</head>
<body>
<div id="app"><div class="login card">Memuat aplikasi…</div></div>
<dialog id="modal">
 <div class="dialog-head"><h2 id="modal-title"></h2>
 <button type="button" id="close-modal" class="small">Tutup ×</button></div>
 <div class="dialog-body" id="modal-body"></div>
</dialog>
<div id="toast" role="status" aria-live="polite"></div>
<div id="print-area"></div>
<script>
const $ = (q, root=document) => root.querySelector(q);
const $$ = (q, root=document) => [...root.querySelectorAll(q)];
const esc = v => String(v ?? "").replace(/[&<>"']/g,c=>(
 {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const rp = v => new Intl.NumberFormat('id-ID',{
 style:'currency',currency:'IDR',maximumFractionDigits:0
}).format(v||0);
const fmt = v => v ? new Date(v.length===10?v+'T12:00:00':v)
 .toLocaleDateString('id-ID',{day:'numeric',month:'short',year:'numeric'}) : '—';
const dt = v => v ? new Date(v).toLocaleString('id-ID') : '—';
const STAGES=['Potong Bahan','Jahit','Finishing & QC'];
const LIFE={active:'Aktif',paused:'Ditunda',cancelled:'Dibatalkan',
 done:'Selesai dan Lunas',unpaid:'Selesai tetapi Belum Lunas',archived:'Diarsipkan'};
let S=null,csrf='',view='dashboard',selected='',tab='ringkasan';
let filter={q:'',status:'',pay:'',ship:'',garment:'',from:'',to:'',sort:'target'};
let pendingInstall=null,toastTimer,draft=null;
const modal=$('#modal');

function toast(message,bad=false){
 const t=$('#toast'); t.textContent=message;t.className=bad?'bad':'';
 t.style.display='block';clearTimeout(toastTimer);
 toastTimer=setTimeout(()=>t.style.display='none',6000);
}
async function api(path,body){
 let r;
 try{
  r=await fetch('/api/'+path,{
   method:body===undefined?'GET':'POST',
   headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},
   credentials:'same-origin',
   ...(body===undefined?{}:{body:JSON.stringify(body)})
  });
 }catch{
  throw Error('Tidak bisa menghubungi server. Periksa koneksi internet Anda.');
 }
 let result;
 try{result=await r.json()}catch{throw Error('Respons server tidak valid.')}
 if(!r.ok){
  if(r.status===401){S=null;modal.close();loginScreen()}
  throw Error(result.error||'Permintaan gagal.');
 }
 return result;
}
async function load(){
 S=await api('state');csrf=S.csrf;render();
}
async function mutate(o,action,data={}){
 let result;
 try{
  result=await api('orders/'+o.id+'/action',{action,version:o.version,...data});
 }catch(e){
  // Konflik versi: data berubah di tab lain. Muat ulang lalu beri tahu.
  if(/berubah pada tab|Data berubah/.test(e.message)){
   await load();
   throw Error('Data pesanan berubah di tab atau perangkat lain. '
    +'Form sudah dimuat ulang — periksa kembali sebelum menyimpan.');
  }
  throw e;
 }
 await load();
 toast('Perubahan tersimpan ke database server.');
 return result;
}
function formData(form){return Object.fromEntries(new FormData(form))}
function bindForm(id,handler){
 const form=$('#'+id);if(!form)return;
 form.onsubmit=async e=>{
  e.preventDefault();
  const buttons=$$('button[type=submit]',form);
  buttons.forEach(x=>x.disabled=true);
  try{await handler(formData(form),form,e.submitter)}
  catch(err){toast(err.message,true)}
  finally{buttons.forEach(x=>x.disabled=false)}
 };
}
function dialog(title,body){
 $('#modal-title').textContent=title;$('#modal-body').innerHTML=body;
 if(!modal.open)modal.showModal();
}
$('#close-modal').onclick=()=>modal.close();
modal.addEventListener('click',e=>{if(e.target===modal)modal.close()});
function buttons(label='Simpan'){
 return `<div class="dialog-actions"><button type="submit" class="primary">${label}</button></div>`;
}
function field(label,name,value='',type='text',extra=''){
 return `<div><label for="f-${name}">${esc(label)}</label>
 <input id="f-${name}" name="${name}" type="${type}" value="${esc(value)}" ${extra}></div>`;
}
function area(label,name,value='',extra=''){
 return `<div class="full"><label for="f-${name}">${esc(label)}</label>
 <textarea id="f-${name}" name="${name}" ${extra}>${esc(value)}</textarea></div>`;
}
function selectField(label,name,options,value=''){
 return `<div><label>${esc(label)}</label><select name="${name}">${
 options.map(x=>`<option value="${esc(x)}" ${x===value?'selected':''}>${esc(x)}</option>`).join('')
 }</select></div>`;
}
function kv(rows){
 return `<div class="kv">${rows.map(([k,v])=>`<span>${esc(k)}</span><b>${esc(v||'—')}</b>`).join('')}</div>`;
}
function badge(s){
 let cls='b-blue';
 if(/Lunas|Selesai|Diterima/.test(s))cls='b-green';
 if(/Jahit|Cicilan/.test(s))cls='b-purple';
 if(/Finishing|DP|Ditunda|Menunggu/.test(s))cls='b-orange';
 if(/Belum|Dibatalkan|Terlambat|Perlu|Kekurangan/.test(s))cls='b-red';
 return `<span class="badge ${cls}">${esc(s)}</span>`;
}
function empty(title,message=''){
 return `<div class="empty"><strong>${esc(title)}</strong>${esc(message)}</div>`;
}
function current(){return S.orders.find(o=>o.id===selected)}
function canChange(o){return ['active','paused','unpaid'].includes(o.life)}
function go(v){
 view=v;selected='';filter={q:'',status:'',pay:'',ship:'',garment:'',from:'',to:'',sort:'target'};
 render();window.scrollTo(0,0);
}
function detail(id){
 selected=id;view='detail';tab='ringkasan';render();window.scrollTo(0,0);
}
function loginScreen(){
 $('#app').innerHTML=`<form id="login-form" class="login card">
 <div class="monogram">RJ</div><div class="eyebrow">MANAJEMEN KONVEKSI</div>
 <h1>Selamat datang.</h1><p class="muted">Masuk untuk mengelola pesanan Rofi Jaya.</p>
 <label>Kata sandi owner</label>
 <input type="password" name="password" minlength="12" required autocomplete="current-password">
 <button type="submit" class="primary" style="width:100%">Masuk ke aplikasi →</button>
 <p class="muted tiny" style="margin:20px 0 0">Akses khusus owner. Jangan bagikan kata sandi Anda.</p>
 </form>`;
 bindForm('login-form',async d=>{
  const r=await api('login',d);csrf=r.csrf;await load();
 });
}
function render(){
 if(!S)return loginScreen();
 const nav=[
  ['dashboard','◫','Dashboard'],['orders','▤','Daftar Pesanan'],
  ['gallery','▧','Galeri Produksi'],['issues','⚑','Revisi & Kendala'],
  ['payments','◉','Pembayaran'],['shipping','▱','Pengiriman'],
  ['history','↺','Riwayat Pesanan'],['settings','⚙','Pengaturan']
 ];
 const activeView=view==='detail'||view==='new'?'orders':view;
 $('#app').innerHTML=`
 <aside class="sidebar" id="sidebar">
 <div class="brand">${S.settings.logo?`<img class="logo" src="${esc(S.settings.logo)}" alt="">`:
 '<div class="monogram">RJ</div>'}
 <div><strong>${esc(S.settings.name)}</strong><span>MANAJEMEN KONVEKSI</span></div></div>
 <nav class="nav">${nav.map(([id,icon,label])=>`
 <button data-nav="${id}" class="${activeView===id?'active':''}">
 <span>${icon}</span>${label}</button>`).join('')}</nav>
 <div class="sidebar-bottom"><strong>Ruang kerja owner</strong>
 <p class="tiny" style="color:#bfd0c7;margin:5px 0 15px">Pesanan rapi. Produksi terkendali.</p>
 <button id="logout" class="small">Keluar</button>
 <button id="install" class="small" style="${pendingInstall?'':'display:none'}">Instal</button>
 </div></aside>
 <div class="main"><header class="topbar">
 <div class="row"><button class="mobile-menu small" id="menu">☰ Menu</button>
 <span class="muted tiny">${esc(nav.find(n=>n[0]===activeView)?.[2]||'Pesanan')}</span></div>
 <div class="row"><span class="muted tiny date-text">${fmt(S.today)}</span>
 <button class="small" id="refresh" title="Muat ulang data dari server">↻ Perbarui</button>
 <span class="badge ${navigator.onLine?'b-green':'b-red'}" id="connection">
 ${navigator.onLine?'● Terhubung ke server':'● Offline · hanya tampilan terakhir'}</span>
 <span class="monogram" style="width:32px;height:32px;font-size:13px;letter-spacing:0">O</span></div>
 </header><main class="content" id="content"></main></div>`;
 $$('[data-nav]').forEach(b=>b.onclick=()=>go(b.dataset.nav));
 $('#menu').onclick=()=>$('#sidebar').classList.toggle('open');
 $('#refresh').onclick=async()=>{
  try{await load();toast('Data diperbarui dari server.')}
  catch(e){toast(e.message,true)}
 };
 $('#logout').onclick=async()=>{
  if(!confirm('Keluar dari aplikasi?'))return;
  try{await api('logout',{});S=null;loginScreen()}catch(e){toast(e.message,true)}
 };
 $('#install').onclick=async()=>{if(pendingInstall){await pendingInstall.prompt();pendingInstall=null}};
 const c=$('#content');
 if(view==='dashboard'||view==='orders'||view==='history')renderList(c);
 else if(view==='new')renderOrderForm(c);
 else if(view==='detail')renderDetail(c);
 else if(view==='settings')renderSettings(c);
 else renderAggregate(c);
}
function heading(title,subtitle,action=''){
 return `<div class="head"><div><div class="eyebrow">ROFI JAYA · RUANG KERJA OWNER</div>
 <h1>${esc(title)}</h1><p class="muted" style="margin-bottom:0">${esc(subtitle)}</p></div>${action}</div>`;
}
function listRows(){
 const history=view==='history';
 let rows=S.orders.filter(o=>history?o.life!=='active':o.life==='active');
 if(filter.q)rows=rows.filter(o=>(o.customer+' '+o.number).toLowerCase().includes(filter.q.toLowerCase()));
 if(filter.status==='Terlambat')rows=rows.filter(o=>o.late);
 else if(filter.status)rows=rows.filter(o=>o.status===filter.status||LIFE[o.life]===filter.status);
 if(filter.pay)rows=rows.filter(o=>filter.pay==='Belum Lunas'?o.remaining>0:o.payment_status===filter.pay);
 if(filter.ship)rows=rows.filter(o=>(
  o.received?'Barang Diterima':o.shipping?'Dikirim':'Belum Dikirim'
 )===filter.ship);
 if(filter.garment)rows=rows.filter(o=>o.garment===filter.garment);
 if(filter.from)rows=rows.filter(o=>o.deal>=filter.from);
 if(filter.to)rows=rows.filter(o=>o.deal<=filter.to);
 rows.sort((a,b)=>filter.sort==='recent'?b.created.localeCompare(a.created):
 a.target.localeCompare(b.target));
 return rows;
}
function renderList(c){
 const dash=view==='dashboard',history=view==='history';
 const active=S.orders.filter(o=>o.life==='active');
 const metrics=[
  ['Pesanan aktif',active.length,'◫',''],
  ['Pesanan baru',active.filter(o=>o.status==='Pesanan Baru').length,'＋','Pesanan Baru'],
  ['Sedang dipotong',active.filter(o=>o.status==='Potong Bahan').length,'✂','Potong Bahan'],
  ['Sedang dijahit',active.filter(o=>o.status==='Jahit').length,'⌁','Jahit'],
  ['Tahap finishing',active.filter(o=>o.status==='Finishing & QC').length,'✓','Finishing & QC'],
  ['Siap kirim',active.filter(o=>o.status==='Siap Kirim').length,'▱','Siap Kirim'],
  ['Lewat estimasi',active.filter(o=>o.late).length,'◷','Terlambat'],
  ['Belum lunas',S.orders.filter(o=>['active','paused','unpaid'].includes(o.life)&&o.remaining>0).length,'◉','unpaid']
 ];
 c.innerHTML=heading(dash?'Gambaran usaha Anda':history?'Riwayat pesanan':'Daftar pesanan',
 dash?'Pantau pesanan, proses produksi, dan pembayaran dalam satu tempat.':
 history?'Pesanan selesai, ditunda, dibatalkan, dan diarsipkan tetap tersimpan.':
 'Kelola seluruh pesanan yang sedang aktif.',
 '<button class="primary" id="new-order">＋ Tambah Pesanan</button>')+
 (dash?`<div class="grid stats">${metrics.map(([label,n,icon,key])=>`
 <button class="card" data-metric="${key}" style="display:block;text-align:left;font-weight:400">
 <span class="stat-icon">${icon}</span><span class="muted tiny">${label}</span>
 <div class="stat-number">${n}</div><span class="muted tiny">pesanan</span></button>`).join('')}</div>
 <div class="notice info">Semua angka berasal dari database. Tahap produksi hanya selesai setelah konfirmasi owner.</div>`:'')+
 `<section class="card"><div class="row spread"><h2 style="margin:0">${
 dash?'Pesanan terbaru':history?'Arsip & riwayat':'Pesanan aktif'}</h2>
 <span class="muted tiny" id="result-count"></span></div>
 <div class="filters">
 <input id="search" placeholder="Cari nama konsumen atau nomor pesanan…" value="${esc(filter.q)}">
 <select id="filter-status"><option value="">Semua status</option>${
 ['Pesanan Baru','Potong Bahan','Menunggu Jahit','Jahit','Menunggu Finishing',
 'Finishing & QC','Siap Kirim','Dikirim','Barang Diterima','Terlambat',
 ...(history?Object.values(LIFE).filter(x=>x!=='Aktif'):[])].map(x=>`
 <option ${filter.status===x?'selected':''}>${x}</option>`).join('')}</select>
 <select id="filter-pay"><option value="">Semua pembayaran</option>${
 ['Belum Bayar','DP Dibayar','Cicilan','Lunas','Belum Lunas'].map(x=>`
 <option ${filter.pay===x?'selected':''}>${x}</option>`).join('')}</select>
 <select id="sort"><option value="target" ${filter.sort==='target'?'selected':''}>Target terdekat</option>
 <option value="recent" ${filter.sort==='recent'?'selected':''}>Pesanan terbaru</option></select></div>
 ${history?`<div class="form-grid" style="margin-bottom:20px">
 <div><label>Tanggal deal dari</label><input type="date" id="filter-from" value="${filter.from}"></div>
 <div><label>Tanggal deal sampai</label><input type="date" id="filter-to" value="${filter.to}"></div>
 <div><label>Jenis pakaian</label><select id="filter-garment"><option value="">Semua jenis</option>${
 [...new Set(S.orders.map(o=>o.garment))].map(x=>`<option ${x===filter.garment?'selected':''}>${esc(x)}</option>`).join('')
 }</select></div><div><label>Pengiriman</label><select id="filter-ship"><option value="">Semua pengiriman</option>${
 ['Belum Dikirim','Dikirim','Barang Diterima'].map(x=>`<option ${x===filter.ship?'selected':''}>${x}</option>`).join('')
 }</select></div></div>`:''}
 <div id="order-table"></div></section>`;
 $('#new-order').onclick=()=>{view='new';render()};
 if(dash)$$('[data-metric]').forEach(b=>b.onclick=()=>{
  if(b.dataset.metric==='unpaid'){go('payments');return}
  view='orders';filter.status=b.dataset.metric;render();
 });
 $('#search').oninput=e=>{filter.q=e.target.value;drawTable()};
 for(const [id,key] of [
 ['filter-status','status'],['filter-pay','pay'],['sort','sort'],
 ['filter-from','from'],['filter-to','to'],['filter-garment','garment'],['filter-ship','ship']
 ]){
  if($('#'+id))$('#'+id).onchange=e=>{filter[key]=e.target.value;drawTable()};
 }
 drawTable();
}
function drawTable(){
 let rows=listRows();$('#result-count').textContent=rows.length+' pesanan';
 if(!rows.length){
  $('#order-table').innerHTML=empty('Belum ada pesanan yang cocok',
   S.orders.length?'Ubah pencarian atau filter Anda.':'Mulai dengan tombol Tambah Pesanan.');
  return;
 }
 $('#order-table').innerHTML=`<div class="table-wrap"><table><thead><tr>
 <th>NO. PESANAN</th><th>KONSUMEN</th><th>JENIS / JUMLAH</th>
 <th>TARGET SELESAI</th><th>PRODUKSI</th><th>PEMBAYARAN</th><th></th>
 </tr></thead><tbody>${rows.map(o=>`<tr>
 <td><button class="link" data-detail="${o.id}"><strong>${esc(o.number)}</strong></button>
 ${o.life!=='active'?`<div class="tiny muted">${esc(LIFE[o.life])}</div>`:''}</td>
 <td><strong>${esc(o.customer)}</strong><div class="muted tiny">+${esc(o.wa)}</div></td>
 <td>${esc(o.garment)}<div class="muted tiny">${o.qty} pcs</div></td>
 <td>${fmt(o.target)}${o.late?'<div>'+badge('Terlambat')+'</div>':''}</td>
 <td>${badge(o.status)}</td><td>${badge(o.payment_status)}<div class="tiny muted">
 ${o.remaining?rp(o.remaining):'Pembayaran lengkap'}</div></td>
 <td><button class="small" data-detail="${o.id}">Detail →</button></td>
 </tr>`).join('')}</tbody></table></div>`;
 bindDetails();
}
function bindDetails(){$$('[data-detail]').forEach(b=>b.onclick=()=>detail(b.dataset.detail))}
function orderFields(o={},editing=false){
 let target=o.target;
 if(!target){
  const d=new Date(S.today+'T12:00:00');d.setDate(d.getDate()+S.settings.default_days);
  target=d.toISOString().slice(0,10);
 }
 return `<div class="form-grid">
 <h3 class="full">01 · Informasi konsumen</h3>
 ${field('Nama konsumen / instansi *','customer',o.customer||'','text','required maxlength="150"')}
 ${field('Nomor WhatsApp *','wa',o.wa||'','tel','required placeholder="0812… atau +62…"')}
 ${area('Alamat pengiriman','address',o.address||'')}
 ${area('Catatan konsumen','customer_note',o.customer_note||'')}
 <h3 class="full" style="margin:8px 0 0">02 · Kesepakatan pesanan</h3>
 ${field('Tanggal deal *','deal',o.deal||S.today,'date','required')}
 ${field('Rencana mulai pengerjaan','work_start',o.work_start||'','date')}
 <div><label>Jenis pakaian *</label><input name="garment" list="garments"
 value="${esc(o.garment||'')}" required placeholder="Pilih atau ketik jenis lainnya">
 <datalist id="garments">${S.settings.garments.map(x=>`<option value="${esc(x)}">`).join('')}</datalist></div>
 <div><label>Jenis bahan *</label><input name="material" list="materials"
 value="${esc(o.material||'')}" required placeholder="Pilih atau ketik bahan lainnya">
 <datalist id="materials">${S.settings.materials.map(x=>`<option value="${esc(x)}">`).join('')}</datalist></div>
 ${field('Warna kain','color',o.color||'')}
 ${field('Jumlah pakaian (pcs) *','qty',o.qty||1,'number','min="1" max="1000000" required')}
 ${field('Rincian ukuran — contoh S:10, M:20, L:20','sizes',
 Object.entries(o.sizes||{}).map(([k,v])=>k+':'+v).join(', '),'text','placeholder="Opsional; total harus sesuai jumlah"')}
 ${field('Estimasi selesai produksi *','target',target,'date','required')}
 ${area('Model / spesifikasi','spec',o.spec||'')}
 ${area('Catatan khusus / kebutuhan bahan','special',o.special||'')}
 <h3 class="full" style="margin:8px 0 0">03 · Harga dan pembayaran</h3>
 ${field('Harga kesepakatan total (Rp) *','total',o.total||0,'number','min="0" step="1" required')}
 ${editing?`<div><label>Pembayaran sudah diterima</label><input disabled value="${esc(rp(o.paid))}"></div>`:
 field('DP awal (Rp)','dp',0,'number','min="0" step="1" required')}
 <div class="full notice info" id="balance-preview"></div>
 ${editing?area('Alasan revisi * — perubahan lama dan baru akan disimpan','reason','','required'):''}
 </div>`;
}
function parseOrder(d){
 const sizes={};
 if(d.sizes.trim()){
  for(const part of d.sizes.split(',')){
   const pair=part.trim().split(':');
   if(pair.length!==2||!pair[0].trim()||!/^\d+$/.test(pair[1].trim()))
    throw Error('Format ukuran harus seperti S:10, M:20, L:20.');
   const key=pair[0].trim();
   if(key in sizes)throw Error('Ukuran tidak boleh ditulis dua kali.');
   sizes[key]=Number(pair[1].trim());
  }
 }
 if(Object.keys(sizes).length&&Object.values(sizes).reduce((a,b)=>a+b,0)!==Number(d.qty))
  throw Error('Jumlah rincian ukuran harus sama dengan jumlah pesanan.');
 return {...d,sizes};
}
function bindBalance(form,o=null){
 const update=()=>{
  const total=Number(form.elements.total.value)||0;
  const received=o?o.paid:Number(form.elements.dp.value)||0;
  $('#balance-preview',form).textContent='Sisa pembayaran: '+rp(total-received)+
   ' · DP adalah bagian dari harga kesepakatan, bukan biaya tambahan.';
 };
 form.elements.total.oninput=update;
 if(!o)form.elements.dp.oninput=update;
 update();
}
function renderOrderForm(c){
 c.innerHTML=heading('Tambah pesanan','Catat kesepakatan sebelum pekerjaan dimulai.',
 '<button id="back-list">← Kembali</button>')+
 `<form id="order-form" class="card" style="max-width:1000px">${orderFields()}
 <div class="dialog-actions"><button type="submit" class="primary">Tinjau ringkasan →</button></div></form>`;
 $('#back-list').onclick=()=>go('orders');
 bindBalance($('#order-form'));
 bindForm('order-form',async d=>{
  const data=parseOrder(d);
  if(Number(data.dp)>Number(data.total))throw Error('DP melebihi harga kesepakatan.');
  draft=data;
  dialog('Ringkasan sebelum disimpan',kv([
   ['Konsumen',data.customer],['WhatsApp',data.wa],['Alamat',data.address],
   ['Pesanan',data.garment+' · '+data.qty+' pcs'],
   ['Bahan / warna',data.material+' / '+data.color],
   ['Spesifikasi',data.spec],['Ukuran',d.sizes],
   ['Harga deal',rp(data.total)],['DP',rp(data.dp)],
   ['Sisa pembayaran',rp(Number(data.total)-Number(data.dp))],
   ['Estimasi selesai',fmt(data.target)]
  ])+`<p class="notice info">Status awal: Pesanan Baru. Tidak ada tahap yang otomatis selesai.</p>
  <div class="dialog-actions"><button id="save-only">Simpan Pesanan</button>
  <button class="primary" id="save-detail">Simpan & Lihat Detail</button></div>`);
  const save=async open=>{
   $('#save-only').disabled=true;$('#save-detail').disabled=true;
   try{
    const r=await api('orders',draft);modal.close();await load();
    if(open)detail(r.id);else go('orders');
    toast('Pesanan berhasil dibuat.');
   }catch(e){
    toast(e.message,true);
    if($('#save-only')){$('#save-only').disabled=false;$('#save-detail').disabled=false}
   }
  };
  $('#save-only').onclick=()=>save(false);$('#save-detail').onclick=()=>save(true);
 });
}
function editOrder(o){
 dialog('Revisi kesepakatan',`<form id="edit-form">${orderFields(o,true)}
 <div class="notice">Perubahan spesifikasi, harga, dan target akan dicatat beserta nilai sebelumnya.
 Perubahan jadwal dapat memengaruhi komitmen kepada konsumen.</div>${buttons('Simpan Revisi')}</form>`);
 bindBalance($('#edit-form'),o);
 bindForm('edit-form',async d=>{
  if(!confirm('Simpan revisi kesepakatan dan riwayat perubahannya?'))return;
  await mutate(o,'edit',{order:parseOrder(d),reason:d.reason});modal.close();
 });
}
function renderDetail(c){
 const o=current();if(!o){go('orders');return}
 c.innerHTML=heading(o.customer,o.number+' · '+o.garment+' · '+o.qty+' pcs',
 '<button id="back-detail">← Daftar Pesanan</button>')+
 `<div class="row spread" style="margin:-8px 0 24px">
 <div class="row">${badge(o.status)}${badge(o.payment_status)}
 ${o.life!=='active'?badge(LIFE[o.life]):''}${o.late?badge('Terlambat'):''}</div>
 <div class="row"><button id="wa-button" class="wa small">↗ Bagikan ke WhatsApp</button>
 <button id="invoice" class="small">Cetak / PDF</button></div></div>
 <div class="tabs">${[
 ['ringkasan','Ringkasan'],['produksi','Timeline Produksi'],['foto','Foto'],
 ['kendala','Revisi & Kendala'],['pembayaran','Pembayaran'],
 ['pengiriman','Pengiriman'],['aktivitas','Riwayat Aktivitas']
 ].map(([id,label])=>`<button data-tab="${id}" class="${tab===id?'active':''}">${label}</button>`).join('')}</div>
 <div id="detail-body"></div>`;
 $('#back-detail').onclick=()=>go('orders');
 $('#wa-button').onclick=()=>waDialog(o);
 $('#invoice').onclick=()=>invoice(o);
 $$('[data-tab]').forEach(b=>b.onclick=()=>{tab=b.dataset.tab;render()});
 const b=$('#detail-body');
 if(tab==='ringkasan')summaryTab(b,o);
 if(tab==='produksi')productionTab(b,o);
 if(tab==='foto')photosTab(b,o);
 if(tab==='kendala')issuesTab(b,o);
 if(tab==='pembayaran')paymentsTab(b,o);
 if(tab==='pengiriman')shippingTab(b,o);
 if(tab==='aktivitas')historyTab(b,o);
}
function summaryTab(b,o){
 b.innerHTML=`<div class="two"><div class="card">
 <div class="row spread"><h2>Kesepakatan pesanan</h2>
 ${o.life==='active'&&!o.shipping?'<button id="edit-order" class="small">Edit / Revisi</button>':''}</div>
 ${kv([['Konsumen',o.customer],['WhatsApp','+'+o.wa],['Alamat',o.address],
 ['Tanggal deal',fmt(o.deal)],['Rencana mulai',fmt(o.work_start)],
 ['Jenis pakaian',o.garment],['Jumlah',o.qty+' pcs'],
 ['Ukuran',Object.entries(o.sizes).map(([k,v])=>k+': '+v).join(' · ')],
 ['Bahan',o.material],['Warna',o.color],['Spesifikasi',o.spec],
 ['Catatan konsumen',o.customer_note],['Catatan khusus',o.special]])}</div>
 <div><div class="card"><h2>Ringkasan tagihan</h2>
 ${kv([['Harga deal',rp(o.total)],['Sudah diterima',rp(o.paid)],
 ['Sisa pembayaran',rp(o.remaining)],['Status',o.payment_status],
 ['Target selesai',fmt(o.target)]])}</div>
 <div class="card"><h2>Kelola status pesanan</h2><p class="muted tiny">
 Pembatalan dan arsip tidak menghapus pembayaran, foto, atau riwayat.
 Pembatalan tidak otomatis mengembalikan pembayaran.</p><div class="row">
 ${o.life==='active'?'<button data-life="paused">Tunda</button><button data-life="cancelled" class="danger">Batalkan</button>':''}
 ${['paused','unpaid'].includes(o.life)?'<button data-life="active" class="primary">Aktifkan kembali</button>':''}
 ${o.life==='paused'?'<button data-life="cancelled" class="danger">Batalkan</button>':''}
 ${['done','cancelled'].includes(o.life)?'<button data-life="archived">Arsipkan</button>':''}
 ${o.life==='active'&&o.received&&o.remaining>0?'<button data-life="unpaid">Pengecualian: selesai belum lunas</button>':''}
 ${['archived','done'].includes(o.life)?'<p class="muted">Riwayat ini tetap dapat dibuka dan dicetak.</p>':''}
 </div></div></div></div>`;
 if($('#edit-order'))$('#edit-order').onclick=()=>editOrder(o);
 $$('[data-life]').forEach(btn=>btn.onclick=()=>{
  const target=btn.dataset.life;
  dialog('Ubah status: '+LIFE[target],`<form id="life-form">
  <p class="notice">Perubahan ini masuk ke riwayat. Pastikan sesuai kondisi sebenarnya.</p>
  ${area('Alasan perubahan *','reason','','required')}${buttons('Konfirmasi Perubahan')}</form>`);
  bindForm('life-form',async d=>{
   await mutate(o,'life',{life:target,reason:d.reason});modal.close();
  });
 });
}
function productionTab(b,o){
 b.innerHTML=`<div class="timeline">${o.stages.map((s,i)=>`
 <div class="step ${s.state}"><span class="dot">${s.state==='done'?'✓':i+1}</span>
 <strong>${STAGES[i]}</strong><span class="tiny muted">${
 s.state==='done'?'Selesai '+fmt(s.finished):s.state==='running'?'Sedang berjalan':
 i===0||o.stages[i-1].state==='done'?'Siap dimulai':'Belum dibuka'}</span></div>`).join('')}
 <div class="step ${o.ready_at?'done':''}"><span class="dot">${o.ready_at?'✓':'4'}</span>
 <strong>Siap Kirim</strong><span class="tiny muted">${o.ready_at?fmt(o.ready_at):'Setelah finishing & QC'}</span></div></div>
 ${o.stages.map((s,i)=>`<div class="card">
 <div class="row spread"><h2>${i+1}. ${STAGES[i]}</h2>
 ${badge(s.state==='done'?'Selesai':s.state==='running'?'Sedang Berjalan':'Belum Dimulai')}</div>
 ${kv([['Mulai aktual',fmt(s.start)],['Estimasi selesai',fmt(s.estimate)],
 ['Selesai aktual',s.finished?dt(s.finished):'Belum selesai'],['Catatan / kebutuhan bahan',s.note]])}
 ${s.state==='running'&&s.estimate<S.today?'<p class="notice error">Tahap melewati estimasi. Status tetap berjalan sampai dikonfirmasi owner.</p>':''}
 <div class="row" style="margin-top:20px">
 ${o.life==='active'&&s.state==='pending'&&(i===0||o.stages[i-1].state==='done')?
 `<button class="primary" data-start="${i}">Mulai ${i===0?'Potong':i===1?'Jahit':'Finishing'}</button>`:''}
 ${o.life==='active'&&s.state==='running'?`
 <button data-stage-edit="${i}">Catatan & Estimasi</button>
 <button class="primary" data-finish="${i}">Selesaikan ${i===0?'Tahap Potong':i===1?'Tahap Jahit':'Finishing'}</button>`:''}
 ${canChange(o)?`<button data-stage-photo="${i}">＋ Foto</button>`:''}
 ${o.life==='active'?'<button data-add-issue>Catat Kendala</button>':''}
 <button class="wa" data-stage-wa="${i}">Bagikan Progres</button>
 <button class="small" data-stage-notify="${i}">Kirim Ulang + Foto</button></div>
 ${s.state==='running'&&o.notified?`<p class="muted tiny">Notifikasi WhatsApp terakhir:
 <b>${esc(o.notified.ok?'berhasil':'gagal')}</b> · ${dt(o.notified.at)} —
 ${esc(o.notified.message||'')}</p>`:''}
 ${i===2?qcSection(o):''}
 </div>`).join('')}`;
 $$('[data-start]').forEach(btn=>btn.onclick=()=>stageDialog(o,+btn.dataset.start,false));
 $$('[data-stage-edit]').forEach(btn=>btn.onclick=()=>stageDialog(o,+btn.dataset.stageEdit,true));
 $$('[data-finish]').forEach(btn=>btn.onclick=async()=>{
  const i=+btn.dataset.finish;
  if(!confirm(`Konfirmasi ${STAGES[i]} benar-benar selesai? Waktu aktual akan dicatat.`))return;
  try{await mutate(o,'finish',{stage:i})}catch(e){toast(e.message,true)}
 });
 $$('[data-stage-photo]').forEach(btn=>btn.onclick=()=>photoDialog(o,STAGES[+btn.dataset.stagePhoto]));
 $$('[data-stage-wa]').forEach(btn=>btn.onclick=()=>waDialog(o,['potong','jahit','finishing'][+btn.dataset.stageWa]));
 $$('[data-stage-notify]').forEach(btn=>btn.onclick=()=>notifyStageDialog(o,STAGES[+btn.dataset.stageNotify]));
 $$('[data-add-issue]').forEach(btn=>btn.onclick=()=>issueDialog(o));
 if($('#qc-form'))bindForm('qc-form',async d=>{
  if(d.approval.trim()&&!confirm('Setujui pengecualian QC secara eksplisit dengan alasan yang ditulis?'))return;
  await mutate(o,'qc',d);
 });
 if($('#checklist-form'))bindForm('checklist-form',async(d,f)=>{
  await mutate(o,'checklist',{values:$$('input[type=checkbox]',f).map(x=>x.checked)});
 });
}
function stageDialog(o,i,edit){
 const s=o.stages[i];
 const canUpload=!edit&&o.life==='active';
 // Centang menentukan pengiriman tahap ini. Sakelar di Pengaturan hanya
 // menentukan apakah centangnya sudah terpasang sejak awal.
 const autoOn=!!S.settings.auto_notify;
 const hasToken=!!S.fonnte_configured;
 const hasWa=!!o.wa;
 const canNotify=hasToken&&hasWa;
 const notifyNote=!hasToken
  ?'Token Fonnte belum dipasang di server — set FONNTE_TOKEN lewat fly secrets.'
  :!hasWa
  ?'Nomor WhatsApp konsumen belum terisi pada pesanan ini.'
  :!autoOn
  ?'Notifikasi otomatis sedang dimatikan di Pengaturan, jadi centang ini '
   +'tidak terpasang sendiri. Centang manual bila tahap ini ingin dikirim.'
  :'Berlaku untuk semua tahap. Foto + catatan dikirim ke '+o.wa
   +'. Jika gagal, tahap tetap tersimpan dan Anda bisa mengirim ulang dari '
   +'tab Timeline Produksi.';
 dialog((edit?'Perbarui ':'Mulai ')+STAGES[i],`<form id="stage-form"><div class="form-grid">
 ${edit?'':field('Tanggal mulai aktual *','start',S.today,'date',`required max="${S.today}"`)}
 ${field('Estimasi selesai tahap *','estimate',s.estimate||o.target,'date','required')}
 ${area('Catatan pengerjaan / kebutuhan bahan','note',s.note)}
 ${canUpload?`<div class="full"><label>Foto hasil ${esc(STAGES[i])} — galeri atau kamera</label>
 <input id="stage-photos" type="file" accept="image/jpeg,image/png,image/webp" multiple>
 <label class="check" style="margin-top:10px"><input type="checkbox" id="stage-camera">
 Ambil dari kamera (bukan galeri)</label>
 <div style="margin-top:10px">${area('Keterangan foto (opsional)','caption')}</div>
 <p class="muted tiny">Maksimal 5 MB per foto. Foto dikompresi, disimpan di server,
 lalu ikut dikirim ke konsumen bersama pembaruan tahap ini.</p></div>
 <div class="full"><label class="check"><input type="checkbox" name="notify" ${
 canNotify&&autoOn?'checked':''} ${canNotify?'':'disabled'}>
 Kirim pembaruan + foto ke WhatsApp konsumen</label>
 <p class="muted tiny">${esc(notifyNote)}</p></div>`:''}
 </div>${buttons(edit?'Simpan Catatan':'Mulai Tahap')}</form>`);

 const cam=$('#stage-camera'),fileInput=$('#stage-photos');
 if(cam&&fileInput){
  const apply=()=>{
   if(cam.checked)fileInput.setAttribute('capture','environment');
   else fileInput.removeAttribute('capture');
  };
  cam.onchange=apply;apply();
 }
 const photoCount=()=>fileInput?(fileInput.files?fileInput.files.length:0):0;
 const label=$('#stage-photos');
 if(label&&canUpload){
  const info=document.createElement('p');
  info.className='muted tiny';info.style.marginTop='6px';
  info.textContent='Belum ada foto dipilih.';
  label.after(info);
  if(fileInput)fileInput.onchange=()=>{
   const n=photoCount();
   info.textContent=n?`${n} foto dipilih.`:'Belum ada foto dipilih.';
  };
 }

 bindForm('stage-form',async d=>{
  if(edit){await mutate(o,'stage',{stage:i,...d});modal.close();return}
  const files=fileInput?[...fileInput.files]:[];
  if(files.some(x=>x.size>5*1024*1024))
   throw Error('Setiap foto maksimal 5 MB.');
  let done=0;
  // Foto diunggah lebih dulu supaya bisa ikut terkirim dalam pembaruan tahap.
  // Setiap unggahan menaikkan versi pesanan, jadi selalu pakai versi terbaru.
  for(const file of files){
   const latest=S.orders.find(x=>x.id===o.id);
   await api('orders/'+o.id+'/action',{action:'photo_add',version:latest.version,
    stage:STAGES[i],caption:(d.caption||'').trim(),data:await readFile(file)});
   done++;await load();
  }
  const fresh=S.orders.find(x=>x.id===o.id)||o;
  const res=await mutate(fresh,'start',{stage:i,start:d.start,estimate:d.estimate,
   note:d.note,notify:!!d.notify});
  modal.close();
  if(res&&res.notified){
   toast(res.notified.ok
    ?'Tahap dimulai. Pembaruan + foto terkirim ke WhatsApp konsumen.'
    :'Tahap dimulai, tetapi WhatsApp gagal: '+res.notified.message,true);
  }else if(done){
   toast(`Tahap dimulai. ${done} foto tersimpan.`);
  }
 });
}
function notifyStageDialog(o,stage){
 const photos=o.photos.filter(p=>p.stage===stage);
 dialog('Kirim pembaruan '+stage+` ke WhatsApp`,`<form id="notify-form">
 <div class="notice info">Tujuan: <strong>+${esc(o.wa)}</strong> (${esc(o.customer)}).
 ${photos.length?`Ada <strong>${photos.length} foto</strong> pada tahap ini yang akan dilampirkan.`
 :'Belum ada foto pada tahap ini — hanya pesan teks yang dikirim.'}</div>
 <div class="form-grid">
 ${area('Catatan untuk konsumen','note',o.stages[STAGES.indexOf(stage)]?.note||'')}
 <div class="full"><label class="check"><input type="checkbox" name="with_photos" checked>
 Lampirkan foto tahap ini</label></div>
 </div><p class="muted tiny">Foto dikirim sebagai tautan galeri yang berlaku
 terbatas, supaya tidak membebani kuota pesan dan tetap bisa dibuka consumer
 dari HP-nya.</p>${buttons('Kirim Sekarang')}</form>`);
 bindForm('notify-form',async d=>{
  const btn=$('#notify-form button[type=submit]');
  if(btn)btn.disabled=true;
  try{
   const r=await api('notify/stage',{id:o.id,stage,note:d.note,
    with_photos:!!d.with_photos});
   await load();modal.close();
   toast(r.ok?'Pembaruan + foto terkirim ke WhatsApp konsumen.'
    :'Gagal mengirim: '+r.message,!r.ok);
  }finally{if(btn)btn.disabled=false}
 });
}
function qcSection(o){
 const q=o.qc,edit=o.life==='active'&&o.stages[2].state==='running';
 return `<hr style="border:0;border-top:1px solid var(--line);margin:25px 0">
 <div class="two"><div><h3>Checklist finishing</h3><form id="checklist-form">
 ${S.qc_items.map((x,i)=>`<label class="check"><input type="checkbox"
 ${o.checklist[i]?'checked':''} ${edit?'':'disabled'}>${esc(x)}</label>`).join('')}
 ${edit?'<button type="submit">Simpan Checklist</button>':''}</form></div>
 <div><h3>Pemeriksaan kualitas</h3>
 ${q.bad?badge('Perlu Perbaikan'):''} ${q.missing?badge('Ada Kekurangan'):''}
 <p class="muted tiny">Jumlah baik + cacat harus sama dengan jumlah diperiksa.
 Kekurangan dihitung dari jumlah pesanan dikurangi jumlah diperiksa.</p>
 ${edit?`<form id="qc-form"><div class="form-grid">
 ${field('Jumlah diperiksa','inspected',q.inspected,'number',`min="0" max="${o.qty}" required`)}
 ${field('Jumlah barang baik','good',q.good,'number',`min="0" max="${o.qty}" required`)}
 ${field('Jumlah barang cacat','bad',q.bad,'number',`min="0" max="${o.qty}" required`)}
 <div><label>Kekurangan tersimpan</label><input disabled value="${q.missing} pcs"></div>
 ${area('Deskripsi cacat / kekurangan','defect',q.defect)}
 ${area('Tindakan perbaikan','correction',q.correction)}
 ${area('Persetujuan pengecualian owner — kosongkan jika tidak menyetujui','approval',q.approval)}
 </div><p class="tiny muted">Persetujuan berisi alasan menerima cacat/kekurangan.
 Kendala penghalang tetap harus diselesaikan.</p>${buttons('Simpan Pemeriksaan')}</form>`:
 kv([['Diperiksa',q.inspected+' pcs'],['Baik',q.good+' pcs'],['Cacat',q.bad+' pcs'],
 ['Kurang',q.missing+' pcs'],['Temuan',q.defect],['Perbaikan',q.correction],
 ['Persetujuan owner',q.approval]])}
 </div></div>`;
}
function photoLabel(o,p){
 if(!p.stage.startsWith('Kendala:'))return p.stage;
 const issue=o.issues.find(x=>x.id===p.stage.slice(8));
 return 'Kendala · '+(issue?.category||'Catatan');
}
function photosHTML(o,editable=true){
 if(!o.photos.length)return empty('Belum ada foto','Unggah dokumentasi proses dan hasil produksi.');
 const groups=[...new Set(o.photos.map(p=>p.stage))];
 return groups.map(group=>`<h3>${esc(photoLabel(o,{stage:group}))}</h3><div class="gallery" style="margin-bottom:25px">
 ${o.photos.filter(p=>p.stage===group).map(p=>`<article class="photo">
 <a href="/api/photos/${p.id}" target="_blank" rel="noopener"><img loading="lazy"
 src="/api/photos/${p.id}" alt="${esc(p.caption||photoLabel(o,p))}"></a>
 <div class="photo-body"><div class="tiny wrap">${esc(p.caption||'Tanpa keterangan')}</div>
 <div class="muted tiny">${dt(p.uploaded)}</div><div class="row" style="margin-top:10px">
 <a class="button small" href="/api/photos/${p.id}?download=1">Unduh</a>
 ${editable&&canChange(o)?`<button class="danger small" data-delete-photo="${p.id}">Hapus</button>`:''}
 </div></div></article>`).join('')}</div>`).join('');
}
function photosTab(b,o){
 b.innerHTML=`<div class="card"><div class="row spread"><h2>Dokumentasi produksi</h2>
 ${canChange(o)?'<button class="primary" id="add-photo">＋ Tambah Foto</button>':''}</div>
 <p class="muted tiny">JPEG, PNG, atau WebP · maksimal 5 MB per foto · tersimpan di database server.
 Klik foto untuk membuka ukuran besar.</p>${photosHTML(o)}</div>`;
 if($('#add-photo'))$('#add-photo').onclick=()=>photoDialog(o);
 $$('[data-delete-photo]').forEach(btn=>btn.onclick=async()=>{
  if(!confirm('Hapus foto ini? Catatan penghapusan tetap disimpan. Untuk mengganti, unggah foto baru.'))return;
  try{await mutate(o,'photo_delete',{photo:btn.dataset.deletePhoto})}catch(e){toast(e.message,true)}
 });
}
function readFile(file){
 return new Promise((resolve,reject)=>{
  const reader=new FileReader();
  reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('Gagal membaca file.'));
  reader.readAsDataURL(file);
 });
}
function photoDialog(o,stage='Potong Bahan'){
 const opts=[...STAGES,'Packing',...o.issues.map(x=>'Kendala:'+x.id)];
 dialog('Tambah foto produksi',`<form id="photo-form"><div class="form-grid">
 <div class="full"><label>Kelompok / tahap</label><select name="stage">${
 opts.map(v=>`<option value="${esc(v)}" ${v===stage?'selected':''}>${
 esc(photoLabel(o,{stage:v}))}</option>`).join('')}</select></div>
 <div class="full"><label>Foto — dapat memilih beberapa</label>
 <input name="files" type="file" accept="image/jpeg,image/png,image/webp" multiple required></div>
 ${area('Keterangan foto','caption')}
 </div><p class="muted tiny">Maksimal 5 MB per file. Foto dikompresi, metadata dihapus, dan disimpan sebagai JPEG.
 Jika sebagian unggahan gagal, foto yang sudah tersimpan tetap tersedia.</p>${buttons('Unggah Foto')}</form>`);
 bindForm('photo-form',async(d,f)=>{
  const files=[...f.elements.files.files];
  if(files.some(x=>x.size>5*1024*1024))throw Error('Setiap foto maksimal 5 MB.');
  let done=0;
  try{
   for(const file of files){
    const latest=S.orders.find(x=>x.id===o.id);
    await api('orders/'+o.id+'/action',{
     action:'photo_add',version:latest.version,stage:d.stage,
     caption:d.caption,data:await readFile(file)
    });
    done++;await load();
   }
   modal.close();toast(`${done} foto tersimpan di server.`);
  }catch(e){
   await load();modal.close();
   throw Error(`${done} foto tersimpan. ${e.message} Unggah ulang hanya foto yang belum tersimpan.`);
  }
 });
}
function issuesTab(b,o){
 b.innerHTML=`<div class="card"><div class="row spread"><h2>Revisi & kendala</h2>
 ${o.life==='active'?'<button class="primary" id="new-issue">＋ Catat Revisi / Kendala</button>':''}</div>
 <p class="muted tiny">Kekurangan bahan dicatat sebagai kendala, bukan inventaris.
 Untuk mengubah spesifikasi atau harga, gunakan Edit / Revisi pada Ringkasan.</p>
 ${o.issues.length?o.issues.map(i=>`<div class="card" style="box-shadow:none">
 <div class="row spread"><strong>${esc(i.category)}</strong>${badge(i.status)}</div>
 <p class="muted tiny">${dt(i.at)}${i.blocking?' · Menghalangi pengiriman/penyelesaian':''}</p>
 <p class="wrap">${esc(i.description)}</p>${kv([
 ['Tindak lanjut',i.action],['Penyelesaian',i.resolution]])}
 <div class="row" style="margin-top:15px">${canChange(o)?`
 <button data-issue="${i.id}">Perbarui Penanganan</button>
 <button data-issue-photo="${i.id}">＋ Foto Pendukung</button>`:''}</div>
 </div>`).join(''):empty('Tidak ada kendala tercatat','Catat perubahan atau masalah agar riwayat tidak hilang.')}
 </div>`;
 if($('#new-issue'))$('#new-issue').onclick=()=>issueDialog(o);
 $$('[data-issue-photo]').forEach(btn=>btn.onclick=()=>photoDialog(o,'Kendala:'+btn.dataset.issuePhoto));
 $$('[data-issue]').forEach(btn=>btn.onclick=()=>{
  const i=o.issues.find(x=>x.id===btn.dataset.issue);
  dialog('Penanganan kendala',`<form id="issue-update">
  <p class="wrap">${esc(i.description)}</p><div class="form-grid">
  ${selectField('Status','status',['Baru','Sedang ditangani','Selesai'],i.status)}
  ${area('Catatan penanganan / penyelesaian','resolution',i.resolution)}</div>${buttons()}</form>`);
  bindForm('issue-update',async d=>{
   await mutate(o,'issue_update',{issue:i.id,...d});modal.close();
  });
 });
}
function issueDialog(o){
 dialog('Catat revisi / kendala',`<form id="issue-add"><div class="form-grid">
 ${selectField('Kategori','category',S.categories)}
 ${area('Deskripsi masalah / perubahan *','description','','required')}
 ${area('Tindakan / bahan tambahan / dampak jadwal','followup')}
 <label class="check full"><input type="checkbox" name="blocking" checked>
 Menghalangi pengiriman atau penyelesaian pesanan</label>
 </div>${buttons('Simpan Catatan')}</form>`);
 bindForm('issue-add',async(d,f)=>{
  await mutate(o,'issue_add',{...d,blocking:f.elements.blocking.checked});modal.close();
 });
}
function paymentsTab(b,o){
 b.innerHTML=`<div class="three">
 ${[['Harga kesepakatan',o.total],['Pembayaran diterima',o.paid],['Sisa pembayaran',o.remaining]]
 .map(([label,n])=>`<div class="card"><span class="muted tiny">${label}</span>
 <h2 style="margin:12px 0 0">${rp(n)}</h2></div>`).join('')}</div>
 <div class="card"><div class="row spread"><h2>Riwayat pembayaran</h2>
 <div class="row">${badge(o.payment_status)}
 ${canChange(o)&&o.remaining>0?'<button class="primary" id="add-payment">＋ Catat Pembayaran</button>':''}
 <button class="wa" id="remind-payment">Pengingat WhatsApp</button></div></div>
 <p class="muted tiny">DP merupakan pembayaran pertama. Transaksi tidak ditimpa.
 Pembayaran tidak mengubah status produksi atau penerimaan barang.</p>
 ${o.payments.length?`<div class="table-wrap"><table><thead><tr><th>TANGGAL</th>
 <th>JENIS</th><th>JUMLAH</th><th>CATATAN</th></tr></thead><tbody>
 ${o.payments.map(p=>`<tr><td>${fmt(p.date)}</td><td>${esc(p.kind)}</td>
 <td><strong>${rp(p.amount)}</strong></td><td style="white-space:normal">${esc(p.note||'—')}</td></tr>`).join('')}
 </tbody></table></div>`:empty('Belum ada pembayaran','Catat DP atau pembayaran yang benar-benar diterima.')}
 </div>`;
 if($('#add-payment'))$('#add-payment').onclick=()=>payDialog(o);
 $('#remind-payment').onclick=()=>waDialog(o,'bayar');
}
function newToken(){
 return Array.from(crypto.getRandomValues(new Uint8Array(24)),n=>n.toString(16).padStart(2,'0')).join('');
}
function payDialog(o){
 const token=newToken();
 dialog('Catat pembayaran',`<form id="pay-form"><div class="notice info">
 Sisa tagihan: <strong>${rp(o.remaining)}</strong></div><div class="form-grid">
 ${field('Jumlah diterima (Rp) *','amount',o.remaining,'number',`min="1" max="${o.remaining}" required`)}
 ${field('Tanggal pembayaran *','date',S.today,'date',`required min="${o.deal}" max="${S.today}"`)}
 ${area('Catatan / metode / referensi pembayaran','note')}
 </div>${buttons('Konfirmasi Pembayaran Diterima')}</form>`);
 bindForm('pay-form',async d=>{
  if(!confirm(`Catat penerimaan pembayaran sebesar ${rp(Number(d.amount))}?`))return;
  await mutate(o,'pay',{...d,token});modal.close();
 });
}
function shippingTab(b,o){
 const sh=o.shipping,ready=o.stages.every(s=>s.state==='done');
 const reasons=[];
 if(!o.received)reasons.push('Barang belum diterima/diserahterimakan.');
 if(o.remaining)reasons.push('Sisa pembayaran '+rp(o.remaining)+'.');
 if(o.issues.some(i=>i.blocking&&i.status!=='Selesai'))reasons.push('Masih ada kendala penghalang yang terbuka.');
 b.innerHTML=`<div class="two"><div class="card"><h2>Informasi pengiriman</h2>
 ${kv([['Tanggal siap kirim',fmt(o.ready_at)],['Alamat konsumen',o.address],
 ['Metode',sh?.method],['Kurir / ekspedisi',sh?.courier],['Nomor resi',sh?.tracking],
 ['Jumlah paket',sh?sh.packages+' paket':'—'],['Jumlah dikirim',sh?sh.qty+' pcs':'—'],
 ['Tanggal kirim',fmt(sh?.date)],['Estimasi tiba',fmt(sh?.eta)],
 ['Barang diterima',fmt(o.received)],['Catatan',sh?.note]])}
 ${!ready?'<p class="notice">Selesaikan finishing dan QC untuk mengaktifkan pengiriman.</p>':''}
 <div class="row" style="margin-top:20px">
 ${ready&&o.life==='active'&&!o.received?`<button class="primary" id="ship-form-open">${
 sh?'Perbarui Pengiriman / Estimasi Tiba':'Catat Pengiriman / Serah Terima'}</button>`:''}
 ${sh&&!o.received&&o.life==='active'?'<button id="receive">Konfirmasi Barang Diterima</button>':''}
 <button id="ship-wa" class="wa">Bagikan Informasi</button>
 ${canChange(o)?'<button id="packing-photo">＋ Foto Packing</button>':''}
 </div></div>
 <div><div class="card"><h2>Pelunasan</h2>${kv([
 ['Harga deal',rp(o.total)],['Pembayaran diterima',rp(o.paid)],
 ['Sisa pelunasan',rp(o.remaining)],['Status',o.payment_status]])}
 ${canChange(o)&&o.remaining?'<button class="primary" id="settle" style="margin-top:20px">Catat Pelunasan</button>':''}</div>
 <div class="card"><h2>Selesaikan pesanan</h2>
 ${reasons.length?`<div class="notice">${reasons.map(esc).join('<br>')}</div>`:
 '<p class="notice info">Barang sudah diterima, pembayaran lunas, dan tidak ada kendala penghalang.</p>'}
 ${o.life==='active'?`<button id="complete" class="primary" ${reasons.length?'disabled':''}>Selesaikan Pesanan</button>`:
 badge(LIFE[o.life])}</div></div></div>`;
 if($('#ship-form-open'))$('#ship-form-open').onclick=()=>shippingDialog(o);
 if($('#settle'))$('#settle').onclick=()=>payDialog(o);
 if($('#packing-photo'))$('#packing-photo').onclick=()=>photoDialog(o,'Packing');
 $('#ship-wa').onclick=()=>waDialog(o,o.received?'terima':sh?'kirim':'siap');
 if($('#receive'))$('#receive').onclick=()=>{
  dialog('Konfirmasi barang diterima',`<form id="receive-form">
  ${field('Tanggal diterima / diserahterimakan *','date',S.today,'date',`required max="${S.today}" min="${sh.date}"`)}
  <p class="notice">Status penerimaan tidak otomatis berarti pembayaran lunas.</p>
  ${buttons('Konfirmasi Diterima')}</form>`);
  bindForm('receive-form',async d=>{
   await mutate(o,'receive',d);modal.close();
  });
 };
 if($('#complete'))$('#complete').onclick=async()=>{
  if(!confirm('Tandai pesanan selesai dan lunas? Pesanan akan masuk Riwayat.'))return;
  try{await mutate(o,'complete')}catch(e){toast(e.message,true)}
 };
}
function shippingDialog(o){
 const s=o.shipping||{date:S.today,eta:S.today,qty:o.qty,packages:1,method:'Kurir'};
 dialog(o.shipping?'Perbarui pengiriman':'Catat pengiriman',`<form id="shipping-form">
 <div class="form-grid">
 ${selectField('Metode','method',['Kurir','Ekspedisi','Diambil langsung'],s.method)}
 ${field('Kurir / ekspedisi','courier',s.courier||'')}
 ${field('Nomor resi','tracking',s.tracking||'')}
 ${field('Jumlah paket *','packages',s.packages,'number','min="1" required')}
 ${field('Jumlah pakaian dikirim *','qty',s.qty,'number',`min="1" max="${o.qty}" required`)}
 ${field('Tanggal pengiriman aktual *','date',s.date,'date',`required max="${S.today}"`)}
 ${field('Estimasi tiba *','eta',s.eta,'date','required')}
 ${area('Catatan pengiriman / alasan jumlah kurang','note',s.note||'')}
 </div>${buttons('Simpan Pengiriman')}</form>`);
 bindForm('shipping-form',async d=>{
  if(!confirm('Simpan informasi pengiriman sesuai kondisi sebenarnya?'))return;
  await mutate(o,'ship',d);modal.close();
 });
}
function historyTab(b,o){
 b.innerHTML=`<div class="card"><h2>Riwayat aktivitas</h2>
 <p class="muted tiny">Waktu server menggunakan WIB. Riwayat perubahan penting tidak ditimpa.</p>
 <div class="history">${[...o.history].reverse().map(h=>`
 <div class="history-item"><strong>${esc(h.message)}</strong>
 <div class="muted tiny">${dt(h.at)}</div>${h.detail!==null?`
 <details><summary>Lihat rincian perubahan</summary><pre>${esc(JSON.stringify(h.detail,null,2))}</pre></details>`:''}
 </div>`).join('')}</div></div>`;
}
function waDialog(o,kind){
 if(!kind)kind=o.received?'terima':o.shipping?'kirim':o.ready_at?'siap':
 o.stages[2].state==='running'?'finishing':o.stages[1].state==='running'?'jahit':'potong';
 const labels={potong:'Update potong',jahit:'Update jahit',finishing:'Update finishing',
 siap:'Pesanan siap kirim',bayar:'Pengingat pelunasan',kirim:'Informasi pengiriman',
 terima:'Konfirmasi barang diterima'};
 dialog('Siapkan pesan WhatsApp',`
 <div class="form-grid"><div class="full"><label>Template pesan</label>
 <select id="wa-kind">${Object.entries(labels).map(([k,v])=>`
 <option value="${k}" ${k===kind?'selected':''}>${v}</option>`).join('')}</select></div>
 <div class="full row">
 <label class="check"><input type="checkbox" id="wa-order" checked>Info pesanan</label>
 <label class="check"><input type="checkbox" id="wa-status" checked>Status produksi</label>
 <label class="check"><input type="checkbox" id="wa-target" checked>Estimasi selesai</label>
 </div>${area('Catatan tambahan untuk konsumen','wa_extra')}
 <div class="full"><label>Pesan — boleh disunting sebelum dibuka</label>
 <textarea id="wa-message" style="min-height:230px"></textarea></div></div>
 <h3 style="margin-top:20px">Foto yang ingin dibagikan</h3>
 ${o.photos.length?o.photos.map(p=>`<label class="check">
 <input type="checkbox" data-wa-photo="${p.id}">${esc(photoLabel(o,p))} · ${esc(p.caption||fmt(p.uploaded))}
 </label>`).join(''):'<p class="muted tiny">Belum ada foto.</p>'}
 <p class="notice">WhatsApp tidak melampirkan foto otomatis melalui tautan.
 Salin/buka pesan, lalu bagikan foto melalui perangkat atau unduh dan lampirkan manual.
 Aplikasi tidak menyatakan pesan sudah terkirim.</p>
 <div class="row"><button id="wa-copy">Salin Pesan</button>
 <a class="button wa" id="wa-open" target="_blank" rel="noopener">Buka WhatsApp ↗</a>
 <button class="primary" id="wa-auto">Kirim Otomatis (Fonnte)</button>
 <button id="wa-share">Bagikan Foto via Perangkat</button>
 <button id="wa-download">Tampilkan Unduhan Foto</button></div><div id="wa-downloads"></div>`);
 const updateLink=()=>$('#wa-open').href='https://wa.me/'+o.wa+'?text='+
  encodeURIComponent($('#wa-message').value);
 const generate=()=>{
  const lines=[];
  if($('#wa-order').checked)lines.push('Nomor Pesanan: '+o.number,'Jenis: '+o.garment,'Jumlah: '+o.qty+' pcs');
  if($('#wa-status').checked)lines.push('Tahap Saat Ini: '+o.status);
  if($('#wa-target').checked)lines.push('Estimasi Selesai: '+fmt(o.target));
  const s=o.shipping||{};
  const vars={
   nama:o.customer,nomor:o.number,jenis:o.garment,jumlah:o.qty,status:o.status,
   estimasi:fmt(o.target),usaha:S.settings.name,ringkasan:lines.join('\n'),
   sisa:rp(o.remaining),total:rp(o.total),dibayar:rp(o.paid),
   metode:s.method||'Belum dicatat',kurir:s.courier||'—',resi:s.tracking||'—',
   tanggal_kirim:fmt(s.date),tiba:fmt(s.eta),diterima:fmt(o.received)
  };
  let msg=S.settings.templates[$('#wa-kind').value].replace(/\{(\w+)\}/g,
   (all,k)=>vars[k]??all);
  const extra=$('[name=wa_extra]').value.trim();
  if(extra)msg+='\n\n'+extra;
  $('#wa-message').value=msg;updateLink();
 };
 ['wa-kind','wa-order','wa-status','wa-target'].forEach(id=>$('#'+id).onchange=generate);
 $('[name=wa_extra]').oninput=generate;$('#wa-message').oninput=updateLink;
 $('#wa-copy').onclick=async()=>{
  try{
   await navigator.clipboard.writeText($('#wa-message').value);toast('Pesan disalin.');
  }catch{
   $('#wa-message').focus();$('#wa-message').select();
   toast('Tekan Salin pada perangkat atau Ctrl+C untuk menyalin pesan.');
  }
 };
 const selectedPhotos=()=>$$('[data-wa-photo]:checked').map(x=>x.dataset.waPhoto);
 $('#wa-auto').onclick=async()=>{
  const btn=$('#wa-auto');btn.disabled=true;
  try{
   const r=await api('notify/message',{id:o.id,kind:$('#wa-kind').value,
    extra:$('[name=wa_extra]').value});
   toast(r.ok?'Pesan terkirim ke '+o.wa+'.':'Gagal mengirim: '+r.message,!r.ok);
  }catch(e){toast(e.message,true)}
  finally{btn.disabled=false}
 };
 $('#wa-download').onclick=()=>{
  const ids=selectedPhotos();
  if(!ids.length)return toast('Pilih foto terlebih dahulu.',true);
  $('#wa-downloads').innerHTML='<p class="tiny muted">Unduh setiap foto, lalu lampirkan di WhatsApp:</p>'+
   ids.map((id,i)=>`<a class="button small" style="margin:5px" href="/api/photos/${id}?download=1">Unduh foto ${i+1}</a>`).join('');
 };
 $('#wa-share').onclick=async()=>{
  const ids=selectedPhotos();if(!ids.length)return toast('Pilih foto terlebih dahulu.',true);
  try{
   const files=await Promise.all(ids.map(async(id,i)=>{
    const r=await fetch('/api/photos/'+id);if(!r.ok)throw Error('Gagal mengambil foto.');
    return new File([await r.blob()],`progres-${i+1}.jpg`,{type:'image/jpeg'});
   }));
   if(!navigator.canShare?.({files}))throw Error('Berbagi file tidak didukung. Gunakan unduhan foto.');
   await navigator.share({files,title:'Progres '+o.number});
   toast('Dialog berbagi perangkat ditutup. Status pengiriman tidak dapat dipastikan aplikasi.');
  }catch(e){if(e.name!=='AbortError')toast(e.message,true)}
 };
 generate();
}
function invoice(o){
 $('#print-area').innerHTML=`
 <div class="row spread"><div>${S.settings.logo?`<img src="${esc(S.settings.logo)}" style="width:70px;height:70px;object-fit:contain">`:''}
 <h1>${esc(S.settings.name)}</h1><div class="wrap">${esc(S.settings.address)}</div>
 <div>WhatsApp: ${esc(S.settings.wa||'—')}</div></div>
 <div><h2>INVOICE / RINGKASAN PESANAN</h2><strong>${esc(o.number)}</strong></div></div>
 <hr><div class="two" style="margin-top:25px"><div><h3>Kepada</h3>
 <strong>${esc(o.customer)}</strong><div>+${esc(o.wa)}</div>
 <div class="wrap">${esc(o.address)}</div></div>
 <div>${kv([['Tanggal deal',fmt(o.deal)],['Estimasi selesai',fmt(o.target)],
 ['Status pembayaran',o.payment_status],['Status produksi',o.status]])}</div></div>
 <table><thead><tr><th>Deskripsi</th><th>Jumlah</th><th>Harga kesepakatan</th></tr></thead>
 <tbody><tr><td style="white-space:normal">${esc(o.garment)}<br>${esc(o.material)} · ${esc(o.color)}
 <div class="wrap">${esc(o.spec)}</div>
 <div>${esc(Object.entries(o.sizes).map(([k,v])=>k+': '+v).join(' · '))}</div></td>
 <td>${o.qty} pcs</td><td>${rp(o.total)}</td></tr></tbody></table>
 ${kv([['Harga deal',rp(o.total)],['Pembayaran diterima',rp(o.paid)],
 ['Sisa pembayaran',rp(o.remaining)]])}
 <h3 style="margin-top:30px">Rincian pembayaran</h3>
 ${o.payments.length?`<table><thead><tr><th>Tanggal</th><th>Jumlah</th><th>Catatan</th></tr></thead><tbody>${
 o.payments.map(p=>`<tr><td>${fmt(p.date)}</td><td>${rp(p.amount)}</td><td style="white-space:normal">${esc(p.note)}</td></tr>`).join('')
 }</tbody></table>`:'<p>Belum ada pembayaran diterima.</p>'}
 <p>Status: <strong>${esc(o.payment_status)}</strong></p>
 <p class="wrap">${esc(o.special)}</p>
 <hr><p>Terima kasih atas kepercayaan Anda kepada ${esc(S.settings.name)}.</p>`;
 window.print();
}
function renderAggregate(c){
 const names={gallery:['Galeri produksi','Foto proses, hasil produksi, dan dokumentasi kendala.'],
 issues:['Revisi & kendala','Pantau masalah yang masih membutuhkan tindak lanjut.'],
 payments:['Pembayaran','Catatan penerimaan pembayaran dan sisa tagihan.'],
 shipping:['Pengiriman','Pantau pesanan siap kirim, perjalanan, dan penerimaan.']};
 c.innerHTML=heading(...names[view])+`<div class="card"><div class="filters">
 <input id="aggregate-search" placeholder="Cari nama konsumen atau nomor pesanan…">
 </div><div id="aggregate-results"></div></div>`;
 const draw=()=>{
  const q=$('#aggregate-search').value.toLowerCase();
  let orders=S.orders.filter(o=>(o.customer+' '+o.number).toLowerCase().includes(q));
  const out=$('#aggregate-results');
  if(view==='gallery'){
   orders=orders.filter(o=>o.photos.length);
   out.innerHTML=orders.length?orders.map(o=>`
   <div class="row spread"><h3>${esc(o.number)} · ${esc(o.customer)}</h3>
   <button class="small" data-detail="${o.id}">Buka Detail</button></div>
   ${photosHTML(o,false)}`).join(''):empty('Belum ada foto yang cocok');
  }else if(view==='issues'){
   orders=orders.filter(o=>o.issues.some(i=>i.status!=='Selesai'));
   out.innerHTML=orders.length?orders.map(o=>`<div class="card">
   <div class="row spread"><strong>${esc(o.number)} · ${esc(o.customer)}</strong>
   <button class="small" data-detail="${o.id}">Tangani di Detail</button></div>
   ${o.issues.filter(i=>i.status!=='Selesai').map(i=>`<div style="margin-top:15px">
   ${badge(i.status)} <strong>${esc(i.category)}</strong>
   <p class="wrap" style="margin:8px 0">${esc(i.description)}</p></div>`).join('')}
   </div>`).join(''):empty('Tidak ada kendala terbuka');
  }else{
   orders=orders.filter(o=>view==='payments'?
    ['active','paused','unpaid'].includes(o.life)&&o.remaining>0:
    o.ready_at&&['active','unpaid','done'].includes(o.life));
   out.innerHTML=orders.length?`<div class="table-wrap"><table><thead><tr>
   <th>PESANAN</th><th>KONSUMEN</th><th>${view==='payments'?'SISA TAGIHAN':'PENGIRIMAN'}</th>
   <th>STATUS</th><th></th></tr></thead><tbody>${orders.map(o=>`<tr>
   <td>${esc(o.number)}</td><td>${esc(o.customer)}</td>
   <td>${view==='payments'?rp(o.remaining):
    esc(o.shipping?o.shipping.method+' · '+(o.shipping.tracking||'Tanpa resi'):'Belum dikirim')}</td>
   <td>${badge(view==='payments'?o.payment_status:o.status)}</td>
   <td><button class="small" data-detail="${o.id}">Kelola →</button></td></tr>`).join('')}
   </tbody></table></div>`:empty(view==='payments'?'Tidak ada tagihan terbuka':'Belum ada pesanan siap kirim');
  }
  $$('[data-detail]').forEach(btn=>btn.onclick=()=>{
   const destination={gallery:'foto',issues:'kendala',payments:'pembayaran',shipping:'pengiriman'}[view];
   detail(btn.dataset.detail);tab=destination;render();
  });
 };
 $('#aggregate-search').oninput=draw;draw();
}
function renderSettings(c){
 const s=S.settings;
 c.innerHTML=heading('Pengaturan','Identitas usaha, master data, keamanan, dan cadangan database.')+
 `<form class="card" id="settings-form"><h2>Identitas usaha</h2><div class="form-grid">
 ${field('Nama usaha *','name',s.name,'text','required')}
 ${field('WhatsApp usaha','wa',s.wa,'tel')}
 ${area('Alamat usaha','address',s.address)}
 ${field('Awalan nomor pesanan','prefix',s.prefix,'text','required pattern="[A-Za-z0-9]{2,12}"')}
 ${field('Default estimasi pengerjaan (hari)','default_days',s.default_days,'number','min="1" max="365" required')}
 <div><label>Mata uang</label><input value="Rupiah (IDR) · format Indonesia" disabled></div>
 <div><label>Logo usaha — maksimal 5 MB</label><input type="file" name="logo" accept="image/jpeg,image/png,image/webp"></div>
 <label class="check full"><input type="checkbox" name="remove_logo">Hapus logo saat menyimpan</label>
 ${area('Daftar jenis pakaian — satu jenis per baris','garments',s.garments.join('\n'),'required')}
 ${area('Daftar jenis bahan — satu bahan per baris','materials',s.materials.join('\n'),'required')}
 </div><h2 style="margin-top:30px">Notifikasi WhatsApp otomatis</h2>
 <div class="form-grid">
 <label class="check full"><input type="checkbox" name="auto_notify" ${s.auto_notify?'checked':''}>
 Kirim pembaruan + foto ke konsumen otomatis saat tahap dimulai</label>
 <label class="check full"><input type="checkbox" name="gallery_link" ${s.gallery_link!==false?'checked':''}>
 Sertakan tautan galeri foto dalam pesan</label>
 <div class="full"><label>Status pengiriman WhatsApp</label>
 <input id="notify-state" value="Memuat…" disabled></div>
 <div class="full"><label>Nomor WhatsApp untuk pesan uji</label>
 <input id="notify-test-target" placeholder="Kosongkan untuk memakai nomor usaha di atas"></div>
 </div>
 <div class="row" style="margin-top:14px">
 <button id="notify-test">Kirim Pesan Uji</button></div>
 <p class="muted tiny wrap" style="margin-top:14px">Pengiriman memakai Fonnte
 (WhatsApp Business API). Token Fonnte diisi di environment server
 (<code>FONNTE_TOKEN</code>), bukan di halaman ini. Biaya Fonnte dipotong dari
 saldo Anda per pesan. Foto dikirim sebagai tautan galeri yang berlaku
 terbatas — tidak memakai kuota foto dan bisa dibuka langsung dari HP consumer.</p>
 </div><h2 style="margin-top:30px">Template WhatsApp</h2>
 <p class="muted tiny wrap">Variabel tersedia: {nama}, {nomor}, {jenis}, {jumlah}, {status}, {estimasi},
 {ringkasan}, {usaha}, {total}, {dibayar}, {sisa}, {metode}, {kurir}, {resi},
 {tanggal_kirim}, {tiba}, {diterima}.</p>
 <div class="form-grid">${Object.entries(s.templates).map(([k,v])=>
 area('Template '+({potong:'potong',jahit:'jahit',finishing:'finishing',siap:'siap kirim',
 bayar:'pengingat pembayaran',kirim:'pengiriman',terima:'barang diterima'}[k]),'tpl_'+k,v,'required')).join('')}</div>
 ${buttons('Simpan Pengaturan')}</form>
 <div class="two"><div class="card"><h2>Backup database</h2>
 <p>Unduh snapshot lengkap berisi pesanan, foto, pembayaran, pengaturan, dan hash kredensial owner.</p>
 <p class="notice">File backup memuat data konsumen. Simpan secara privat dan terenkripsi.
 Backup belum dijadwalkan otomatis oleh aplikasi.</p>
 <div class="row">
 <button class="primary" id="backup">Unduh Backup Lengkap</button>
 <button id="backup-light">Tanpa Foto (lebih kecil)</button></div>
 <hr style="border:0;border-top:1px solid var(--line);margin:22px 0">
 <h3>Pulihkan dari backup</h3>
 <p class="muted tiny wrap">Pilih file backup JSON. Semua pesanan, foto, dan pembayaran yang ada
 sekarang akan <strong>diganti</strong> oleh isi file. Pengaturan usaha dan kata sandi owner
 tidak ikut berubah.</p>
 <input type="file" id="restore-file" accept="application/json,.json">
 <button id="restore-go" class="danger" style="margin-top:12px">Pulihkan Data dari File</button>
 <p class="tiny muted">Format file JSON. Disarankan juga menyimpan salinan manual ke penyimpanan
/cloud Anda — backup di dalam aplikasi ini bukan pengganti arsip luar.</p>
 </div><form class="card" id="password-form"><h2>Ubah kata sandi owner</h2>
 <div class="stack">${field('Kata sandi lama','old','','password','required autocomplete="current-password"')}
 ${field('Kata sandi baru — minimal 12 karakter','new','','password','minlength="12" required autocomplete="new-password"')}
 </div>${buttons('Ubah Kata Sandi')}</form></div>
 <div class="notice info">Penyimpanan utama: PostgreSQL (Supabase) di server, bukan browser.
 PWA membutuhkan koneksi server. Aplikasi tidak mengantre perubahan offline dan tidak mengklaim
 data tersinkron sebelum server mengonfirmasi.</div>`;
 bindForm('settings-form',async(d,f)=>{
  const templates={};
  Object.keys(s.templates).forEach(k=>templates[k]=d['tpl_'+k]);
  const file=f.elements.logo.files[0];
  if(file&&file.size>5*1024*1024)throw Error('Logo maksimal 5 MB.');
  await api('settings',{
   ...d,garments:d.garments.split('\n').map(x=>x.trim()).filter(Boolean),
   materials:d.materials.split('\n').map(x=>x.trim()).filter(Boolean),
   templates,remove_logo:f.elements.remove_logo.checked,
   auto_notify:f.elements.auto_notify.checked,
   gallery_link:f.elements.gallery_link.checked,
   logo:file?await readFile(file):''
  });
  await load();toast('Pengaturan tersimpan.');
  refreshNotifyState();
 });
 $('#notify-test').onclick=async()=>{
  const target=$('#notify-test-target').value.trim();
  const btn=$('#notify-test');btn.disabled=true;
  try{
   const r=await api('notify/test',target?{target}:{});
   toast('Pesan uji terkirim: '+r.message);
  }catch(e){toast(e.message,true)}
  finally{btn.disabled=false}
 };
 bindForm('password-form',async d=>{
  if(!confirm('Ubah kata sandi dan keluar dari sesi ini?'))return;
  await api('password',d);S=null;loginScreen();toast('Kata sandi diperbarui. Silakan masuk kembali.');
 });
 $('#backup').onclick=()=>{
  if(confirm('Unduh salinan database lengkap? File mengandung data konsumen dan wajib disimpan secara aman.'))
   location.href='/api/backup';
 };
 $('#backup-light').onclick=()=>{
  if(confirm('Unduh salinan database tanpa foto? Ukurannya jauh lebih kecil.'))
   location.href='/api/backup?photos=0';
 };
 $('#restore-go').onclick=async()=>{
  const file=$('#restore-file').files[0];
  if(!file)return toast('Pilih file backup JSON terlebih dahulu.',true);
  if(!confirm('Pulihkan data dari backup? SEMUA pesanan, foto, dan pembayaran '
   +'yang ada sekarang akan diganti. Tindakan ini tidak bisa dibatalkan.'))return;
  $('#restore-go').disabled=true;
  try{
   const parsed=JSON.parse(await file.text());
   const tables=parsed.tables||parsed;
   const r=await api('backup/restore',{confirm:'GANTI SEMUA DATA',tables});
   await load();
   toast('Pemulihan selesai: '+r.orders+' pesanan, '+r.photos+' foto dipulihkan.');
  }catch(e){toast(e.message,true)}
  finally{$('#restore-go').disabled=false}
 };
 refreshNotifyState();
}
async function refreshNotifyState(){
 const el=$('#notify-state');if(!el)return;
 let status;
 try{
  const r=await api('notify/status');
  status=r.fonnte_configured
   ?'Token Fonnte terpasang · tautan galeri berlaku '+r.ttl_days+' hari'
   :'Belum terhubung — set FONNTE_TOKEN di environment server (fly secrets set FONNTE_TOKEN=...)';
 }catch(e){el.value='Status tidak bisa dimuat: '+e.message;return}
 el.value=status+' · memeriksa device…';
 // Cek langsung ke Fonnte supaya owner tahu nomor, paket, dan sisa kuota.
 try{
  const d=await api('notify/device');
  if(!d.ok){el.value=status+' · device tidak terbaca: '+d.message;return}
  el.value=status+' · '+(d.connected?'terhubung':'TERPUTUS')
   +' · nomor '+d.device+(d.name?' ('+d.name+')':'')
   +' · paket '+d.package+' · sisa kuota '+d.quota
   +(d.expired?' · berlaku sampai '+d.expired:'');
 }catch(e){el.value=status+' · device tidak terbaca: '+e.message}
}
window.addEventListener('beforeinstallprompt',e=>{
 e.preventDefault();pendingInstall=e;
 if($('#install'))$('#install').style.display='inline-flex';
});
window.addEventListener('offline',()=>{
 if($('#connection')){$('#connection').textContent='● Offline · perubahan belum dapat disimpan';
 $('#connection').className='badge b-red'}
 toast('Koneksi terputus. Tidak ada penyimpanan atau antrean offline.',true);
});
window.addEventListener('online',async()=>{
 try{if(S){await load();toast('Terhubung kembali. Data dimuat dari server.')}}catch(e){toast(e.message,true)}
});
if('serviceWorker' in navigator){
 navigator.serviceWorker.register('/sw.js').catch(()=>{});
}
(async()=>{
 try{await load()}
 catch(e){if(S)toast(e.message,true);else loginScreen()}
})();
</script>
</body>
</html>
"""

@app.get("/")
def index():
    return Response(HTML, mimetype="text/html")

@app.get("/manifest.webmanifest")
def manifest():
    return jsonify({
        "id": "/",
        "name": "Rofi Jaya — Manajemen Pesanan & Produksi",
        "short_name": "Rofi Jaya",
        "description": "Manajemen pesanan konveksi untuk owner.",
        "lang": "id",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f5f6f3",
        "theme_color": "#143e35",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ]
    })

@app.get("/icon-<int:size>.png")
def icon(size):
    if size not in (192, 512):
        return Response(status=404)
    im = Image.new("RGB", (size, size), "#143e35")
    draw = ImageDraw.Draw(im)
    pad = int(size * .18)
    draw.rounded_rectangle(
        (pad, pad, size-pad, size-pad),
        radius=int(size*.14), fill="#c9a66b"
    )
    # Monogram berbasis bentuk; tidak bergantung font sistem.
    x, y, w = int(size*.34), int(size*.30), max(8, int(size*.07))
    draw.line((x,y,x,int(size*.70)), fill="#143e35", width=w)
    draw.arc((x-w//2,y-w//2,int(size*.66),int(size*.54)),
             270, 90, fill="#143e35", width=w)
    draw.line((x,int(size*.51),int(size*.66),int(size*.70)),
              fill="#143e35", width=w)
    out = io.BytesIO()
    im.save(out, "PNG")
    return Response(out.getvalue(), mimetype="image/png")

@app.get("/sw.js")
def service_worker():
    # Tidak menyimpan data konsumen/API/foto dalam cache browser.
    # Offline hanya menampilkan pemberitahuan, bukan form mutasi.
    source = r"""
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  if(e.request.mode === 'navigate' && e.request.method === 'GET') {
    e.respondWith(fetch(e.request).catch(() => new Response(
      '<!doctype html><html lang="id"><meta charset="utf-8">'+
      '<meta name="viewport" content="width=device-width,initial-scale=1">'+
      '<title>Rofi Jaya — Offline</title>'+
      '<body style="font:16px system-ui;background:#f5f6f3;color:#143e35;padding:40px">'+
      '<h1>Koneksi server terputus.</h1>'+
      '<p>Data pesanan tetap tersimpan di server. Aplikasi tidak menyimpan perubahan offline.</p>'+
      '<p>Sambungkan internet atau jaringan server, lalu muat ulang halaman.</p>'+
      '<a href="/">Coba lagi</a></body></html>',
      {headers:{'Content-Type':'text/html; charset=utf-8'},status:503}
    )));
  }
});
"""
    return Response(source, mimetype="application/javascript")

if __name__ == "__main__":
    initialize()
    from waitress import serve
    host = os.getenv("HOST", "0.0.0.0" if PAAS else "127.0.0.1")
    port = int(os.getenv("PORT", "8080"))
    threads = int(os.getenv("WEB_THREADS", "8"))
    print(f"\nRofi Jaya berjalan di http://{host}:{port}")
    print("Database dan foto: PostgreSQL (Supabase)")
    if not app.config["SESSION_COOKIE_SECURE"]:
        print("PERINGATAN: cookie session tidak ditandai Secure. "
              "Set COOKIE_SECURE=1 bila aplikasi diakses lewat HTTPS.")
    print("Gunakan HTTPS sebelum membuka aplikasi ke internet.\n")
    serve(app, host=host, port=port, threads=threads)