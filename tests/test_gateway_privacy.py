import json
import os
import re
import unittest
from unittest.mock import patch

import httpx

import app
from services.llm_gateway import GatewayError, INCIDENT_SLOT, LLMGatewayService, STORY_SLOT
from services.privacy import placeholders


def completion(slots):
    return httpx.Response(200, json={"choices": [{
        "finish_reason": "stop",
        "message": {"content": json.dumps({"slots": slots})},
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

    @staticmethod
    def masked_story(request):
        body = json.loads(request.content)
        content = body["messages"][1]["content"]
        return body, content, content.partition("\nUntrusted user story: ")[2]

    async def test_chronology_masks_outbound_sensitive_facts_and_restores_exact_story(self):
        calls = []

        def handler(request):
            body, content, story = self.masked_story(request)
            outbound = json.dumps(body, ensure_ascii=False)
            for value in self.context.values():
                self.assertNotIn(value, outbound)
            for kind in ("NAMA_PELAPOR", "NIK", "TELEPON", "EMAIL", "ALAMAT", "TANGGAL_LAHIR", "TEMPAT_LAHIR", "REKENING"):
                self.assertIn("[" + kind + "_", story)
            self.assertIn("19 Oktober 2026 10:00", content)
            self.assertIn("Rp10000000", story)
            self.assertIn("dari rekening", story)
            self.assertIn("Alamat saya", story)
            calls.append(request)
            return completion([
                {"field": STORY_SLOT, "value": story, "confidence": 1.0},
                {"field": INCIDENT_SLOT, "value": "19 Oktober 2026 10:00", "confidence": 1.0},
            ])

        gateway = LLMGatewayService(transport=httpx.MockTransport(handler))
        result = await gateway.synthesize_chronology(self.story, {"values": self.context})
        self.assertEqual(result.values[STORY_SLOT], self.story)
        self.assertEqual(result.values[INCIDENT_SLOT], "19 Oktober 2026 10:00")
        self.assertFalse(result.simulated)
        self.assertEqual(len(calls), 1)

    async def test_chronology_rejects_missing_or_invented_sensitive_tokens(self):
        for change in ("missing", "invented"):
            with self.subTest(change=change):
                def handler(request):
                    _, _, story = self.masked_story(request)
                    if change == "missing":
                        story = story.replace(sorted(placeholders(story))[0], "korban")
                    else:
                        story += " [NIK_999]"
                    return completion([{"field": STORY_SLOT, "value": story, "confidence": 1.0}])

                gateway = LLMGatewayService(transport=httpx.MockTransport(handler))
                with self.assertRaises(GatewayError) as error:
                    await gateway.synthesize_chronology(self.story, self.context)
                for value in self.context.values():
                    self.assertNotIn(value, str(error.exception))

    async def test_reserved_token_in_context_is_rejected_before_http_with_safe_error(self):
        def forbidden(request):
            self.fail("Reserved placeholders must fail before any HTTP request")

        gateway = LLMGatewayService(transport=httpx.MockTransport(forbidden))
        with self.assertRaises(GatewayError) as error:
            await gateway.synthesize_chronology(self.story, {
                **self.context, "tahap1.nama_pelapor": "[NAMA_PELAPOR_1]",
            })
        self.assertIn("disamarkan", str(error.exception))
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

    async def test_legacy_gateway_masks_text_and_restores_account_before_draft_validation(self):
        real_client = httpx.AsyncClient
        calls = []

        def handler(request):
            body = json.loads(request.content)
            content = body["messages"][1]["content"][0]["text"]
            for value in ("0000123456", "0000000000000000", "081234567890"):
                self.assertNotIn(value, json.dumps(body))
            account = re.search(r"rekening (\[[A-Z_]+_[0-9]+\])", content)[1]
            nik = re.search(r"NIK (\[[A-Z_]+_[0-9]+\])", content)[1]
            phone = re.search(r"telepon (\[[A-Z_]+_[0-9]+\])", content)[1]
            calls.append(request)
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
                "rekening_pengirim": account, "pelapor_nik": nik, "pelapor_telepon": phone,
            })}}]})

        def factory(**kwargs):
            return real_client(transport=httpx.MockTransport(handler), **kwargs)

        text = (
            'Current missing fields: ["rekening_pengirim", "pelapor_nik", "pelapor_telepon"]\n'
            "User answer: rekening 0000123456; NIK 0000000000000000; telepon 081234567890"
        )
        with patch.dict(os.environ, {"AI_MODEL": "deepseek-v4-flash"}), patch("app.httpx.AsyncClient", side_effect=factory):
            result = await app.gateway_extract(text)
        self.assertEqual(result, {"rekening_pengirim": "0000123456", "pelapor_nik": "0000000000000000", "pelapor_telepon": "081234567890"})
        self.assertEqual(len(calls), 1)

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
