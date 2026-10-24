import json
import unittest

from services.chronology import validate_chronology


class ChronologyGroundingTests(unittest.TestCase):
    def test_formal_paraphrase_preserves_masked_facts_with_normalized_money_and_time(self):
        source = (
            "Saya bayar 320 ribu pada 19 Oktober 2026 jam 10 pagi kepada [NAMA_TERLAPOR_1]. "
            "Penjual memblokir saya. Barang belum dikirim.\n"
            + json.dumps({"nominal_transaksi": 320000, "nomor_rekening_akun": "[REKENING_1]"})
        )
        validate_chronology(
            "Pada 19-10-2026 pukul 10.00, pelapor mentransfer Rp320.000,00 ke rekening "
            "[REKENING_1] atas nama [NAMA_TERLAPOR_1]. Setelah itu penjual memblokir pelapor. "
            "Pesanan belum dikirimkan.", source, {"[REKENING_1]", "[NAMA_TERLAPOR_1]"},
        )

    def test_empty_or_oversized_output_is_rejected(self):
        for narrative in ("", "   ", "x" * 4001):
            with self.subTest(narrative=narrative[:20]), self.assertRaises(ValueError):
                validate_chronology(narrative, "Saya tertipu.", set())

    def test_unknown_and_forbidden_private_tokens_are_rejected_even_if_issued(self):
        for token in ("[REKENING_999]", "[NIK_1]", "[TANGGAL_LAHIR_1]", "[RAHASIA_1]"):
            allowed = set() if token == "[REKENING_999]" else {token}
            with self.subTest(token=token), self.assertRaises(ValueError):
                validate_chronology("Pelapor tertipu " + token, "Pelapor tertipu " + token, allowed)

    def test_explicit_victim_account_owner_name_is_allowed(self):
        validate_chronology(
            "Rekening atas nama [NAMA_PELAPOR_1].",
            '{"tahap4.nama_pemilik_rekening_akun_korban": "[NAMA_PELAPOR_1]"}', {"[NAMA_PELAPOR_1]"},
        )

    def test_masked_name_label_does_not_turn_following_words_into_an_invented_name(self):
        validate_chronology(
            "Saya mentransfer ke rekening atas nama [NAMA_TERLAPOR_1] pada 19 Oktober 2026.",
            "Saya transfer pada 19 Oktober 2026 atas nama [NAMA_TERLAPOR_1].", {"[NAMA_TERLAPOR_1]"},
        )

    def test_new_url_or_handle_is_rejected_but_existing_reference_is_allowed(self):
        source = "Saya tertipu melalui https://contoh.test/toko dan akun @toko_contoh."
        validate_chronology("Pelapor menemukan akun @toko_contoh di https://contoh.test/toko.", source, set())
        for reference in ("https://baru.test/toko", "@pelaku_baru"):
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                validate_chronology("Pelapor tertipu melalui " + reference, source, set())

    def test_currency_values_cannot_be_invented_from_date_digits_or_other_amounts(self):
        source = "Pada 25 Oktober 2026 saya transfer Rp320.000."
        for amount in ("Rp25", "Rp350.000", "USD320000"):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                validate_chronology("Pelapor mentransfer " + amount + ".", source, set())

    def test_json_amount_and_natural_units_are_equivalent(self):
        for source in ('{"nominal_transaksi": 1500000}', "Saya membayar 1,5 juta."):
            with self.subTest(source=source):
                validate_chronology("Nominal sebesar Rp1.500.000,00.", source, set())

    def test_unsupported_calendar_date_and_clock_are_rejected(self):
        source = "Pada 19 Oktober 2026 jam 10 pagi saya transfer Rp200.000."
        for temporal in ("20 Oktober 2026", "19 November 2026", "pukul 10.01", "19 Oktober 2026 pukul 11.00"):
            with self.subTest(temporal=temporal), self.assertRaises(ValueError):
                validate_chronology("Pada " + temporal + " pelapor mentransfer Rp200.000.", source, set())

    def test_multiple_known_event_times_and_iso_timezone_are_supported(self):
        source = "Saya transfer pada 2026-10-19T03:00:00Z, lalu diblokir pada 19 Oktober 2026 pukul 12.00."
        validate_chronology(
            "Pelapor mentransfer pada 19 Oktober 2026 pukul 10:00. "
            "Pada 19-10-2026 jam 12:00 pelapor diblokir.", source, set(),
        )

    def test_iso_datetime_without_timezone_can_paraphrase_named_datetime(self):
        validate_chronology(
            "Pelapor mentransfer pada 2026-10-19T10:00:00.",
            "Saya transfer pada 19 Oktober 2026 pukul 10.00.", set(),
        )

    def test_new_raw_identifier_or_count_is_rejected(self):
        source = "Saya mentransfer ke rekening [REKENING_1]."
        for narrative in ("Pelapor mentransfer ke rekening 1234567890.", "Pelapor mentransfer 3 kali."):
            with self.subTest(narrative=narrative), self.assertRaises(ValueError):
                validate_chronology(narrative, source, {"[REKENING_1]"})

    def test_new_unmasked_private_names_and_contacts_are_rejected(self):
        source = "Saya mentransfer untuk membeli sepatu melalui Bank Mandiri."
        for detail in ("kepada Budi Karangan", "atas nama Rudi", "email pelaku@example.test"):
            with self.subTest(detail=detail), self.assertRaises(ValueError):
                validate_chronology("Saya mentransfer " + detail + " untuk pembelian sepatu.", source, set())
        validate_chronology("Saya mentransfer melalui Bank Mandiri untuk membeli sepatu.", source, set())

    def test_unsupported_events_are_rejected(self):
        for event in ("Pelapor sudah mentransfer.", "Pelaku memblokir pelapor.", "Barang sudah dikirim.", "Dana telah dikembalikan."):
            with self.subTest(event=event), self.assertRaises(ValueError):
                validate_chronology(event, "Pelapor menemukan toko yang mencurigakan.", set())

    def test_recorded_transaction_supports_completed_transfer_missing_from_raw_story(self):
        source = "Saya membeli sepatu melalui WhatsApp, tetapi barang belum dikirim.\n" + json.dumps({
            "tahap4.daftar_penyelenggara_terlapor.0.daftar_rincian_transaksi.0.nominal_transaksi": 320000,
            "tahap4.daftar_penyelenggara_terlapor.0.daftar_rincian_transaksi.0.waktu_transaksi": "19 Oktober 2026 10:00:00",
        })
        validate_chronology(
            "Pada 19 Oktober 2026 pukul 10:00, saya mentransfer Rp320.000 untuk membeli sepatu "
            "melalui WhatsApp, tetapi barang belum dikirim.", source, set(),
        )

    def test_transaction_word_or_incomplete_transaction_does_not_prove_a_transfer(self):
        prefix = "tahap4.daftar_penyelenggara_terlapor.0.daftar_rincian_transaksi."
        for context in (
            {"keterangan": "Ada transaksi senilai Rp320.000."},
            {prefix + "0.nominal_transaksi": 320000},
            {prefix + "0.waktu_transaksi": "19 Oktober 2026 10:00:00"},
            {prefix + "0.nominal_transaksi": 320000, prefix + "1.waktu_transaksi": "19 Oktober 2026 10:00:00"},
        ):
            source = "Saya belum melakukan transfer.\n" + json.dumps(context)
            with self.subTest(context=context), self.assertRaises(ValueError):
                validate_chronology("Saya sudah mentransfer.", source, set())

    def test_obvious_negation_reversal_is_rejected_for_transfer_delivery_and_refund(self):
        for source, narrative in (
            ("Saya belum melakukan transfer.", "Pelapor sudah mentransfer."),
            ("Barang belum dikirim.", "Pesanan sudah dikirimkan."),
            ("Saya belum menerima pengembalian dana.", "Pelapor menerima pengembalian dana."),
            ("Dana saya belum dikembalikan.", "Uang sudah dikembalikan."),
            ("Saya telah mentransfer.", "Pelapor belum melakukan transfer."),
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                validate_chronology(narrative, source, set())

    def test_negative_event_paraphrase_and_transferring_money_are_supported(self):
        validate_chronology(
            "Pelapor telah mengirimkan uang. Pesanan tidak kunjung dikirimkan. Dana belum dikembalikan.",
            "Saya sudah transfer. Barang belum dikirim. Belum ada pengembalian dana.", set(),
        )
        validate_chronology(
            "Saya mengirimkan uang untuk membeli sepatu, tetapi barang belum dikirimkan.",
            "Saya sudah transfer untuk membeli sepatu, barang belum dikirim.", set(),
        )

    def test_rejection_does_not_echo_private_evidence(self):
        with self.assertRaises(ValueError) as error:
            validate_chronology("Pelaku memblokir SECRET_PRIBADI.", "Cerita SECRET_PRIBADI.", set())
        self.assertNotIn("SECRET_PRIBADI", str(error.exception))


if __name__ == "__main__":
    unittest.main()
