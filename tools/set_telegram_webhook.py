"""Set/cek webhook bot Telegram untuk Rofi Konveksi.

Pemakaian:
    python tools/set_telegram_webhook.py --url https://rofi-jaya.fly.dev/telegram/webhook
    python tools/set_telegram_webhook.py --check

Butuh TELEGRAM_TOKEN (dan opsional TELEGRAM_WEBHOOK_SECRET) di .env / env.
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rofi_core import load_env_file  # noqa: E402

load_env_file(ROOT / ".env")

TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
API_BASE = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").strip().rstrip("/")


def _call(method, payload):
    if not TOKEN:
        print("TELEGRAM_TOKEN belum diset di .env.", file=sys.stderr)
        raise SystemExit(2)
    req = urllib.request.Request(
        f"{API_BASE}/bot{TOKEN}/{method}", data=json.dumps(payload).encode(),
        method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()[:300]}", file=sys.stderr)
        raise SystemExit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="URL webhook publik, mis. https://rofi-jaya.fly.dev/telegram/webhook")
    ap.add_argument("--check", action="store_true", help="Tampilkan info webhook saat ini")
    a = ap.parse_args()

    if a.check:
        data = _call("getWebhookInfo", {})
        print(json.dumps(data.get("result", data), indent=2, ensure_ascii=False))
        return

    if not a.url:
        ap.error("butuh --url atau --check")

    payload = {"url": a.url}
    if SECRET:
        payload["secret_token"] = SECRET
    data = _call("setWebhook", payload)
    if data.get("ok"):
        print("Webhook diset:", a.url)
        if SECRET:
            print("Secret token ikut diset.")
    else:
        print("Gagal:", data.get("description"), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
