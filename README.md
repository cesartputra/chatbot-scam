# Replika IASC lokal + Hybrid OCR & Chat

PoC FastAPI dengan replika lima tahap pelaporan IASC dan chatbot yang dapat ditempel melalui iframe. **Tidak mengirim laporan resmi, memverifikasi identitas nyata, atau memblokir rekening. Gunakan data dummy.**

UI mengikuti acuan halaman publik dan screenshot IASC yang diperiksa pada 20 Oktober 2026. Kontrak Pydantic lima tahap mengikuti spesifikasi yang diberikan pengguna; **belum diverifikasi terhadap kontrak backend resmi ASP.NET IASC**. Target pengisian di bawah 45 detik belum diukur dan bukan jaminan performa.

## Jalankan

Memerlukan Python 3.11+; diuji pada Python 3.14.4. Node hanya diperlukan untuk test JavaScript. Tesseract tidak diperlukan untuk alur v1; hanya OCR lokal pada asisten lama yang memakainya.

```bash
cd /lokasi/iasc-ai-intake
cp .env.example .env
bash start.sh
```

Peluncuran pertama membuat `.venv` dan memasang `requirements.txt`, sehingga memerlukan akses indeks paket. Peluncuran berikutnya memakai environment tersebut. `.env` dimuat otomatis oleh `main.py`; environment yang sudah diekspor tetap diutamakan. Peluncur menjalankan `uvicorn main:app` pada **127.0.0.1:8787**, satu worker, tanpa access log. Hentikan dengan Ctrl+C. Gunakan `PORT=8788 bash start.sh` untuk port lain.

| Halaman | Alamat lokal |
| --- | --- |
| Beranda replika | [Buka beranda](http://127.0.0.1:8787/) |
| Formulir lima tahap + widget | [Buka formulir](http://127.0.0.1:8787/Guest/LaporanV2) |
| Demo satu berkas HTML yang membungkus replika | [Buka demo widget](http://127.0.0.1:8787/widget/iasc-ai-widget.html) |
| Cek hasil simulasi browser | [Buka Cek Laporan](http://127.0.0.1:8787/Guest/CekLaporan) |
| Panduan API / OpenAPI / kontrak data | [Panduan](http://127.0.0.1:8787/docs), [OpenAPI](http://127.0.0.1:8787/openapi.json), [JSON Schema](http://127.0.0.1:8787/api/v1/schema) |

`widget/iasc-ai-widget.html` juga dapat dibuka dari disk; berkas itu memuat replika pada `http://127.0.0.1:8787`, sehingga server tetap harus berjalan pada port tersebut.

## Coba melalui browser

1. Buka formulir, lalu klik **Bantu susun laporan**.
2. Klik **Pakai bukti dummy** atau pilih empat gambar: KTP, transfer, komunikasi, dan bukti rekening korban. Identitas dan rekening dikelompokkan dalam satu bagian UI, tetapi tetap menjadi dua berkas berbeda.
3. Dalam mode default, isi dua data yang belum tersedia: nomor HP dan email. Tombol jawaban contoh tersedia. Periksa kartu ringkasan; setiap perubahan membatalkan konfirmasi dan e-KYC sebelumnya.
4. Klik **Data sudah sesuai**, lalu **Jalankan simulasi e-KYC**. Ini memakai skor contoh dan mencocokkan nama dari dua bukti; tidak memakai kamera, biometrik, atau sumber identitas resmi.
5. Untuk demo auto-fill lokal, pengguna dapat mencentang persetujuan simulasi, mengetik jawaban CAPTCHA lokal, lalu memilih **Auto-Fill Form ASP.NET**. Tombol itu menghasilkan payload dan menerapkannya ke replika lokal. Tombol kirim laporan resmi tetap dinonaktifkan.

Formulir manual tetap tersedia jika AI gagal. **Simpan Simulasi Lokal** hanya menyimpan metadata di localStorage browser dengan `SIM-…`, `simulated:true`, `submitted:false`. Berkas asli tidak masuk localStorage. Isian formulir aktif dan file di memori tab hilang ketika halaman dimuat ulang; metadata simulasi tersimpan dapat dihapus melalui Cek Laporan.

## Struktur proyek

```text
iasc-ai-intake/
├── main.py                       # FastAPI v1, batas origin/host, integrasi mock
├── schemas.py                    # LaporanIASC dan lima model tahap Pydantic v2
├── requirements.txt
├── .env.example
├── start.sh
├── services/
│   ├── __init__.py
│   ├── orchestrator.py            # Sesi, state machine, confidence, validasi file
│   ├── llm_gateway.py             # API OpenAI-compatible + simulasi berlabel
│   ├── image_processor.py         # Validasi gambar, kompresi, pointer bukti
│   └── normalizer.py              # Bank, provinsi/kota, media
├── widget/iasc-ai-widget.html      # HTML/CSS/JS asisten dan wrapper demonstrasi
├── static/
│   ├── widget.js / widget.css     # Floating launcher dan iframe
│   ├── replica/                   # Lima tahap, dialog, beranda, Cek Laporan
│   │   ├── report-core.mjs        # Master dropdown dan validasi replika
│   │   ├── report.html / report.js / replica.css
│   │   └── assets/NOTICE.md       # Sumber aset dan pemberitahuan kepemilikan
│   ├── docs.html
│   └── ...                       # Halaman integrasi dan asisten lama
├── fixtures/v1/                   # ktp, bukti_transfer, bukti_chat, rekening PNG
├── tests/
│   ├── test_workflow_v1.py
│   ├── test_schemas_v1.py
│   ├── test_services_v1.py
│   ├── test_app.py                # Regresi asisten lama
│   └── report-core.test.mjs
├── app.py                        # Replika/aset dan API asisten lama
└── TEST_RESULTS.md
```

`/assistant` dan `/api/sessions` adalah asisten lama dengan skema ringkas dan sesi terpisah. OCR Tesseract pada jalur lama tidak berarti alur v1 melakukan OCR dalam mode simulasi. Entry point utama proyek ini adalah **`main:app`**.

## AI Gateway

Default `AI_MODE=auto` dengan `AI_API_KEY` kosong memakai **hasil dummy tetap yang terprogram**, bukan pembacaan isi gambar. Mode ini tetap memvalidasi dan mengompresi unggahan. Label simulasi tampil di UI dan respons API.

Contoh `.env` untuk provider cloud yang mendukung Chat Completions, gambar, dan structured output:

```dotenv
AI_MODE=remote
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=isi_secret_di_server
VISION_MODEL_NAME=gpt-4o
CHAT_MODEL_NAME=gpt-4o-mini
AI_RESPONSE_FORMAT=json_schema
AI_TIMEOUT_SECONDS=35
```

Contoh gateway on-premise dengan dua alias model:

```dotenv
AI_MODE=remote
AI_BASE_URL=http://127.0.0.1:4000/v1
AI_API_KEY=secret_gateway_lokal
VISION_MODEL_NAME=qwen2.5-vl
CHAT_MODEL_NAME=deepseek-v3
AI_RESPONSE_FORMAT=json_object
```

Kedua model menggunakan **satu `AI_BASE_URL`**; vLLM/LiteLLM atau router lain harus menyediakan alias model tersebut dan dukungan konten masing-masing. HTTP tanpa TLS hanya diterima pada localhost; keyless localhost harus memakai `AI_MODE=remote` secara eksplisit. Model vision dan dukungan `json_schema`/`json_object` harus diuji pada provider yang dipilih. Contoh nama model bukan klaim kompatibilitas yang telah diuji.

Dalam mode remote, gambar yang telah dibersihkan metadata dan konteks jawaban dikirim ke gateway terkonfigurasi. Kunci tetap di server. Kegagalan provider **tidak berpindah otomatis ke data dummy** dan tidak mengganti draft yang sudah ada. Ubah konfigurasi lalu restart untuk mengganti mode/model. Gateway hanya mengekstrak kolom; model tidak dapat memberi persetujuan, menjalankan e-KYC, atau mengubah state sendiri.

## API v1: alur lima state

`STATE_1_EVIDENCE_UPLOAD` → `STATE_2_DELTA_SLOT_FILLING` → `STATE_3_CONFIRMATION_CARD` → `STATE_4_EKYC_VERIFICATION` → `STATE_5_DISPATCH_FREEZE`.

Nama state terakhir adalah nama kontrak PoC; tidak ada freeze nyata. Kolom kosong/invalid dan confidence di bawah 0,85 menahan alur. Mutasi data membatalkan konfirmasi, e-KYC, dan hasil dispatch terdahulu. Endpoint tidak mengizinkan melewati urutan tersebut.

Contoh berikut hanya memanggil server lokal yang sedang berjalan. Membutuhkan `curl` dan Python untuk membaca token JSON:

```bash
API_BASE=http://127.0.0.1:8787
SESSION_ID=$(curl -fsS -H 'Content-Type: application/json' -d '{}' \
  "$API_BASE/api/v1/session/init" | python3 -c 'import json,sys; print(json.load(sys.stdin)["session_id"])')
SESSION_URL="$API_BASE/api/v1/session/$SESSION_ID"
curl -fsS "$SESSION_URL/upload" \
  -F ktp=@fixtures/v1/ktp.png \
  -F bukti_transfer=@fixtures/v1/bukti_transfer.png \
  -F bukti_chat=@fixtures/v1/bukti_chat.png \
  -F bukti_rekening_korban=@fixtures/v1/bukti_rekening_korban.png
curl -fsS "$SESSION_URL/chat" -H 'Content-Type: application/json' \
  -d '{"values":{"tahap1.nomor_telepon_pelapor":"80000000000","tahap1.email_pelapor":"pelapor.dummy@example.com"}}'
curl -fsS "$SESSION_URL/chat" -H 'Content-Type: application/json' -d '{"confirm":true}'
curl -fsS "$SESSION_URL/verify-ekyc" -H 'Content-Type: application/json' \
  -d '{"simulate":true,"liveness_score":0.98}'
```

`chat` juga menerima `{"text":"email=pelapor.dummy@example.com"}` untuk slot yang sedang diminta. Teks hasil transkripsi dapat dikirim dengan cara sama; perekaman atau transkripsi audio tidak disediakan.

Baca tantangan melalui `GET "$SESSION_URL"`. Pengguna memasukkan jawaban lokal sendiri; contoh berikut menghasilkan payload DOM dan **tidak mengirim laporan resmi**:

```bash
curl -fsS "$SESSION_URL"
printf 'Jawaban CAPTCHA lokal: '
read -r CAPTCHA_ANSWER
curl -fsS "$SESSION_URL/submit" -H 'Content-Type: application/json' \
  -d "{\"setuju_syarat_dan_ketentuan\":true,\"captcha_answer\":\"$CAPTCHA_ANSWER\",\"integration_mode\":\"dom\"}"
```

Mode `dom` mengembalikan payload lima tahap, mapping selector, dan koleksi dialog untuk adapter lokal. Untuk menguji Mode A, ganti `integration_mode` menjadi `webhook`. Default webhook memakai adapter mock dalam proses yang sama; `IASC_WEBHOOK_URL` hanya boleh berupa URL HTTP pada IP loopback. Endpoint eksternal/resmi ditolak. Hasil mock berupa tiket `SIM-…`, `freeze_status:SIMULATED_NO_BANK_ACTION`, `submitted:false`; retry revisi yang sama memakai kunci idempotensi yang sama.

Endpoint pendukung: `GET /api/v1/session/{id}`, `GET .../status`, `GET .../files/{file_id}`, `DELETE /api/v1/session/{id}`, `GET /api/v1/schema`, dan `GET /health`. Token sesi memberi akses data/file sesi; perlakukan sebagai rahasia. CAPTCHA terikat pada sesi server dan dibatasi lima jawaban salah.

## Tempel widget ke ASP.NET

```html
<script src="http://127.0.0.1:8787/static/widget.js" defer></script>
```

Script membuat floating widget dan iframe; API dipanggil dari iframe ke origin intake yang sama. Atur `EMBED_ORIGINS` pada server intake untuk origin host yang diizinkan memuat iframe. CSP host juga harus mengizinkan origin intake pada `script-src`, `style-src`, dan `frame-src`; host HTTPS memerlukan layanan intake HTTPS.

Widget biasa tidak mengisi form host. Bridge `data-integrate="replica"` hanya aktif jika host dan layanan mempunyai origin yang sama, serta memeriksa origin dan sumber pesan iframe. Adapter lokal mengisi kolom kosong, mempertahankan isian manual, dan memetakan file bukti; tidak auto-submit. Integrasi ASP.NET asli membutuhkan verifikasi nama field/master ID, pengisian koleksi modal, transport file, autentikasi, dan kontrak backend oleh pemilik portal.

## Batas implementasi

- Sesi v1 berada di memori: maksimal 20 sesi, kedaluwarsa setelah satu jam tidak aktif, maksimal 12 unggahan tersimpan per sesi. File hasil kompresi juga di memori server. Pembersihan berlangsung saat akses berikutnya; restart menghapus data. Jalankan satu worker.
- Unggahan v1 menerima JPG/PNG/WebP maksimal 10 MiB per file dan 12 megapiksel, diverifikasi dari isi, dihapus metadata, lalu dikonversi ke JPEG **di bawah 900.000 byte**. Kontrak final mengizinkan PDF/JPG/PNG, 1 MiB untuk identitas dan 2 MiB untuk bukti lain; ekstraksi PDF belum tersedia.
- Satu bukti chat dipakai ulang untuk bukti komunikasi, sumber/media, dan kejadian. Nomor rekening/NIK/telepon tetap string; nominal divalidasi sebagai Decimal positif. Konfirmasi kontak disalin otomatis. Nama pemilik rekening default tidak dianggap bukti kecocokan identitas independen.
- Master kota mencakup DKI Jakarta dan sebagian Jawa Barat. Lokasi OCR yang belum terpetakan membutuhkan konfirmasi manusia; katalog ini belum merupakan master resmi lengkap. Dropdown bank/media juga pilihan demonstrasi.
- e-KYC hanya simulasi. Permintaan `simulate:false` menghasilkan HTTP 501; kecocokan nama bukan bukti keaslian KTP. Pelaporan perwakilan diarahkan ke formulir manual karena kontrak pengguna belum memasukkan verifikasi korban dan surat kuasa.
- Tidak ada autentikasi pengguna, penyimpanan persisten, biometrik, transkripsi suara, auto-freeze, ring-fencing, multi-hop tracing, akses bank, atau integrasi IASC resmi. PoC ini belum siap dipasang untuk data pribadi nyata atau akses publik.

## Pengujian

```bash
.venv/bin/python -m unittest discover -s tests -v
node --test tests/report-core.test.mjs
```

**54 test Python dan 13 test Node lulus** pada pemeriksaan 21 Oktober 2026. Cakupan: lima state, kontrak, kompresi, confidence, koreksi atomik, bukti pengganti, kepemilikan file, e-KYC tiruan, CAPTCHA, origin/host, kedua mode integrasi mock, gateway tiruan, dan regresi alur lama. Hasil browser dan batas pemeriksaan dicatat di `TEST_RESULTS.md`. Provider cloud/on-premise nyata dan backend ASP.NET resmi belum diuji.

Referensi: [FastAPI multipart uploads](https://fastapi.tiangolo.com/tutorial/request-files/), [Pydantic validators](https://docs.pydantic.dev/latest/concepts/validators/), [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs). Aset acuan dan hak pemiliknya tercatat dalam `static/replica/assets/NOTICE.md`.
