# Hasil verifikasi PoC — 22 Oktober 2026

Entry point `main:app`, Python 3.14.4 pada macOS. Uji cloud hanya memakai fixture dummy. Contoh KTP pengguna diproses lokal; gambar/nilai identitas tidak disimpan dalam repository. Tidak ada pengiriman laporan ke IASC atau tindakan bank.

## Pengujian otomatis

| Suite | Hasil |
| --- | --- |
| Python: `.venv/bin/python -m pytest -q` | **122 lulus, 130 subtest lulus** |
| JavaScript: `node --test tests/*.test.mjs` | **26 lulus, 0 gagal** |

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
- Sumopod: URL/Authorization/model/JSON object, ID Gemini lengkap, confidence yang hilang menjadi 0 untuk konfirmasi manusia, serta error model/izin/kuota tanpa membocorkan respons provider.
- KTP: Tesseract dan parser lokal; gambar maupun OCR KTP tidak memanggil HTTP, pada mode `image` maupun `ocr_text`. Field valid tetap tersimpan bila field lain tidak terbaca; bacaan bertentangan memerlukan konfirmasi.
- Privasi: nama, NIK, rekening, kontak, alamat, biodata dari konteks, referensi, serta rahasia berlabel dimasking dan dipulihkan lokal. Token asing/rusak/tidak pernah dikirim ditolak; kronologi harus mempertahankan penanda. Nomor di samping tanggal tetap disamarkan dan alamat tidak menelan nominal/waktu kejadian.
- Koreksi satu kolom pribadi pada API v1 dan API chat lama tetap lokal, termasuk jawaban nama huruf kecil tanpa label.

Node meliputi validasi fase/modal, dokumen perwakilan, parsing nominal dan tanggal, mapping payload lama, shared object URL, serta mapping progresif untuk radio/dropdown/tanggal/file dan koleksi bersarang. Cakupan progresif juga meliputi path/revisi tidak sah, sesi lama, Decimal tanpa kehilangan presisi, konflik manual, reset isian AI saat sesi baru, dan gate hasil simulasi untuk consent/CAPTCHA. Tes tidak menghubungi IASC.

## Pemeriksaan browser versi percakapan sebelumnya (20–21 Oktober)

- Chat memiliki satu lampiran dan satu input teks; quick reply status memulai unggah KTP dummy. Biodata terlihat mengisi radio, tanggal, dropdown dan kolom teks satu per satu; badge melaporkan 12 field yang benar-benar berubah.
- Satu balasan natural nomor HP dan email mengisi empat kolom kontak/konfirmasi, lalu wizard otomatis pindah ke Tahap 2.
- Bukti chat menambah baris terlapor dan media beserta lampiran. Cerita khusus penguji tentang tas dipertahankan pada kronologi Tahap 3, tanggal/jam eksplisit terisi, dan bukti komunikasi dipakai ulang.
- Opsi lewati laporan polisi membuka Tahap 4. Bukti rekening mengisi bank, nomor, pemilik, dan lampiran. Dua unggahan transfer (satu melalui pemilih file) menghasilkan dua rincian Rp100.000 pada penerima yang sama; ringkasan menunjukkan Rp200.000.
- Tahap 5 menampilkan ringkasan di host dan kartu chat. Persetujuan tetap belum dicentang, jawaban CAPTCHA kosong, dan tombol kirim resmi dinonaktifkan. Pengujian browser berhenti sebelum menjawab CAPTCHA/penyelesaian; tiket lokal lengkap diuji melalui API dan mapping Node, bukan klik browser.
- Sesi baru membersihkan nama/lampiran hasil AI dan mengunci ulang tahap berikutnya, sambil mempertahankan pekerjaan yang diedit manual.
- Lampiran pada input native tetap terpasang setelah berpindah tahap dan kembali; diperiksa melalui nilai kontrol file setelah perbaikan render ulang.
- Screenshot kelima tahap lokal disimpan sebagai artefak pengujian terpisah. Pemeriksaan ini memakai browser in-app pada ukuran default; belum mencakup seluruh perangkat.

Satu warning deprecation Starlette/httpx muncul pada pytest; tidak ada tes gagal.

## Regresi chat berhenti pada detail media Tahap 2

- Penyebab direproduksi: hasil ekstraksi kosong menghasilkan respons sukses dengan revisi/pertanyaan tetap; widget menyembunyikan balasan sebagai duplikat. Nilai yang dibuang normalizer juga dapat menghasilkan keadaan ini.
- Server kini memberi penjelasan bila ekstraksi tidak mengisi kolom yang diminta, termasuk normalisasi kosong dan nilai manual yang dilindungi. Draft tetap atomik. Widget selalu menampilkan balasan untuk pesan baru, sedangkan pembacaan ulang status tetap menghindari duplikasi.
- Pertanyaan membedakan media (WhatsApp, Instagram, dll.) dari detail kontaknya. Nama media, nomor telepon, `@username`, dan URL eksplisit diparsing lokal. Pengulangan nama media tidak dimasukkan sebagai detail. Sapaan `halo` menampilkan panduan tanpa API AI; data yang tidak tersedia tidak ditebak.
- Lima tes Python baru dan dua tes Node baru mencakup ekstraksi kosong, normalizer yang membuang nilai, perlindungan isian manual, balasan identik berulang, error terlihat, pemulihan status, dan input eksplisit tanpa provider.
- Browser in-app diuji pada server sementara dengan fixture sesi parsial tahap 2: `whatsapp` → pertanyaan nomor/username/tautan → `whatsapp` lagi → penjelasan terlihat → `halo` → panduan terlihat → nomor dummy → pilihan lanjut Tahap 3. Screenshot disimpan sebagai artefak terpisah. Server/tab pengujian dibersihkan; tidak ada submit, CAPTCHA, atau panggilan Sumopod nyata pada regresi ini.

## Diagnosis instalasi dari clone baru

- FastAPI `0.153.0` diverifikasi tersedia lewat metadata resmi PyPI. Uji virtualenv kosong dengan indeks resmi tetap mendapat `Connection reset by peer`; `curl` dan HTTP client ke PyPI juga mendapat reset. Ini kegagalan akses jaringan sebelum daftar versi terbaca, bukan bukti pin paket tidak tersedia.
- Peluncur mempertahankan konfigurasi indeks/proxy/sertifikat, menggunakan cache pip, timeout 60 detik dan lima retry. Pesan kegagalan memberi langkah diagnosis; versi dependensi tetap.
- Tiga tes peluncur memakai proses Python tiruan: instalasi gagal tidak memulai server atau menulis marker, percobaan ulang berhasil, peluncuran berikutnya melewati pip, perubahan requirements memicu instalasi, dan indeks/port kustom tetap berlaku. `bash -n start.sh` lulus.
- Instalasi nyata dari nol belum berhasil diverifikasi karena koneksi PyPI masih terputus. Server sementara dan direktori pengujian dibersihkan; tidak ada key AI atau data laporan yang dipakai.

## Pemeriksaan API Sumopod nyata

- Key hanya berada pada `.env` yang diabaikan Git, mode berkas 600. Katalog key saat diagnosis memuat `gemini/gemini-3.5-flash-lite`, `deepseek-v4-flash`, dan `deepseek-flash`.
- Nama Gemini tanpa prefix ditolak HTTP 403. Dengan prefix benar, respons awal tidak menyertakan confidence per slot. Schema lengkap dan contoh confidence dalam prompt JSON object memperbaikinya. `json_schema` menghasilkan HTTP 400 dari upstream Gemini pada gateway ini.
- **Satu key yang sama berhasil untuk chat dan vision.** Tidak diperlukan key terpisah; izin model tetap mengikuti pengaturan akun/key.
- Gateway aplikasi membaca fixture `bukti_chat` (6/6 field sesuai, 4,4 detik), `bukti_rekening_korban` (3/3, 2,8 detik), dan `bukti_transfer` (6/6, 3,5 detik) melalui vision Gemini. Nomor rekening tetap memiliki nol awal. Pengukuran satu kali, bukan benchmark.
- Chat `deepseek-v4-flash` memproses narasi dummy yang telah dimasking; nama dan rekening asli dipulihkan di server, kronologi lolos validasi (15,2 detik pada satu percobaan).
- **Uji API aplikasi melalui ASGI pada 22 Oktober**: status pelapor → OCR KTP lokal → kontak → vision bukti chat → kronologi Sumopod dengan masking → lewati laporan polisi → vision bukti rekening → vision transfer → `FINAL_CONFIRMATION`, wizard tahap 5. `submitted:false`, tanpa request submit atau jawaban CAPTCHA. Tidak memakai respons provider tiruan.
- Pengujian browser penuh tidak diulang untuk perubahan ini. Target seluruh intake di bawah 45 detik belum diukur.

## Regresi validasi OCR KTP

- Nilai `PEREMPUAN`, `ISLAM`, `ktp`, `WNI`, serta tanggal `18-02-1986`, `18/02/1986`, ISO dan bulan Indonesia dengan kapitalisasi/angka hari berbeda kini dinormalkan sebelum validasi kontrak.
- Ekstraksi dokumen mempertahankan field valid dan lampirannya ketika field lain tidak valid. Alur upload → pertanyaan NIK yang belum terbaca → koreksi lokal lewat chat diperiksa melalui ASGI, dengan larangan HTTP untuk KTP dan koreksi tersebut.
- NIK numerik, notasi desimal/ilmiah, karakter huruf yang menyerupai angka, dan panjang selain 16 digit tidak dipaksakan menjadi NIK valid. Confidence rendah tetap meminta konfirmasi. Path terlarang, duplikat dan envelope rusak tetap ditolak; validasi chat/manual tetap ketat.
- JPEG contoh pengguna dibaca oleh Tesseract dan parser lokal nyata: 11 kolom terdeteksi, termasuk tempat/tanggal lahir, jenis kelamin, agama, dan wilayah. Bacaan yang bertentangan diberi confidence 0,70 untuk konfirmasi. Foto/hasil OCR tidak dikirim ke provider dan tidak dimasukkan ke repository.
- Confidence OCR lokal merupakan heuristik, bukan probabilitas yang telah dikalibrasi. Parser tidak menebak digit NIK, membaca tanggal penerbitan sebagai tanggal lahir, atau memverifikasi keaslian identitas.

## Yang belum diuji

- Provider/model selain uji Sumopod terbatas di atas, on-premise, passive liveness/keaslian KTP, dan backend ASP.NET IASC.
- Seluruh variasi struk bank, master kota/bank resmi lengkap, ekstraksi PDF, audio/transkripsi, dan verifikasi perwakilan/surat kuasa.
- Target di bawah 45 detik, akurasi operasional, peluang intersepsi dana, beban produksi, dan ketahanan multi-worker.
- Kesamaan UI setiap piksel atau semua perangkat/browser. Replika mengikuti acuan tampilan dan belum menjadi kontrak resmi terverifikasi.
- Masking berbasis pola/konteks tidak menjamin deteksi semua nama/alamat baru tanpa label. Masking teks tidak mengubah piksel bukti non-KTP yang dikirim ke vision; gunakan gambar dummy atau yang telah disamarkan.

Runtime tetap lokal, satu worker, dengan sesi/file di memori. Tiket `SIM-…`, hasil e-KYC, consent, dan CAPTCHA di sini merupakan simulasi; tidak membuktikan pelaporan resmi, verifikasi identitas, pemblokiran dana, ring-fencing, ataupun multi-hop tracing.
