"""Uji alur nyata v2 memakai Flask test client.

Membutuhkan mode lokal (SQLite): jalankan dengan
    DATABASE_URL="" SQLITE_PATH="data/rofi-e2e.sqlite3" OWNER_PASSWORD=... \
        python tools/e2e_v2.py

Setiap langkah memakai HTTP seperti aplikasi sungguhan (login, CSRF,
create order, tahap produksi, pembayaran, tracking publik).
"""
import json
import os
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Uji memakai SQLite lokal yang terpisah dari data aplikasi; nilai .env
# (DATABASE_URL produksi) sengaja ditimpa agar tidak menyentuh data asli.
os.environ["SQLITE_PATH"] = str(ROOT / "data" / "rofi-e2e.sqlite3")
os.environ["OWNER_PASSWORD"] = os.environ.get("E2E_PASSWORD", "uji-konveksi-2026")
os.environ["SECRET_KEY"] = "z" * 64
os.environ["DATABASE_URL"] = ""
os.environ["APP_ORIGIN"] = "http://127.0.0.1"
os.environ["FONNTE_TOKEN"] = ""

for stale in Path(os.environ["SQLITE_PATH"]).parent.glob("rofi-e2e.sqlite3*"):
    try:
        stale.unlink()
    except OSError:
        pass

import app as A  # noqa: E402

A.initialize()
client = A.app.test_client()
ORIGIN = {"Origin": "http://127.0.0.1"}
fails = []


def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + ("" if cond else f" :: {extra}"))
    if not cond:
        fails.append(name)


def post(path, payload, csrf=True):
    headers = dict(ORIGIN)
    if csrf:
        headers["X-CSRF-Token"] = client.get("/api/v2/state").get_json().get("csrf", "")
    r = client.post(path, data=json.dumps(payload), headers=headers,
                    content_type="application/json")
    return r


print("1. Halaman & akses publik")
r = client.get("/")
check("halaman utama 200", r.status_code == 200)
check("UI v2 dimuat", b"/api/v2/state" in r.data or b"v2/state" in r.data)
check("tanpa login state 401", client.get("/api/v2/state").status_code == 401)
check("tanpa login order detail 401", client.get("/api/v2/orders/abc").status_code == 401)
r = post("/api/v2/orders", {"customer": "x", "wa": "0812"}, csrf=False)
check("tanpa CSRF/login ditolak", r.status_code in (401, 403), r.status_code)

print("2. Login owner")
r = post("/api/login", {"password": "salah-password"}, csrf=False)
check("password salah ditolak", r.status_code == 401)
r = post("/api/login", {"password": os.environ["OWNER_PASSWORD"]}, csrf=False)
check("password benar diterima", r.status_code == 200, r.data[:200])
csrf = r.get_json()["csrf"]
st = client.get("/api/v2/state").get_json()
check("state memuat pengaturan", st["settings"]["name"] == "Rofi Jaya")
check("4 tahap tersedia", [k for k, _ in st["stages"]] == ["potong", "jahit", "finishing", "serah"])
check("checklist default 6 item", len(st["checklist"]) == 6)

print("3. Buat pesanan (validasi + simpan)")
bad = {
    "customer": "Budi", "wa": "081234567890", "deal": A.today(), "target": A.today(),
    "items": [{"garment": "Batik", "qty": 10, "price": 150000,
               "sizes": [{"label": "M", "qty": 3}]}],
}
r = post("/api/v2/orders", bad)
check("ukuran tidak cocok ditolak", r.status_code == 400, r.get_json())
bad["items"][0]["sizes"] = [{"label": "M", "qty": 4}, {"label": "L", "qty": 6}]
bad["dp"] = 10_000_000
r = post("/api/v2/orders", bad)
check("DP > total ditolak", r.status_code == 400, r.get_json())

payload = {
    "customer": "Budi Santoso", "wa": "081234567890", "company": "SMK Negeri 1",
    "address": "Jl. Merdeka 10", "customer_note": "Kirim sebelum wisuda",
    "agreement_note": "Batik tulis cap, warna sogan.",
    "deal": A.today(), "target": A.today(),
    "items": [
        {"garment": "Baju batik", "name": "Batik PDL Sekolah", "material": "Katun primis",
         "color": "Sogan", "qty": 20, "price": 175000,
         "sizes": [{"label": "M", "qty": 10}, {"label": "L", "qty": 10}],
         "design": "Motif parang, bordir logo sekolah"},
        {"garment": "Celana", "name": "Celana bahan hitam", "material": "Drill",
         "color": "Hitam", "qty": 10, "price": 125000, "sizes": []},
    ],
    "discount": 100000, "extra": 50000,
    "dp": 1000000, "dp_method": "Transfer bank", "dp_note": "Transfer BCA",
}
expect_total = 20 * 175000 + 10 * 125000 - 100000 + 50000
r = post("/api/v2/orders", payload)
check("pesanan dibuat", r.status_code == 200, r.get_json())
oid = r.get_json()["id"]
number = r.get_json()["number"]
o = client.get(f"/api/v2/orders/{oid}").get_json()["order"]
check("total dihitung benar", o["total"] == expect_total, o["total"])
check("sisa = total - DP", o["remaining"] == expect_total - 1000000, o["remaining"])
check("status pembayaran DP Dibayar", o["payment_status"] == "DP Dibayar", o["payment_status"])
check("status produksi Menunggu Potong", o["status"] == "Menunggu Potong", o["status"])
check("qty total 30", o["qty"] == 30, o["qty"])
check("tracking token acak", len(o["tracking_token"]) >= 24 and number not in o["tracking_token"])
check("4 tahap dibuat", len(o["stages"]) == 4)
check("checklist belum dicentang", not any(x["done"] for x in o["checklist"]))

print("4. Aturan urutan tahap")
r = post(f"/api/v2/orders/{oid}/stage", {"action": "finish", "stage": "potong"})
check("finish sebelum mulai ditolak", r.status_code == 400, r.get_json())
r = post(f"/api/v2/orders/{oid}/stage", {"action": "start", "stage": "jahit"})
check("jahit sebelum potong ditolak", r.status_code == 400, r.get_json())
r = post(f"/api/v2/orders/{oid}/stage", {"action": "start", "stage": "potong",
                                        "start": A.today(), "note": "Bahan sudah dipotong"})
check("mulai potong", r.status_code == 200, r.get_json())

print("5. Nota & tracking publik")
nota = client.get(f"/nota/{o['tracking_token']}")
check("nota publik 200", nota.status_code == 200)
check("nota memuat nomor", number.encode() in nota.data)
check("nota memuat total", A.format_rupiah(expect_total).encode() in nota.data)
track = client.get(f"/tracking/{o['tracking_token']}")
check("tracking 200", track.status_code == 200)
check("tracking menampilkan Sedang Dipotong", "Sedang Dipotong".encode() in track.data)
check("tracking menyamarkan nama", b"Bu" in track.data and b"Budi Santoso" not in track.data)
check("token tidak valid 404", client.get("/tracking/tidak-valid-token").status_code == 404)
check("nota token tidak valid 404", client.get("/nota/ngawur").status_code == 404)
check("tracking tidak membocorkan harga", A.format_rupiah(expect_total).encode() not in track.data)

print("6. Selesaikan potong → jahit → finishing")
check("finish potong", post(f"/api/v2/orders/{oid}/stage",
                            {"action": "finish", "stage": "potong"}).status_code == 200)
o = client.get(f"/api/v2/orders/{oid}").get_json()["order"]
check("status Potong Selesai", o["status"] == "Potong Selesai", o["status"])
check("mulai jahit", post(f"/api/v2/orders/{oid}/stage",
                          {"action": "start", "stage": "jahit"}).status_code == 200)
check("finish jahit", post(f"/api/v2/orders/{oid}/stage",
                           {"action": "finish", "stage": "jahit"}).status_code == 200)
check("tahap jahit selesai", client.get(f"/api/v2/orders/{oid}").get_json()["order"]["stages"][1]["state"] == "done")
check("mulai finishing", post(f"/api/v2/orders/{oid}/stage",
                              {"action": "start", "stage": "finishing"}).status_code == 200)
r = post(f"/api/v2/orders/{oid}/stage", {"action": "finish", "stage": "finishing"})
check("finish finishing ditolak sebelum checklist", r.status_code == 400, r.get_json())
o = client.get(f"/api/v2/orders/{oid}").get_json()["order"]
for item in o["checklist"]:
    post(f"/api/v2/orders/{oid}/checklist", {"item": item["id"]})
o = client.get(f"/api/v2/orders/{oid}").get_json()["order"]
check("semua checklist selesai", all(x["done"] for x in o["checklist"]))
check("finish finishing", post(f"/api/v2/orders/{oid}/stage",
                               {"action": "finish", "stage": "finishing"}).status_code == 200)
o = client.get(f"/api/v2/orders/{oid}").get_json()["order"]
check("status Siap Diserahkan", o["status"] == "Siap Diserahkan", o["status"])
track = client.get(f"/tracking/{o['tracking_token']}")
check("tracking menunjukkan Siap Diserahkan", "Siap Diserahkan".encode() in track.data)

print("7. Pembayaran")
r = post(f"/api/v2/orders/{oid}/payment",
         {"amount": expect_total, "method": "Tunai", "date": A.today()})
check("bayar lebih dari sisa ditolak", r.status_code == 400, r.get_json())
r = post(f"/api/v2/orders/{oid}/payment",
         {"amount": 500000, "method": "Transfer bank", "date": A.today(), "note": "Cicilan 1"})
check("cicilan dicatat", r.status_code == 200, r.get_json())
o = client.get(f"/api/v2/orders/{oid}").get_json()["order"]
check("pembayaran = DP + cicilan", o["paid"] == 1500000, o["paid"])
check("sisa diperbarui", o["remaining"] == expect_total - 1500000, o["remaining"])
check("status Pembayaran Sebagian", o["payment_status"] == "Pembayaran Sebagian")
pid = o["payments"][-1]["id"]
check("koreksi pembayaran butuh alasan",
      post(f"/api/v2/orders/{oid}/payment/{pid}/void", {}).status_code == 400)
check("koreksi pembayaran",
      post(f"/api/v2/orders/{oid}/payment/{pid}/void", {"reason": "Salah input"}).status_code == 200)
o = client.get(f"/api/v2/orders/{oid}").get_json()["order"]
check("sisa kembali setelah koreksi", o["remaining"] == expect_total - 1000000)
check("transaksi koreksi tetap tersimpan", len(o["voided_payments"]) == 1)
post(f"/api/v2/orders/{oid}/payment",
     {"amount": expect_total - 1000000, "method": "Transfer bank", "date": A.today()})
o = client.get(f"/api/v2/orders/{oid}").get_json()["order"]
check("lunas setelah pelunasan", o["payment_status"] == "Lunas", o["payment_status"])

print("8. Penyerahan & selesai")
check("penyerahan dicatat",
      post(f"/api/v2/orders/{oid}/handover",
           {"method": "Diambil konsumen", "date": A.today()}).status_code == 200)
o = client.get(f"/api/v2/orders/{oid}").get_json()["order"]
check("status Selesai Diserahkan", o["status"] == "Selesai Diserahkan", o["status"])
check("pesanan selesai", post(f"/api/v2/orders/{oid}/life",
                              {"life": "done", "reason": "Sudah diterima"}).status_code == 200)
o = client.get(f"/api/v2/orders/{oid}").get_json()["order"]
check("life done", o["life"] == "done")
check("riwayat aktivitas tersimpan", len(o["history"]) >= 8, len(o["history"]))

print("9. WhatsApp")
wa = post(f"/api/v2/orders/{oid}/wa", {"kind": "nota"}).get_json()
check("pesan nota memuat nomor", number in wa["message"])
check("link wa.me valid", wa["url"].startswith("https://wa.me/6281234567890?text="))
check("link nota absolut", wa["nota"].startswith("http"))
check("pesan ter-encode", "%0A" in wa["url"] or urllib.parse.quote(wa["message"]) in wa["url"])
wa2 = post(f"/api/v2/orders/{oid}/wa", {"kind": "tracking"}).get_json()
check("pesan tracking memuat tautan tracking", wa2["tracking"] in wa2["message"])

print("10. Data bertahan setelah restart proses")
again = A.app.test_client()
again.post("/api/login", data=json.dumps({"password": os.environ["OWNER_PASSWORD"]}),
           headers=ORIGIN, content_type="application/json")
check("pesanan masih ada setelah klien baru",
      again.get(f"/api/v2/orders/{oid}").status_code == 200)
check("tracking tetap dapat dibuka publik",
      again.get(f"/tracking/{o['tracking_token']}").status_code == 200)

print()
if fails:
    print(f"{len(fails)} pemeriksaan GAGAL: {fails}")
    sys.exit(1)
print("Semua pemeriksaan alur v2 lolos.")
