"""Set secret Fly.io dari file .env (tanpa mencetak nilai rahasia).

Pemakaian (dari root proyek):
    python tools/set_fly_secrets.py

Variabel yang disalin dari .env:
    DATABASE_URL, SECRET_KEY, OWNER_PASSWORD, FONNTE_TOKEN,
    IMAGEKIT_PRIVATE_KEY, IMAGEKIT_URL_ENDPOINT,
    TELEGRAM_TOKEN, TELEGRAM_ALLOWED_IDS, TELEGRAM_WEBHOOK_SECRET (opsional)

APP_ORIGIN SELALU dipaksa ke https://rofi-jaya.fly.dev untuk produksi.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

KEYS = [
    "DATABASE_URL", "SECRET_KEY", "OWNER_PASSWORD", "FONNTE_TOKEN",
    "IMAGEKIT_PRIVATE_KEY", "IMAGEKIT_URL_ENDPOINT",
    "TELEGRAM_TOKEN", "TELEGRAM_ALLOWED_IDS", "TELEGRAM_WEBHOOK_SECRET",
]


def load_env(path):
    env = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return env
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k:
            env[k] = v.strip().strip('"').strip("'")
    return env


def main():
    env = load_env(ROOT / ".env")
    args = ["fly", "secrets", "set"]
    found = []
    for k in KEYS:
        v = env.get(k, "").strip()
        if k == "TELEGRAM_WEBHOOK_SECRET" and not v:
            continue
        if not v:
            print(f"  [SKIP] {k} kosong")
            continue
        args.append(f"{k}={v}")
        found.append(k)
    args.append("APP_ORIGIN=https://rofi-jaya.fly.dev")
    found.append("APP_ORIGIN")
    print("Akan mengirim secret:", ", ".join(found))
    print("Menjalankan: fly secrets set ...")
    r = subprocess.run(args, cwd=str(ROOT))
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
