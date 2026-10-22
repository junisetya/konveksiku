"""Reset kata sandi owner tanpa perlu login.

Dipakai saat kata sandi owner lupa atau salah. Tidak ada data pesanan yang
disentuh — hanya baris `owner` yang diperbarui.

Contoh (Windows CMD):
    set DATABASE_URL=sqlite&& python tools/reset_password.py
    python tools/reset_password.py --password "kata-sandi-baru-2026"

PowerShell:
    $env:DATABASE_URL='sqlite'; python tools/reset_password.py

Produksi (PostgreSQL/Supabase): pastikan DATABASE_URL di .env benar, lalu
    python tools/reset_password.py --password "..."
Kata sandi juga boleh diketik saat diminta (tidak tampil di layar/riwayat).
"""
import argparse
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# app.py memuat .env sendiri; pastikan folder proyek jadi cwd acuan data/.
os.chdir(ROOT)
import app as A  # noqa: E402

MIN_LEN = 12


def read_password(cli_value):
    if cli_value:
        return cli_value, False
    env_value = os.getenv("NEW_OWNER_PASSWORD", "")
    if env_value:
        return env_value, False
    if not sys.stdin.isatty():
        print("Kata sandi tidak diberikan. Gunakan --password \"...\" "
              "atau variabel NEW_OWNER_PASSWORD.")
        raise SystemExit(2)
    first = getpass.getpass("Kata sandi baru (minimal 12 karakter): ")
    second = getpass.getpass("Ulangi kata sandi baru: ")
    if first != second:
        print("Kata sandi tidak sama. Tidak ada perubahan.")
        raise SystemExit(2)
    return first, True


def main():
    parser = argparse.ArgumentParser(
        description="Reset kata sandi owner Rofi Jaya.")
    parser.add_argument("--password", "-p", default="",
                        help="kata sandi baru (minimal 12 karakter)")
    parser.add_argument("--show", action="store_true",
                        help="hanya tampilkan status owner, tanpa mengubah")
    args = parser.parse_args()

    mode = "SQLite lokal" if A.using_sqlite() else "PostgreSQL"
    print(f"Database: {mode}")
    if A.using_sqlite():
        print(f"File    : {A.SQLITE_PATH}")
    else:
        from rofi_core import db_host
        print(f"Server  : {db_host(A.DATABASE_URL)}")

    try:
        with A.connect() as c:
            row = c.execute(
                "SELECT id, password_hash FROM owner WHERE id=1").fetchone()
    except RuntimeError as e:
        print("\n" + str(e))
        raise SystemExit(2)

    if args.show:
        print("Owner   : " + ("ada (kata sandi tersimpan sebagai hash)" if row
                              else "belum ada"))
        return

    password, typed = read_password(args.password)
    if len(password) < MIN_LEN:
        print(f"Kata sandi minimal {MIN_LEN} karakter. Tidak ada perubahan.")
        raise SystemExit(2)

    new_hash = A.generate_password_hash(password)
    with A.connect() as c:
        if row:
            c.execute("UPDATE owner SET password_hash=%s WHERE id=1", (new_hash,))
            action = "Kata sandi owner diperbarui."
        else:
            c.execute("INSERT INTO owner(id, password_hash) VALUES(1,%s)",
                      (new_hash,))
            action = "Owner dibuat dengan kata sandi baru."

    print("\n" + action)
    print("Login di aplikasi memakai kata sandi yang baru saja diisi.")
    print("Semua sesi lama otomatis tidak berlaku (hash berubah).")
    if typed:
        print("Tip: simpan kata sandi di pengelola kata sandi, bukan di .env "
              "yang ikut terkirim ke server.")


if __name__ == "__main__":
    main()
