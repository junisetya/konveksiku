"""Simpan koneksi Supabase ke .env, lalu uji koneksinya.

Kenapa lewat skrip: file `.env` berisi rahasia (sandi database, token
Fonnte, kata sandi owner). Skrip ini hanya mengganti baris DATABASE_URL
dan tidak menampilkan sandi di layar.

Pemakaian (Windows CMD):
    python tools/setup_supabase.py
    :: tempel connection string saat diminta (boleh tanpa tanda kutip)

Pemakaian sekali jalan:
    python tools/setup_supabase.py --url "postgresql://postgres.<ref>:<sandi>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require"

Connection string diambil dari Supabase:
Project Settings → Database → Connection string → URI
(bila jaringan tidak mendukung IPv6, pilih "Session pooler").
"""
import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"


def normalize(url):
    """Rapikan URL: buang kutip/spasi, paksa sslmode=require, cek bentuk."""
    url = (url or "").strip().strip('"').strip("'").strip()
    url = url.replace(" ", "")
    if not url:
        raise ValueError("Connection string kosong.")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if not url.startswith("postgresql://"):
        raise ValueError("Harus diawali postgresql:// (salin dari Supabase, "
                         "bukan dari .env lain).")
    if "[YOUR-PASSWORD]" in url or "YOUR-PASSWORD" in url:
        raise ValueError("Ganti [YOUR-PASSWORD] dengan sandi database asli.")
    parsed = urlparse(url)
    try:
        hostname, password = parsed.hostname, parsed.password
    except ValueError:
        raise ValueError("Sandi memuat karakter yang tidak aman di URL. "
                         "Encode karakter seperti @ / # : menjadi %40 %2F %23 %3A.")
    if not hostname or not password:
        raise ValueError("URL belum memuat host dan sandi database.")
    if "@" in (password or ""):
        raise ValueError("Sandi memuat karakter @. Ganti @ dengan %40 "
                         "di dalam connection string.")
    if hostname.count(".") < 2 or " " in hostname:
        raise ValueError("Host tidak valid: " + hostname)
    if "sslmode=" not in parsed.query:
        sep = "&" if parsed.query else "?"
        url = url + sep + "sslmode=require"
    return url


def write_env(url):
    """Ganti hanya baris DATABASE_URL; komentar & baris lain dipertahankan."""
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    replaced = False
    for i, line in enumerate(lines):
        if re.match(r"^\s*DATABASE_URL\s*=", line):
            lines[i] = "DATABASE_URL=" + url
            replaced = True
            break
    if not replaced:
        lines.append("DATABASE_URL=" + url)
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        ENV.chmod(0o600)
    except OSError:
        pass


def mask(url):
    p = urlparse(url)
    host = p.hostname or "?"
    port = ":" + str(p.port) if p.port else ""
    user = p.username or ""
    return f"postgresql://{user}:***@{host}{port}{p.path}"


def ask_url():
    print("Tempel connection string Supabase (URI) lalu tekan Enter:")
    print("  Dashboard → Project Settings → Database → Connection string → URI")
    try:
        value = input("DATABASE_URL: ")
    except EOFError:
        return ""
    return value


def main():
    ap = argparse.ArgumentParser(description="Set koneksi Supabase di .env")
    ap.add_argument("--url", help="connection string Supabase")
    ap.add_argument("--no-test", action="store_true", help="jangan uji koneksi")
    args = ap.parse_args()

    raw = args.url or ask_url()
    try:
        url = normalize(raw)
    except ValueError as e:
        print("\nGAGAL:", e)
        return 2

    write_env(url)
    print("\nDATABASE_URL disimpan di", ENV)
    print("  ->", mask(url))

    if args.no_test:
        print("Uji koneksi dilewati (--no-test).")
        return 0

    print("\nMenguji koneksi…")
    os.environ["DATABASE_URL"] = url
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    # subprocess (bukan os.system) agar path Windows yang memuat spasi/
    # karakter khusus tidak diparse ulang oleh shell.
    import subprocess
    rc = subprocess.call(
        [sys.executable, str(ROOT / "tools" / "check_supabase.py")],
        cwd=str(ROOT),
        env={**os.environ, "DATABASE_URL": url},
    )
    if rc == 0:
        print("\nBerhasil. Langkah berikutnya:")
        print("  1) python app.py            (skema dibuat otomatis di Supabase)")
        print("  2) Buka http://127.0.0.1:8099 dan masuk sebagai owner")
        print("  3) Owner pertama dibuat dari OWNER_PASSWORD di .env")
    else:
        print("\nKoneksi belum berhasil. Periksa pesan di atas, lalu ulangi.")
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
