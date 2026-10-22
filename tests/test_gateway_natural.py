import os
import unittest
from unittest.mock import patch

import httpx

from services.llm_gateway import (
    EMAIL_SLOT, INCIDENT_SLOT, PHONE_SLOT, STORY_SLOT, GatewayError,
    LLMGatewayService, SIMULATION_VALUES,
)


class NaturalGatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "AI_MODE": "simulation", "AI_API_KEY": "", "AI_BASE_URL": "http://localhost:8000/v1",
            "AI_RESPONSE_FORMAT": "json_object", "AI_TIMEOUT_SECONDS": "10",
            "VISION_MODEL_NAME": "vision-test", "CHAT_MODEL_NAME": "chat-test",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    async def test_contacts_from_one_natural_answer_and_indonesian_prefixes(self):
        for number in ("08123456789", "+62 812 3456 789", "628123456789", "8123456789"):
            with self.subTest(number=number):
                result = await LLMGatewayService().extract_contacts(f"Nomor saya {number}, email saya pelapor@example.com.")
                self.assertEqual(result.values, {PHONE_SLOT: "8123456789", EMAIL_SLOT: "pelapor@example.com"})
                self.assertEqual(set(result.confidence.values()), {1.0})

    async def test_numbers_in_email_do_not_become_telephone(self):
        result = await LLMGatewayService().extract_contacts("pelapor08123456789@example.com")
        self.assertEqual(result.values, {EMAIL_SLOT: "pelapor08123456789@example.com"})

    async def test_partial_contacts_stay_partial_and_ambiguity_is_not_guessed(self):
        gateway = LLMGatewayService()
        result = await gateway.extract_contacts("HP saya 08123456789")
        self.assertEqual(result.values, {PHONE_SLOT: "8123456789"})
        self.assertEqual((await gateway.extract_contacts("Saya belum punya email")).values, {})
        for text in ("08123456789, 08987654321", "satu@example.com atau dua@example.com", "08123456789, salah@invalid"):
            with self.subTest(text=text), self.assertRaises(GatewayError):
                await gateway.extract_contacts(text)

    async def test_contacts_are_local_even_when_remote_gateway_is_configured(self):
        os.environ["AI_MODE"] = "remote"

        def unexpected_request(request):
            self.fail("Explicitly typed contacts do not need external AI.")

        result = await LLMGatewayService(transport=httpx.MockTransport(unexpected_request)).extract_contacts("08123456789, pelapor@example.com")
        self.assertFalse(result.simulated)
        self.assertEqual(result.values[PHONE_SLOT], "8123456789")

    async def test_simulation_chronology_uses_persons_story_and_no_clock_inference(self):
        story = "Saya membeli sepatu melalui Instagram.\n  Setelah membayar Rp250.000, penjual memblokir saya."
        result = await LLMGatewayService().synthesize_chronology(story, {"values": {
            "tahap4.daftar_penyelenggara_terlapor.0.daftar_rincian_transaksi.0.waktu_transaksi": "19 Oktober 2026 10:00:00",
        }})
        self.assertEqual(result.values, {STORY_SLOT: " ".join(story.split())})
        self.assertNotIn("WhatsApp", result.values[STORY_SLOT])
        self.assertNotIn("100.000", result.values[STORY_SLOT])

    async def test_chronology_parses_explicit_dates_and_reuses_only_incident_time(self):
        gateway = LLMGatewayService()
        for date in ("19 Oktober 2026 pukul 10.00", "2026-10-19T10:00:00+07:00", "19 oktober 2026 10:00"):
            with self.subTest(date=date):
                result = await gateway.synthesize_chronology(f"Pada {date}, saya tertipu pembelian sepatu.", {})
                self.assertEqual(result.values[INCIDENT_SLOT], "19 Oktober 2026 10:00")
        result = await gateway.synthesize_chronology("Saya membeli sepatu yang tidak dikirim.", {"values": {INCIDENT_SLOT: "19 Oktober 2026 10:00"}})
        self.assertEqual(result.values[INCIDENT_SLOT], "19 Oktober 2026 10:00")

    async def test_ambiguous_dates_do_not_select_one_and_oversized_story_is_not_truncated(self):
        gateway = LLMGatewayService()
        result = await gateway.synthesize_chronology("Pada 19 Oktober 2026 10:00 saya transfer. Pada 19 Oktober 2026 12:00 saya diblokir.", {})
        self.assertNotIn(INCIDENT_SLOT, result.values)
        for story in ("x" * 2001, "Kejadian 31 Februari 2026 10:00."):
            with self.subTest(story=story[:60]), self.assertRaises(ValueError):
                await gateway.synthesize_chronology(story, {})

    async def test_remote_chronology_keeps_actual_facts_locally_without_llm_rewriting(self):
        os.environ["AI_MODE"] = "remote"

        def forbidden(request):
            self.fail("Chronology must not be rewritten or augmented by the cloud model")

        gateway = LLMGatewayService(transport=httpx.MockTransport(forbidden))
        story = "Saya membeli sepatu yang tidak dikirim."
        result = await gateway.synthesize_chronology(story, {"api_key": "secret-key"})
        self.assertEqual(result.values[STORY_SLOT], story)
        self.assertNotIn(INCIDENT_SLOT, result.values)
        self.assertEqual(result.confidence[STORY_SLOT], 1.0)
        self.assertFalse(result.simulated)
        result = await gateway.synthesize_chronology("Pada 19 Oktober 2026 10:00 saya transfer untuk sepatu yang tidak dikirim.", {})
        self.assertEqual(result.values[INCIDENT_SLOT], "19 Oktober 2026 10:00")

    async def test_simulation_documents_do_not_decide_workflow_or_replace_user_story(self):
        self.assertNotIn("tahap1.apakah_mengalami_sendiri", SIMULATION_VALUES["ktp"])
        self.assertNotIn(STORY_SLOT, SIMULATION_VALUES["bukti_chat"])
        self.assertFalse(any(path.startswith("tahap4.nama_penyelenggara_layanan_korban") for path in SIMULATION_VALUES["bukti_transfer"]))
        self.assertFalse(any(path.startswith("tahap4.nomor_rekening_akun_korban") for path in SIMULATION_VALUES["bukti_transfer"]))

    async def test_plain_scalar_and_contact_answers_do_not_require_field_assignments(self):
        gateway = LLMGatewayService()
        result = await gateway.extract_chat("08123456789, pelapor@example.com", [PHONE_SLOT, EMAIL_SLOT], {})
        self.assertEqual(result.values, {PHONE_SLOT: "8123456789", EMAIL_SLOT: "pelapor@example.com"})
        result = await gateway.extract_chat("Nama Pelaku", ["tahap2.daftar_informasi_terlapor.0.nama_terlapor"], {})
        self.assertEqual(list(result.values.values()), ["Nama Pelaku"])
        result = await gateway.extract_chat("2026-10-19 10:00", [INCIDENT_SLOT], {})
        self.assertEqual(result.values[INCIDENT_SLOT], "19 Oktober 2026 10:00")


if __name__ == "__main__":
    unittest.main()
