"""Utilitas kecil untuk performa & SEO: sitemap, robots, pencegah tracking.

Modul ini sengaja tanpa dependensi (selain stdlib) supaya bisa dipakai
app.py maupun rofi_api_v2.py tanpa impor melingkar.
"""
import json


def _origin(base):
    return (base or "").rstrip("/")


def robots_txt(base_url):
    """robots.txt: dashboard, nota, dan tracking konsumen tidak diindeks."""
    base = _origin(base_url)
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "Disallow: /api/v2/\n"
        "Disallow: /nota/\n"
        "Disallow: /tracking/\n"
        "Disallow: /g/\n"
        "\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )


def sitemap_xml(base_url, orders=None):
    """Sitemap hanya memuat halaman publik.

    Halaman nota/tracking bersifat privat (berisi data satu konsumen) dan
    sengaja tidak dimasukkan walaupun tokennya unik. Halaman indeks
    `/tracking` juga tidak ada, jadi tidak dimasukkan ke sitemap.
    """
    base = _origin(base_url)
    pages = [
        (f"{base}/", "1.0", "weekly"),
    ]
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc, priority, freq in pages:
        parts.append(
            f"<url><loc>{loc}</loc><changefreq>{freq}</changefreq>"
            f"<priority>{priority}</priority></url>"
        )
    parts.append("</urlset>")
    return "\n".join(parts) + "\n"


def schema_org(base_url, brand_name):
    """Structured data minimal untuk halaman login/dashboard internal."""
    data = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": brand_name or "Rofi Jaya",
        "url": _origin(base_url) + "/",
    }
    return json.dumps(data, ensure_ascii=False)


# Marker bot/crawler yang TIDAK boleh mengakses /nota dan /tracking.
# Semua string di sini harus dalam bentuk lower-case.
_BOT_MARKERS = (
    "preview",            # generic preview crawler
    "bot",                # mencakup WhatsAppBot, TelegramBot, Discordbot, dsb.
    "crawl",              # crawler generik (Googlebot sudah tercakup "bot")
    "slack",              # Slack link preview
    "facebookexternalhit",  # preview crawler Facebook (BUKAN in-app browser)
    "twitterbot",
    "linkedinbot",
    "skype",
    "curl", "wget",       # CLI tools
    "python-requests", "python-httpx", "httpx",
    "headless",           # headless browser
)

# Marker in-app browser yang WAJIB DIIZINKAN (jangan diblokir walau
# string "bot" tidak ada). Dipakai sebagai pengecualian eksplisit agar
# tidak salah blokir kalau suatu saat marker baru ditambahkan.
_INAPP_BROWSER_MARKERS = (
    "whatsapp/",   # WhatsApp in-app browser (mis. "WhatsApp/2.23.20.0")
    "fban",        # Facebook in-app browser (mis. "FBAN/FB4A")
    "fbav",        # Facebook app version
    "fb_iab",      # Facebook in-app browser iOS
    "instagram",   # Instagram in-app browser
    "line/",       # LINE in-app browser
    "micromessenger",  # WeChat in-app browser
)


def tracking_block_reason(user_agent):
    """Kembalikan alasan bila permintaan terlihat sebagai bot.

    Nota & tracking memuat data pesanan satu konsumen; tautannya rahasia
    tetapi tidak boleh bocor ke pengindeks/preview bot milik aplikasi lain.

    PENTING: WhatsApp/Facebook/Instagram/LINE in-app browser HARUS
    diizinkan, karena konsumen membuka link dari chat aplikasi tersebut.
    Yang diblokir hanya crawler preview (WhatsAppBot, facebookexternalhit,
    dsb.) yang mengambil metadata link sebelum pesan benar-benar dibaca.
    """
    ua = (user_agent or "").lower()
    if not ua:
        # User-agent kosong: tolak, karena tidak ada cara membedakan
        # crawler dengan klien aneh. Browser normal selalu mengirim UA.
        return "User-agent kosong."

    # In-app browser: izinkan lebih dulu, sebelum cek marker bot,
    # supaya "WhatsApp/2.23" tidak salah tertangkap oleh marker "bot"
    # (mis. kalau UA-nya "WhatsAppBot" kita tetap blokir di bawah).
    if any(m in ua for m in _INAPP_BROWSER_MARKERS):
        # WhatsAppBot dan sejenisnya tetap diblokir walau mengandung
        # "whatsapp/" pada beberapa varian UA crawler.
        if "whatsappbot" in ua or "facebookexternalhit" in ua:
            return "User-agent crawler aplikasi pesan."
        return ""

    for marker in _BOT_MARKERS:
        if marker in ua:
            return f"User-agent diperlakukan sebagai bot ({marker})."
    return ""