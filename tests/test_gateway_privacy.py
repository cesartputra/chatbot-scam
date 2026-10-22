import json
import os
import unittest
from unittest.mock import patch

import httpx

import app
from fastapi import HTTPException
from services.llm_gateway import GatewayError, INCIDENT_SLOT, LLMGatewayService, STORY_SLOT


def completion(slots):
    return httpx.Response(200, json={"choices": [{
        "finish_reason": "stop",
        "message": {"content": json.dumps({"slots": slots, "is_relevant_to_scam_report": True, "injection_detected": False})},
    }]})


class GatewayPrivacyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "AI_MODE": "remote", "AI_API_KEY": "dummy-test-key",
            "AI_BASE_URL": "https://ai.sumopod.com/v1",
            "CHAT_MODEL_NAME": "deepseek-v4-flash", "VISION_MODEL_NAME": "vision-test",
            "AI_RESPONSE_FORMAT": "json_object", "AI_TIMEOUT_SECONDS": "10",
            "VISION_INPUT_MODE": "image",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.context = {
            "tahap1.nama_pelapor": "PELAPOR CONTOH",
            "tahap1.nomor_identitas": "0000000000000000",
            "tahap1.nomor_telepon_pelapor": "081234567890",
            "tahap1.email_pelapor": "pelapor@example.test",
            "tahap1.alamat_pelapor": "Jalan Contoh Nomor 17, Jakarta",
            "tahap1.tempat_lahir_pelapor": "Jakarta",
            "tahap1.tanggal_lahir_pelapor": "18 Februari 1986",
            "tahap4.nomor_rekening_akun_korban": "0000123456",
            "tahap4.nama_pemilik_rekening_akun_korban": "PELAPOR CONTOH",
        }
        self.story = (
            "Saya PELAPOR CONTOH, NIK 0000000000000000, lahir di Jakarta pada 18 Februari 1986. "
            "Alamat saya Jalan Contoh Nomor 17, Jakarta; email pelapor@example.test dan telepon 081234567890. "
            "Pada 19 Oktober 2026 10:00 saya transfer Rp10000000 dari rekening 0000123456 untuk pesanan yang tidak dikirim."
        )

    async def test_report_extraction_masks_outbound_sensitive_context(self):
        calls = []
        bank = "tahap4.nama_penyelenggara_layanan_korban"

        def handler(request):
            body = json.loads(request.content)
            content = body["messages"][1]["content"]
            outbound = json.dumps(body, ensure_ascii=False)
            for value in self.context.values():
                self.assertNotIn(value, outbound)
            for kind in ("NAMA_PELAPOR", "NIK", "TELEPON", "EMAIL", "ALAMAT", "TANGGAL_LAHIR", "TEMPAT_LAHIR", "REKENING"):
                self.assertIn("[" + kind + "_", content)
            self.assertIn("19 Oktober 2026 10:00", content)
            self.assertIn("Rp10000000", content)
            self.assertIn("<untrusted_user_report>", content)
            self.assertEqual(body["temperature"], 0)
            self.assertEqual(body["response_format"], {"type": "json_object"})
            calls.append(request)
            return completion([{"field": bank, "value": "BNI", "confidence": 1.0}])

        gateway = LLMGatewayService(transport=httpx.MockTransport(handler))
        # KTP-labelled text itself is blocked; private session context is masked.
        report = self.story.replace("NIK 0000000000000000, ", "")
        result = await gateway.extract_chat(report + " Bank rekening korban adalah BNI.", [bank], {"values": self.context})
        self.assertEqual(result.values, {bank: "BNI"})
        self.assertFalse(result.simulated)
        self.assertEqual(len(calls), 1)

    async def test_chronology_keeps_private_story_local_without_cloud_rewriting(self):
        def forbidden(request):
            self.fail("Chronology and its private details must stay local")

        result = await LLMGatewayService(transport=httpx.MockTransport(forbidden)).synthesize_chronology(self.story, self.context)
        self.assertEqual(result.values[STORY_SLOT], self.story)
        self.assertEqual(result.values[INCIDENT_SLOT], "19 Oktober 2026 10:00")

    async def test_provider_invented_sensitive_tokens_are_rejected(self):
        bank = "tahap4.nama_penyelenggara_layanan_korban"
        gateway = LLMGatewayService(transport=httpx.MockTransport(lambda request: completion([
            {"field": bank, "value": "[NIK_999]", "confidence": 1.0},
        ])))
        with self.assertRaises(ValueError) as error:
            await gateway.extract_chat("Saya transfer dari rekening BNI untuk pesanan yang tidak dikirim.", [bank], self.context)
        for value in self.context.values():
            self.assertNotIn(value, str(error.exception))

    async def test_reserved_token_in_context_is_rejected_before_http_with_safe_error(self):
        def forbidden(request):
            self.fail("Reserved placeholders must fail before any HTTP request")

        gateway = LLMGatewayService(transport=httpx.MockTransport(forbidden))
        with self.assertRaises(ValueError) as error:
            await gateway.extract_chat("Saya transfer dari rekening BNI untuk pesanan yang tidak dikirim.", ["tahap4.nama_penyelenggara_layanan_korban"], {
                **self.context, "tahap1.nama_pelapor": "[NAMA_PELAPOR_1]",
            })
        self.assertNotIn("0000000000000000", str(error.exception))

    async def test_single_private_corrections_are_validated_without_http(self):
        def forbidden(request):
            self.fail("A private single-field correction must stay on the server")

        gateway = LLMGatewayService(transport=httpx.MockTransport(forbidden))
        cases = [
            ("tahap1.nama_pelapor", "nama saya Pelapor Contoh", "Pelapor Contoh"),
            ("tahap1.nomor_identitas", "0000000000000000", "0000000000000000"),
            ("tahap1.nomor_telepon_pelapor", "081234567890", "81234567890"),
            ("tahap1.email_pelapor", "pelapor@example.com", "pelapor@example.com"),
            ("tahap1.alamat_pelapor", "Blok A Nomor 7", "Blok A Nomor 7"),
            ("tahap1.tanggal_lahir_pelapor", "18 Februari 1986", "18 Februari 1986"),
            ("tahap4.nomor_rekening_akun_korban", "0000123456", "0000123456"),
        ]
        for field, text, expected in cases:
            with self.subTest(field=field):
                result = await gateway.extract_chat(text, [field], {})
                self.assertEqual(result.values, {field: expected})
                self.assertFalse(result.simulated)

    async def test_legacy_gateway_cannot_bypass_strict_llm_policy(self):
        with patch("httpx.AsyncClient", side_effect=AssertionError("Legacy outbound gateway must stay disabled")):
            with self.assertRaises(HTTPException) as error:
                await app.gateway_extract("rekening 0000123456; NIK 0000000000000000")
        self.assertEqual(error.exception.status_code, 403)

    async def test_legacy_private_answers_are_local_even_with_remote_ai_enabled(self):
        from fastapi.testclient import TestClient

        app.SESSIONS.clear()
        with patch("app.gateway_extract", side_effect=AssertionError("Private answers must stay local")), TestClient(app.app) as client:
            session = client.post("/api/sessions").json()["session_id"]
            url = "/api/sessions/" + session
            for value in ("budi santoso", "budi@example.com", "081234567890", "0000000000000000"):
                result = client.post(url + "/messages", json={"text": value})
                self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["data"]["pelapor_nama"], "budi santoso")
            self.assertEqual(result.json()["data"]["pelapor_nik"], "0000000000000000")
        app.SESSIONS.clear()


if __name__ == "__main__":
    unittest.main()
