# Rofi Jaya — Manajemen Pesanan & Produksi Konveksi

Aplikasi web untuk pemilik usaha konveksi: mencatat kesepakatan, memantau empat tahap
produksi (**Potong → Jahit → Finishing → Penyerahan**), mencatat pembayaran sebagai
transaksi terpisah, membuat **nota digital** yang bisa dicetak/PDF, dan memberi
konsumen **link tracking** yang bisa dibuka tanpa akun.

Data disimpan di database server (**PostgreSQL/Supabase**; mode lokal memakai SQLite),
bukan di browser. Setiap perubahan disimpan ke server dan baru dianggap sah setelah
server mengonfirmasi. Aplikasi tidak mengantre perubahan offline.

> Desain v2: dashboard gelap (charcoal + sage), status produksi **dipisah** dari status
> pembayaran, dan tidak ada tahap yang dianggap selesai tanpa tindakan owner.

## Isi repo

| File | Keterangan |
|---|---|
| `app.py` | Bootstrap Flask, autentikasi, keamanan, foto, notifikasi Fonnte, backup |
| `rofi_api_v2.py` | API pesanan/produksi/pembayaran + halaman nota & tracking publik |
| `rofi_ui.py` | Antarmuka dashboard owner (HTML/CSS/JS) |
| `rofi_core.py` | Konfigurasi bersama: path, `.env`, WIB, URL publik |
| `tools/migrate_v2.py` | Migrasi skema v2 (idempoten) + backfill pesanan lama |
| `tools/perf.py` | `robots.txt`, `sitemap.xml`, filter bot untuk halaman privat |
| `tools/e2e_v2.py` | Uji alur nyata (login → pesanan → notifikasi/tracking → lunas) |
| `tools/seed_demo.py` | Data contoh untuk melihat tampilan |
| `tools/reset_password.py` | Reset kata sandi owner tanpa login (lupa/salah sandi) |
| `tools/setup_supabase.py` | Simpan connection string Supabase ke `.env` + uji koneksi |
| `tools/check_supabase.py` | Diagnosa koneksi Supabase (versi server, tabel v2) |
| `Dockerfile` / `fly.toml` | Deploy produksi Fly.io |
| `tools/check.py` | Pemeriksaan cepat tanpa server |

## Halaman & route publik

| Route | Keterangan |
|---|---|
| `/` | Dashboard owner (wajib login) |
| `/nota/<token>` | Nota digital konsumen — cetak/simpan PDF dari browser |
| `/tracking/<token>` | Progres produksi untuk konsumen, diperbarui otomatis 60 detik |
| `/robots.txt`, `/sitemap.xml` | Halaman privat tidak diindeks |

---

## Menjalankan secara lokal

Butuh Python 3.11+. **Tanpa `DATABASE_URL`, aplikasi otomatis memakai SQLite lokal**
di `data/rofi-jaya.sqlite3` sehingga bisa dicoba langsung. Isi `DATABASE_URL` untuk
memakai PostgreSQL/Supabase (produksi).

Jika `.env` masih berisi `DATABASE_URL` lama (mis. PostgreSQL lokal port 5433 yang
mati), aplikasi berhenti dengan pesan jelas. Untuk menjalankan tanpa PostgreSQL,
beri nilai placeholder — **nilai kosong dari baris perintah akan tertimpa `.env`**:

```bat
set DATABASE_URL=sqlite&& python app.py
```

PowerShell: `$env:DATABASE_URL='sqlite'; python app.py` · Git Bash: `DATABASE_URL=sqlite python app.py`

Nilai apa pun yang bukan `postgres://` / `postgresql://` otomatis memakai SQLite.

```bash
python -m venv .venv
```

Aktifkan virtualenv sesuai shell Anda (`source .venv/Scripts/activate` di Git Bash,
`.venv\Scripts\activate` di PowerShell), lalu:

```bash
pip install -r requirements.txt
```

Buat file `.env` dari contoh:

```bash
cp .env.example .env
```

Isi `DATABASE_URL`, `SECRET_KEY`, dan `OWNER_PASSWORD`. Di PowerShell:

```bash
Get-Content .env | ForEach-Object { $n,$v=$_.Split('=',2); Set-Item -Path "env:$n" -Value $v }
```

Jalankan:

```bash
python app.py
```

Aplikasi tersedia di `http://127.0.0.1:8080`. Tabel database dibuat otomatis saat
pertama kali dijalankan, dan kata sandi owner dibuat dari `OWNER_PASSWORD`.

Catatan mode lokal: hapus `data/rofi-jaya.sqlite3` untuk memulai dari kosong, atau
jalankan `python tools/seed_demo.py` (kata sandi `demo-rofi-jaya-2026`) untuk data contoh.

`app.py` membaca file `.env` otomatis saat dijalankan, jadi tidak perlu mengisi
environment secara manual. Nilai yang sudah ada di environment **selalu menang**,
sehingga rahasia dari `fly secrets` di produksi tidak tertimpa file `.env` lokal.
`.env` sudah masuk `.gitignore` — jangan pernah di-commit.

## Deploy ke Fly.io

```bash
fly launch --no-deploy        # sekali saja, bila belum ada app
fly secrets set DATABASE_URL="postgresql://..."
fly secrets set SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(48))')"
fly secrets set OWNER_PASSWORD="kata-sandi-minimal-12-karakter"
fly secrets set APP_ORIGIN="https://rofi-jaya.fly.dev"
fly deploy
fly logs
```

> `SECRET_KEY` **wajib** diganti di produksi. Kalau kosong, aplikasi membuat
> `data/session-secret` otomatis — file itu tidak ikut ter-deploy ke mana pun dan
> akan hilang saat instance di-restart, sehingga semua sesi owner keluar.

Untuk mengaktifkan notifikasi WhatsApp otomatis, tambahkan juga:

```bash
fly secrets set FONNTE_TOKEN="token-dari-fonnte.com"
```

`fly.toml` sudah mendaftarkan health check ke `/api/healthz`. Endpoint itu juga bisa
dipakai untuk monitoring: mengembalikan `200` bila database terjangkau, `503` bila tidak.

## Variabel environment

| Variabel | Wajib | Default | Keterangan |
|---|---|---|---|
| `DATABASE_URL` | ya | — | Koneksi PostgreSQL/Supabase |
| `SECRET_KEY` | produksi | — | Kunci sesi, minimal 32 karakter |
| `OWNER_PASSWORD` | saat pertama jalan | — | Kata sandi owner awal, minimal 12 karakter |
| `APP_ORIGIN` | disarankan | host request | Asal yang boleh mengirim request tulis |
| `COOKIE_SECURE` | tidak | `auto` | Tandai cookie `Secure` |
| `TRUST_PROXY` | tidak | otomatis di PaaS | Percayai `X-Forwarded-*` |
| `DB_POOL_MAX` | tidak | `10` | Jumlah koneksi database |
| `WEB_THREADS` | tidak | `8` | Thread waitress |
| `SESSION_HOURS` | tidak | `8` | Masa berlaku sesi |
| `MAX_UPLOAD_MB` | tidak | `9` | Batas ukuran unggahan |
| `MAX_RESTORE_MB` | tidak | `200` | Batas ukuran file pemulihan |
| `FONNTE_TOKEN` | untuk notifikasi otomatis | — | Token Fonnte (WhatsApp Business API) |
| `FONNTE_IMAGE_MODE` | tidak | `comma` | `comma` / `single` / `none` |
| `FONNTE_MAX_IMAGES` | tidak | `3` | Jumlah foto dilampirkan (tiap foto = 1 pesan) |
| `FONNTE_DELAY` | tidak | `2` | Jeda (detik) antar pesan foto |
| `FONNTE_API_URL` | tidak | API Fonnte | Alamat kirim (untuk pengujian) |
| `FONNTE_DEVICE_URL` | tidak | API Fonnte | Alamat cek device/kuota |
| `GALLERY_TTL_DAYS` | tidak | `90` | Masa berlaku tautan galeri |

---

## Foto per tahap & notifikasi WhatsApp otomatis

Alur yang berjalan di aplikasi:

1. Owner membuka **Timeline Produksi** → **Mulai Potong / Jahit / Finishing**.
2. Dialog diisi: tanggal mulai, estimasi selesai, catatan pengerjaan.
3. Owner menempelkan foto — dari **galeri HP** atau **kamera** (ada centang
   "Ambil dari kamera"), boleh beberapa foto sekaligus, plus keterangan.
4. Owner menekan **Mulai Tahap**. Foto diunggah dulu, lalu tahap ditandai berjalan.
5. Kalau centang "Kirim pembaruan + foto ke WhatsApp konsumen" aktif, server
   mengirim pesan + foto ke nomor WhatsApp konsumen secara otomatis lewat Fonnte.

Foto **tidak** dikirim sebagai file attachment besar. Yang dikirim adalah
*tautan galeri* yang di-host di server sendiri, berisi foto + ringkasan pesanan
(nomor pesanan, jenis pakaian, jumlah, bahan, warna, tahap, estimasi selesai).
Tautan ditandatangani dan berlaku 90 hari, jadi hanya penerima tautan yang
bisa membukanya.

Foto juga dilampirkan langsung ke pesan Fonnte. API Fonnte hanya menerima
**satu lampiran per permintaan** (field `url`), jadi beberapa foto dikirim
sebagai beberapa pesan berurutan dengan jeda `FONNTE_DELAY` detik. Jumlah
foto dibatasi `FONNTE_MAX_IMAGES` (default 3) karena setiap foto menambah
satu pesan yang dibayar. Kalau lampiran ditolak Fonnte, pesan teks dikirim
ulang tanpa lampiran — isinya tetap memuat tautan galeri, jadi konsumen
masih bisa melihat fotonya.

Pesan selalu dikirim ke nomor WhatsApp yang diisi owner saat membuat pesanan
(`o["wa"]`), bukan nomor lain.

Bila pesan gagal terkirim, **tahap tetap tersimpan** dan hasilnya dicatat di
riwayat. Owner bisa mengirim ulang lewat tombol **"Kirim Ulang + Foto"** pada
tiap tahap, atau lewat tombol **"Kirim Otomatis (Fonnte)"** di dialog WhatsApp.

### Menyiapkan Fonnte

1. Daftar di [fonnte.com](https://fonnte.com), tambahkan device WhatsApp
   Business, lalu salin token dari menu **Device → Token**.
2. Set token di server:

```bash
fly secrets set FONNTE_TOKEN="token-anda-dari-fonnte"
```

3. Buka aplikasi → **Pengaturan → Notifikasi WhatsApp otomatis**, cek
   "Kirim pembaruan + foto ke konsumen otomatis", lalu tekan **Kirim Pesan Uji**
   ke nomor Anda sendiri untuk memastikan terhubung.

Halaman Pengaturan menampilkan status device langsung dari Fonnte: nomor yang
terhubung, nama device, paket, sisa kuota, dan tanggal berlaku. Kalau device
terputus atau kuota habis, itu terlihat di situ sebelum pesan gagal terkirim.

> Biaya Fonnte dipotong dari saldo Anda per pesan. Satu tahap dengan tiga foto
> memakai tiga pesan (batas Fonnte: satu lampiran per permintaan), jadi
> `FONNTE_MAX_IMAGES` juga menentukan biaya. Turunkan bila ingin lebih hemat —
> foto tetap bisa dilihat konsumen lewat tautan galeri di dalam pesan.

Centang di dialog **Mulai Tahap** menentukan apakah tahap itu dikirim ke
konsumen. Kalau token Fonnte belum dipasang atau nomor konsumen kosong,
centangnya otomatis tidak aktif dan dialog menjelaskan alasannya.

Catatan paket **Free**: hasil uji menunjukkan paket ini tetap bisa mengirim
gambar (baik lewat unggahan langsung maupun field `url`), walau respons API
device menampilkan `"attachment": false`. Kalau suatu saat lampiran ditolak,
pesan teks tetap terkirim beserta tautan galeri, jadi konsumen tidak kehilangan
informasi.

## Keamanan yang sudah diterapkan

- **Sesi**: cookie `HttpOnly` + `SameSite=Strict`, `Secure` otomatis saat `APP_ORIGIN`
  memakai HTTPS, kedaluwarsa 8 jam.
- **CSRF**: token per-sesi pada setiap request tulis, dibandingkan dengan
  `secrets.compare_digest`.
- **Origin**: request tulis dari asal yang tidak terdaftar ditolak.
- **Kata sandi**: disimpan sebagai hash werkzeug (scrypt), minimal 12 karakter.
- **Rate limit login**: maksimal 10 percobaan per 5 menit per instance.
- **Anti-Klik Jacking**: `X-Frame-Options: DENY` + CSP `frame-ancestors 'none'`.
- **Anti-injeksi**: seluruh query memakai parameter psycopg2, tanpa string SQL
  yang dirakit dari input pengguna.
- **Optimistic locking**: setiap perubahan pesanan membawa `version`; data yang
  berubah di tab lain ditolak, bukan ditimpa diam-diam.
- **Idempotensi pembayaran**: token transaksi mencegah pembayaran ganda saat tombol
  ditekan dua kali.
- **Validasi unggahan**: hanya JPEG/PNG/WebP, maksimal 5 MB, maksimal 25 megapiksel,
  metadata dibuang, foto dikompresi ulang ke JPEG.

## Yang perlu diketahui sebagai pemilik

- **Backup manual, belum otomatis.** application → Pengaturan → Backup database.
  Unduh salinan secara berkala dan simpan di luar server (cloud/USB). Tombol
  "Tanpa Foto" menghasilkan berkas jauh lebih kecil untuk arsip rutin.
- **Pemulihan dari backup** tersedia di menu Pengaturan. Semua pesanan yang ada
  akan diganti — kata sandi owner dan pengaturan usaha tidak ikut berubah.
- **Aplikasi ini belum multi-user.** Satu akun owner, satu perangkat idealnya.
  Kalau dibuka di dua perangkat, perubahan dari satu perangkat bisa membuat
  perangkat lain mendapat pesan "data berubah di tab lain".
- **Tidak ada antrean offline.** Kalau koneksi terputus, perubahan tidak tersimpan
  dan Anda perlu mengulangnya setelah tersambung kembali.
- **Data foto disimpan sebagai BYTEA di database.** Backup dengan foto bisa berukuran
  besar; gunakan "Tanpa Foto" bila hanya perlu data pesanan.

## Menghubungkan ke Supabase

1. Supabase Dashboard → **Project Settings → Database → Connection string → URI**.
   Pilih **Session pooler** bila jaringan Anda tidak mendukung IPv6 (sering terjadi
   di Windows/ISP rumahan); host-nya `aws-0-<region>.pooler.supabase.com:5432`.
2. Ganti `[YOUR-PASSWORD]` dengan **sandi database** (bukan sandi akun Supabase).
3. Simpan ke `.env` lewat skrip (tidak menampilkan sandi):

```bat
python tools/setup_supabase.py
:: tempel connection string saat diminta, Enter
```

Atau sekali jalan:

```bat
python tools/setup_supabase.py --url "postgresql://postgres.<ref>:<sandi>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require"
```

4. Uji koneksi tanpa menjalankan aplikasi: `python tools/check_supabase.py`
   (melaporkan versi server, tabel v2 yang sudah ada, dan penyebab umum kegagalan).
5. `python app.py` → tabel dibuat otomatis di Supabase, owner pertama dibuat dari
   `OWNER_PASSWORD` di `.env`, lalu login di `http://127.0.0.1:8099`.

Catatan penting:

- `OWNER_PASSWORD` hanya dipakai **saat tabel owner masih kosong**. Setelah itu
  gunakan `python tools/reset_password.py --password "..."` (tanpa `set DATABASE_URL=sqlite`).
- Jika project Free di-pause karena lama tidak dipakai, aktifkan dulu di dashboard.
- Sandi berisi karakter `@ / # : ?` harus di-encode (`%40 %2F %23 %3A %3F`).
- Jangan commit `.env` (sudah masuk `.gitignore`); untuk Fly.io pakai `fly secrets set`.

## Lupa / salah kata sandi owner

Kata sandi disimpan sebagai hash, jadi tidak bisa dibaca ulang — hanya direset.
Tidak perlu login dan tidak menyentuh data pesanan:

```bat
:: Windows CMD — mode SQLite lokal
set DATABASE_URL=sqlite&& python tools/reset_password.py --password "kata-sandi-baru-2026"
```

PowerShell: `$env:DATABASE_URL='sqlite'; python tools/reset_password.py --password "..."`

Tanpa `--password`, skrip menanyakan kata sandi dua kali (tidak tampil di layar).
Cek status tanpa mengubah apa pun: `python tools/reset_password.py --show`.
Untuk produksi (PostgreSQL/Supabase) cukup pastikan `DATABASE_URL` di `.env` benar,
lalu jalankan perintah yang sama tanpa `set DATABASE_URL=sqlite`.

Setelah reset, semua sesi lama otomatis tidak berlaku.

## Pemeriksaan cepat

```bash
python tools/check.py        # validasi, template, keamanan (tanpa server)
bash tools/run_checks.sh     # compile + check + sintaks JS
DATABASE_URL="" python tools/e2e_v2.py   # uji alur lengkap di SQLite terpisah
```

`e2e_v2.py` menjalankan alur nyata lewat HTTP: login owner, validasi pesanan,
perhitungan total & sisa, urutan tahap produksi, checklist finishing, koreksi
pembayaran, penyerahan, nota/tracking publik (termasuk token salah), dan pesan
WhatsApp. File database uji (`data/rofi-e2e.sqlite3`) terpisah dari data aplikasi.

## Pemisahan data produksi & publik

- Owner: `/`, `/api/v2/*` — wajib sesi + token CSRF.
- Konsumen: `/nota/<token>`, `/tracking/<token>` — token acak 32 byte per pesanan.
  Yang tampil hanya nomor nota, nama tersamar, ringkasan pesanan, status tahap,
  tanggal progres, dan status pembayaran (tanpa nominal, tanpa catatan internal).
- User-agent preview/bot (Slack, WhatsApp, crawler) ditolak `403` untuk halaman privat
  agar data konsumen tidak bocor ke layanan pihak ketiga.
