import copy
from decimal import Decimal
import unittest

from pydantic import ValidationError

from schemas import FileMetadata, LaporanIASC, Tahap1InformasiPihakPelapor, to_indonesian_date, validate_slot_value
from services.normalizer import normalize_bank, normalize_location, normalize_media


def metadata(size=1000):
    return {"file_id": "a" * 32, "filename": "dummy.jpg", "content_type": "image/jpeg", "size_bytes": size, "sha256": "b" * 64, "url": "/api/v1/session/" + "c" * 32 + "/files/" + "a" * 32}


def valid_payload():
    return {
        "tahap1": {
            "apakah_mengalami_sendiri": "Ya, saya sendiri", "upload_kartu_identitas_korban": metadata(),
            "jenis_kelamin": "Laki-laki", "nama_pelapor": "PELAPOR DUMMY", "tempat_lahir_pelapor": "Jakarta",
            "tanggal_lahir_pelapor": "1 Oktober 1990", "agama_pelapor": "Islam", "pekerjaan_pelapor": "Karyawan",
            "nomor_telepon_pelapor": "08000000000", "email_pelapor": "dummy@example.com", "nomor_identitas": "0000000000000001",
            "provinsi_domisili_pelapor": "DKI Jakarta", "kota_domisili_pelapor": "Kota Adm. Jakarta Pusat", "alamat_pelapor": "ALAMAT DUMMY",
        },
        "tahap2": {
            "daftar_informasi_terlapor": [{"nomor_terlapor": "08000000001", "nama_terlapor": "TERLAPOR DUMMY", "upload_bukti_komunikasi": metadata()}],
            "daftar_sumber_media_penipuan": [{"sumber_media_informasi_penipuan": "WhatsApp", "detail_sumber_media_informasi_penipuan": "https://example.invalid/dummy", "upload_bukti_sumber_media": metadata()}],
        },
        "tahap3": {"tanggal_dan_waktu_kejadian": "19 Oktober 2020 10:00", "kronologi_kejadian_penipuan": "SIMULASI: korban menerima tautan palsu dan mentransfer dana.", "upload_bukti_pendukung_kejadian": metadata()},
        "tahap4": {
            "nama_penyelenggara_layanan_korban": "BNI", "nomor_rekening_akun_korban": "0000000000", "bukti_kepemilikan_rekening_akun_korban": metadata(),
            "daftar_penyelenggara_terlapor": [{"nama_penyelenggara": "BCA", "nomor_rekening_akun": "0000000001", "nama_pemilik_rekening_akun": "TERLAPOR DUMMY", "daftar_rincian_transaksi": [{"waktu_transaksi": "19 Oktober 2020 10:00:00", "nominal_transaksi": 100000, "upload_bukti_pendukung_kejadian": metadata(), "extraction_confidence": 0.98}]}],
        },
        "tahap5": {
            "ringkasan_sumber_transaksi_korban": {"penyelenggara_layanan": "BNI", "pemilik_rekening": "PELAPOR DUMMY", "nomor_rekening_akun": "0000000000"},
            "ringkasan_lembaga_terlapor": [{"penyelenggara_layanan": "BCA", "pemilik_rekening": "TERLAPOR DUMMY", "nomor_rekening_akun": "0000000001"}],
            "setuju_syarat_dan_ketentuan": True, "captcha_question": "78 + 0 =", "captcha_answer": "78",
        },
    }


class SchemaContractTests(unittest.TestCase):
    def test_five_stage_contract_preserves_identifiers_and_autocopies(self):
        payload = valid_payload()
        original = copy.deepcopy(payload)
        model = LaporanIASC.model_validate(payload)
        self.assertEqual(payload, original)
        self.assertEqual(model.tahap1.nomor_identitas, "0000000000000001")
        self.assertEqual(model.tahap1.konfirmasi_nomor_telepon_pelapor, "08000000000")
        self.assertEqual(model.tahap1.konfirmasi_email_pelapor, "dummy@example.com")
        self.assertEqual(model.tahap4.nama_pemilik_rekening_akun_korban, "PELAPOR DUMMY")
        self.assertEqual(model.tahap4.daftar_penyelenggara_terlapor[0].daftar_rincian_transaksi[0].nominal_transaksi, Decimal("100000"))
        self.assertEqual(model.model_dump(mode="json")["tahap5"]["ringkasan_sumber_transaksi_korban"]["nomor_rekening_akun"], "0000000000")

    def test_mismatched_confirmations_are_not_overwritten(self):
        for field, bad in [("konfirmasi_nomor_telepon_pelapor", "08000000009"), ("konfirmasi_email_pelapor", "wrong@example.com")]:
            payload = valid_payload()["tahap1"]
            payload[field] = bad
            with self.subTest(field=field), self.assertRaises(ValidationError):
                Tahap1InformasiPihakPelapor.model_validate(payload)

    def test_independently_read_owner_is_not_replaced(self):
        payload = valid_payload()
        payload["tahap4"]["nama_pemilik_rekening_akun_korban"] = "OTHER OWNER"
        payload["tahap5"]["ringkasan_sumber_transaksi_korban"]["pemilik_rekening"] = "OTHER OWNER"
        self.assertEqual(LaporanIASC.model_validate(payload).tahap4.nama_pemilik_rekening_akun_korban, "OTHER OWNER")

    def test_file_limits_are_applied_to_each_stage(self):
        payload = valid_payload()
        payload["tahap1"]["upload_kartu_identitas_korban"] = metadata(1_048_577)
        with self.assertRaises(ValidationError):
            LaporanIASC.model_validate(payload)
        self.assertEqual(FileMetadata.model_validate(metadata(2_097_152)).size_bytes, 2_097_152)
        for bad in [metadata(2_097_153), metadata(0), {**metadata(), "size_bytes": True}, {**metadata(), "url": "https://example.com/evil"}, {**metadata(), "content_type": "text/html"}]:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                FileMetadata.model_validate(bad)
        self.assertEqual(FileMetadata.model_validate({**metadata(), "filename": "../dummy.jpg"}).filename, "dummy.jpg")

    def test_date_and_money_constraints(self):
        for value in [True, 0, -1, float("nan"), float("inf"), "100.001", "1.000.000"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_slot_value("tahap4.daftar_penyelenggara_terlapor.0.daftar_rincian_transaksi.0.nominal_transaksi", value)
        self.assertEqual(validate_slot_value("tahap4.daftar_penyelenggara_terlapor.0.daftar_rincian_transaksi.0.nominal_transaksi", "1000.25"), Decimal("1000.25"))
        payload = valid_payload()
        payload["tahap4"]["daftar_penyelenggara_terlapor"][0]["daftar_rincian_transaksi"][0]["nominal_transaksi"] = "1E+5"
        wire = LaporanIASC.model_validate(payload).model_dump(mode="json")
        self.assertEqual(wire["tahap4"]["daftar_penyelenggara_terlapor"][0]["daftar_rincian_transaksi"][0]["nominal_transaksi"], "100000")
        for value in ["31 Februari 2020", "2020-01-01", "1 Januari 2999"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_slot_value("tahap1.tanggal_lahir_pelapor", value)
        self.assertEqual(to_indonesian_date("2020-10-19T03:00:00Z", with_time=True, seconds=True), "19 Oktober 2020 10:00:00")
        with self.assertRaises(ValueError):
            to_indonesian_date("2020-10-19", with_time=True)

    def test_strict_consent_challenge_summary_and_collections(self):
        for value in [False, "true", 1]:
            payload = valid_payload()
            payload["tahap5"]["setuju_syarat_dan_ketentuan"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                LaporanIASC.model_validate(payload)
        for key, value in [("captcha_answer", "77"), ("ringkasan_lembaga_terlapor", []), ("unexpected", "value")]:
            payload = valid_payload()
            payload["tahap5"][key] = value
            with self.subTest(key=key), self.assertRaises(ValidationError):
                LaporanIASC.model_validate(payload)
        payload = valid_payload()
        payload["tahap5"]["ringkasan_sumber_transaksi_korban"]["nomor_rekening_akun"] = "9999999999"
        with self.assertRaises(ValidationError):
            LaporanIASC.model_validate(payload)

    def test_scalars_reject_numbers_for_identifiers_and_nested_replacement(self):
        self.assertEqual(validate_slot_value("tahap4.nomor_rekening_akun_korban", "0000000000"), "0000000000")
        for path, value in [("tahap4.nomor_rekening_akun_korban", 1234567890), ("tahap1", {}), ("tahap1.upload_kartu_identitas_korban", metadata()), ("tahap2.daftar_informasi_terlapor.100.nama_terlapor", "Dummy"), ("tahap1.unknown", "x")]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_slot_value(path, value)
        self.assertEqual(validate_slot_value("tahap1.agama_pelapor", "Protestan"), "Kristen")


class NormalizerTests(unittest.TestCase):
    def test_bank_aliases_and_unknowns(self):
        self.assertEqual(normalize_bank("PT BANK NEGARA INDONESIA (PERSERO) TBK"), "BNI")
        self.assertEqual(normalize_bank("BANK CENTRAL ASIA"), "BCA")
        self.assertEqual(normalize_bank("Mandiri"), "Bank Mandiri")
        self.assertIsNone(normalize_bank("BANK NEVER EXISTS"))

    def test_location_is_conservative_when_master_is_incomplete(self):
        self.assertEqual(normalize_location("JAKARTA PUSAT"), ("DKI Jakarta", "Kota Adm. Jakarta Pusat"))
        self.assertEqual(normalize_location("Kota Bandung", "Jawa Barat"), ("Jawa Barat", "Kota Bandung"))
        self.assertEqual(normalize_location("JAKARTA PUSAT", "Bali"), ("Bali", None))
        self.assertEqual(normalize_location("Atlantis"), (None, None))
        self.assertEqual(normalize_location("Paris", "Luar Negeri"), ("Luar Negeri", None))
        self.assertEqual(normalize_location("Kota Denpasar", "Bali"), ("Bali", None))

    def test_media_aliases_and_unknowns(self):
        self.assertEqual(normalize_media("WA"), "WhatsApp")
        self.assertEqual(normalize_media("IG"), "Instagram")
        self.assertEqual(normalize_media("web"), "Website")
        self.assertEqual(normalize_media("Tokopedia"), "Tokopedia")
        self.assertEqual(normalize_media("Media Lainnya"), "Media Lainnya")
        self.assertIsNone(normalize_media("Unknown social network"))


if __name__ == "__main__":
    unittest.main()
