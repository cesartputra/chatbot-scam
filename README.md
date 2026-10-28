# Replika IASC lokal + Help Center OCR & Chat

PoC FastAPI dengan replika lima tahap pelaporan IASC dan asisten pengisian bertahap yang dapat ditempel melalui iframe. LLM mengekstrak JSON pelaporan dan memilih FAQ terkurasi; tidak menyediakan obrolan bebas. **Tidak mengirim laporan resmi, memverifikasi identitas nyata, atau memblokir rekening. Gunakan data dummy.**

UI mengikuti acuan halaman publik dan screenshot IASC yang diperiksa pada 20 Oktober 2026. Kontrak Pydantic lima tahap mengikuti spesifikasi pengguna; **belum diverifikasi terhadap backend resmi ASP.NET IASC**. Target pengisian di bawah 45 detik belum diukur dan bukan jaminan performa.

## Jalankan

Memerlukan Python 3.11+; diuji pada Python 3.14.4. Node diperlukan untuk tes JavaScript. **Tesseract open source dengan trained data `eng` wajib dipasang pada server**, untuk OCR KTP dan pemeriksaan lokal setiap bukti sebelum vision, termasuk mode simulasi. KTP selalu dibaca lokal; simulasi tanpa key memakai hasil dummy untuk bukti non-KTP yang lolos pemeriksaan.

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

Jika instalasi menampilkan `ConnectionResetError` lalu `from versions: none`, koneksi indeks terputus sebelum pip mendapat daftar versi. FastAPI `0.153.0` tersedia di [PyPI](https://pypi.org/project/fastapi/0.153.0/); jangan mengubah pin paket berdasarkan pesan jaringan tersebut. Coba satu peluncuran dengan indeks resmi:

```bash
PIP_INDEX_URL=https://pypi.org/simple bash start.sh
```

Jika masih terputus, coba hotspot/jaringan lain dan periksa proxy/VPN. Peluncur memakai timeout 60 detik, lima retry, dan cache pip; konfigurasi indeks/proxy/sertifikat Anda tetap berlaku. Penanda dependensi hanya dibuat setelah instalasi sukses, sehingga kegagalan dapat dicoba ulang tanpa menghapus `.venv` atau `.env`.

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
3. Ceritakan kejadian beserta tanggal dan jam sebenarnya. Dengan key aktif, AI menyusun kronologi dari cerita, fakta bukti chat, serta data terlapor/media yang sudah tercatat. Waktu kejadian tetap ditentukan dari input/kolom yang jelas; bila belum lengkap, chat menanyakannya. Bukti chat dipakai ulang untuk kejadian. Unggah gambar laporan polisi atau pilih **Lewati / Belum Ada**.
4. Kirim bukti kepemilikan rekening, lalu bukti transfer. Bukti transfer berikutnya menambah rincian transaksi pada penerima yang sama atau menambah penerima baru; transaksi sebelumnya dipertahankan.
5. Periksa kartu ringkasan. Pesan menjelaskan bahwa mengetik jawaban CAPTCHA lokal berarti menyetujui S&K **simulasi lokal**. Jawaban benar menghasilkan tiket `SIM-…` di chat dan host. Tidak ada langkah pengiriman resmi atau tindakan bank.

Setiap respons membawa perubahan field. Replika mengisinya satu per satu dengan jeda **120 ms**, menyorot/menggulir field, mengisi radio/dropdown/tanggal/lampiran serta tabel bersarang, lalu berpindah ke tahap aktif. Isian manual yang sudah ada dipertahankan dan konflik diberitahukan. Sesi baru menghapus isian hasil AI sebelumnya sambil mempertahankan perubahan manual.

Pada Tahap 2, **media** seperti WhatsApp berbeda dari **detail media** berupa nomor kontak, `@username`, atau tautan lengkap pelaku. Nilai eksplisit ini diparsing lokal. Sapaan, kebingungan, kepanikan, dan pertanyaan seperti “nomor yang mana?” menerima bantuan empatik sesuai kolom aktif, tanpa API atau perubahan draft. Pertanyaan tidak disimpan sebagai nama/nomor. Instruksi berbahaya dan permintaan di luar pelaporan tetap ditolak disertai arahan melanjutkan. Balasan selalu terlihat setelah pesan/unggahan baru, termasuk ketika revisi tidak berubah. Maksimal satu pesan adalah **2.000 karakter**.

Jawaban tidak harus sama persis dengan format kolom: `320 ribu`, `1,5 juta`, `jam 10 pagi`, dan `pukul 3 sore` diparsing lokal. Kalimat lain memakai interpretasi JSON Sumopod untuk kolom yang sedang ditanyakan, misalnya nominal dalam kata-kata atau nama panjang bank. Jika baru jam yang diketahui, asisten menyimpannya sementara lalu meminta tanggal; tanggal hari ini tidak ditambahkan otomatis. Nilai ambigu tetap memerlukan konfirmasi. Mode tanpa key hanya menyediakan parser lokal, bukan interpretasi bahasa oleh model.

Formulir manual tetap tersedia bila AI gagal. **Simpan Simulasi Lokal** menyimpan metadata di localStorage browser dengan `SIM-…`, `simulated:true`, `submitted:false`; berkas asli tidak disimpan di sana. Isian aktif/file di memori tab hilang saat halaman dimuat ulang. Metadata tiket dapat dihapus melalui Cek Laporan. Tombol kirim laporan resmi dinonaktifkan.

## FAQ: jawab lalu lanjutkan laporan

`services/faq_grounding.py` menyimpan 12 FAQ bahasa Indonesia dengan ID, jawaban, kata kunci, state terkait, URL sumber, asal panduan, dan tanggal peninjauan. Sumber prosedur resmi diperiksa pada **28 Oktober 2026** melalui [portal IASC OJK](https://iasc.ojk.go.id/). Panduan aplikasi lokal—contoh bukti bank digital, batas/kompresi file, melewati unggahan LP, dan OCR lokal—ditandai terpisah dari prosedur resmi. Melapor ke polisi tetap diperlukan untuk jalur hukum; laporan IASC tidak menjamin dana kembali.

Pencarian memakai token/kata kunci dan peningkatan relevansi tahap di memori, tanpa embedding, database vektor, dependensi atau model tambahan. Pertanyaan seperti **“Pakai bank digital, upload apa?”** dijawab lalu diakhiri dengan permintaan file/kolom aktif. FAQ atau penolakan tidak mengubah state, lampiran, isian, revisi, maupun `dom_patches`. Pertanyaan yang belum tercakup mendapat jawaban bahwa panduan terverifikasi belum tersedia.

Pesan **“Nomor HP saya 081299887766 dan email budi@mail.com, apakah uang saya pasti kembali?”** mengisi kontak terlebih dahulu, menjawab bahwa pengembalian tidak dijamin, lalu meminta bukti chat. Pertanyaan tidak ikut disimpan ke kolom atau kronologi; pertanyaan/kalimat bersyarat yang diceritakan sebagai kejadian tetap bagian dari cerita. Nominal dan jam parsial juga dapat diberikan bersama pertanyaan; bagian tanggal/jam yang masih kurang tetap ditanyakan.

Pada mode remote, LLM hanya memilih ID dari paling banyak dua FAQ yang ditemukan, melalui JSON dengan temperature **0,7**. Teks jawaban terkurasi dan pengingat langkah dirender server; model tidak dapat menambahkan janji/prosedur baru. Teks pengguna dimasking dan data formulir/pengingat privat tidak dikirim. Bila API gagal, JSON tidak valid, atau mode simulasi aktif, jawaban deterministik tetap tersedia. Pertanyaan di luar topik dan prompt injection ditolak sebelum API.

Respons menambahkan `turn_intent` (`SLOT_INPUT`, `IASC_FAQ_QUESTION`, `MIXED_INPUT_AND_QUESTION`, `OUT_OF_CONTEXT`), `grounded_faq_ids`, `guardrail_triggered`, dan `faq_quick_asks`. Widget menampilkan badge panduan/refokus dan satu atau dua chip pertanyaan sesuai tahap; chip mengirim pertanyaan biasa, bukan aksi melanjutkan/submit. API lama juga menerima FAQ secara lokal, tanpa cloud.

Untuk menambah FAQ, edit satu entri `IASC_FAQ_KNOWLEDGE_BASE`, sertakan sumber/provenance, kata kunci dan tanggal tinjauan, lalu tambahkan tes retrieval dan restart server. Perbarui `_unsafe`/aturan topik hanya bersama tes yang membedakan cerita penipuan dari permintaan di luar konteks. Pencocokan leksikal tetap dapat melewatkan variasi bahasa yang belum tercakup.

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
│   ├── faq_grounding.py           # FAQ terkurasi, pencarian leksikal, answer-and-pivot
│   ├── guardrails.py              # Allowlist tugas, scope, injection, pesan penolakan
│   ├── ktp_ocr.py                 # OCR dan parser KTP sepenuhnya lokal
│   ├── privacy.py                 # Pseudonim data pribadi sebelum API teks
│   ├── natural_input.py           # Nominal, tanggal/jam parsial, jawaban pribadi
│   ├── chronology.py              # Pemeriksaan fakta hasil penyusunan kronologi
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

`/assistant` dan `/widget` mengarahkan ke demo percakapan baru pada `/Guest/LaporanV2?assistant=1`. UI lama masih tersedia pada `/static/index.html`; `/api/sessions` memakai skema ringkas dan sesi terpisah. API lama hanya memakai parser lokal; akses cloud lamanya dinonaktifkan agar tidak melewati guardrail v1. Entry point utama adalah **`main:app`**.

## AI Gateway

Default `AI_MODE=auto` dengan key kosong memakai **ekstraksi bukti non-KTP dummy tetap** setelah pemeriksaan OCR lokal. KTP selalu diekstrak oleh parser lokal. Unggahan tetap divalidasi/dikompresi. Nomor/email diambil dari teks yang benar-benar diketik, dan kronologi memakai cerita pengguna. UI/respons menandai ekstraksi simulasi.

Provider ekstraksi JSON adalah **Sumopod AI** melalui base URL `https://ai.sumopod.com/v1` dan API key pada server, mengikuti [dokumentasi OpenAI-compatible resmi](https://docs.sumopod.com/guides/ai/openai-compatible-api). Pilih nama model dari dashboard atau `/v1/models` untuk key Anda; akses model dapat berbeda antar akun.

Konfigurasi utama memisahkan KTP lokal, chat Sumopod, dan vision Sumopod untuk bukti lain:

Untuk instalasi yang sudah memiliki `.env`, `git pull` tidak mengganti file tersebut. Sesuaikan ID model dan `VISION_INPUT_MODE` seperti contoh berikut, pertahankan key Anda, lalu restart `bash start.sh`.

```dotenv
AI_MODE=auto
AI_BASE_URL=https://ai.sumopod.com/v1
AI_API_KEY=isi_key_sumopod_di_server
VISION_INPUT_MODE=image
VISION_MODEL_NAME=gemini/gemini-3.5-flash-lite
CHAT_MODEL_NAME=deepseek-v4-flash
AI_RESPONSE_FORMAT=json_object
AI_TIMEOUT_SECONDS=60
```

Key kosong mempertahankan simulasi berlabel; isi key dan restart untuk memakai Sumopod. **Satu API key dapat dipakai untuk chat dan vision** bila key tersebut mengizinkan kedua model. ID model harus persis seperti hasil `/v1/models`, termasuk prefix `gemini/`. Nama tanpa prefix ditolak oleh key pengujian; bukan karena key yang sama dipakai dua model.

Gateway memakai **`temperature=0.7`** dan `response_format={"type":"json_object"}` untuk seluruh panggilan model; `AI_RESPONSE_FORMAT` tidak mengubah format ini. Schema lengkap dan contoh confidence disertakan dalam prompt. Confidence dokumen yang tidak dikembalikan provider menjadi **0**, sehingga wajib dikonfirmasi manusia. Error akses model, nama model, kuota, timeout, dan kontrak respons dibedakan tanpa menampilkan isi respons/key. Bantuan empatik tetap memakai template lokal.

KTP diproses oleh Tesseract dan parser label di server; **gambar maupun teks OCR KTP tidak dikirim ke Sumopod**. Parser menangani label KTP Indonesia, header wilayah, tempat/tanggal lahir, dan alamat. Hasil yang tidak terbaca tetap kosong. Ini ekstraksi data, bukan pemeriksaan keaslian KTP.

Hasil OCR KTP dinormalkan sebelum validasi: kapitalisasi jenis kelamin/agama/identitas, `WNI`, dan format tanggal yang jelas. Kolom yang masih invalid dibiarkan kosong untuk ditanyakan lewat chat; kolom valid serta lampiran tetap disimpan. Digit NIK tidak ditebak, ditambah, atau dikonversi dari angka.

Teks ekstraksi memakai pseudonim bertipe, misalnya `[NAMA_PELAPOR_1]`, `[NIK_1]`, `[REKENING_1]`, `[EMAIL_1]`, dan `[TELEPON_1]`. Nilai pribadi yang sudah diketahui dari sesi serta pola pengenal pada pesan disamarkan sebelum API; relasi pelapor/terlapor, jumlah transaksi, dan waktu kejadian dipertahankan. Pemetaan hanya ada di memori selama permintaan dan dipulihkan sebelum validasi/isian formulir. Model tidak mendapat tabel pemetaan. Penanda baru/rusak ditolak. Kontak, NIK, tanggal/nominal eksplisit, serta jawaban pribadi yang jelas diparsing lokal. Kalimat pribadi yang memerlukan interpretasi hanya diteruskan bila memiliki token masking; model wajib memilih tepat satu token yang diterbitkan, tanpa menambah teks atau mengarang identitas.

### Penyusunan kronologi AI

Saat Tahap 3, Sumopod menyusun paragraf kronologi formal maksimal **4.000 karakter** dari cerita pengguna, fakta yang terbaca pada bukti chat, data terlapor/media, dan data transaksi yang sudah tersedia. Vision bukti chat dapat mengembalikan maksimal delapan kutipan/fakta singkat per gambar; fakta tersebut tersimpan privat di sesi, bukan sebagai kolom tambahan pada laporan. Cerita asli juga disimpan privat, sehingga pembaruan tidak berulang kali merangkum hasil AI sebelumnya.

Saat melanjutkan ke ringkasan Tahap 5, AI memperbarui kronologi dengan rekening dan transfer yang baru diunggah. Koreksi fakta pada ringkasan memperbarui hanya kronologi yang masih bersumber dari AI. Kronologi yang sudah dikoreksi atau dikonfirmasi manual dipertahankan. Jika API gagal, draft dan cerita asli tetap utuh; pengguna dapat mencoba lagi atau mengisi kronologi manual. Pada simulasi tanpa key, cerita pengguna tetap dipakai tanpa sintesis cloud.

Konteks cloud hanya berisi fakta terlapor/media, waktu kejadian, rekening/transaksi, dan fakta chat yang dimasking. Biodata KTP, file/foto KTP, CAPTCHA, dan field sesi lain tidak disertakan; token biodata dan rahasia dalam cerita dihapus. Output tetap berupa JSON satu kolom kronologi dalam tugas `extract_report_fields`, bukan balasan obrolan bebas. `services/chronology.py` memeriksa token, identitas baru yang terdeteksi, nominal, tanggal/jam, tautan, serta beberapa kejadian/negasi umum sebelum data pribadi dipulihkan. Nilai confidence rendah tetap memerlukan konfirmasi. Pemeriksaan ini bersifat heuristik dan tidak membuktikan semua hubungan atau urutan kejadian benar; pengguna harus memeriksa hasilnya.

Masking berbasis konteks dan pola **bukan jaminan anonimisasi menyeluruh**: nama baru huruf kecil tanpa penanda atau konteks bisa tidak dikenali. Tuliskan identitas baru dengan label seperti `nama terlapor:`. Bukti selain KTP dikirim sebagai gambar ke vision; masking teks **tidak menyamarkan piksel gambar**. Gunakan bukti dummy atau gambar yang data sensitifnya sudah disamarkan. Laporan polisi hanya disimpan lokal, tanpa ekstraksi cloud.

`ocr_text` tetap tersedia sebagai pilihan eksplisit untuk bukti non-KTP: Tesseract membaca gambar lalu teksnya dimasking sebelum model ekstraksi teks. Pada mode `image`, OCR lokal memeriksa indikasi KTP sebelum gambar dikirim. Jika mesin OCR gagal/tidak tersedia, gambar tetap lokal; jika mesin berjalan tetapi teks kosong atau keliru, vision tetap dapat membaca piksel. Hasil vision tidak lagi harus identik dengan OCR lokal yang kurang akurat. Kutipan perintah penipu dalam bukti diperlakukan sebagai data pasif, bukan perintah untuk asisten atau alasan otomatis menolak seluruh bukti. Pemeriksaan prompt injection pada pesan pengguna, prompt ekstraksi pasif, flag provider, whitelist field, dan validasi skema tetap berlaku. Nilai yang tidak terbaca atau disamarkan pada gambar tidak boleh ditebak. Kegagalan provider tidak diganti data dummy.

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

Untuk MacBook M1 8 GB dengan Ollama yang sudah terpasang, siapkan `ollama pull qwen2.5:3b` dan jalankan layanan Ollama, lalu gunakan:

```dotenv
AI_MODE=remote
AI_BASE_URL=http://127.0.0.1:11434/v1
AI_API_KEY=
CHAT_MODEL_NAME=qwen2.5:3b
VISION_MODEL_NAME=qwen2.5:3b
VISION_INPUT_MODE=ocr_text
```

`qwen2.5:3b` adalah model teks: bukti non-KTP dibaca Tesseract lokal sebelum ekstraksi teks, sehingga tidak mengirim input gambar ke model teks. KTP tetap memakai parser lokal. FAQ tidak menambahkan model, embedding, atau database ke RAM. Kecepatan dan konsumsi RAM pada perangkat M1 8 GB belum diukur; contoh ini tidak otomatis memasang/mengunduh model.

Gateway tetap model-agnostic: kedua model memakai **satu `AI_BASE_URL`**; untuk on-premise, router vLLM/LiteLLM harus menyediakan alias dan kemampuan masing-masing. HTTP tanpa TLS hanya diterima pada localhost. Keyless localhost memerlukan `AI_MODE=remote` eksplisit. Konfigurasi on-premise belum diuji.

Restart setelah mengganti konfigurasi. Model mengekstrak slot atau memilih ID FAQ yang disediakan; state, consent, validasi, dan tiket dikendalikan server. Key tetap di server dan `.env` tidak masuk Git.

## Guardrail yang dapat diperbarui

Aturan server berada di **`services/guardrails.py`**. `ALLOWED_LLM_TASKS` hanya berisi `extract_report_fields`, `extract_transfer_proof`, `extract_victim_account_proof`, dan `extract_chat_proof`; tugas lain menghasilkan `ValueError`. Tambahkan pola injeksi pada `_INJECTION`, aturan topik pada pemeriksaan scope, dan kasus regresi pada `tests/test_guardrails.py`, lalu jalankan pytest dan restart server. Pemilihan ID FAQ menggunakan jalur khusus `generate_grounded_faq_reply`, di luar empat tugas ekstraksi, dengan jawaban tetap dirender dari registry lokal. Mengubah system prompt saja tidak mengubah izin server.

Input diperiksa sebelum pemrosesan state: maksimal 2.000 karakter, normalisasi Unicode, pembersihan karakter kontrol, deteksi instruksi/tag role/script, serta penolakan topik di luar pelaporan. Bantuan dan pertanyaan klarifikasi diarahkan ke template empatik lokal; jawaban singkat divalidasi terhadap kolom aktif. Cerita pada tahap kronologi memakai konteks tahap, sehingga tidak wajib menyebut kata “penipuan”. Deskripsi seperti “penipu berperan sebagai petugas bank” diperlakukan sebagai cerita, sedangkan perintah mengganti peran asisten tetap ditolak. Input terlalu panjang ditolak HTTP 422. Bantuan/penolakan mempertahankan data, revisi, consent, tiket, dan tahap laporan, tanpa patch baru.

Model menerima sumber di dalam `<untrusted_user_report>` sebagai data pasif. Output wajib memiliki `slots`, `is_relevant_to_scam_report`, dan `injection_detected`; Pydantic memakai `extra="forbid"`. Bukti chat juga mengizinkan metadata `evidence_facts` dengan batas ketat; tugas lain menolak key tambahan tersebut. Flag penolakan, field asing/duplikat, teks obrolan, dan penanda privasi palsu ditolak. Ekstraksi teks bukti dibandingkan dengan teks sumber; vision memakai piksel gambar. Interpretasi jawaban hanya boleh mengisi satu kolom aktif. Sintesis kronologi memiliki pemeriksaan fakta tersendiri agar parafrasa diizinkan. Field dibatasi per tugas, dinormalkan, dan divalidasi terhadap kontrak laporan. Pesan percakapan asisten berasal dari template Python; paragraf AI hanya mengisi kolom kronologi. Penolakan berikut disertai panduan kolom/tahap aktif:

> Maaf, asisten ini hanya memproses data pelaporan penipuan keuangan IASC (kronologi kejadian, data rekening, dan bukti transaksi). Mohon masukkan informasi atau unggah bukti yang berkaitan dengan laporan Anda.

Deteksi pola, identifikasi KTP, dan pencocokan fakta bergantung pada OCR/heuristik: dapat menolak bukti sah dan tidak menjamin semua injeksi tersamarkan terdeteksi. Pencocokan nilai tidak membuktikan pemilik rekening atau keaslian bukti. Hasil tetap perlu ditinjau manusia; model tidak memiliki alat, akses submit, atau kewenangan mengubah state.

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

**234 tes Python, 522 subtest, dan 27 tes Node lulus** pada pemeriksaan 24 Oktober 2026. Cakupan mencakup sintesis/pembaruan kronologi, pemeriksaan fakta dan privasi, koreksi manual, rollback API, interpretasi kolom aktif, nominal natural, tanggal/jam parsial, vision, guardrail, serta pengisian progresif. Uji alur API aplikasi memakai Sumopod nyata pada temperature 0,7 berhasil sampai ringkasan akhir, dengan KTP lokal dan kronologi yang diperbarui dari bukti/transaksi dummy, tanpa submit/CAPTCHA. Browser tidak diulang pada perubahan ini. Hasil serta riwayat pemeriksaan dicatat dalam `TEST_RESULTS.md`; on-premise dan backend ASP.NET resmi belum diuji.

Referensi: [FastAPI multipart uploads](https://fastapi.tiangolo.com/tutorial/request-files/), [Pydantic validators](https://docs.pydantic.dev/latest/concepts/validators/), [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs). Sumber/hak aset tercatat dalam `static/replica/assets/NOTICE.md`.
