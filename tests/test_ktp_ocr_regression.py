"""KTP OCR variations must not discard otherwise usable evidence or trust bad fields."""

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.llm_gateway import GatewayError, LLMGatewayService, SIMULATION_VALUES, _Envelope, _validated_result


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/v1/ktp.png"
ENV = {
    "AI_MODE": "remote", "AI_API_KEY": "synthetic-test-key",
    "AI_BASE_URL": "https://example.test/v1", "AI_TIMEOUT_SECONDS": "5",
    "VISION_MODEL_NAME": "vision-test", "CHAT_MODEL_NAME": "chat-test",
    "VISION_INPUT_MODE": "image", "AI_RESPONSE_FORMAT": "json_object",
    "IASC_WEBHOOK_URL": "",
}


def slot(name, value, confidence=0.97):
    return {"field": "tahap1." + name, "value": value, "confidence": confidence}


def completion(slots):
    return httpx.Response(200, json={"choices": [{
        "finish_reason": "stop", "message": {"content": json.dumps({"slots": slots})},
    }]})


class KtpOCRGatewayRegressionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        environment = patch.dict(os.environ, ENV)
        environment.start()
        self.addCleanup(environment.stop)

    async def extract(self, slots):
        # Validate OCR slots directly: KTP extraction no longer goes to an AI API.
        try:
            envelope = _Envelope.model_validate({"slots": slots})
        except ValidationError:
            raise GatewayError("Ekstraksi lokal tidak valid.") from None
        return _validated_result(envelope.slots, set(SIMULATION_VALUES["ktp"]), False, allow_partial=True)

    async def test_ktp_uses_local_ocr_without_any_http_request(self):
        requests = []

        def handler(request):
            requests.append(request)
            raise AssertionError("KTP must never reach an AI provider")

        values = {"tahap1.nama_pelapor": "PELAPOR DUMMY"}
        gateway = LLMGatewayService(transport=httpx.MockTransport(handler))
        with patch("services.llm_gateway.extract_ktp_locally", return_value=(values, {key: 0.9 for key in values})) as local_ocr:
            result = await gateway.extract("ktp", FIXTURE.read_bytes(), "image/png")
        self.assertEqual(result.values, values)
        self.assertFalse(result.simulated)
        local_ocr.assert_called_once()
        self.assertEqual(requests, [])

    async def test_uppercase_ktp_labels_and_numeric_birth_date_are_canonical(self):
        result = await self.extract([
            slot("nama_pelapor", "PELAPOR DUMMY"), slot("jenis_kelamin", "PEREMPUAN"),
            slot("agama_pelapor", "ISLAM"), slot("jenis_identitas", "ktp"),
            slot("kewarganegaraan_pelapor", "WNI"), slot("tanggal_lahir_pelapor", "18-02-1986"),
            slot("nomor_identitas", "0000 0000-0000 0000"),
        ])
        self.assertEqual(result.values, {
            "tahap1.nama_pelapor": "PELAPOR DUMMY", "tahap1.jenis_kelamin": "Perempuan",
            "tahap1.agama_pelapor": "Islam", "tahap1.jenis_identitas": "KTP",
            "tahap1.kewarganegaraan_pelapor": "Indonesia",
            "tahap1.tanggal_lahir_pelapor": "18 Februari 1986",
            "tahap1.nomor_identitas": "0000000000000000",
        })
        self.assertFalse(result.simulated)

    async def test_explicit_birth_date_variants_keep_the_same_calendar_date(self):
        for value in ("1986-02-18", "18/02/1986", "18-02-1986", "18 FEBRUARI 1986", "01 Februari 1986"):
            with self.subTest(value=value):
                result = await self.extract([slot("tanggal_lahir_pelapor", value)])
                self.assertEqual(result.values["tahap1.tanggal_lahir_pelapor"], "1 Februari 1986" if value.startswith("01 ") else "18 Februari 1986")

    async def test_enum_normalization_keeps_low_confidence_for_human_review(self):
        for name, raw, expected in [
            ("jenis_kelamin", " LAKI-LAKI ", "Laki-laki"),
            ("agama_pelapor", "KRISTEN", "Kristen"),
            ("agama_pelapor", "PROTESTAN", "Kristen"),
        ]:
            with self.subTest(name=name, raw=raw):
                result = await self.extract([slot(name, raw, 0.6)])
                self.assertEqual(result.values["tahap1." + name], expected)
                self.assertEqual(result.confidence["tahap1." + name], 0.6)

    async def test_one_invalid_ktp_field_does_not_discard_valid_fields(self):
        result = await self.extract([
            slot("nama_pelapor", "PELAPOR DUMMY"), slot("jenis_kelamin", "PEREMPUAN"),
            slot("nomor_identitas", "12345"), slot("tanggal_lahir_pelapor", "31-02-1986"),
            slot("agama_pelapor", "BELUM TERBACA"),
        ])
        self.assertEqual(result.values, {"tahap1.nama_pelapor": "PELAPOR DUMMY", "tahap1.jenis_kelamin": "Perempuan"})
        self.assertEqual(result.values.keys(), result.confidence.keys())

    async def test_invalid_identity_numbers_are_never_padded_corrected_or_coerced(self):
        for value in (1234567890123456, 1e15, "000000000000000.0", "000000000000000O", "000000000000000", "00000000000000000"):
            with self.subTest(value=value):
                result = await self.extract([slot("nomor_identitas", value), slot("nama_pelapor", "PELAPOR DUMMY")])
                self.assertNotIn("tahap1.nomor_identitas", result.values)
                self.assertEqual(result.values["tahap1.nama_pelapor"], "PELAPOR DUMMY")

    async def test_all_invalid_scalar_fields_are_left_missing_without_dummy_data(self):
        result = await self.extract([
            slot("jenis_kelamin", "TIDAK TERBACA"), slot("tanggal_lahir_pelapor", "31-02-1986"),
            slot("nomor_identitas", "12345"), slot("nama_pelapor", ""),
        ])
        self.assertEqual(result.values, {})
        self.assertEqual(result.confidence, {})
        self.assertFalse(result.simulated)

    async def test_partial_ocr_never_relaxes_paths_duplicates_or_envelope_validation(self):
        good = slot("nama_pelapor", "PELAPOR DUMMY")
        examples = [
            [good, {"field": "tahap5.setuju_syarat_dan_ketentuan", "value": "true", "confidence": 1.0}],
            [good, {"field": "tahap1.unknown", "value": "dummy", "confidence": 0.9}],
            [good, good],
            [good, slot("jenis_kelamin", "PEREMPUAN", 1.1)],
            [good, slot("jenis_kelamin", "PEREMPUAN", True)],
            [good, slot("jenis_kelamin", {"execute": "submit"})],
        ]
        for slots in examples:
            with self.subTest(slots=slots), self.assertRaises(GatewayError):
                await self.extract(slots)

    async def test_chat_field_validation_stays_strict(self):
        gateway = LLMGatewayService(transport=httpx.MockTransport(lambda request: completion([slot("jenis_kelamin", "PEREMPUAN")])))
        with self.assertRaises(GatewayError):
            await gateway.extract_chat("PEREMPUAN", ["tahap1.jenis_kelamin"], {})


class KtpOCRWorkflowRegressionTests(unittest.TestCase):
    def test_partial_ktp_stores_valid_data_and_evidence_then_accepts_requested_correction(self):
        with patch.dict(os.environ, ENV), patch("dotenv.load_dotenv", return_value=False):
            import main
            from services.orchestrator import IntakeState, SESSIONS

            values = {**SIMULATION_VALUES["ktp"], "tahap1.jenis_kelamin": "PEREMPUAN",
                      "tahap1.agama_pelapor": "ISLAM", "tahap1.tanggal_lahir_pelapor": "18-02-1986",
                      "tahap1.nomor_identitas": "12345"}
            evidence_slots = [{"field": path, "value": value, "confidence": 0.97} for path, value in values.items()]
            local_result = _validated_result(_Envelope.model_validate({"slots": evidence_slots}).slots, set(SIMULATION_VALUES["ktp"]), False, allow_partial=True)
            requests = []

            def handler(request):
                content = json.loads(request.content)["messages"][1]["content"]
                requests.append(content)
                raise AssertionError("KTP extraction and explicit NIK correction must stay local")

            gateway = LLMGatewayService(transport=httpx.MockTransport(handler))
            SESSIONS.clear()
            try:
                with patch("services.llm_gateway.extract_ktp_locally", return_value=(local_result.values, local_result.confidence)) as local_ocr, patch.object(main, "gateway", return_value=gateway), TestClient(main.app) as client:
                    created = client.post("/api/v1/session/init", json={})
                    self.assertEqual(created.status_code, 201)
                    url = "/api/v1/session/" + created.json()["session_id"]
                    self.assertEqual(client.post(url + "/chat", json={"text": "Ya, saya sendiri"}).status_code, 200)
                    uploaded = client.post(url + "/upload", files={"file": ("ktp-dummy.png", FIXTURE.read_bytes(), "image/png")})
                    self.assertEqual(uploaded.status_code, 200, uploaded.text)
                    state = uploaded.json()
                    self.assertEqual(requests, [])
                    local_ocr.assert_called_once()
                    self.assertEqual(state["state"], IntakeState.PELAPOR)
                    self.assertEqual(state["next_slot"], "tahap1.nomor_identitas")
                    self.assertEqual(state["data"]["tahap1"]["nama_pelapor"], "PELAPOR DUMMY")
                    self.assertEqual(state["data"]["tahap1"]["jenis_kelamin"], "Perempuan")
                    self.assertEqual(state["data"]["tahap1"]["tanggal_lahir_pelapor"], "18 Februari 1986")
                    self.assertNotIn("nomor_identitas", state["data"]["tahap1"])
                    proof = state["data"]["tahap1"]["upload_kartu_identitas_korban"]
                    self.assertEqual(client.get(proof["url"]).status_code, 200)
                    self.assertEqual(state["evidence"][0]["file_id"], proof["file_id"])
                    self.assertIn("tahap1.upload_kartu_identitas_korban", [item["path"] for item in state["dom_patches"]])
                    corrected = client.post(url + "/chat", json={"text": "0000000000000000"})
                    self.assertEqual(corrected.status_code, 200, corrected.text)
                    self.assertEqual(corrected.json()["state"], IntakeState.CONTACT)
                    self.assertEqual(corrected.json()["data"]["tahap1"]["nomor_identitas"], "0000000000000000")
                    self.assertEqual(requests, [])
            finally:
                SESSIONS.clear()


if __name__ == "__main__":
    unittest.main()
