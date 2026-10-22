"""KTP pixels and text are processed locally, including partial unreadable cards."""

from io import BytesIO
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from PIL import Image

from services.image_processor import ImageProcessingError
from services.ktp_ocr import extract_ktp_locally


ROOT = Path(__file__).resolve().parents[1]


def synthetic_image():
    output = BytesIO()
    Image.new("RGB", (600, 400), "white").save(output, format="PNG")
    return output.getvalue()


class LocalKtpTests(unittest.TestCase):
    def extract(self, text):
        with patch("services.ktp_ocr.local_ocr_text", return_value=text) as ocr:
            result = extract_ktp_locally(synthetic_image())
        self.assertIn(ocr.call_count, (1, 2))
        self.assertEqual(result[0].keys(), result[1].keys())
        return result[0]

    def test_actual_ktp_labels_are_normalized_and_same_row_blood_type_is_ignored(self):
        values = self.extract("""
PROVINSI DKI JAKARTA
JAKARTA BARAT
NIK : 0000 0000-0000 0000
Nama : PELAPOR CONTOH
Tempat/Tgl Lahir : JAKARTA, 18-02-1986
Jenis Kelamin : PEREMPUAN Gol. Darah : B
Alamat : JL. CONTOH 7
RT/RW : 001/002
Kel/Desa : KELURAHAN CONTOH
Kecamatan : KECAMATAN CONTOH
Agama : ISLAM
Status Perkawinan : KAWIN
Pekerjaan : PEGAWAI SWASTA
Kewarganegaraan : WNI
Berlaku Hingga : 22-02-2017
JAKARTA BARAT
02-12-2012
""")
        expected = {
            "nama_pelapor": "PELAPOR CONTOH", "nomor_identitas": "0000000000000000",
            "tempat_lahir_pelapor": "JAKARTA", "tanggal_lahir_pelapor": "18 Februari 1986",
            "jenis_kelamin": "Perempuan", "agama_pelapor": "Islam",
            "pekerjaan_pelapor": "PEGAWAI SWASTA", "kewarganegaraan_pelapor": "Indonesia",
            "provinsi_domisili_pelapor": "DKI Jakarta", "kota_domisili_pelapor": "Kota Adm. Jakarta Barat",
            "alamat_pelapor": "JL. CONTOH 7, RT/RW 001/002, Kel/Desa KELURAHAN CONTOH, Kecamatan KECAMATAN CONTOH",
        }
        self.assertEqual(values, {"tahap1." + key: value for key, value in expected.items()})

    def test_canonical_fixture_labels_only_accept_identity_fields(self):
        values = self.extract("""
nama_pelapor: PELAPOR DUMMY
tahap1.tanggal_lahir_pelapor: 1 OKTOBER 1990
jenis_kelamin: laki-laki
agama_pelapor: PROTESTAN
jenis_identitas: KTP
nomor_identitas: 0000000000000000
provinsi_domisili_pelapor: DKI Jakarta
kota_domisili_pelapor: Kota Adm. Jakarta Pusat
alamat_pelapor: Jalan Contoh Nomor 1
apakah_mengalami_sendiri: Ya, saya sendiri
nomor_telepon_pelapor: 8000000000
tahap5.setuju_syarat_dan_ketentuan: true
""")
        self.assertEqual(values["tahap1.tanggal_lahir_pelapor"], "1 Oktober 1990")
        self.assertEqual(values["tahap1.agama_pelapor"], "Kristen")
        self.assertEqual(values["tahap1.jenis_kelamin"], "Laki-laki")
        self.assertEqual(values["tahap1.kota_domisili_pelapor"], "Kota Adm. Jakarta Pusat")
        self.assertNotIn("tahap1.apakah_mengalami_sendiri", values)
        self.assertNotIn("tahap1.nomor_telepon_pelapor", values)
        self.assertNotIn("tahap5.setuju_syarat_dan_ketentuan", values)

    def test_invalid_fields_do_not_destroy_partial_extraction(self):
        for nik in ("000000000000000", "00000000000000000", "000000000000000O", "00000000000000.0", "1e15"):
            with self.subTest(nik=nik):
                values = self.extract(f"Nama: PELAPOR DUMMY\nNIK: {nik}\nTempat/Tgl Lahir: JAKARTA, 31-02-1986\nAgama: TIDAK TERBACA")
                self.assertEqual(values["tahap1.nama_pelapor"], "PELAPOR DUMMY")
                self.assertNotIn("tahap1.nomor_identitas", values)
                self.assertNotIn("tahap1.tanggal_lahir_pelapor", values)
                self.assertNotIn("tahap1.agama_pelapor", values)

    def test_conflicting_readable_identity_values_need_human_confirmation(self):
        values = self.extract("Nama: PELAPOR SATU\nNama: PELAPOR DUA\nNama: PELAPOR SATU\nAgama: ISLAM")
        self.assertEqual(values, {"tahap1.agama_pelapor": "Islam"})

    def test_ocr_punctuation_on_labels_and_date_does_not_hide_valid_fields(self):
        values = self.extract("Tempat/Tgl Lahir_ : JAKARTA, 18-02-1986 .\n‘Agama: ISLAM\nAlamat: Jalan Contoh\nRTIRW: 001/002 garbage")
        self.assertEqual(values["tahap1.tempat_lahir_pelapor"], "JAKARTA")
        self.assertEqual(values["tahap1.tanggal_lahir_pelapor"], "18 Februari 1986")
        self.assertEqual(values["tahap1.agama_pelapor"], "Islam")
        self.assertEqual(values["tahap1.alamat_pelapor"], "Jalan Contoh")

    def test_unrecognized_location_is_left_for_chat_and_expiry_is_not_birth_date(self):
        values = self.extract("PROVINSI TIDAK TERBACA\nKOTA TIDAK TERBACA\nNama: PELAPOR DUMMY\nBerlaku Hingga: 22-02-2017")
        self.assertEqual(values, {"tahap1.nama_pelapor": "PELAPOR DUMMY"})

    def test_blank_ocr_has_no_demo_identity_fallback(self):
        self.assertEqual(self.extract("\n"), {})

    def test_local_body_crop_recovers_missing_values_and_marks_disagreements(self):
        full = "NIK: 0000000000000000\nNama: PELAPOR DUMMY\nTempat/Tgl Lahir: JAKARTA, tidak terbaca\nAlamat: Jalan Contoh!"
        crop = "NIK: 0000000000000000\nNama: PELAPOR DUMMY\nTempat/Tgl Lahir: JAKARTA, 18-02-1986\nAlamat: Jalan Contoh\nAgama: ISLAM"
        with patch("services.ktp_ocr.local_ocr_text", side_effect=[full, crop]) as ocr:
            values, confidence = extract_ktp_locally(synthetic_image())
        self.assertEqual(ocr.call_count, 2)
        self.assertEqual(values["tahap1.tanggal_lahir_pelapor"], "18 Februari 1986")
        self.assertEqual(values["tahap1.agama_pelapor"], "Islam")
        self.assertEqual(confidence["tahap1.alamat_pelapor"], 0.70)
        self.assertEqual(confidence["tahap1.tanggal_lahir_pelapor"], 0.85)

    def test_optional_crop_failure_preserves_first_pass_results(self):
        text = "NIK: 0000000000000000\nNama: PELAPOR DUMMY\nTempat/Tgl Lahir: JAKARTA, tidak terbaca"
        with patch("services.ktp_ocr.local_ocr_text", side_effect=[text, ImageProcessingError("OCR gagal")]):
            values, _ = extract_ktp_locally(synthetic_image())
        self.assertEqual(values["tahap1.nama_pelapor"], "PELAPOR DUMMY")

    def test_invalid_image_fails_before_starting_ocr(self):
        with patch("services.ktp_ocr.local_ocr_text") as ocr, self.assertRaises(ImageProcessingError):
            extract_ktp_locally(b"not an image")
        ocr.assert_not_called()

    @unittest.skipUnless(shutil.which("tesseract"), "Tesseract is not installed")
    def test_real_tesseract_reads_only_synthetic_repo_fixture(self):
        values, confidence = extract_ktp_locally((ROOT / "fixtures/v1/ktp.png").read_bytes())
        self.assertEqual(values["tahap1.nama_pelapor"], "PELAPOR DUMMY")
        self.assertEqual(values["tahap1.nomor_identitas"], "0000000000000000")
        self.assertEqual(values["tahap1.jenis_kelamin"], "Laki-laki")
        self.assertEqual(values["tahap1.tanggal_lahir_pelapor"], "1 Oktober 1990")
        self.assertEqual(values["tahap1.kota_domisili_pelapor"], "Kota Adm. Jakarta Pusat")
        self.assertEqual(values.keys(), confidence.keys())


if __name__ == "__main__":
    unittest.main()
