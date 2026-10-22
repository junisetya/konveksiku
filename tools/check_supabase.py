"""Uji koneksi ke Supabase dari DATABASE_URL di .env.

Tidak mengubah data: hanya SELECT 1, cek versi, dan status tabel v2.
Jalankan: python tools/check_supabase.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
import app as A  # noqa: E402  (memuat .env)

from rofi_core import db_host, is_local_db  # noqa: E402

PLACEHOLDERS = ("PROJECT_REF", "SUPABASE_DB_PASSWORD", "SANDI", "PASSWORD@", "PROJECT.supabase")


def main():
    url = A.DATABASE_URL
    print("Database :", "SQLite lokal" if A.using_sqlite() else "PostgreSQL")
    if A.using_sqlite():
        print("DATABASE_URL di .env belum berupa URL postgres://.")
        print("Isi dulu dengan connection string Supabase (lihat .env.example).")
        return 2
    print("Server   :", db_host(url))
    if is_local_db(url):
        print("Catatan  : URL ini menunjuk PostgreSQL lokal, bukan Supabase.")
    if any(p in url for p in PLACEHOLDERS):
        print("\nGAGAL: DATABASE_URL masih memuat placeholder "
              "(PROJECT_REF / SUPABASE_DB_PASSWORD).")
        print("Ganti dengan nilai asli dari Supabase → Project Settings → Database.")
        return 2
    if "sslmode" not in url:
        print("Catatan  : tambahkan ?sslmode=require di akhir URL Supabase.")
    try:
        with A.connect() as c:
            one = c.execute("SELECT 1 AS ok").fetchone()
            ver = c.execute("SELECT current_setting('server_version') AS v").fetchone()
            tables = c.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public'"
            ).fetchall()
    except RuntimeError as e:  # pesan dari app.database_help()
        print("\nGAGAL terhubung:\n" + str(e))
        return 1
    except Exception as e:  # noqa: BLE001
        detail = str(e).splitlines()[0]
        print("\nGAGAL terhubung:", detail)
        low = detail.lower()
        if "password authentication failed" in low:
            print("  Sandi database salah. Ambil ulang dari Supabase → "
                  "Project Settings → Database → Reset database password.")
        elif "could not translate host name" in low or "name or service" in low:
            print("  Host tidak ditemukan. Periksa <ref> project / region pooler.")
        elif "timeout" in low or "timed out" in low:
            print("  Jaringan tidak bisa menjangkau host. Coba 'Session pooler' "
                  "(IPv4) karena db.<ref>.supabase.co hanya IPv6.")
        elif "does not support ssl" in low:
            print("  Tambahkan ?sslmode=require di DATABASE_URL.")
        elif "does not appear to be an IPv4" in low:
            print("  Host hanya punya IPv6. Gunakan connection string "
                  "'Session pooler' dari Supabase.")
        print("\nPeriksa juga: project tidak sedang pause (Free plan).")
        return 1
    print("Tersambung:", one["ok"] == 1, "| versi:", ver.get("v", "?"))
    names = {t["table_name"] for t in tables}
    perlu = {"owner", "settings", "orders", "order_items", "production_stages",
             "production_checklist_items", "payments", "order_status_history"}
    ada = sorted(perlu & names)
    print("Tabel v2 :", len(ada), "dari", len(perlu), "->", ", ".join(ada) or "-")
    if len(ada) < len(perlu):
        print("\nTabel belum lengkap. Jalankan aplikasi sekali "
              "(python app.py) agar skema dibuat otomatis.")
    else:
        print("\nSiap dipakai. Jalankan: python app.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
