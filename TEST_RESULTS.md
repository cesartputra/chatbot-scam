# Hasil verifikasi PoC — 21 Oktober 2026

Build yang diuji memakai entry point `main:app`, FastAPI 0.153.0, Pydantic 2.14.1, Python 3.14.4 pada macOS. Semua data pengujian fiktif. Tidak ada pengiriman laporan ke IASC atau tindakan bank.

## Pengujian otomatis

| Suite | Hasil |
| --- | --- |
| Python: `python -m unittest discover -s tests -v` | **54 lulus, 0 gagal, 0 skip** |
| JavaScript: `node --test tests/report-core.test.mjs` | **13 lulus, 0 gagal, 0 skip** |

Suite Python meliputi:

- Transisi lima state, dua delta slot kontak setelah empat unggahan dummy, kartu konfirmasi, e-KYC simulasi, dan ekspor payload.
- Mode DOM lokal dan webhook mock; tiket `SIM-…`, idempotensi, dan penolakan URL webhook eksternal sebelum akses jaringan.
- Seluruh model lima tahap, daftar bersarang, ringkasan transaksi konsisten, batas lampiran 1/2 MiB, tanggal Indonesia, nominal positif/finite, dan preservasi nol awal.
- Auto-copy kontak tanpa menutupi konfirmasi eksplisit yang berbeda; nama pemilik rekening independen tetap dipertahankan.
- Kompresi di bawah 900.000 byte, penghapusan metadata, penolakan tipe/isi palsu, file terlalu besar, gambar animasi, dan resolusi berlebih.
- Smart re-use bukti chat pada tiga kolom, isolasi/expiry/penghapusan sesi, akses file milik sesi, dan penolakan metadata file palsu.
- Confidence di bawah 0,85 membutuhkan koreksi/konfirmasi; ketidakpastian hasil chat remote dipertahankan. OCR lokasi yang belum terpetakan tetap memerlukan pemeriksaan manusia.
- Koreksi atomik, identitas Paspor → KTP memerlukan NIK sah, serta penolakan pasangan kota/provinsi dikenal yang bertentangan.
- Bukti pengganti memperbarui fakta OCR dan menghapus fakta lama yang tidak ditemukan, sambil mempertahankan koreksi manual.
- Perubahan data membatalkan konfirmasi/e-KYC/dispatch. Tahapan tidak dapat dilewati; skor liveness rendah atau nama bukti berbeda ditolak. e-KYC nyata menghasilkan 501.
- Persetujuan eksplisit, CAPTCHA terikat sesi, host/origin yang diizinkan, dan respons error yang tidak menggemakan data pribadi.
- AI Gateway menggunakan respons HTTP tiruan: schema/JSON object, pemilihan model, penolakan field aksi/duplikat/confidence tidak valid, refusal/timeout/error. Kegagalan tidak memunculkan data dummy atau mengubah draft lama.
- Regresi asisten lama termasuk OCR Tesseract terhadap fixture; jalur ini terpisah dari simulasi v1.

Suite JavaScript meliputi validasi lima fase dan modal transaksi, dokumen perwakilan korban, parsing rupiah, lampiran/tanggal, isian manual yang dipertahankan, pembersihan metadata, pemetaan payload v1 ke replika, tanggal Indonesia, dan masa berlaku object URL bukti yang dipakai bersama, dan round-trip nominal pecahan dua desimal dari payload ke modal. Test tidak menghubungi IASC.

## Pemeriksaan browser pada versi ini

- Beranda, formulir lima fase, dan widget iframe dimuat dari server lokal.
- Empat bukti dummy diproses dalam mode simulasi berlabel; ini bukan OCR nyata pada alur v1.
- Quick reply nomor HP dan email melengkapi dua slot; kartu ringkasan dapat dibuka untuk melihat kelima tahap.
- Koreksi nominal `-10` ditolak dan nilai draft tetap utuh; koreksi sah `100000` diterima.
- Konfirmasi ringkasan diikuti simulasi e-KYC berhasil mencapai `STATE_5_DISPATCH_FREEZE`; tantangan CAPTCHA lokal tampil.
- Pengujian browser sengaja berhenti **sebelum persetujuan, pengisian CAPTCHA, dan auto-fill**. Penerapan bridge penuh belum diverifikasi melalui browser. Mapping seluruh tahap/file dan kedua mode integrasi telah diperiksa melalui test JavaScript/API.
- Tombol Sesi baru menghapus sesi lama dan kembali ke unggah bukti; diperiksa melalui browser.
- Peluncur `bash start.sh` diuji; enam route utama mengembalikan HTTP 200 dan widget memakai CSP nonce.
- Iframe menggunakan izin `allow-forms` agar submit jawaban chat dapat diproses. Tidak ada laporan resmi yang dikirim.

## Yang belum diuji

- Provider/model cloud atau on-premise nyata, passive liveness/keaslian KTP nyata, dan backend ASP.NET IASC.
- Seluruh variasi struk bank, katalog kota/bank resmi lengkap, PDF extraction, audio/voice transcription, dan laporan perwakilan dengan surat kuasa.
- Waktu pengisian di bawah 45 detik, akurasi operasional, peluang intersepsi dana, beban produksi, dan ketahanan multi-worker.
- Kesamaan UI setiap piksel atau seluruh perangkat/browser. Replika mengikuti acuan tampilan, bukan kontrak resmi yang terverifikasi.

Runtime tetap lokal dan tidak mempunyai integrasi pemblokiran dana, amount ring-fencing, ataupun multi-hop tracing. Penanda `verified` pada e-KYC dan tiket mock selalu disertai konteks simulasi; keduanya bukan bukti verifikasi/pelaporan resmi.
