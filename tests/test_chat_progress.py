"""Every manual answer must progress the requested slot or explain what is missing."""

from copy import deepcopy
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

import main
from services.llm_gateway import ExtractionResult, GatewayError, LLMGatewayService
from services.orchestrator import IntakeState, SESSIONS
from services.guardrails import REFUSAL_MESSAGE


MEDIA = "tahap2.daftar_sumber_media_penipuan.0.sumber_media_informasi_penipuan"
DETAIL = "tahap2.daftar_sumber_media_penipuan.0.detail_sumber_media_informasi_penipuan"


class ChatProgressTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"AI_MODE": "simulation", "AI_API_KEY": ""})
        environment.start()
        self.addCleanup(environment.stop)
        SESSIONS.clear()
        self.addCleanup(SESSIONS.clear)
        self.client = self.enterContext(TestClient(main.app))
        created = self.client.post("/api/v1/session/init", json={})
        self.assertEqual(created.status_code, 201, created.text)
        self.url = "/api/v1/session/" + created.json()["session_id"]
        self.session = SESSIONS[created.json()["session_id"]]
        self.send("Ya, saya sendiri")
        self.upload("ktp")
        self.send("08123456789, pelapor.dummy@example.com")
        self.upload("bukti_chat")
        self.session.state = IntakeState.TERLAPOR

    def send(self, text):
        response = self.client.post(self.url + "/chat", json={"text": text})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def upload(self, kind):
        path = main.ROOT / "fixtures/v1" / (kind + ".png")
        response = self.client.post(self.url + "/upload", files={"file": (path.name, path.read_bytes(), "image/png")})
        self.assertEqual(response.status_code, 200, response.text)

    def remove_media_fields(self, *names):
        row = self.session.data["tahap2"]["daftar_sumber_media_penipuan"][0]
        for name in names:
            row.pop(name, None)
            path = "tahap2.daftar_sumber_media_penipuan.0." + name
            self.session.confidence.pop(path, None)
            self.session.sources.pop(path, None)

    def assert_unchanged(self, before):
        after = self.client.get(self.url).json()
        for key in ("state", "data", "confidence", "sources", "evidence", "revision", "result"):
            self.assertEqual(after[key], before[key], key)

    def test_media_repeat_and_greeting_keep_guidance_then_contact_advances(self):
        self.remove_media_fields("sumber_media_informasi_penipuan", "detail_sumber_media_informasi_penipuan")
        state = self.send("whatsapp")
        self.assertEqual(state["next_slot"], DETAIL)
        self.assertIn("WhatsApp", state["assistant_message"])
        self.assertIn("nomor kontak", state["assistant_message"])
        self.assertIn("username", state["assistant_message"])
        repeated = self.client.post(self.url + "/chat", json={"text": "whatsapp"})
        self.assertEqual(repeated.status_code, 422)
        self.assertIn("Nama media sudah tercatat", repeated.json()["detail"])
        self.assert_unchanged(state)
        with patch.object(main, "gateway", side_effect=AssertionError("Greetings must not call AI")):
            greeting = self.send("halo")
        self.assertEqual(greeting["assistant_message"], REFUSAL_MESSAGE)
        self.assertEqual(greeting["next_slot"], DETAIL)
        completed = self.send("08000000001")
        self.assertEqual(completed["state"], IntakeState.CHAT_MORE)
        self.assertEqual(completed["data"]["tahap2"]["daftar_sumber_media_penipuan"][0]["detail_sumber_media_informasi_penipuan"], "08000000001")

    def test_empty_ai_extraction_returns_explanation_and_keeps_draft_atomic(self):
        self.remove_media_fields("detail_sumber_media_informasi_penipuan")
        before = self.client.get(self.url).json()
        gateway = SimpleNamespace(extract_chat=AsyncMock(return_value=ExtractionResult()))
        with patch.object(main, "gateway", return_value=gateway):
            response = self.client.post(self.url + "/chat", json={"text": "jawaban belum lengkap"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("belum menemukan jawaban", response.json()["detail"])
        self.assertIn("nomor kontak", response.json()["detail"])
        self.assert_unchanged(before)

    def test_unknown_bank_discarded_by_normalizer_cannot_silently_succeed(self):
        self.session.state = IntakeState.ACCOUNT_DETAILS
        self.session.data["tahap4"] = {
            "nomor_rekening_akun_korban": "0000000000",
            "nama_pemilik_rekening_akun_korban": "PELAPOR DUMMY",
            "bukti_kepemilikan_rekening_akun_korban": deepcopy(self.session.evidence["bukti_chat"]),
        }
        bank = "tahap4.nama_penyelenggara_layanan_korban"
        before = self.client.get(self.url).json()
        self.assertEqual(before["next_slot"], bank)
        result = ExtractionResult(values={bank: "UNKNOWN BANK XYZ"}, confidence={bank: 1.0})
        with patch.object(main, "gateway", return_value=SimpleNamespace(extract_chat=AsyncMock(return_value=result))):
            response = self.client.post(self.url + "/chat", json={"text": "bank tidak dikenali"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("belum menemukan jawaban", response.json()["detail"])
        self.assert_unchanged(before)

    def test_protected_manual_value_is_not_overwritten_or_reported_as_success(self):
        self.session.sources[DETAIL] = "manual"
        self.session.confidence[DETAIL] = 0.5
        before = self.client.get(self.url).json()
        self.assertEqual(before["next_slot"], DETAIL)
        result = ExtractionResult(values={DETAIL: "08000000002"}, confidence={DETAIL: 1.0})
        with patch.object(main, "gateway", return_value=SimpleNamespace(extract_chat=AsyncMock(return_value=result))):
            response = self.client.post(self.url + "/chat", json={"text": "08000000002"})
        self.assertEqual(response.status_code, 422)
        self.assert_unchanged(before)


class LocalMediaAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_media_and_contact_details_never_call_remote_provider(self):
        def forbidden(request):
            self.fail("Explicit media and contacts must be parsed locally")

        with patch.dict(os.environ, {"AI_MODE": "remote", "AI_API_KEY": "synthetic-test-key", "AI_BASE_URL": "https://example.test/v1"}):
            gateway = LLMGatewayService(transport=httpx.MockTransport(forbidden))
            for path, text, expected in (
                (MEDIA, "whatsapp", "WhatsApp"),
                (DETAIL, "+62 800 0000 001", "+62 800 0000 001"),
                (DETAIL, "@akun_contoh", "@akun_contoh"),
                (DETAIL, "https://example.com/profil", "https://example.com/profil"),
            ):
                with self.subTest(path=path, text=text):
                    result = await gateway.extract_chat(text, [path], {})
                    self.assertEqual(result.values, {path: expected})
                    self.assertEqual(result.confidence, {path: 1.0})
                    self.assertFalse(result.simulated)
            for text in ("whatsapp", "https://[invalid"):
                with self.subTest(text=text), self.assertRaises(GatewayError) as error:
                    await gateway.extract_chat(text, [DETAIL], {})
                self.assertNotIn("synthetic-test-key", str(error.exception))


if __name__ == "__main__":
    unittest.main()
