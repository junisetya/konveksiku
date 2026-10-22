"""Pemeriksaan cepat tanpa server.

Memeriksa aturan validasi input, template pesan, dan konfigurasi keamanan
tanpa perlu database yang hidup.

Jalankan: python tools/check.py
"""
import os
import re
import sys
import json
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
os.environ.setdefault("OWNER_PASSWORD", "sepatu-konveksi-2026")
os.environ.setdefault("SECRET_KEY", "x" * 64)

try:
    spec = importlib.util.spec_from_file_location("appmod", ROOT / "app.py")
    app_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app_mod)
except ModuleNotFoundError as e:
    print(f"Tidak bisa memuat app.py: {e}. "
          "Jalankan `pip install -r requirements.txt` lebih dulu.")
    sys.exit(2)

failures = []


def assert_true(cond, msg="kondisi tidak terpenuhi"):
    assert cond, msg


def expect_error(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except app_mod.ValidationError:
        return
    raise AssertionError("diharapkan ValidationError, tidak Raised")


def check(name, fn):
    try:
        fn()
        print(f"  OK   {name}")
    except AssertionError as e:
        failures.append((name, str(e)))
        print(f"  FAIL {name}: {e}")
    except Exception as e:  # noqa: BLE001
        failures.append((name, repr(e)))
        print(f"  ERR  {name}: {e!r}")


def placeholders():
    out = set()
    for t in app_mod.TEMPLATES.values():
        out |= set(re.findall(r"\{(\w+)\}", t))
    return out


KNOWN_VARS = {
    "nama", "nomor", "jenis", "jumlah", "status", "estimasi", "ringkasan",
    "usaha", "total", "dibayar", "sisa", "metode", "kurir", "resi",
    "tanggal_kirim", "tiba", "diterima",
}


def routes_lengkap():
    required = {
        "/api/login", "/api/logout", "/api/state", "/api/settings",
        "/api/password", "/api/orders", "/api/orders/<ident>/action",
        "/api/photos/<ident>", "/api/backup", "/api/backup/restore",
        "/api/healthz", "/", "/manifest.webmanifest", "/sw.js",
        "/api/notify/status", "/api/notify/device", "/api/notify/test",
        "/api/notify/stage", "/api/notify/message",
        "/api/gallery-link/<ident>", "/g/<token>", "/g/<token>/p/<photo_id>",
    }
    have = {r.rule for r in app_mod.app.url_map.iter_rules()}
    hilang = required - have
    assert not hilang, f"route hilang: {sorted(hilang)}"


def header_aman(path, expect_cache):
    client = app_mod.app.test_client()
    resp = client.get(path)
    headers = resp.headers
    assert headers.get("X-Frame-Options") == "DENY", "X-Frame-Options"
    assert headers.get("X-Content-Type-Options") == "nosniff", "nosniff"
    assert "frame-ancestors 'none'" in headers.get(
        "Content-Security-Policy", ""), "CSP"
    assert headers.get("Cache-Control") == expect_cache, (
        f"Cache-Control = {headers.get('Cache-Control')!r}, "
        f"harusnya {expect_cache!r}")


def _sw_source():
    client = app_mod.app.test_client()
    return client.get("/sw.js").get_data(as_text=True)


print("validasi input")

check("teks terlalu panjang ditolak", lambda: expect_error(
    app_mod.text, "x" * 3000, 2000))
check("angka negatif ditolak", lambda: expect_error(
    app_mod.integer, "-5", 0, 10))
check("angka desimal ditolak", lambda: expect_error(
    app_mod.integer, "1.5", 0, 10))
check("angka boolean ditolak", lambda: expect_error(
    app_mod.integer, True, 0, 10))
check("tanggal format salah ditolak", lambda: expect_error(
    app_mod.date_value, "21-10-2026"))
check("nomor WA 08 -> 62", lambda: assert_true(
    app_mod.normalize_wa("081234567890") == "6281234567890"))
check("nomor WA 8 -> 62", lambda: assert_true(
    app_mod.normalize_wa("81234567890") == "6281234567890"))
check("nomor WA tidak valid ditolak", lambda: expect_error(
    app_mod.normalize_wa, "12345"))

print("struktur data")
check("prefix 2-12 huruf/angka valid", lambda: assert_true(
    re.fullmatch(r"[A-Z0-9]{2,12}", "KVK") is not None))
check("prefix terlalu pendek tidak valid", lambda: assert_true(
    re.fullmatch(r"[A-Z0-9]{2,12}", "K") is None))
check("ada 3 tahap produksi", lambda: assert_true(
    len(app_mod.STAGES) == 3))
check("default_days dalam rentang", lambda: assert_true(
    1 <= app_mod.DEFAULT_SETTINGS["default_days"] <= 365))
check("semua template pesan terisi", lambda: assert_true(
    all(v.strip() for v in app_mod.TEMPLATES.values())))
check("placeholder template dikenal", lambda: assert_true(
    placeholders() <= KNOWN_VARS, f"tak dikenal: {placeholders() - KNOWN_VARS}"))

print("notifikasi WhatsApp")


def _row(**kw):
    """Baris pesanan tiruan, seperti hasil SELECT di server."""
    data = {
        "customer": "Budi", "garment": "Kemeja", "material": "Katun",
        "color": "Biru", "qty": 10, "total": 500000, "target": "2026-11-01",
        "deal": "2026-10-01", "wa": "6281234567890", "payments": [],
        "stages": [{"state": "pending", "start": "", "estimate": "",
                    "finished": "", "note": ""} for _ in app_mod.STAGES],
        "history": [], "issues": [], "qc": {}, "checklist": [],
        "life": "active", "shipping": None, "received": "",
    }
    data.update(kw)
    return {"id": "abc123", "number": "KVK-202610-0001",
            "version": 1, "data": json.dumps(data)}


def pesanan_lengkap():
    return app_mod.order_from_row(_row())


check("pesanan dari database punya id", lambda: assert_true(
    app_mod.order_from_row(_row()).get("id") == "abc123"))
check("pesanan dari database punya number", lambda: assert_true(
    app_mod.order_from_row(_row()).get("number") == "KVK-202610-0001"))
check("nomor pesanan ikut di ringkasan", lambda: assert_true(
    "KVK-202610-0001" in app_mod.order_summary(pesanan_lengkap())))
check("id/number tidak ikut disimpan di blob", lambda: assert_true(
    "id" not in json.loads(app_mod.order_data(pesanan_lengkap()))
    and "number" not in json.loads(app_mod.order_data(pesanan_lengkap()))))
check("pesan tahap tidak melempar tanpa id", lambda: assert_true(
    isinstance(app_mod.render_message(
        app_mod.TEMPLATES["potong"], pesanan_lengkap(),
        app_mod.order_summary(pesanan_lengkap()), "Rofi Jaya"), str)))
check("notifikasi otomatis aktif secara bawaan", lambda: assert_true(
    app_mod.DEFAULT_SETTINGS["auto_notify"] is True))


def variabel_terisi():
    """Setiap variabel yang dijanjikan UI harus benar-benar diganti.

    Template bawaan tidak memakai semua variabel (mis. {status}), jadi yang
    diperiksa bukan "dipakai di template", melainkan "tersedia saat
    pengiriman". Kalau tidak, UI menjanjikan variabel yang tak pernah terisi.
    """
    o = app_mod.order_from_row(_row())
    contoh = " ".join("{" + v + "}" for v in sorted(KNOWN_VARS))
    hasil = app_mod.render_message(contoh, o, "ringkasan", "Rofi Jaya")
    sisa = set(re.findall(r"\{(\w+)\}", hasil))
    assert not sisa, f"variabel tidak terisi: {sorted(sisa)}"


check("variabel template benar-benar terisi", variabel_terisi)
check("semua tahap punya template pesan", lambda: assert_true(
    all(stage in app_mod.STAGE_TEMPLATE for stage in app_mod.STAGES)))
check("semua tahap punya template terdaftar", lambda: assert_true(
    all(app_mod.STAGE_TEMPLATE[s] in app_mod.TEMPLATES
        for s in app_mod.STAGES)))


def minta_fonnte(env, urls):
    """Daftar permintaan Fonnte dengan environment sementara."""
    lama = {k: os.environ.get(k) for k in env}
    try:
        os.environ.update({k: str(v) for k, v in env.items()})
        return app_mod.fonnte_requests("6281234567890", "halo", urls)
    finally:
        for k, v in lama.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


check("tanpa foto hanya satu permintaan", lambda: assert_true(
    len(minta_fonnte({}, [])) == 1
    and "url" not in minta_fonnte({}, [])[0]))
check("satu foto dilampirkan pada field url", lambda: assert_true(
    minta_fonnte({"FONNTE_IMAGE_MODE": "single"},
                 ["https://contoh.test/a.jpg"])[0].get("url")
    == "https://contoh.test/a.jpg"))
check("Fonnte tidak punya field images", lambda: assert_true(
    all("images" not in r for r in minta_fonnte(
        {"FONNTE_IMAGE_MODE": "comma"},
        ["https://contoh.test/a.jpg", "https://contoh.test/b.jpg"]))))
check("banyak foto jadi beberapa permintaan berurutan", lambda: assert_true(
    [r.get("url") for r in minta_fonnte(
        {"FONNTE_IMAGE_MODE": "comma"},
        ["https://contoh.test/a.jpg", "https://contoh.test/b.jpg"])]
    == ["https://contoh.test/a.jpg", "https://contoh.test/b.jpg"]))
check("teks lengkap hanya pada permintaan pertama", lambda: assert_true(
    minta_fonnte({"FONNTE_IMAGE_MODE": "comma"},
                 ["https://contoh.test/a.jpg", "https://contoh.test/b.jpg"]
                 )[0].get("message") == "halo"))
check("tidak ada permintaan dengan message kosong", lambda: assert_true(
    all(r.get("message") for r in minta_fonnte(
        {"FONNTE_IMAGE_MODE": "comma"},
        ["https://contoh.test/a.jpg", "https://contoh.test/b.jpg",
         "https://contoh.test/c.jpg"])),
    "Fonnte menolak message kosong: 'message cannot empty'"))
check("teks lanjutan kosong tetap diberi cadangan", lambda: assert_true(
    all(r.get("message") for r in minta_fonnte(
        {"FONNTE_IMAGE_MODE": "comma", "FONNTE_FOLLOWUP_TEXT": ""},
        ["https://contoh.test/a.jpg", "https://contoh.test/b.jpg"]))))
check("foto lanjutan diberi jeda", lambda: assert_true(
    all(r.get("delay") for r in minta_fonnte(
        {"FONNTE_IMAGE_MODE": "comma"},
        ["https://contoh.test/a.jpg", "https://contoh.test/b.jpg"])[1:])))
check("mode none tidak melampirkan foto", lambda: assert_true(
    all("url" not in r for r in minta_fonnte(
        {"FONNTE_IMAGE_MODE": "none"}, ["https://contoh.test/a.jpg"]))))
check("jumlah foto dibatasi max images", lambda: assert_true(
    len(minta_fonnte({"FONNTE_IMAGE_MODE": "comma", "FONNTE_MAX_IMAGES": "2"},
                     ["https://contoh.test/1.jpg", "https://contoh.test/2.jpg",
                      "https://contoh.test/3.jpg"])) == 2))


def baca_env():
    """File .env dibaca, tapi environment yang sudah ada tetap menang."""
    import tempfile
    from pathlib import Path as P

    kunci = "KVK_UJI_ENV_" + os.urandom(4).hex()
    ada = "KVK_UJI_ADA_" + os.urandom(4).hex()
    os.environ[ada] = "dari_environment"
    with tempfile.TemporaryDirectory() as d:
        f = P(d) / ".env"
        f.write_text(
            f"# komentar\n\n{kunci}=nilai_dari_file\n"
            f"{ada}=nilai_dari_file\n"
            "BARIS_TANPA_SAMA_DENGAN\n"
            f'KUTIP_GANDA_{kunci}="berkutip"\n',
            encoding="utf-8")
        app_mod.load_env_file(f)
    assert os.environ.get(kunci) == "nilai_dari_file", "nilai .env tidak terbaca"
    assert os.environ.get(ada) == "dari_environment", \
        "environment yang ada tertimpa .env"
    assert os.environ.get(f"KUTIP_GANDA_{kunci}") == "berkutip", "kutip tidak dibuang"
    for k in (kunci, ada, f"KUTIP_GANDA_{kunci}"):
        os.environ.pop(k, None)


check("file .env dibaca tanpa menimpa environment", baca_env)


def device_tanpa_token():
    """Tanpa token, cek device harus menolak tanpa menghubungi jaringan."""
    lama = os.environ.pop("FONNTE_TOKEN", None)
    try:
        info, pesan = app_mod.fonnte_device()
        assert info is None, "device terbaca tanpa token"
        assert "FONNTE_TOKEN" in pesan, f"pesan tidak jelas: {pesan}"
    finally:
        if lama is not None:
            os.environ["FONNTE_TOKEN"] = lama


check("cek device tanpa token tidak menghubungi jaringan", device_tanpa_token)

print("keamanan & konfigurasi")
check("secret key cukup panjang", lambda: assert_true(
    len(app_mod.app.secret_key) >= 32))
check("cookie HttpOnly aktif", lambda: assert_true(
    app_mod.app.config["SESSION_COOKIE_HTTPONLY"] is True))
check("cookie SameSite Strict", lambda: assert_true(
    app_mod.app.config["SESSION_COOKIE_SAMESITE"] == "Strict"))
check("batas ukuran unggahan aktif", lambda: assert_true(
    app_mod.app.config["MAX_CONTENT_LENGTH"] > 0))
check("semua route API ada", routes_lengkap)
check("header keamanan di halaman", lambda: header_aman("/", "no-cache"))
check("header keamanan di API", lambda: header_aman("/api/healthz", "no-store"))
check("DATABASE_URL terbaca", lambda: assert_true(
    bool(app_mod.DATABASE_URL)))
def tanpa_aset_luar():
    """CSP memakai default-src 'self', jadi aset dari domain lain akan
    diblokir browser dan halaman rusak tanpa pesan yang jelas. Tautan biasa
    (mis. ke wa.me) tidak dimuat browser, jadi hanya atribut pemuat aset
    yang diperiksa."""
    luar = re.findall(
        r"""<(?:script|link|img|iframe|source)\b[^>]*?"""
        r"""(?:src|href)\s*=\s*["'](?:https?:)?//[^"']+""",
        app_mod.HTML, re.IGNORECASE | re.DOTALL)
    assert not luar, f"ada aset dari luar: {luar[:3]}"


check("halaman tidak memuat aset luar", tanpa_aset_luar)
check("CSP dikirim lewat header", lambda: assert_true(
    "frame-ancestors 'none'" in app_mod.app.test_client().get(
        "/").headers.get("Content-Security-Policy", "")))
check("frontend escaped output", lambda: assert_true(
    "constesc=v=>string(v??" in "".join(app_mod.HTML.split()).lower()))
check("service worker tidak menyimpan data", lambda: assert_true(
    "caches.open" not in _sw_source(), "service worker menyimpan cache"))

print()
if failures:
    print(f"{len(failures)} pemeriksaan GAGAL")
    for n, e in failures:
        print(f"  - {n}: {e}")
    sys.exit(1)
print("semua pemeriksaan lolos")
