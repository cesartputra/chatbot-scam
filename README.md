# Replika IASC lokal + Help Center OCR & Chat

PoC FastAPI dengan replika lima tahap pelaporan IASC dan chatbot percakapan yang dapat ditempel melalui iframe. **Tidak mengirim laporan resmi, memverifikasi identitas nyata, atau memblokir rekening. Gunakan data dummy.**

UI mengikuti acuan halaman publik dan screenshot IASC yang diperiksa pada 20 Oktober 2026. Kontrak Pydantic lima tahap mengikuti spesifikasi pengguna; **belum diverifikasi terhadap backend resmi ASP.NET IASC**. Target pengisian di bawah 45 detik belum diukur dan bukan jaminan performa.

## Jalankan

Memerlukan Python 3.11+; diuji pada Python 3.14.4. Node diperlukan untuk tes JavaScript. **Tesseract dengan trained data `eng` diperlukan untuk konfigurasi Sumopod remote `VISION_INPUT_MODE=ocr_text`** dan OCR asisten lama; mode simulasi tanpa key tidak memerlukannya.

```bash
# macOS
brew install tesseract
# Debian / Ubuntu
sudo apt-get install tesseract-ocr tesseract-ocr-eng
# Pastikan eng tercantum
tesseract --list-langs
```

```bash
cd /lokasi/iasc-ai-intake
cp -n .env.example .env
bash start.sh
```

Pastikan `AI_MODE=auto` dan `AI_API_KEY` kosong untuk demo tanpa provider. Peluncuran pertama membuat `.venv` dan memasang `requirements.txt`, sehingga memerlukan akses indeks paket. `.env` dimuat otomatis; environment yang sudah diekspor diutamakan. Peluncur memakai `uvicorn main:app` pada **127.0.0.1:8787**, satu worker, tanpa access log. Hentikan dengan Ctrl+C. Untuk port lain: `PORT=8788 bash start.sh`.

| Halaman | Alamat lokal |
| --- | --- |
| Beranda replika | [Beranda](http://127.0.0.1:8787/) |
| Formulir lima tahap + chat terbuka | [Mulai demo](http://127.0.0.1:8787/Guest/LaporanV2?assistant=1) |
| Demo satu berkas HTML yang membungkus replika | [Demo widget](http://127.0.0.1:8787/widget/iasc-ai-widget.html) |
| Halaman integrasi replika + chat | [Integrasi](http://127.0.0.1:8787/integration) |
| Metadata tiket simulasi browser | [Cek Laporan](http://127.0.0.1:8787/Guest/CekLaporan) |
| Panduan API / OpenAPI / kontrak | [Panduan](http://127.0.0.1:8787/docs), [OpenAPI](http://127.0.0.1:8787/openapi.json), [JSON Schema](http://127.0.0.1:8787/api/v1/schema) |

`widget/iasc-ai-widget.html` dapat dibuka dari disk. Wrapper tersebut memuat replika dari `http://127.0.0.1:8787`, sehingga server tetap harus berjalan.

## Coba melalui browser

Chat hanya memiliki satu tombol lampiran, satu input teks, tombol kirim, dan jawaban cepat yang sesuai pertanyaan saat ini. Jenis dokumen ditentukan server dari urutan percakapan.

1. Pilih mengalami sendiri atau mewakili korban. Kirim KTP dummy; biodata mulai masuk ke Tahap 1. Ketik nomor HP dan email dalam satu jawaban, misalnya `08123456789, pelapor.dummy@example.com`.
2. Kirim bukti komunikasi. Chat melengkapi informasi terlapor/media pada Tahap 2 dan menanyakan informasi yang belum terbaca. Tambahkan bukti chat lain atau lanjut.
3. Ceritakan kejadian beserta tanggal dan jam sebenarnya. Mode simulasi mempertahankan cerita pengguna; tidak menggantinya dengan cerita dummy. Bila waktu belum disebut, chat menanyakannya. Bukti chat dipakai ulang untuk kejadian. Unggah gambar laporan polisi atau pilih **Lewati / Belum Ada**.
4. Kirim bukti kepemilikan rekening, lalu bukti transfer. Bukti transfer berikutnya menambah rincian transaksi pada penerima yang sama atau menambah penerima baru; transaksi sebelumnya dipertahankan.
5. Periksa kartu ringkasan. Pesan menjelaskan bahwa mengetik jawaban CAPTCHA lokal berarti menyetujui S&K **simulasi lokal**. Jawaban benar menghasilkan tiket `SIM-…` di chat dan host. Tidak ada langkah pengiriman resmi atau tindakan bank.

Setiap respons membawa perubahan field. Replika mengisinya satu per satu dengan jeda **120 ms**, menyorot/menggulir field, mengisi radio/dropdown/tanggal/lampiran serta tabel bersarang, lalu berpindah ke tahap aktif. Isian manual yang sudah ada dipertahankan dan konflik diberitahukan. Sesi baru menghapus isian hasil AI sebelumnya sambil mempertahankan perubahan manual.

Formulir manual tetap tersedia bila AI gagal. **Simpan Simulasi Lokal** menyimpan metadata di localStorage browser dengan `SIM-…`, `simulated:true`, `submitted:false`; berkas asli tidak disimpan di sana. Isian aktif/file di memori tab hilang saat halaman dimuat ulang. Metadata tiket dapat dihapus melalui Cek Laporan. Tombol kirim laporan resmi dinonaktifkan.

## Struktur proyek

```text
iasc-ai-intake/
├── main.py                        # API v1, batas origin/host, dispatch mock
├── schemas.py                     # Kontrak Pydantic lima tahap
├── requirements.txt / requirements-dev.txt
├── .env.example / start.sh
├── services/
│   ├── orchestrator.py            # State, sesi, delta patch, confidence
│   ├── llm_gateway.py             # Gateway OpenAI-compatible dan simulasi
│   ├── image_processor.py         # Validasi/kompresi dan pointer bukti
│   └── normalizer.py              # Bank, lokasi, media
├── widget/iasc-ai-widget.html      # Chat, kartu ringkasan, wrapper demo
├── static/
│   ├── widget.js / widget.css      # Floating launcher dan bridge iframe
│   ├── integration.html / integration.js / integration.css
│   ├── replica/
│   │   ├── report-core.mjs         # Validasi, dropdown, mapping replika
│   │   ├── progressive-fill.mjs    # Patch leaf, revisi, konflik manual
│   │   ├── report.html / report.js / replica.css
│   │   └── assets/NOTICE.md        # Sumber aset dan hak pemilik
│   └── docs.html
├── fixtures/v1/                   # Empat gambar dummy
├── tests/                         # pytest dan Node test runner
├── app.py                         # Replika/aset dan API asisten lama
└── TEST_RESULTS.md
```

`/assistant` dan `/widget` mengarahkan ke demo percakapan baru pada `/Guest/LaporanV2?assistant=1`. UI lama masih tersedia pada `/static/index.html`; `/api/sessions` memakai skema ringkas dan sesi terpisah. Entry point utama adalah **`main:app`**.

## AI Gateway

Default `AI_MODE=auto` dengan key kosong memakai **ekstraksi dokumen dummy tetap**, bukan membaca isi gambar. Unggahan tetap divalidasi/dikompresi. Nomor/email diambil dari teks yang benar-benar diketik, dan kronologi memakai cerita pengguna. UI/respons menandai mode simulasi.

Provider utama chat adalah **Sumopod AI** melalui base URL `https://ai.sumopod.com/v1` dan API key pada server, mengikuti [dokumentasi OpenAI-compatible resmi](https://docs.sumopod.com/guides/ai/openai-compatible-api). Pilih nama model dari dashboard atau `/v1/models` untuk key Anda; akses model dapat berbeda antar akun.

Konfigurasi utama memakai OCR Tesseract lokal, lalu mengirim **teks hasil OCR** ke model chat Sumopod:

```dotenv
AI_MODE=auto
AI_BASE_URL=https://ai.sumopod.com/v1
AI_API_KEY=isi_key_sumopod_di_server
VISION_INPUT_MODE=ocr_text
VISION_MODEL_NAME=deepseek-v4-flash-vision-exp
CHAT_MODEL_NAME=deepseek-v4-flash
AI_RESPONSE_FORMAT=json_object
AI_TIMEOUT_SECONDS=60
```

Key kosong mempertahankan simulasi berlabel; isi key dan restart untuk memakai Sumopod. Uji live pada akun pengujian berhasil memanggil model chat `deepseek-v4-flash`. Jalur gambar langsung model `deepseek-v4-flash-vision-exp` masih eksperimental dan belum berhasil pada akun tersebut; nama ini tidak dipakai saat `ocr_text` aktif. Hasil pengujian OCR+Sumopod dicatat terpisah dalam `TEST_RESULTS.md`.

`ocr_text` adalah mode eksplisit, bukan perpindahan provider saat gagal. OCR berjalan di thread terpisah dengan trained data Inggris (`eng`). Hasilnya kehilangan konteks tata letak/visual dan dapat salah membaca foto buram; field kosong atau confidence rendah tetap perlu koreksi/konfirmasi manusia. Kegagalan OCR atau Sumopod menghasilkan error tanpa memasukkan data dummy. Transport HTTP tiruan juga menguji endpoint, model, Authorization, dan format request.

Contoh on-premise dengan alias model pada satu gateway:

```dotenv
AI_MODE=remote
AI_BASE_URL=http://127.0.0.1:4000/v1
AI_API_KEY=secret_gateway_lokal
VISION_INPUT_MODE=image
VISION_MODEL_NAME=qwen2.5-vl
CHAT_MODEL_NAME=deepseek-v3
AI_RESPONSE_FORMAT=json_object
```

Gateway tetap model-agnostic: kedua model memakai **satu `AI_BASE_URL`**; untuk on-premise, router vLLM/LiteLLM harus menyediakan alias dan kemampuan masing-masing. HTTP tanpa TLS hanya diterima pada localhost. Keyless localhost memerlukan `AI_MODE=remote` eksplisit. Konfigurasi on-premise belum diuji.

Mode remote `image` mengirim gambar yang telah dibersihkan metadata ke model vision; `ocr_text` mengirim teks OCR lokal ke model chat. Jawaban/kronologi dikirim ke model chat bila diperlukan. Kontak eksplisit diparsing lokal. Key tetap di server. Kegagalan provider **tidak beralih ke dummy** dan tidak mengganti draft yang ada. Restart setelah mengganti konfigurasi. Model hanya mengekstrak slot; state, consent, validasi, dan tiket dikendalikan server.

## API v1: percakapan bertahap

State utama mengikuti urutan:

```text
PELAPOR_STATUS → KTP_UPLOAD → PELAPOR_DETAILS → CONTACT_INPUT
→ CHAT_EVIDENCE_UPLOAD → TERLAPOR_DETAILS → CHAT_MORE
→ CHRONOLOGY_INPUT → KEJADIAN_DETAILS → POLICE_REPORT_OPTIONAL
→ ACCOUNT_PROOF_UPLOAD → ACCOUNT_DETAILS
→ TRANSFER_UPLOAD → TRANSFER_DETAILS → TRANSFER_MORE
→ FINAL_CONFIRMATION → COMPLETED
```

State `*_DETAILS` dilewati bila data lengkap. Kolom wajib kosong/invalid atau confidence di bawah **0,85** menahan alur dan memicu pertanyaan. Pilihan bukti tambahan kembali ke state unggah terkait. Koreksi data membatalkan konfirmasi, e-KYC simulasi opsional, dan tiket lama.

| Endpoint | Kontrak |
| --- | --- |
| `POST /api/v1/session/init` | Membuat sesi; state awal `PELAPOR_STATUS` |
| `POST .../{id}/upload` | Satu multipart **`file`**; jenis ditentukan `expected_upload_type` server |
| `POST .../{id}/chat` | `{"text":"jawaban alami"}`; quick reply dapat menyertakan `action` |
| `GET .../{id}` | Snapshot dan seluruh patch draft untuk pemulihan |
| `DELETE .../{id}` | Menghapus sesi dan file di memori |
| `GET .../{id}/files/{file_id}` | File yang dimiliki sesi tersebut |
| `GET .../{id}/status` | State dan hasil simulasi |
| `POST .../{id}/verify-ekyc` | Pemeriksaan nama/skor tiruan opsional; bukan syarat alur chat |
| `POST .../{id}/submit` | Adapter DOM/webhook mock eksplisit, tetap lokal |
| `GET /api/v1/schema`, `GET /health` | Kontrak dan status layanan |

Respons sesi memuat `state`, `active_wizard_step`, `expected_upload_type`, `assistant_message`, `quick_replies`, `data`, `dom_patches`, `revision`, dan `result`. Patch berbentuk `{"op":"set","path":"tahap1.nama_pelapor","value":"NAMA DUMMY","step":1}`. File merupakan satu objek metadata, sedangkan tabel memakai path leaf berindeks. GET sesi mengirim ulang seluruh patch untuk resinkronisasi.

Contoh awal alur lokal:

```bash
API_BASE=http://127.0.0.1:8787
SESSION_ID=$(curl -fsS -H 'Content-Type: application/json' -d '{}' \
  "$API_BASE/api/v1/session/init" | python3 -c 'import json,sys; print(json.load(sys.stdin)["session_id"])')
SESSION_URL="$API_BASE/api/v1/session/$SESSION_ID"
curl -fsS "$SESSION_URL/chat" -H 'Content-Type: application/json' \
  -d '{"text":"Ya, saya sendiri"}'
curl -fsS "$SESSION_URL/upload" -F file=@fixtures/v1/ktp.png
curl -fsS "$SESSION_URL/chat" -H 'Content-Type: application/json' \
  -d '{"text":"08123456789, pelapor.dummy@example.com"}'
curl -fsS "$SESSION_URL/upload" -F file=@fixtures/v1/bukti_chat.png
curl -fsS "$SESSION_URL/chat" -H 'Content-Type: application/json' \
  -d '{"text":"Lanjut ke Tahap 3","action":"continue"}'
```

Lanjutkan dengan kronologi pengguna, opsi laporan polisi (`action:"skip_police"`), unggahan rekening, lalu transfer. Pilihan tambahan memakai `more_chat` atau `more_transfer`; `continue` melanjutkan tahap. Nilai kontak konfirmasi disalin otomatis. API juga menerima koreksi terstruktur `{"values":{"tahap1.email_pelapor":"koreksi@example.com"}}`; UI chat utama tidak memakai form field.

Pada `FINAL_CONFIRMATION`, pengguna membaca ringkasan dan mengetik jawaban CAPTCHA melalui `/chat`. Jawaban benar menyimpan persetujuan simulasi serta membuat tiket lokal; jawaban tidak dihitung/dikirim otomatis oleh widget. Tantangan dimiliki server dan dibatasi lima jawaban salah.

`/submit` dipertahankan untuk adapter: body `setuju_syarat_dan_ketentuan:true`, `captcha_answer`, dan `integration_mode:"dom"` atau `"webhook"`. DOM mengembalikan mapping/koleksi; webhook default memanggil mock dalam proses yang sama. `IASC_WEBHOOK_URL` hanya menerima HTTP pada IP loopback; endpoint resmi/eksternal ditolak. Hasil selalu `SIM-…`, `freeze_status:SIMULATED_NO_BANK_ACTION`, `submitted:false`, tanpa ring-fencing/tracing. Retry revisi sama memakai kunci idempotensi sama.

## Tempel widget ke ASP.NET

```html
<script src="http://127.0.0.1:8787/static/widget.js" defer></script>
```

Script membuat floating widget/iframe; API dipanggil dari iframe ke origin intake yang sama. Atur `EMBED_ORIGINS` agar CSP intake mengizinkan host. CSP host perlu mengizinkan origin intake pada `script-src`, `style-src`, dan `frame-src`; host HTTPS memerlukan layanan intake HTTPS.

Bridge replika memakai `<script src="/static/widget.js" data-integrate="replica" defer></script>` pada **origin yang sama**. Pesan `iasc-intake:progress` diperiksa sumber/originnya. Host menerapkan patch setiap 120 ms, lalu mengirim acknowledgment `iasc-intake:progress-applied`; chat menunggu hasil pengisian sebelum pertanyaan selanjutnya. Revisi duplikat diabaikan dan perubahan manual dipertahankan. Mode embed biasa hanya menampilkan chat.

Integrasi ASP.NET resmi masih memerlukan kontrak field/master ID, tabel modal, transport file, autentikasi, dan adapter yang disetujui pemilik portal. Selector replika bukan kontrak backend resmi.

## Batas implementasi

- Sesi/file berada di memori: maksimal 20 sesi, satu jam tidak aktif, 12 unggahan per sesi. Pembersihan saat akses berikutnya; restart menghapus data. Jalankan **satu worker**. Token sesi memberi akses ke data/file sesi dan harus diperlakukan sebagai rahasia.
- Upload menerima JPG/PNG/WebP maksimal 10 MiB dan 12 megapiksel, memverifikasi isi, menghapus metadata, serta mengonversi ke JPEG **di bawah 900.000 byte**. Kontrak final mengizinkan PDF/JPG/PNG dengan batas identitas 1 MiB/bukti 2 MiB, tetapi jalur chat saat ini **tidak menerima PDF atau audio**. Teks transkripsi dapat diketik; perekaman/transkripsi tidak tersedia.
- Smart re-use menghubungkan bukti chat dengan kolom komunikasi/media/kejadian. NIK/rekening/telepon tetap string; nominal berupa Decimal positif dengan maksimal dua desimal. Default nama rekening memerlukan konfirmasi bila belum teramati pada bukti independen.
- Master lokasi hanya DKI Jakarta dan sebagian Jawa Barat; bank/media juga katalog demo. Lokasi belum terpetakan memerlukan pemeriksaan manusia.
- e-KYC bersifat opsional dan simulasi. `simulate:false` menghasilkan 501. Pelaporan perwakilan dapat didemokan, tetapi verifikasi korban/surat kuasa belum diterapkan; endpoint e-KYC menolaknya. Jangan menganggap tiket perwakilan lokal sebagai laporan resmi yang terverifikasi.
- Belum ada autentikasi, penyimpanan persisten, biometrik, integrasi bank/IASC, auto-freeze, ring-fencing, atau multi-hop tracing. PoC belum siap untuk data pribadi nyata atau akses publik.

## Pengujian

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
node --test tests/*.test.mjs
```

**70 tes Python, 65 subtest, dan 24 tes Node lulus** pada pemeriksaan 21 Oktober 2026. Cakupan meliputi urutan percakapan, kontak alami, kronologi aktual, bukti tambahan, confidence, koreksi atomik, kepemilikan file, CAPTCHA, integrasi mock, mapping progresif, revisi, dan isian manual. Hasil serta batas pemeriksaan dicatat dalam `TEST_RESULTS.md`. Uji live Sumopod terbatas pada akun/model yang dicatat di `TEST_RESULTS.md`; on-premise dan backend ASP.NET resmi belum diuji.

Referensi: [FastAPI multipart uploads](https://fastapi.tiangolo.com/tutorial/request-files/), [Pydantic validators](https://docs.pydantic.dev/latest/concepts/validators/), [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs). Sumber/hak aset tercatat dalam `static/replica/assets/NOTICE.md`.
