# Hasil verifikasi PoC — 24 Oktober 2026

Entry point `main:app`, Python 3.14.4 pada macOS. Uji cloud hanya memakai fixture dummy. Contoh KTP pengguna diproses lokal; gambar/nilai identitas tidak disimpan dalam repository. Tidak ada pengiriman laporan ke IASC atau tindakan bank.

## Pengujian otomatis

| Suite | Hasil |
| --- | --- |
| Python: `.venv/bin/python -m pytest -q` | **234 lulus, 522 subtest lulus** |
| JavaScript: `node --test tests/*.test.mjs` | **27 lulus, 0 gagal** |

Python meliputi:

- Urutan state percakapan dari status pelapor sampai tiket lokal; server menentukan jenis unggahan tunggal dan menolak lompatan tahap.
- Ekstraksi nomor HP/email dari satu jawaban alami, prefix Indonesia, kontak parsial, nomor di alamat email, dan penolakan kontak ambigu.
- Sintesis kronologi AI dari cerita, fakta chat, terlapor/media, dan transaksi, dengan timestamp kejadian tetap ditentukan lokal. Kronologi AI diperbarui pada ringkasan akhir; koreksi manual dilindungi.
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
- Gateway HTTP tiruan: JSON object dan temperature 0,7, pemilihan model, field terlarang/duplikat, confidence invalid, refusal/timeout/error. Kegagalan provider tidak beralih ke dummy.
- Sumopod: URL/Authorization/model/JSON object, ID Gemini lengkap, confidence yang hilang menjadi 0 untuk konfirmasi manusia, serta error model/izin/kuota tanpa membocorkan respons provider.
- KTP: Tesseract dan parser lokal; endpoint memanggil OCR langsung tanpa memasuki gateway. Gateway menolak jenis `ktp` pada semua mode serta KTP dummy yang disamarkan sebagai setiap jenis bukti lain. Field valid tetap tersimpan bila field lain tidak terbaca; bacaan bertentangan memerlukan konfirmasi.
- Privasi: nama, NIK, rekening, kontak, alamat, biodata dari konteks, referensi, serta rahasia berlabel dimasking. Token asing/rusak/tidak pernah dikirim ditolak. Konteks sintesis kronologi mengecualikan biodata KTP/CAPTCHA dan menghapus token biodata/rahasia sebelum HTTP. Token pribadi yang relevan dipulihkan lokal setelah validasi.
- Jawaban pribadi yang jelas tetap lokal, termasuk nama huruf kecil tanpa label. Kalimat yang memerlukan interpretasi memakai token masking; model hanya boleh memilih tepat satu token yang diterbitkan, tanpa menambah nama/nomor. API chat lama tetap lokal.

Node meliputi validasi fase/modal, dokumen perwakilan, parsing nominal dan tanggal, mapping payload lama, shared object URL, serta mapping progresif untuk radio/dropdown/tanggal/file dan koleksi bersarang. Cakupan progresif juga meliputi path/revisi tidak sah, sesi lama, Decimal tanpa kehilangan presisi, konflik manual, reset isian AI saat sesi baru, dan gate hasil simulasi untuk consent/CAPTCHA. Tes tidak menghubungi IASC.

## Kronologi AI dan temperature 0,7 — 24 Oktober

- Perilaku lama direproduksi: mode remote mengembalikan cerita pengguna persis tanpa memanggil AI. Tes baru gagal sebelum perubahan, lalu lulus untuk sintesis dari cerita dan konteks yang dimasking.
- Vision bukti chat kini mengembalikan metadata `evidence_facts` terbatas (maksimal delapan fakta/kutipan, 500 karakter per fakta). Penanda privasi dikembalikan ke nilai lokal sebelum fakta disimpan privat pada sesi; regresi token yang tidak dipulihkan direproduksi dan diperbaiki.
- Cerita asli disimpan privat. Sintesis awal menggunakan fakta yang tersedia pada Tahap 3, lalu diperbarui saat melanjutkan dari bukti transfer ke Tahap 5. Koreksi fakta pada ringkasan memperbarui kronologi AI; koreksi manual pada kronologi tidak ditimpa. Kegagalan API mempertahankan data, revisi, state, cerita asli, dan fakta bukti.
- Output hanya boleh berisi satu field kronologi dalam JSON, maksimal 4.000 karakter. Field tambahan, balasan obrolan bebas, nominal/waktu/identitas baru yang terdeteksi, token palsu/rahasia, serta beberapa kejadian dan pembalikan negasi yang tidak didukung ditolak. Timestamp kejadian tidak diserahkan ke model. Confidence rendah tidak dinaikkan otomatis.
- Pemeriksaan nominal dan waktu membandingkan nilai bertipe, bukan sekadar digit. Regresi mencakup transfer sah yang hanya terbukti dari baris transaksi lengkap, metadata confidence yang salah terbaca sebagai jam, format nominal berbeda, pemulihan token, privasi outbound, serta perlindungan koreksi manual.
- **Uji Sumopod nyata, temperature 0,7:** fixture chat/rekening/transfer menghasilkan 6/3/6 field; chat menghasilkan enam fakta. Sintesis awal dan akhir berhasil menghasilkan 511/616 karakter dari cerita singkat; hasil akhir mencakup terlapor, WhatsApp, rekening BNI/BCA, dan rincian transfer. Uji memakai data dummy tanpa submit/CAPTCHA. Respons model tertentu ditolak pemeriksaan fakta; heuristik dan prompt tidak menjamin semua keluaran benar atau selalu diterima.
- Uji alur aplikasi menemukan penolakan palsu pada format jam Indonesia `10.00.00`. Regresi direproduksi sebelum perbaikan parser bersama; hasil live yang sebelumnya ditolak kini lolos pemeriksaan fakta. **ASGI dengan Sumopod nyata** kemudian berhasil: status → KTP dummy lokal → kontak → vision chat → kronologi awal → lewati laporan polisi → vision rekening/transfer → kronologi akhir → `FINAL_CONFIRMATION`. Kronologi awal/akhir 413/499 karakter; cerita asli tetap tersimpan, sumber `chronology_ai`, S&K belum disetujui, `submitted:false`, CAPTCHA tidak dijawab. Sesi pengujian dihapus.
- Tepat empat nama tugas tetap dipertahankan; sintesis hanya memakai `extract_report_fields` pada jalur kronologi khusus. Tidak ada dependensi baru. Browser belum diulang; alur/progressive-fill tercakup tes API dan Node.

## Riwayat bukti dan jawaban natural — 24 Oktober (sebelum sintesis kronologi)

- Akar masalah direproduksi sebelum perbaikan: vision tidak berjalan saat teks OCR kosong, hasil nama/rekening dibuang bila tidak cocok dengan OCR yang keliru, serta kutipan perintah penipu menolak seluruh bukti. Tes baru gagal pada perilaku lama lalu lulus setelah perbaikan. Mesin OCR yang gagal tetap menghentikan forwarding; hasil OCR kosong kini dapat dilanjutkan ke vision gambar. KTP tetap ditolak gateway.
- Parser nominal menerima `320 ribu`, `320rb`, `1,5 juta`, serta format ribuan/desimal yang jelas dengan Decimal. Nilai negatif, pecahan terlalu kecil, ambigu, dan mata uang asing tidak diam-diam menjadi rupiah.
- Tanggal/jam bisa diberikan terpisah. `jam 10 pagi` disimpan sementara dan meminta tanggal; tanggal lengkap kemudian mengisi kolom. Koreksi jam memakai tanggal yang sudah diketahui, transaksi tidak meminjam tanggal kejadian, tanggal tidak valid ditolak, dan hari ini tidak diasumsikan.
- Kalimat lain dapat memakai interpretasi JSON satu kolom aktif, bukan dibatasi dua contoh parser: nominal dalam kata-kata, alias bank panjang, dan ungkapan waktu. Pertanyaan bantuan tetap tidak disimpan sebagai nilai. Prompt injection dan penolakan menjaga draft serta komponen tanggal/jam sementara.
- Output semantik tetap dibatasi field/skema. Identitas dalam kalimat dimasking; nama karangan, penanda palsu, atau tambahan teks setelah token ditolak. Regresi tambahan direproduksi sebelum perbaikan untuk waktu lama yang menimpa koreksi baru dan nominal USD yang salah dianggap rupiah.
- **Uji Sumopod nyata, temperature 0,3:** gambar chat dan transfer dummy masing-masing **6/6 field sesuai**, dengan teks OCR lokal sengaja dikosongkan untuk menguji pembacaan piksel. Nominal `tiga ratus dua puluh ribu rupiah` menjadi 320000, kalimat PT Bank Central Asia menjadi BCA, dan `sekitar setengah sepuluh pagi` menjadi jam 09:30 tanpa mengarang tanggal. Nama dummy dalam kalimat dipilih melalui token masking dan dipulihkan lokal setelah prompt menjelaskan hubungan jawaban dengan kolom yang sedang ditanyakan. Semua pengujian memakai fixture/teks dummy, tanpa submit/CAPTCHA.
- Pada pemeriksaan ini temperature masih 0,3. Perubahan sintesis terbaru di atas menggunakan 0,7 sesuai permintaan pengguna. Tidak ada dependensi baru. Pemeriksaan browser tidak diulang; regresi alur/progressive-fill diuji melalui API dan Node.

## Riwayat percakapan terlalu ketat dan bantuan empatik — 23 Oktober

Bagian ini mencatat perilaku saat itu; pembatasan OCR/vision di bawah telah diperbarui pada 24 Oktober.

- Penyebab direproduksi: OCR screenshot chat/struk sah tidak mengandung kata kunci pelaporan, sehingga vision tidak pernah dipanggil. Satu ketidakcocokan grounding tanggal/nominal juga membuang seluruh unggahan. Pertanyaan “nama pemilik rekening yang mana?” dapat tersimpan sebagai nama.
- Konteks jenis bukti dari state dipakai untuk vision; kata kunci tertentu tidak wajib. KTP/injeksi tetap diblokir. OCR kosong atau gagal menghasilkan ekstraksi kosong lokal, tanpa forwarding gambar, dengan file tersimpan dan pertanyaan kolom yang belum terisi.
- Ekstraksi bukti mempertahankan kolom valid dan mengosongkan hanya nilai yang tidak didukung sumber. Uji mencakup format nominal IDR/Indonesia/US/spasi, tanggal numerik dan singkatan bulan, serta pencegahan nominal/tanggal berubah menjadi nomor rekening.
- Sapaan, kepanikan, kebingungan, dan pertanyaan klarifikasi memakai template empatik sesuai tahap/kolom, tanpa gateway atau perubahan draft. Pertanyaan tidak menjadi nilai kolom. Penolakan disertai panduan melanjutkan; deskripsi pelaku yang berperan sebagai petugas tidak dianggap perintah mengganti peran asisten.
- “Boleh lanjut?”/“lanjutkan” bekerja pada pilihan bukti tambahan, sementara navigasi/action lama di tahap yang tidak sesuai tidak dapat mengisi nama atau melewati syarat. Kronologi tidak perlu kata kunci khusus; bank/media seperti “rekening saya BCA” dan “lewat WA” diparsing lokal.
- Widget menampilkan jawaban pada setiap unggahan, termasuk dua penolakan berturut-turut dengan snapshot identik, lalu mengaktifkan kembali kontrol.
- **Uji Sumopod nyata, temperature 0,3:** bukti chat dummy **6/6 field sesuai, 5,9 detik**; bukti transfer dummy **6/6 field sesuai, 2,8 detik**. Hanya fixture dummy, tanpa submit/CAPTCHA. Pengukuran satu kali, bukan benchmark.
- **Browser in-app lokal:** pesan panik → bantuan empatik → status pelapor → KTP dummy lokal mengisi 12 kolom → kontak → Tahap 2 → “saya bingung” → panduan unggah → bukti chat mengisi tabel → “boleh lanjut?” → Tahap 3 → kronologi tanpa kata “penipuan” diterima. Screenshot bantuan disimpan di luar repository. Pengujian berhenti sebelum penyelesaian; server/tab sementara dibersihkan.

## Security dan scope guardrails

- `services/guardrails.py` mengizinkan tepat empat tugas ekstraksi; tugas lain, penggunaan tugas bukti untuk field yang berbeda, forwarding data KTP, dan URL gambar eksternal ditolak sebelum HTTP.
- Pola injeksi Indonesia/Inggris, tag role, penyamaran Unicode/karakter kontrol, payload kode/script, serta permintaan di luar pelaporan seperti coding/politik ditolak secara deterministik. Sapaan dan bantuan terkait pengisian memakai template lokal. Pesan di atas 2.000 karakter ditolak dengan HTTP 422 tanpa API.
- Penolakan diuji pada beberapa state, termasuk konfirmasi dan selesai, serta pada `values`/`action`, upload, dan API lama: data, revisi, file, consent, tiket, dan state tetap; patch baru kosong. Gateway/API cloud lama dinonaktifkan.
- Schema Pydantic ketat menolak key asing, teks balasan bebas, JSON berkey duplikat, dan flag relevansi/injeksi tidak aman. Ekstraksi teks bukti dibandingkan dengan teks sumber; vision memakai piksel, sedangkan interpretasi jawaban memakai kontrak satu kolom aktif. Nomor rekening mempertahankan nol awal; angka tanggal/nominal tidak dapat dipakai sebagai rekening. Nominal asing tidak dikonversi dan komponen tanggal/jam yang tidak diketahui ditanyakan.
- Parsing tanggal/nominal eksplisit tetap lokal, termasuk Decimal besar dengan sen utuh. Kronologi asli dipertahankan privat; hasil sintesis AI hanya mengisi kolom kronologi dan pesan percakapan tetap berasal dari template server. Alur progressive-fill tercakup dalam suite penuh.
- Tesseract nyata memeriksa keempat fixture dummy; KTP dikenali, sedangkan tiga bukti lain lolos pemeriksaan relevansi. Respons vision tiruan kemudian diuji terhadap hasil OCR transfer nyata untuk memastikan fakta yang valid diterima.
- **Uji Sumopod nyata pada 22 Oktober**: vision `gemini/gemini-3.5-flash-lite` mengekstrak bukti transfer dummy, **6/6 field cocok, 4,7 detik**. Ekstraksi teks `deepseek-v4-flash` mengembalikan bank eksplisit yang benar, **1,6 detik**. Keduanya menerima temperature 0 saat itu, JSON object, serta flag relevansi/injeksi. Temperature 0,3 dan terbaru 0,7 diuji pada bagian di atas. Pengukuran sekali, bukan benchmark.
- Tidak ada data identitas nyata, request submit, jawaban CAPTCHA, atau tindakan bank pada uji cloud ini. Alur browser penuh tidak diulang untuk guardrail; pengujian API/state dan Node mencakup regresinya.

OCR dan pola bersifat heuristik: dapat menolak bukti sah dan tidak membuktikan kekebalan terhadap semua injeksi atau keaslian/pemilik bukti. Masking teks tidak menyamarkan piksel gambar non-KTP. Tinjauan manusia tetap diperlukan.

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

## Regresi chat berhenti pada detail media Tahap 2 (sebelum guardrail ketat)

- Penyebab direproduksi: hasil ekstraksi kosong menghasilkan respons sukses dengan revisi/pertanyaan tetap; widget menyembunyikan balasan sebagai duplikat. Nilai yang dibuang normalizer juga dapat menghasilkan keadaan ini.
- Server kini memberi penjelasan bila ekstraksi tidak mengisi kolom yang diminta, termasuk normalisasi kosong dan nilai manual yang dilindungi. Draft tetap atomik. Widget selalu menampilkan balasan untuk pesan baru, sedangkan pembacaan ulang status tetap menghindari duplikasi.
- Pertanyaan membedakan media (WhatsApp, Instagram, dll.) dari detail kontaknya. Nama media, nomor telepon, `@username`, dan URL eksplisit diparsing lokal. Pengulangan nama media tidak dimasukkan sebagai detail. Sapaan `halo` menampilkan panduan tanpa API AI; data yang tidak tersedia tidak ditebak.
- Lima tes Python baru dan dua tes Node baru mencakup ekstraksi kosong, normalizer yang membuang nilai, perlindungan isian manual, balasan identik berulang, error terlihat, pemulihan status, dan input eksplisit tanpa provider.
- Browser in-app diuji pada server sementara dengan fixture sesi parsial tahap 2: `whatsapp` → pertanyaan nomor/username/tautan → `whatsapp` lagi → penjelasan terlihat → `halo` → panduan terlihat → nomor dummy → pilihan lanjut Tahap 3. Screenshot disimpan sebagai artefak terpisah. Server/tab pengujian dibersihkan; tidak ada submit, CAPTCHA, atau panggilan Sumopod nyata pada regresi ini.

Pada guardrail 22 Oktober, sapaan `halo` sempat menerima penolakan scope tetap. Perbaikan 23 Oktober memulihkan bantuan lokal yang mengikuti tahap aktif; parser media/detail dan perbaikan tampilan balasan tetap berlaku.

## Diagnosis instalasi dari clone baru

- FastAPI `0.153.0` diverifikasi tersedia lewat metadata resmi PyPI. Uji virtualenv kosong dengan indeks resmi tetap mendapat `Connection reset by peer`; `curl` dan HTTP client ke PyPI juga mendapat reset. Ini kegagalan akses jaringan sebelum daftar versi terbaca, bukan bukti pin paket tidak tersedia.
- Peluncur mempertahankan konfigurasi indeks/proxy/sertifikat, menggunakan cache pip, timeout 60 detik dan lima retry. Pesan kegagalan memberi langkah diagnosis; versi dependensi tetap.
- Tiga tes peluncur memakai proses Python tiruan: instalasi gagal tidak memulai server atau menulis marker, percobaan ulang berhasil, peluncuran berikutnya melewati pip, perubahan requirements memicu instalasi, dan indeks/port kustom tetap berlaku. `bash -n start.sh` lulus.
- Instalasi nyata dari nol belum berhasil diverifikasi karena koneksi PyPI masih terputus. Server sementara dan direktori pengujian dibersihkan; tidak ada key AI atau data laporan yang dipakai.

## Pemeriksaan API Sumopod nyata sebelum guardrail ketat

- Key hanya berada pada `.env` yang diabaikan Git, mode berkas 600. Katalog key saat diagnosis memuat `gemini/gemini-3.5-flash-lite`, `deepseek-v4-flash`, dan `deepseek-flash`.
- Nama Gemini tanpa prefix ditolak HTTP 403. Dengan prefix benar, respons awal tidak menyertakan confidence per slot. Schema lengkap dan contoh confidence dalam prompt JSON object memperbaikinya. `json_schema` menghasilkan HTTP 400 dari upstream Gemini pada gateway ini.
- **Satu key yang sama berhasil untuk chat dan vision.** Tidak diperlukan key terpisah; izin model tetap mengikuti pengaturan akun/key.
- Gateway aplikasi membaca fixture `bukti_chat` (6/6 field sesuai, 4,4 detik), `bukti_rekening_korban` (3/3, 2,8 detik), dan `bukti_transfer` (6/6, 3,5 detik) melalui vision Gemini. Nomor rekening tetap memiliki nol awal. Pengukuran satu kali, bukan benchmark.
- Chat `deepseek-v4-flash` memproses narasi dummy yang telah dimasking; nama dan rekening asli dipulihkan di server, kronologi lolos validasi (15,2 detik pada satu percobaan).
- **Uji API aplikasi melalui ASGI pada 22 Oktober**: status pelapor → OCR KTP lokal → kontak → vision bukti chat → kronologi Sumopod dengan masking → lewati laporan polisi → vision bukti rekening → vision transfer → `FINAL_CONFIRMATION`, wizard tahap 5. `submitted:false`, tanpa request submit atau jawaban CAPTCHA. Tidak memakai respons provider tiruan.
- Pengujian browser penuh tidak diulang untuk perubahan ini. Target seluruh intake di bawah 45 detik belum diukur.

Hasil di bagian ini merupakan riwayat diagnosis; implementasi dan uji sintesis kronologi terbaru dicatat di atas.

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
