"""Buat pesanan contoh di SQLite lokal untuk diperiksa di browser.

Jalankan setelah aplikasi dihentikan (supaya tidak bentrok file database):
    DATABASE_URL="" python tools/seed_demo.py
Data ini HANYA untuk melihat tampilan; hapus file data/rofi-jaya.sqlite3
untuk memulai dari kosong.
"""
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = ""
os.environ.setdefault("SQLITE_PATH", str(ROOT / "data" / "rofi-jaya.sqlite3"))
os.environ["OWNER_PASSWORD"] = "demo-rofi-jaya-2026"  # hanya untuk data contoh
os.environ.setdefault("SECRET_KEY", "d" * 64)
os.environ["APP_ORIGIN"] = "http://127.0.0.1"  # .env bisa berisi domain lain

import app as A  # noqa: E402

A.initialize()
client = A.app.test_client()
ORIGIN = {"Origin": "http://127.0.0.1"}


def login():
    r = client.post("/api/login", data=json.dumps(
        {"password": os.environ["OWNER_PASSWORD"]}),
        headers=ORIGIN, content_type="application/json")
    return r.get_json()["csrf"] if r.status_code == 200 else ""


csrf = login()
if not csrf:
    print("Gagal login. Ubah OWNER_PASSWORD atau hapus data/rofi-jaya.sqlite3.")
    sys.exit(1)
H = {**ORIGIN, "X-CSRF-Token": csrf}


def post(path, payload):
    r = client.post(path, data=json.dumps(payload), headers=H,
                    content_type="application/json")
    if r.status_code != 200:
        print("GAGAL", path, r.status_code, r.get_json())
        sys.exit(1)
    return r.get_json()


today = date.today()
orders = [
    {
        "customer": "Budi Santoso", "wa": "081234567890", "company": "SMK Negeri 1",
        "address": "Jl. Merdeka 10", "deal": (today - timedelta(days=10)).isoformat(),
        "target": (today + timedelta(days=9)).isoformat(),
        "agreement_note": "Baju batik seragam guru, motif parang sogan.",
        "items": [
            {"garment": "Baju batik", "name": "Batik PDL Guru", "material": "Katun primis",
             "color": "Sogan", "qty": 24, "price": 175000,
             "sizes": [{"label": "M", "qty": 12}, {"label": "L", "qty": 12}],
             "design": "Kerah kemeja, bordir logo sekolah"},
        ],
        "dp": 2000000, "dp_method": "Transfer bank", "dp_note": "BCA 12/10",
        "steps": ["start:potong", "finish:potong", "start:jahit", "finish:jahit",
                  "start:finishing"],
    },
    {
        "customer": "Rina Wulandari", "wa": "081377788899", "company": "Komunitas Lari Pagi",
        "deal": (today - timedelta(days=4)).isoformat(),
        "target": (today + timedelta(days=16)).isoformat(),
        "items": [
            {"garment": "Jersey", "name": "Jersey lari dri-fit", "material": "Dri-fit",
             "color": "Hijau sage", "qty": 40, "price": 135000,
             "sizes": [{"label": "S", "qty": 10}, {"label": "M", "qty": 15},
                       {"label": "L", "qty": 15}], "printing": "Sublim"},
        ],
        "dp": 1500000, "dp_method": "E-wallet", "steps": ["start:potong"],
    },
    {
        "customer": "Hendra Pratama", "wa": "081255566677", "company": "PT Sinar Abadi",
        "deal": (today - timedelta(days=40)).isoformat(),
        "target": (today - timedelta(days=12)).isoformat(),
        "items": [
            {"garment": "Kemeja", "name": "Kemeja kerja lengan panjang",
             "material": "Katun Oxford", "color": "Putih", "qty": 30, "price": 165000,
             "sizes": [{"label": "M", "qty": 10}, {"label": "L", "qty": 20}],
             "design": "Bordir logo di dada kiri"},
        ],
        "dp": 4950000, "dp_method": "Transfer bank", "steps": [],
    },
]

created = []
for spec in orders:
    payload = {k: v for k, v in spec.items() if k not in ("steps",)}
    result = post("/api/v2/orders", payload)
    oid = result["id"]
    created.append((oid, result["number"]))
    for step in spec.get("steps", []):
        action, stage = step.split(":")
        body = {"action": action, "stage": stage}
        if action == "start":
            body["start"] = (today - timedelta(days=2)).isoformat()
        post(f"/api/v2/orders/{oid}/stage", body)
    print(f"  {result['number']} · {spec['customer']}")

# Pelunasan + penyerahan untuk pesanan ketiga agar statusnya berbeda.
oid = created[2][0]
order = client.get(f"/api/v2/orders/{oid}").get_json()["order"]
if order["remaining"]:
    post(f"/api/v2/orders/{oid}/payment",
         {"amount": order["remaining"], "method": "Transfer bank",
          "date": today.isoformat(), "note": "Pelunasan"})

print("\nSelesai. Masuk dengan kata sandi:", os.environ["OWNER_PASSWORD"])
print("Hapus data/rofi-jaya.sqlite3 bila ingin memulai tanpa data contoh.")
