import json
import unittest

from services.privacy import PrivacyError, PrivacyMasker, placeholders, sensitive_kind


class PrivacyMaskerTests(unittest.TestCase):
    def test_context_masks_identity_and_restores_nested_slots(self):
        context = {
            "tahap1.nama_pelapor": "PELAPOR CONTOH",
            "tahap1.nomor_identitas": "0000000000000000",
            "tahap1.nomor_telepon_pelapor": "81234567890",
            "tahap1.email_pelapor": "pelapor@example.test",
            "tahap1.alamat_pelapor": "Jl. Contoh No. 17, Jakarta",
            "tahap1.tanggal_lahir_pelapor": "18 Februari 1986",
            "tahap4.nomor_rekening_akun_korban": "0000123456",
            "tahap4.nama_pemilik_rekening_akun_korban": "PELAPOR CONTOH",
            "tahap3.tanggal_dan_waktu_kejadian": "19 Oktober 2026 10:00",
            "tahap4.daftar_penyelenggara_terlapor.0.daftar_rincian_transaksi.0.nominal_transaksi": 10000000,
        }
        masker = PrivacyMasker({"values": context})
        masked = masker.mask_text(json.dumps(context, ensure_ascii=False))
        for key, value in context.items():
            if key.startswith("tahap1") or "rekening_akun" in key:
                self.assertNotIn(value, masked)
        self.assertIn("19 Oktober 2026 10:00", masked)
        self.assertIn("10000000", masked)
        self.assertEqual(masker.restore(json.loads(masked)), context)
        self.assertEqual(masker.mask_text("PELAPOR CONTOH"), masker.mask_text("pelapor contoh"))

    def test_unknown_contacts_identifiers_and_labelled_names(self):
        masker = PrivacyMasker()
        text = "nama saya pelapor contoh, email pelapor@example.test, nomor hp +62 812-3456-7890, rekening 0001234567. NIK 0000000000000000"
        masked = masker.mask_text(text)
        for value in ("pelapor contoh", "pelapor@example.test", "+62 812-3456-7890", "0001234567", "0000000000000000"):
            self.assertNotIn(value, masked)
        self.assertEqual(masker.restore(masked), text)
        self.assertIn("nama saya [NAMA_", masked)

    def test_known_values_stay_private_when_json_escapes_quotes_and_newlines(self):
        context = {"reporter_name": 'pelapor "contoh"', "address": 'blok "a"\nlantai 2'}
        masker = PrivacyMasker(context)
        masked = masker.mask_text(json.dumps(context, ensure_ascii=False))
        self.assertNotIn("pelapor", json.loads(masked)["reporter_name"])
        self.assertNotIn("blok", json.loads(masked)["address"])
        self.assertEqual(masker.restore(json.loads(masked)), context)

    def test_narrative_preserves_money_incident_time_but_masks_personal_data(self):
        text = "Pada 19 Oktober 2026 10:00, saya transfer Rp10000000 ke rekening 1234567 atas nama Siti Aminah. Alamat saya Jalan Melati No 17, Bandung; tanggal lahir 18-02-1986."
        masker = PrivacyMasker()
        masked = masker.mask_text(text)
        self.assertIn("19 Oktober 2026 10:00", masked)
        self.assertIn("Rp10000000", masked)
        for value in ("1234567", "Siti Aminah", "Jalan Melati No 17, Bandung", "18-02-1986"):
            self.assertNotIn(value, masked)
        self.assertEqual(masker.restore(masked), text)

    def test_named_unknown_people_and_street_are_masked(self):
        masker = PrivacyMasker()
        text = "Saya dihubungi Bapak Dedi Santoso dan mengirim uang kepada Rina Kusuma. Lokasi Jalan Mawar 17."
        masked = masker.mask_text(text)
        for value in ("Dedi Santoso", "Rina Kusuma", "Jalan Mawar 17"):
            self.assertNotIn(value, masked)
        self.assertEqual(masker.restore(masked), text)

    def test_iso_incident_time_preserved_and_formatted_contacts_masked(self):
        text = "Transfer 10000000 pada 2026-10-19T10:00:00+07:00 ke RINA KUSUMA. Nomor hp 0812.3456.7890; alamat saya Blok A nomor 7; referensi MB110ABC123."
        masker = PrivacyMasker()
        masked = masker.mask_text(text)
        self.assertIn("2026-10-19T10:00:00+07:00", masked)
        self.assertIn("Transfer 10000000", masked)
        for value in ("RINA KUSUMA", "0812.3456.7890", "Blok A nomor 7", "MB110ABC123"):
            self.assertNotIn(value, masked)
        self.assertEqual(masker.restore(masked), text)

    def test_alias_and_nested_context_support_target_slot_seed(self):
        values = {"reporter_name": "Adi Nugraha", "reporter_id": "0000000000000000", "victim_account": "0000123456", "phone": "81234567890", "address": "Blok A nomor 7"}
        masker = PrivacyMasker(values)
        masked = masker.mask_text(json.dumps(values))
        self.assertEqual(masker.restore(json.loads(masked)), values)
        self.assertNotIn("Adi Nugraha", masked)
        nested = PrivacyMasker({"tahap4": {"daftar_penyelenggara_terlapor": [{"nomor_rekening_akun": "0000123456"}]}})
        self.assertEqual(nested.mask_text("0000123456"), "[REKENING_1]")
        for field in ("pelapor_nama", "korban_nama", "nama_pengirim", "terlapor_nama", "nama_penerima", "pelapor_telepon", "korban_nik", "rekening_pengirim", "rekening_penerima", "korban_alamat", "pelapor_email"):
            with self.subTest(field=field):
                self.assertIsNotNone(sensitive_kind(field))

    def test_short_secrets_and_unknown_labelled_names_are_not_sent(self):
        text = 'Saya dihubungi oleh rudi hartono, PIN 1234; OTP saya 654321; password "dua kata rahasia"; API key=sk_dummy_secret.'
        masker = PrivacyMasker()
        masked = masker.mask_text(text)
        for value in ("rudi hartono", "1234", "654321", "dua kata rahasia", "sk_dummy_secret"):
            self.assertNotIn(value, masked)
        self.assertIn("[RAHASIA_", masked)
        self.assertEqual(masker.restore(masked), text)

    def test_identifier_adjacent_to_date_is_still_masked(self):
        for identifier in ("081234567890", "0000000000000000"):
            with self.subTest(identifier=identifier):
                text = f"Hubungi {identifier} 2026-10-19 pukul 10:00."
                masker = PrivacyMasker()
                masked = masker.mask_text(text)
                self.assertNotIn(identifier, masked)
                self.assertIn("2026-10-19 pukul 10:00", masked)
                self.assertEqual(masker.restore(masked), text)

    def test_address_must_not_hide_following_transaction(self):
        for text in (
            "Alamat saya Jalan Contoh 17, saya transfer Rp10000000 pada 19 Oktober 2026 10:00",
            "Alamat saya Jalan Contoh 17, pada 19 Oktober 2026 10:00 saya transfer Rp10000000",
        ):
            masker = PrivacyMasker()
            masked = masker.mask_text(text)
            self.assertNotIn("Jalan Contoh 17", masked)
            self.assertIn("Rp10000000", masked)
            self.assertIn("19 Oktober 2026 10:00", masked)
            self.assertEqual(masker.restore(masked), text)

    def test_tokens_are_request_local_and_unknown_output_is_rejected(self):
        masker = PrivacyMasker({"email": "a@example.test"})
        masked = masker.mask_text("a@example.test")
        self.assertEqual(placeholders([{"value": masked}, 5]), {"[EMAIL_1]"})
        self.assertEqual(masker.restore({"value": masked, "confidence": 0.9}), {"value": "a@example.test", "confidence": 0.9})
        for value in ("[EMAIL_999]", "[MADE_UP_1]", "[EMAIL_1"):
            with self.subTest(value=value), self.assertRaises(PrivacyError):
                masker.restore(value)
        with self.assertRaises(PrivacyError):
            PrivacyMasker().restore(masked)
        unseen = PrivacyMasker({"email": "a@example.test"})
        unseen.mask_text("No personal data in this prompt")
        with self.assertRaises(PrivacyError):
            unseen.restore("[EMAIL_1]")

    def test_user_cannot_inject_reserved_tokens(self):
        for value in ("Nama saya [NIK_1]", "[MADE_UP_1]", "[EMAIL_42"):
            with self.subTest(value=value), self.assertRaises(PrivacyError):
                PrivacyMasker().mask_text(value)
        with self.assertRaises(PrivacyError):
            PrivacyMasker({"reporter_name": "[NAMA_1]"})

    def test_originals_never_appear_in_public_errors(self):
        masker = PrivacyMasker({"reporter_id": "0000000000000000"})
        with self.assertRaises(PrivacyError) as error:
            masker.restore("[NIK_2]")
        self.assertNotIn("0000000000000000", str(error.exception))


if __name__ == "__main__":
    unittest.main()
