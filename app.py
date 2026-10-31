import os
import re
import io
import json
import uuid
import base64
import secrets
import sqlite3
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

# Konfigurasi path, .env, zona waktu, dan deteksi PaaS ada di rofi_core
# agar bisa dipakai modul lain (API v2, halaman nota/tracking).
from rofi_core import (  # noqa: E402
    DATA, PAAS, ROOT, WIB, database_config, db_host, is_local_db,
    load_env_file, now, public_base_url, today,
)

SECRET_FILE = DATA / "session-secret"


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


# -------------------------- Koneksi Database --------------------------

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SQLITE_PATH = Path(os.getenv("SQLITE_PATH", str(DATA / "rofi-jaya.sqlite3")))


def using_sqlite():
    """Mode lokal (tanpa PostgreSQL) memakai SQLite di data/.

    SQLite dipakai bila DATABASE_URL kosong ATAU bukan URL postgres:// —
    ini penting karena file .env bisa saja masih berisi DATABASE_URL lama,
    sehingga variabel kosong dari baris perintah tertimpa dan pengguna
    terjebak pada error koneksi. Produksi cukup mengisi URL postgres://.
    """
    return not DATABASE_URL.startswith(("postgres://", "postgresql://"))


POOL = None
POOL_LOCK = threading.Lock()
SQLITE_LOCAL = threading.local()


def get_pool():
    """Pool koneksi. Dibuat sekali lalu dipakai bersama oleh semua request."""
    global POOL
    if POOL is None:
        with POOL_LOCK:
            if POOL is None:
                try:
                    POOL = psycopg2.pool.ThreadedConnectionPool(
                        1, int(os.getenv("DB_POOL_MAX", "10")),
                        dsn=DATABASE_URL, **database_config(DATABASE_URL)
                    )
                except psycopg2.OperationalError as e:
                    raise RuntimeError(database_help(e)) from e
    return POOL


def database_help(error=None):
    """Pesan jelas saat database tidak bisa dijangkau.

    Tanpa ini pengguna hanya melihat traceback psycopg2 dan tidak tahu
    bahwa cukup mengosongkan DATABASE_URL untuk memakai SQLite lokal.
    """
    detail = str(error).splitlines()[0] if error else "-"
    local = is_local_db(DATABASE_URL)
    if local and "refused" in detail.lower():
        sebab = (
            "PostgreSQL lokal di " + db_host(DATABASE_URL) + " tidak sedang berjalan.\n"
            "  Pilih salah satu:\n"
            "   1) Hidupkan PostgreSQL/instalasi yang memakai port itu, atau\n"
            "   2) Pakai Supabase: ganti DATABASE_URL di file .env, atau\n"
            "   3) Pakai mode lokal tanpa database server (paling cepat):\n"
            "      Windows CMD:          set DATABASE_URL=&& python app.py\n"
            "      Windows PowerShell:   $env:DATABASE_URL=''; python app.py\n"
            "      Git Bash:             DATABASE_URL= python app.py\n"
            "   Catatan: DATABASE_URL yang sudah terisi di .env akan menimpa\n"
            "   variabel kosong di atas, jadi beri nilai placeholder, misalnya\n"
            "      set DATABASE_URL=sqlite&& python app.py\n"
            "   (nilai apa pun selain postgres:// akan dianggap mode SQLite).\n"
            "   Data disimpan di data/rofi-jaya.sqlite3.\n"
        )
    else:
        sebab = (
            "Tidak bisa terhubung ke database PostgreSQL di "
            + db_host(DATABASE_URL) + ".\n"
            "  - Periksa DATABASE_URL di .env / fly secrets (host, port, sandi).\n"
            "  - Pastikan server database hidup dan jaringan mengizinkan koneksi.\n"
        )
    return sebab + "  Detail: " + detail


SQLITE_SCRIPT_SPLIT = re.compile(r";\s*\n")


def _sqlite_translate(query):
    """Ubah placeholder %s menjadi ? dan tangani RETURNING.

    SQLite (>=3.35) mendukung RETURNING, jadi query seperti
    `INSERT ... ON CONFLICT ... RETURNING value` tetap berjalan.
    """
    return query.replace("%s", "?")


class SQLiteCursor:
    """Pembungkus cursor SQLite dengan API yang sama seperti psycopg2."""

    def __init__(self, conn):
        self.conn = conn
        self.cur = conn.cursor()

    def execute(self, query, params=None):
        # Satu pernyataan per panggilan. Skrip multi-pernyataan memakai
        # executescript() supaya setiap pernyataan benar-benar dijalankan
        # (sqlite3.executescript mengabaikan pernyataan setelah yang gagal
        # dan sqlite3.execute hanya menjalankan pernyataan pertama).
        vals = params
        if isinstance(vals, list):
            vals = tuple(vals)
        if vals is None:
            self.cur.execute(_sqlite_translate(query))
        else:
            self.cur.execute(_sqlite_translate(query), vals)
        return self

    def executemany(self, query, params):
        self.cur.executemany(_sqlite_translate(query), params)

    def executescript(self, script):
        self.cur.executescript(_sqlite_translate(script))

    def fetchone(self):
        row = self.cur.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self):
        return [dict(r) for r in self.cur.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())

    def close(self):
        with contextlib.suppress(Exception):
            self.cur.close()


class SQLiteConn:
    """Koneksi SQLite per-thread: murah dibuat, tidak perlu pool."""

    def __init__(self, path):
        SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), timeout=15,
                                    isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=8000")

    def cursor(self, **_):
        return self.conn.cursor()

    def commit(self):
        with contextlib.suppress(sqlite3.Error):
            self.conn.commit()

    def rollback(self):
        with contextlib.suppress(sqlite3.Error):
            self.conn.rollback()


class DBWrapper:
    """Pembungkus cursor yang dipakai seluruh aplikasi."""

    def __init__(self, conn, sqlite=False):
        self.conn = conn
        self.cursor = SQLiteCursor(conn) if sqlite else conn.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor)
    def execute(self, query, params=None):
        self.cursor.execute(query, params)
        return self.cursor
    def executemany(self, query, params):
        self.cursor.executemany(query, params)
    def executescript(self, script):
        # SQLite: cursor.executescript; psycopg2 tidak punya executescript(),
        # jadi skrip DDL dikirim sebagai satu perintah biasa.
        if isinstance(self.cursor, SQLiteCursor):
            self.cursor.executescript(script)
        else:
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
    """Satu koneksi per operasi; selalu dikembalikan, even saat error."""
    if using_sqlite():
        conn = SQLiteConn(SQLITE_PATH)
        wrapper = DBWrapper(conn, sqlite=True)
        wrapper.conn.conn.execute("BEGIN")
        try:
            try:
                yield wrapper
            except Exception:
                wrapper.rollback()
                raise
            else:
                wrapper.commit()
        finally:
            wrapper.close_cursor()
            with contextlib.suppress(Exception):
                conn.conn.close()
        return
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
            data TEXT NOT NULL,
            target TEXT NOT NULL DEFAULT '',
            life TEXT NOT NULL DEFAULT 'active'
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
    elif request.path.startswith(("/nota/", "/tracking/", "/g/")):
        # Halaman konsumen: token unik per pesanan, boleh di-cache singkat
        # agar progres terbaru tetap cepat terlihat saat dibuka ulang.
        response.headers["Cache-Control"] = "private, max-age=30"
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
        if action == "pay":
            # Pembayaran v1 tetap tercatat sebagai transaksi di tabel
            # payments agar nota & ringkasan v2 konsisten.
            with contextlib.suppress(Exception):
                c.execute(
                    "INSERT INTO payments(id,order_id,amount,date,method,note,"
                    "reference,kind,recorded_at) VALUES(%s,%s,%s,%s,%s,%s,'',%s,%s)",
                    (p["id"], ident, p["amount"], p["date"],
                     "Tunai/Transfer", p.get("note", ""), p.get("kind", "Pembayaran"),
                     p.get("at", now()))
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
    ("orders", "SELECT id,number,version,data,target,life,customer_name,agreed_date,tracking_token,total,updated_at FROM orders ORDER BY number"),
    ("customers", "SELECT * FROM customers"),
    ("order_items", "SELECT * FROM order_items ORDER BY order_id, position"),
    ("size_breakdowns", "SELECT * FROM size_breakdowns"),
    ("production_stages", "SELECT * FROM production_stages ORDER BY order_id, stage_key"),
    ("production_checklist_items", "SELECT * FROM production_checklist_items ORDER BY order_id, position"),
    ("payments", "SELECT * FROM payments ORDER BY order_id, date"),
    ("order_status_history", "SELECT * FROM order_status_history ORDER BY order_id, at"),
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
# UI v2 ada di rofi_ui.py, API v2 di rofi_api_v2.py. Bagian HTML lama
# (v1) sengaja tidak dipakai lagi agar dashboard tidak tampil ganda.

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
import migrate_v2 as _mig

# app.py bisa berjalan sebagai __main__ (python app.py) sekaligus diimpor
# modul lain. Daftarkan modul ini dengan nama "app" supaya `from app import
# app` di rofi_api_v2 selalu mengacu ke instans Flask yang sama — tanpa ini
# Flask bisa terduplikasi dan route v2 tidak pernah terpasang.
if __name__ == "__main__":
    sys.modules.setdefault("app", sys.modules["__main__"])

import rofi_api_v2  # noqa: E402,F401  (mendaftarkan route v2 + migrasi)
from rofi_ui import HTML  # noqa: E402

import telegram_bot  # noqa: E402,F401  (bot Telegram: webhook /telegram/webhook)
telegram_bot.setup(app)

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


@app.get("/robots.txt")
def robots():
    from perf import robots_txt
    return Response(robots_txt(public_base_url()), mimetype="text/plain")


@app.get("/sitemap.xml")
def sitemap():
    from perf import sitemap_xml
    return Response(sitemap_xml(public_base_url()),
                    mimetype="application/xml")


@app.get("/favicon.ico")
def favicon():
    """Hindari 404 di console browser; ikon sama dengan ikon PWA 32px."""
    return icon(192)


if __name__ == "__main__":
    try:
        initialize()
        with connect() as _c:
            _mig.ensure_schema(_c)
            _mig.backfill(_c)
        rofi_api_v2.v2_ready = True
    except RuntimeError as _err:
        print("\n" + str(_err) + "\n")
        raise SystemExit(2)
    except psycopg2.Error as _err:
        print("\n" + database_help(_err) + "\n")
        raise SystemExit(2)
    from waitress import serve
    host = os.getenv("HOST", "0.0.0.0" if PAAS else "127.0.0.1")
    port = int(os.getenv("PORT", "8080"))
    threads = int(os.getenv("WEB_THREADS", "8"))
    print(f"\nRofi Jaya berjalan di http://{host}:{port}")
    print("Database dan foto: " + ("SQLite lokal (data/rofi-jaya.sqlite3)"
                                  if using_sqlite() else "PostgreSQL (Supabase)"))
    if not app.config["SESSION_COOKIE_SECURE"]:
        print("PERINGATAN: cookie session tidak ditandai Secure. "
              "Set COOKIE_SECURE=1 bila aplikasi diakses lewat HTTPS.")
    print("Gunakan HTTPS sebelum membuka aplikasi ke internet.\n")
    serve(app, host=host, port=port, threads=threads)
