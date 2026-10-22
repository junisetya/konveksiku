"""Konfigurasi bersama antara app.py dan modul v2.

Modul ini tidak mengimpor Flask maupun app, sehingga aman diimpor dari
mana pun tanpa risiko impor melingkar.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Modul ini khusus aplikasi Rofi Jaya, jadi modul lain harus dicari di
# folder yang sama lebih dulu. Tanpa ini `import app` bisa menemukan
# paket `flask.app` saat app.py dijalankan sebagai __main__.
_HERE = str(Path(__file__).resolve().parent)
import sys as _sys  # noqa: E402
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(mode=0o700, exist_ok=True)

WIB = timezone(timedelta(hours=7))
PAAS = any(os.getenv(v) for v in (
    "FLY_APP_NAME", "RENDER_SERVICE_ID", "RAILWAY_ENVIRONMENT",
    "HEROKU_APP_NAME", "DYNO",
))


def load_env_file(path):
    """Muat KEY=VALUE dari file .env bila ada (environment selalu menang)."""
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


load_env_file(ROOT / ".env")


def now():
    return datetime.now(WIB).isoformat(timespec="seconds")


def today():
    return datetime.now(WIB).date().isoformat()


def public_base_url():
    """Alamat publik aplikasi dari APP_ORIGIN, atau host request saat ini."""
    from flask import request  # impor lokal: modul ini juga dipakai tanpa app
    origin = os.getenv("APP_ORIGIN", "").strip().rstrip("/")
    if origin:
        return origin
    base = request.host_url.rstrip("/")
    if PAAS and base.startswith("http://"):
        base = "https://" + base[len("http://"):]
    return base


def db_host(url):
    """Host:port dari DATABASE_URL tanpa menampilkan kata sandi."""
    parsed = urlparse(url or "")
    host = parsed.hostname or ""
    if not host:
        return "(tidak diketahui)"
    return host + (":" + str(parsed.port) if parsed.port else "")


def is_local_db(url):
    """True bila URL menunjuk PostgreSQL di komputer yang sama."""
    return (urlparse(url or "").hostname or "") in (
        "127.0.0.1", "localhost", "::1", "0.0.0.0")


def database_config(url):
    """Opsi koneksi psycopg2 yang aman untuk Supabase/PostgreSQL terkelola."""
    if not url:
        raise RuntimeError(
            "DATABASE_URL belum diisi. Set DATABASE_URL "
            "postgres://user:password@host:5432/dbname"
        )
    parsed = urlparse(url)
    opts = {}
    query = parse_qs(parsed.query)
    for key in ("sslmode", "sslrootcert", "sslcert", "sslkey",
                "connect_timeout", "application_name"):
        if query.get(key):
            opts[key] = query[key][0]
    opts.setdefault("sslmode", "require")
    opts.setdefault("connect_timeout", "10")
    opts.setdefault("application_name", "rofi-jaya")
    return opts


def dump(obj):
    return json.dumps(obj, ensure_ascii=False)


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
