# Hasil verifikasi PoC — 21 Oktober 2026

Entry point `main:app`, Python 3.14.4 pada macOS. Seluruh data pengujian fiktif. Tidak ada pengiriman laporan ke IASC atau tindakan bank.

## Pengujian otomatis

| Suite | Hasil |
| --- | --- |
| Python: `.venv/bin/python -m pytest -q` | **70 lulus, 65 subtest lulus** |
| JavaScript: `node --test tests/*.test.mjs` | **24 lulus, 0 gagal** |

Python meliputi:

- Urutan state percakapan dari status pelapor sampai tiket lokal; server menentukan jenis unggahan tunggal dan menolak lompatan tahap.
- Ekstraksi nomor HP/email dari satu jawaban alami, prefix Indonesia, kontak parsial, nomor di alamat email, dan penolakan kontak ambigu.
- Kronologi berdasarkan cerita pengguna, tanggal/jam eksplisit, permintaan waktu yang belum disebut, serta penolakan tanggal yang ditambahkan AI.
- Lampiran laporan polisi opsional atau dilewati; bukti chat dipakai ulang dan chat tambahan menambah baris dengan file yang sesuai.
- Transfer tambahan menambah rincian pada penerima yang sama atau menambah penerima baru tanpa menghapus transaksi lama.
- Confidence di bawah 0,85 menahan alur; konfirmasi manusia memperbarui confidence. Ketidakpastian chat remote dipertahankan.
- Patch leaf per respons, file atomik, nomor/rekening tetap string, nominal Decimal, serta GET snapshot untuk resinkronisasi.
- Koreksi atomik, pemeliharaan koreksi manual, pembatalan tiket/consent setelah koreksi, dan rollback seluruh unggahan bila gambar/provider gagal.
- Validasi model lima tahap, ringkasan bersarang, batas lampiran 1/2 MiB, tanggal Indonesia, nominal positif/finite, dan auto-copy kontak.
- Kompresi di bawah 900.000 byte, penghapusan metadata, tipe palsu, gambar rusak/animasi/terlalu besar, dan batas resolusi.
- Kepemilikan file per sesi, penolakan metadata palsu, expiry/penghapusan/kapasitas sesi, origin/host, batas permintaan, dan error tanpa echo data pribadi.
- Jawaban CAPTCHA lokal melalui chat membuat tiket `SIM-…` tanpa akses jaringan; persetujuan eksplisit pada adapter, lima percobaan salah, dan hasil idempoten.
- Adapter DOM/webhook mock, penolakan endpoint eksternal, e-KYC tiruan opsional, serta regresi API/asisten lama.
- Gateway HTTP tiruan: schema/JSON object, pemilihan model, field terlarang/duplikat, confidence invalid, refusal/timeout/error. Kegagalan tidak beralih ke dummy.
- Sumopod: URL/Authorization/model/JSON object, OCR lokal mengirim teks ke model chat tanpa gambar, serta OCR kosong/gagal menghentikan permintaan sebelum provider.

Node meliputi validasi fase/modal, dokumen perwakilan, parsing nominal dan tanggal, mapping payload lama, shared object URL, serta mapping progresif untuk radio/dropdown/tanggal/file dan koleksi bersarang. Cakupan progresif juga meliputi path/revisi tidak sah, sesi lama, Decimal tanpa kehilangan presisi, konflik manual, reset isian AI saat sesi baru, dan gate hasil simulasi untuk consent/CAPTCHA. Tes tidak menghubungi IASC.

## Pemeriksaan browser versi percakapan

- Chat memiliki satu lampiran dan satu input teks; quick reply status memulai unggah KTP dummy. Biodata terlihat mengisi radio, tanggal, dropdown dan kolom teks satu per satu; badge melaporkan 12 field yang benar-benar berubah.
- Satu balasan natural nomor HP dan email mengisi empat kolom kontak/konfirmasi, lalu wizard otomatis pindah ke Tahap 2.
- Bukti chat menambah baris terlapor dan media beserta lampiran. Cerita khusus penguji tentang tas dipertahankan pada kronologi Tahap 3, tanggal/jam eksplisit terisi, dan bukti komunikasi dipakai ulang.
- Opsi lewati laporan polisi membuka Tahap 4. Bukti rekening mengisi bank, nomor, pemilik, dan lampiran. Dua unggahan transfer (satu melalui pemilih file) menghasilkan dua rincian Rp100.000 pada penerima yang sama; ringkasan menunjukkan Rp200.000.
- Tahap 5 menampilkan ringkasan di host dan kartu chat. Persetujuan tetap belum dicentang, jawaban CAPTCHA kosong, dan tombol kirim resmi dinonaktifkan. Pengujian browser berhenti sebelum menjawab CAPTCHA/penyelesaian; tiket lokal lengkap diuji melalui API dan mapping Node, bukan klik browser.
- Sesi baru membersihkan nama/lampiran hasil AI dan mengunci ulang tahap berikutnya, sambil mempertahankan pekerjaan yang diedit manual.
- Lampiran pada input native tetap terpasang setelah berpindah tahap dan kembali; diperiksa melalui nilai kontrol file setelah perbaikan render ulang.
- Screenshot kelima tahap lokal disimpan sebagai artefak pengujian terpisah. Pemeriksaan ini memakai browser in-app pada ukuran default; belum mencakup seluruh perangkat.

Satu warning deprecation Starlette/httpx muncul pada pytest; tidak ada tes gagal.

## Pemeriksaan API Sumopod nyata

- Key hanya berada pada `.env` yang diabaikan Git. `/v1/models` merespons HTTP 200; model yang tersedia pada key pengujian adalah `deepseek-flash`, `deepseek-v4-flash`, dan `deepseek-v4-flash-vision-exp`.
- Chat `deepseek-v4-flash` menghasilkan ekstraksi nama dummy yang lolos validasi. `gpt-4o-mini` tidak tersedia pada key tersebut.
- Model vision eksperimental merespons HTTP 401 dengan error autentikasi upstream. Dua alias teks menerima request gambar tetapi tidak mengekstrak field; ini tidak dianggap pembacaan gambar yang berhasil.
- Konfigurasi eksplisit `VISION_INPUT_MODE=ocr_text` memakai Tesseract lokal lalu `deepseek-v4-flash`. KTP dummy menghasilkan 13 field dan nama yang sesuai fixture; bukti transfer menghasilkan 6 field. Respons nyata ini bukan data simulasi terprogram.
- Browser dimuat ulang dengan koneksi Sumopod aktif: label Asisten AI tampil, KTP diunggah melalui lampiran tunggal, biodata otomatis terisi, dan chat meminta kontak setelah host mengonfirmasi pengisian.
- Satu percobaan KTP melewati timeout 35 detik; pengulangan berhasil dalam 19,6 detik. Contoh konfigurasi memakai timeout 60 detik. Target seluruh intake di bawah 45 detik belum terbukti.

## Yang belum diuji

- Provider/model selain uji Sumopod terbatas di atas, on-premise, passive liveness/keaslian KTP, dan backend ASP.NET IASC.
- Seluruh variasi struk bank, master kota/bank resmi lengkap, ekstraksi PDF, audio/transkripsi, dan verifikasi perwakilan/surat kuasa.
- Target di bawah 45 detik, akurasi operasional, peluang intersepsi dana, beban produksi, dan ketahanan multi-worker.
- Kesamaan UI setiap piksel atau semua perangkat/browser. Replika mengikuti acuan tampilan dan belum menjadi kontrak resmi terverifikasi.

Runtime tetap lokal, satu worker, dengan sesi/file di memori. Tiket `SIM-…`, hasil e-KYC, consent, dan CAPTCHA di sini merupakan simulasi; tidak membuktikan pelaporan resmi, verifikasi identitas, pemblokiran dana, ring-fencing, ataupun multi-hop tracing.
