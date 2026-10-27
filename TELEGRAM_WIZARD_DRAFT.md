# Draft Modul Telegram — Rofi Konveksi (Mode Wizard)

Dokumen ini adalah **draft desain** (belum ada kode yang diubah). Tujuannya
agar kita sepakat dulu soal bentuk modul sebelum implementasi.

---

## 1. Ringkasan & keputusan

- Fitur: admin mengontrol web app lewat bot Telegram (wizard) untuk:
  1. **Buat nota** (pesanan) setelah deal offline — data diisi lewat tanya-jawab.
  2. **Update tahap produksi** (mulai / selesai / catatan).
  3. **Upload foto** tahap → diproses ImageKit → muncul otomatis di link tracking konsumen.
- Web app yang ada sudah punya semua mesinnya (buat order, validasi, URL nota/tracking, kirim WhatsApp via Fonnte, upload ImageKit). Bot tinggal "memencet tombol yang sama".
- Keputusan input: **wizard tanya-jawab** (bukan format 1 baris).

---

## 2. Perintah bot

| Perintah | Fungsi |
|---|---|
| `/start` | Perkenalan + daftar perintah |
| `/nota` | Mulai wizard buat nota baru |
| `/tahap` | Update tahap: mulai / selesai / catatan / ulang |
| `/foto` | Upload foto ke tahap tertentu |
| `/status` | Status device Fonnte + jumlah pesanan hari ini |
| `/batal` | Batalkan wizard yang sedang berjalan |
| `/bantuan` | Ringkasan perintah |

Hanya chat_id yang terdaftar (allowlist) yang dilayani.

---

## 3. Arsitektur & komponen baru

```
Telegram (BotFather token)
   │  kirim update (webhook POST)
   ▼
Flask route baru:  POST /telegram/webhook
   │  verifikasi (chat_id allowlist + secret/HMAC)
   ├─ handler /nota  → state machine wizard (3.3)
   ├─ handler /tahap → panggil logika tahap internal
   ├─ handler /foto  → unduh foto Telegram → upload ImageKit
   └─ balas pesan via Telegram Bot API (sendMessage)
```

### 3.1 Route webhook
- `POST /telegram/webhook`, menerima JSON update dari Telegram.
- Respons `200 OK` secepat mungkin; pemrosesan bisa synchronous karena cepat.
- Wajib di-set sekali: `setWebhook` ke `https://<PUBLIC>/telegram/webhook`.

### 3.2 Verifikasi keamanan (wajib)
1. `TELEGRAM_TOKEN` di `.env` (dari BotFather).
2. **Allowlist chat_id**: `TELEGRAM_ALLOWED_IDS` (pisah koma). Selain itu diabaikan diam-diam.
3. Opsional tapi disarankan: verifikasi header `X-Telegram-Bot-Api-Secret-Token` yang kita set saat `setWebhook` — mencegah panggilan palsu ke endpoint.
4. Semua input user tetap lewat validasi yang sama dengan form web (`_validate_order_payload`, `normalize_wa`, `_num`, `_date`, dst).

### 3.3 Manajemen state wizard
- Simpan state di **dict dalam memori** (key = `chat_id`), dengan TTL (mis. 15 menit) supaya tidak menumpuk:
  ```python
  WIZARD = {}  # chat_id -> {"step": ..., "data": {...}, "expires": ...}
  ```
- Setiap jawaban = satu `step`; step berurutan. `/batal` bersihkan state.
- Data dikumpulkan sementara; validasi per-langkah; di akhir ada ringkasan + konfirmasi.

---

## 4. Alur wizard buat nota (`/nota`)

### 4.1 Urutan pertanyaan
| # | Step | Pertanyaan ke admin | Contoh jawaban |
|---|---|---|---|
| 1 | customer | Siapa nama konsumen? | `Budi Santoso` |
| 2 | wa | Nomor WhatsApp konsumen? | `081234567890` |
| 3 | company | Instansi/perusahaan? (ketik `-` kalau kosong) | `SMK Negeri 1` |
| 4 | address | Alamat / catatan pengiriman? (`-`) | `Jl. Merdeka 10` |
| 5 | item_garment | Model pakaian item 1? | `Batik lengan panjang` |
| 6 | item_qty | Jumlah pcs? | `10` |
| 7 | item_price | Harga per pcs (Rp)? | `175000` |
| 8 | item_sizes | Ukuran (format `M=4, L=6` atau `-`)? | `M=4, L=6` |
| 9 | item_material | Bahan? (`-`) | `Katun primis` |
| 10 | item_color | Warna? (`-`) | `Sogan` |
| 11 | item_design | Spesifikasi/desain? (`-`) | `Motif parang` |
| 12 | more_items | Tambah item lagi? (ya/tidak) | `tidak` |
| 13 | dp | DP diterima (Rp)? (0 kalau belum) | `300000` |
| 14 | dp_method | Metode DP? (default Tunai) | `Transfer bank` |
| 15 | deal | Tanggal kesepakatan? (default hari ini) | `2026-10-27` |
| 16 | target | Estimasi selesai (tanggal)? | `2026-11-10` |
| 17 | target_payment | Target pelunasan? (`-`) | `-` |
| 18 | agreement_note | Catatan kesepakatan (tampil di nota)? (`-`) | `Batik tulis cap` |
| 19 | confirm | Ringkasan + konfirmasi | `ya` |

> Catatan: item bisa lebih dari satu (`more_items = ya` → ulangi step 5–12 untuk item berikutnya). Maksimum 20 item (sesuai batas `_validate_items`).

### 4.2 Validasi tiap jawaban
- `wa`: `normalize_wa()` — wajib valid (08… atau 628…).
- `qty`/`price`/`dp`: angka bulat ≥ 0; `dp ≤ total`.
- `sizes`: format `Label=Jumlah, ...`; jumlah total ukuran harus sama dengan qty item.
- `deal`/`target`: format `YYYY-MM-DD`; `target ≥ deal`; `deal ≤ hari ini`.
- Salah → bot balas pesan error spesifik dan ulangi step yang sama.

### 4.3 Ringkasan & konfirmasi
Sebelum eksekusi, bot tampilkan ringkasan (nama, WA, item, total, DP, estimasi)
dan minta `ya` / `ulangi` / `batal`.

### 4.4 Pemetaan ke payload pesanan
Hasil wizard dibentuk menjadi payload yang sama persis dengan form web v2:

```python
{
  "customer": ..., "wa": ..., "company": ..., "address": ...,
  "deal": ..., "target": ..., "target_payment": ...,
  "dp": ..., "dp_method": ..., "dp_date": ..., "dp_note": "",
  "customer_note": "", "agreement_note": ...,
  "items": [
    {"garment": ..., "name": ..., "qty": ..., "price": ...,
     "sizes": [{"label": "M", "qty": 4}, ...],
     "material": ..., "color": ..., "design": ..., "printing": "", "note": ""}
  ],
  "discount": 0, "extra": 0,
}
```

Setelah validasi lolos (`_validate_order_payload`), pesanan dibuat, lalu
**langsung kirim nota + link ke WhatsApp konsumen** lewat Fonnte
(ulangi logika `v2_send_wa` untuk kind="nota").

---

## 5. Update tahap (`/tahap`)

Sub-perintah (pilih lewat inline keyboard / teks):
- `/tahap mulai <kode>` — mulai tahap (mis. `potong`). Tambahan: tanggal mulai (default hari ini), catatan, opsi kirim notifikasi ke konsumen.
- `/tahap selesai <kode>` — selesaikan tahap (validasi urutan tetap berlaku).
- `/tahap catatan <kode>` — simpan catatan tahap.
- `/tahap ulang <kode>` — buka ulang tahap.

Kode tahap: `potong`, `jahit`, `finishing`, `serah` (sesuai `STAGE_KEYS`).
Logika memakai internals yang sama dengan `v2_stage` (validasi urutan, checklist finishing, dst).

---

## 6. Upload foto (`/foto`)

Alur:
1. Admin kirim `/foto` → bot tanya kode tahap (`potong/jahit/finishing/serah/umum`).
2. Admin kirim **foto** (Telegram mengirim file; bot unduh lewat `getFile` + URL file).
3. Bot konversi ke base64 `data:image/jpeg;base64,...`, lalu panggil logika
   yang sama dengan `v2_upload_photo`:
   - upload ke ImageKit (`upload.imagekit.io`),
   - simpan `remote_url` di tabel `photos` Supabase,
   - catat riwayat.
4. Balas sukses + link tracking pesanan (foto otomatis muncul di sana).

> Konfirmasi: foto tampil di halaman `/tracking/<token>` (verified — render langsung
> dari `remote_url` ImageKit).

---

## 7. Panggilan internal vs HTTP

Bot berjalan **di dalam proses Flask yang sama**, jadi tidak perlu session/CSRF.
Ulangi dengan memanggil **fungsi internal** (bukan HTTP endpoint):

| Aksi | Fungsi internal yang dipakai (ada / usulan refactor) |
|---|---|
| Validasi & buat nota | `_validate_order_payload()` + logika `v2_create_order` (usulan: refactor ke `create_order_internal(c, d)`) |
| Kirim nota ke WA | `fonnte_send()`, bangun pesan dari `order_urls()` (sama dgn `v2_send_wa`) |
| Update tahap | logika `v2_stage` (usulan: refactor ke `stage_action_internal(c, ident, action, ...)`) |
| Upload foto | logika `v2_upload_photo` (usulan: refactor ke `upload_photo_internal(ident, stage, caption, image_data)`) |

Refactor dipisah ke fungsi internal kecil **tanpa mengubah perilaku HTTP yang ada**.

---

## 8. Notifikasi ke admin

- **Balasan Telegram** selalu jadi konfirmasi (sukses/gagal kirim nota, link nota).
- Opsional (perlu keputusan): setelah `fonnte_send()` ke konsumen sukses, kirim
  konfirmasi ke **nomor WhatsApp usaha** (`settings()["wa"]`) — tambahan ±3–5 baris.

---

## 9. Konfigurasi (env)

| Variabel | Contoh | Keterangan |
|---|---|---|
| `TELEGRAM_TOKEN` | `123456:ABC-xyz` | Token BotFather |
| `TELEGRAM_ALLOWED_IDS` | `123456789` | chat_id admin (pisah koma) |
| `TELEGRAM_WEBHOOK_SECRET` | `rahasia-bebas` | Header `X-Telegram-Bot-Api-Secret-Token` |
| `TELEGRAM_API_BASE` | `https://api.telegram.org` | default |
| `FONNTE_TOKEN` | sudah ada | untuk kirim ke konsumen |
| `IMAGEKIT_PRIVATE_KEY`, `IMAGEKIT_URL_ENDPOINT` | sudah ada | untuk foto |
| `APP_ORIGIN` | `https://rofi-jaya.fly.dev` | wajib publik agar link nota bisa dibuka konsumen |

---

## 10. Dependensi

- Cukup **`requests`** (sudah dipakai di ekosistem) untuk Bot API — tidak wajib
  `python-telegram-bot` (boleh, tapi menambah bobot).
- Ditambahkan ke `requirements.txt`: `requests` (kalau belum ada).

---

## 11. Langkah implementasi (bertahap, bisa direview per langkah)

1. **Refactor kecil (non-destruktif):** buat `create_order_internal`, `stage_action_internal`, `upload_photo_internal` dari logika v2 yang sudah ada; pastikan uji `tools/e2e_v2.py` tetap lulus.
2. **Modul `telegram_bot.py`:** verifikasi webhook, allowlist, helper balas pesan.
3. **Wizard `/nota`:** state machine + validasi + ringkasan + konfirmasi + buat nota + kirim WA.
4. **`/tahap` & `/foto`:** panggil internals + unduh file foto.
5. **Route `/telegram/webhook`** di `app.py` (atau blueprint) + `setWebhook` helper.
6. **Env & deploy:** set `TELEGRAM_*` di Fly; pastikan `APP_ORIGIN` publik.
7. **Uji nyata** (lihat bagian 12).

---

## 12. Uji coba yang disarankan

1. `setWebhook` → kirim `/start` dari chat admin (must respond; non-admin tidak).
2. Wizard `/nota` sampai konfirmasi → cek pesanan muncul di dashboard web, nota
   terkirim ke WA konsumen (nomor uji coba), link tebuka.
3. `/tahap mulai potong` + `/foto` → cek foto muncul di `/tracking/<token>`.
4. Uji error: nomor WA salah, harga bukan angka, ukuran tak cocok → pesan error spesifik.
5. `setWebhook` ulang setelah deploy ulang (secret token ikut diset).

---

## 13. Catatan & keterbatasan

- **Fonnte**: setiap nota terkirim = 1 pesan dari kuota (saat ini sisa 987, paket Free).
- **State wizard di memori**: hilang saat server restart; jika butuh persisten, bisa
  disimpan ke tabel kecil di Supabase (tahap lanjutan).
- **Foto**: batas 5 MB/foto (sesuai `v2_upload_photo`); format jpeg/png/webp dari Telegram aman.
- **Notifikasi otomatis tahap lama** (centang "Kirim pembaruan + foto" di UI) masih
  pakai galeri blob DB — tidak terpengaruh bot, tapi tetap jadi item perapian terpisah.
- **Bot hanya satu admin** (allowlist); kalau nanti multi-admin, perlu tabel izin.

