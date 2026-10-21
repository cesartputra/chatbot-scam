"""ASGI-only integration checks; no requests are made to the official portal."""

from copy import deepcopy
import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import main
from services.llm_gateway import ExtractionResult, GatewayError, LLMGatewayService
from services.orchestrator import EVIDENCE_KINDS, IntakeState, SESSIONS, SESSION_TTL, get_path


PHONE = "tahap1.nomor_telepon_pelapor"
EMAIL = "tahap1.email_pelapor"
TARGET_ACCOUNT = "tahap4.daftar_penyelenggara_terlapor.0.nomor_rekening_akun"


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(main.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def setUp(self):
        self.env = patch.dict(os.environ, {"AI_MODE": "simulation", "AI_API_KEY": "", "IASC_WEBHOOK_URL": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        SESSIONS.clear()
        self.addCleanup(SESSIONS.clear)
        self.state = self.new_session()
        self.session_id = self.state["session_id"]
        self.url = "/api/v1/session/" + self.session_id

    def new_session(self):
        response = self.client.post("/api/v1/session/init", json={})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def files(self, kinds=EVIDENCE_KINDS):
        return {kind: (kind + ".png", (main.ROOT / "fixtures/v1" / (kind + ".png")).read_bytes(), "image/png") for kind in kinds}

    def upload(self, kinds=EVIDENCE_KINDS):
        response = self.client.post(self.url + "/upload", files=self.files(kinds))
        self.assertEqual(response.status_code, 200, response.text)
        self.state = response.json()
        return self.state

    def fill_contacts(self):
        response = self.client.post(self.url + "/chat", json={"text": "nomor hp=800000000000\nemail=pelapor.dummy@example.com"})
        self.assertEqual(response.status_code, 200, response.text)
        self.state = response.json()
        return self.state

    def confirm(self):
        response = self.client.post(self.url + "/chat", json={"confirm": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.state = response.json()
        return self.state

    def ready(self):
        self.upload()
        self.fill_contacts()
        self.confirm()
        response = self.client.post(self.url + "/verify-ekyc", json={"simulate": True, "liveness_score": 0.98})
        self.assertEqual(response.status_code, 200, response.text)
        self.state = response.json()
        return self.state

    def submit_body(self, mode="dom", **updates):
        # This is a local API contract test of a server-generated arithmetic challenge.
        question = self.state["captcha_question"].split()
        return {"setuju_syarat_dan_ketentuan": True, "captcha_answer": str(int(question[0]) + int(question[2])), "integration_mode": mode, **updates}

    def test_happy_path_five_states_two_delta_slots_and_both_integrations(self):
        self.assertEqual(self.state["state"], IntakeState.EVIDENCE)
        self.assertEqual(self.state["missing_evidence"], list(EVIDENCE_KINDS))
        self.assertFalse(self.state["external_dispatch_enabled"])
        state = self.upload()
        self.assertEqual(state["state"], IntakeState.DELTA)
        self.assertEqual({item["path"] for item in state["missing_slots"]}, {PHONE, EMAIL})
        self.assertEqual(len(state["evidence"]), 4)
        self.assertTrue(state["simulation"])
        chat_meta = state["data"]["tahap2"]["daftar_informasi_terlapor"][0]["upload_bukti_komunikasi"]
        self.assertEqual(chat_meta, state["data"]["tahap2"]["daftar_sumber_media_penipuan"][0]["upload_bukti_sumber_media"])
        self.assertEqual(chat_meta, state["data"]["tahap3"]["upload_bukti_pendukung_kejadian"])
        self.assertTrue(all(meta["size_bytes"] < 900_000 for meta in state["evidence"]))
        state = self.fill_contacts()
        self.assertEqual(state["state"], IntakeState.CONFIRM)
        self.assertEqual(state["missing_slots"], [])
        self.assertEqual(state["data"]["tahap1"]["konfirmasi_nomor_telepon_pelapor"], "800000000000")
        self.assertEqual(state["data"]["tahap1"]["konfirmasi_email_pelapor"], "pelapor.dummy@example.com")
        self.assertEqual(self.confirm()["state"], IntakeState.EKYC)
        response = self.client.post(self.url + "/verify-ekyc", json={"simulate": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.state = response.json()
        self.assertEqual(self.state["state"], IntakeState.DISPATCH)
        self.assertFalse(self.state["ekyc"]["identity_verified_for_production"])
        response = self.client.post(self.url + "/submit", json=self.submit_body())
        self.assertEqual(response.status_code, 200, response.text)
        dom = response.json()
        self.assertEqual(dom["mode"], "DOM_AUTOFILL")
        self.assertEqual(dom["dom_mapping"]["target"], "LOCAL_REPLICA_ONLY")
        self.assertFalse(dom["dom_mapping"]["submit_automatically"])
        self.assertFalse(dom["submitted"])
        self.assertEqual(set(dom["data"]), {f"tahap{i}" for i in range(1, 6)})
        response = self.client.post(self.url + "/submit", json=self.submit_body("webhook"))
        self.assertEqual(response.status_code, 200, response.text)
        webhook = response.json()
        self.assertTrue(webhook["ticket_number"].startswith("SIM-"))
        self.assertEqual(webhook["freeze_status"], "SIMULATED_NO_BANK_ACTION")
        self.assertEqual(webhook["amount_ring_fencing"], "NOT_EXECUTED")
        self.assertEqual(webhook["multi_hop_tracing"], "NOT_EXECUTED")
        self.assertFalse(webhook["submitted"])
        self.assertEqual(self.client.post(self.url + "/submit", json=self.submit_body("webhook")).json(), webhook)
        status = self.client.get(self.url + "/status").json()
        self.assertEqual(status["result"]["ticket_number"], webhook["ticket_number"])

    def test_stage_transitions_cannot_be_skipped(self):
        self.assertEqual(self.client.post(self.url + "/chat", json={"confirm": True}).status_code, 409)
        self.assertEqual(self.client.post(self.url + "/verify-ekyc", json={"simulate": True}).status_code, 409)
        self.assertEqual(self.client.post(self.url + "/submit", json=self.submit_body()).status_code, 409)
        self.upload(("ktp",))
        self.assertEqual(self.state["state"], IntakeState.EVIDENCE)
        self.assertEqual(self.client.post(self.url + "/chat", json={"confirm": True}).status_code, 409)

    def test_manual_values_survive_ocr_and_invalid_patch_is_atomic(self):
        response = self.client.post(self.url + "/chat", json={"values": {TARGET_ACCOUNT: "9999999999"}})
        self.assertEqual(response.status_code, 200)
        state = self.upload()
        self.assertEqual(get_path(state["data"], TARGET_ACCOUNT), "9999999999")
        self.assertEqual(state["sources"][TARGET_ACCOUNT], "manual")
        self.assertEqual(state["confidence"][TARGET_ACCOUNT], 1.0)
        original_data, revision = deepcopy(state["data"]), state["revision"]
        response = self.client.post(self.url + "/chat", json={"values": {EMAIL: "changed@example.com", TARGET_ACCOUNT: "bad digits"}})
        self.assertEqual(response.status_code, 422)
        state = self.client.get(self.url).json()
        self.assertEqual(state["data"], original_data)
        self.assertEqual(state["revision"], revision)

    def test_low_confidence_digits_require_human_answer_before_confirmation(self):
        original_extract = LLMGatewayService.extract

        async def uncertain_extract(gateway, kind, data, mime):
            result = await original_extract(gateway, kind, data, mime)
            if kind == "bukti_transfer":
                result.confidence[TARGET_ACCOUNT] = 0.6
            return result

        with patch.object(LLMGatewayService, "extract", uncertain_extract):
            self.upload()
        state = self.fill_contacts()
        self.assertEqual(state["state"], IntakeState.DELTA)
        self.assertEqual(state["missing_slots"], [{"path": TARGET_ACCOUNT, "reason": "low_confidence", "label": "Nomor rekening terlapor", "question": "Mohon periksa dan konfirmasi Nomor rekening terlapor."}])
        self.assertEqual(self.client.post(self.url + "/chat", json={"confirm": True}).status_code, 409)
        response = self.client.post(self.url + "/chat", json={"text": "0000000001"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["confidence"][TARGET_ACCOUNT], 1.0)
        self.assertEqual(response.json()["state"], IntakeState.CONFIRM)

    def test_edit_invalidates_confirmation_ekyc_and_previous_dispatch(self):
        self.ready()
        response = self.client.post(self.url + "/submit", json=self.submit_body())
        self.assertEqual(response.status_code, 200)
        response = self.client.post(self.url + "/chat", json={"values": {EMAIL: "changed@example.com"}})
        self.assertEqual(response.status_code, 200)
        state = response.json()
        self.assertEqual(state["state"], IntakeState.CONFIRM)
        self.assertFalse(state["confirmed"])
        self.assertFalse(state["ekyc"]["verified"])
        self.assertIsNone(self.client.get(self.url + "/status").json()["result"])
        self.assertEqual(self.client.post(self.url + "/submit", json=self.submit_body()).status_code, 409)
        self.confirm()
        self.assertEqual(self.client.post(self.url + "/verify-ekyc", json={"simulate": True}).status_code, 200)

    def test_real_ekyc_and_low_liveness_are_not_accepted(self):
        self.upload()
        self.fill_contacts()
        self.confirm()
        self.assertEqual(self.client.post(self.url + "/verify-ekyc", json={"simulate": False, "liveness_score": 1.0}).status_code, 501)
        self.assertEqual(self.client.post(self.url + "/verify-ekyc", json={"simulate": True, "liveness_score": 0.89}).status_code, 422)
        self.assertFalse(self.client.get(self.url).json()["ekyc"]["verified"])

    def test_observed_identity_and_account_name_mismatch_rejected(self):
        original_extract = LLMGatewayService.extract

        async def different_name(gateway, kind, data, mime):
            result = await original_extract(gateway, kind, data, mime)
            if kind == "bukti_rekening_korban":
                result.values["tahap4.nama_pemilik_rekening_akun_korban"] = "ORANG BERBEDA"
            return result

        with patch.object(LLMGatewayService, "extract", different_name):
            self.upload()
        self.fill_contacts()
        self.confirm()
        response = self.client.post(self.url + "/verify-ekyc", json={"simulate": True})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertFalse(self.client.get(self.url).json()["ekyc"]["verified"])

    def test_manually_changing_name_cannot_bypass_observed_evidence(self):
        self.upload()
        self.fill_contacts()
        response = self.client.post(self.url + "/chat", json={"values": {"tahap1.nama_pelapor": "NAMA DIUBAH", "tahap4.nama_pemilik_rekening_akun_korban": "NAMA DIUBAH"}})
        self.assertEqual(response.status_code, 200)
        self.confirm()
        self.assertEqual(self.client.post(self.url + "/verify-ekyc", json={"simulate": True}).status_code, 422)

    def test_consent_and_captcha_must_be_explicit_and_valid(self):
        self.ready()
        self.assertEqual(self.client.post(self.url + "/submit", json=self.submit_body(setuju_syarat_dan_ketentuan=False)).status_code, 422)
        self.assertEqual(self.client.post(self.url + "/submit", json=self.submit_body(setuju_syarat_dan_ketentuan="true")).status_code, 422)
        for _ in range(5):
            self.assertEqual(self.client.post(self.url + "/submit", json=self.submit_body(captcha_answer="999")).status_code, 422)
        self.assertEqual(self.client.post(self.url + "/submit", json=self.submit_body()).status_code, 429)
        self.assertIsNone(self.client.get(self.url + "/status").json()["result"])

    def test_evidence_is_session_owned_and_metadata_cannot_be_forged(self):
        self.upload()
        proof = self.state["evidence"][0]
        response = self.client.get(proof["url"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/jpeg")
        other = self.new_session()
        self.assertEqual(self.client.get(f'/api/v1/session/{other["session_id"]}/files/{proof["file_id"]}').status_code, 404)
        self.assertEqual(self.client.post(self.url + "/chat", json={"values": {"tahap1.upload_kartu_identitas_korban": proof}}).status_code, 422)
        self.fill_contacts()
        self.confirm()
        self.assertEqual(self.client.post(self.url + "/verify-ekyc", json={"simulate": True}).status_code, 200)
        SESSIONS[self.session_id].data["tahap1"]["upload_kartu_identitas_korban"]["sha256"] = "0" * 64
        response = self.client.post(self.url + "/submit", json=self.submit_body())
        self.assertEqual(response.status_code, 422)
        self.assertIn("Lampiran", response.json()["detail"])

    def test_failed_upload_batch_rolls_back_data_evidence_and_confirmation(self):
        self.ready()
        original = self.client.get(self.url).json()
        files = self.files(("ktp",))
        files["bukti_chat"] = ("bad.png", b"<script>invalid</script>", "image/png")
        response = self.client.post(self.url + "/upload", files=files)
        self.assertEqual(response.status_code, 422)
        state = self.client.get(self.url).json()
        for key in ("data", "confidence", "sources", "evidence", "revision", "confirmed", "ekyc"):
            self.assertEqual(state[key], original[key], key)

    def test_gateway_failure_never_replaces_current_data_or_falls_back_to_dummy(self):
        self.upload(("ktp",))
        original = self.client.get(self.url).json()
        with patch.object(LLMGatewayService, "extract", new=AsyncMock(side_effect=GatewayError("Gateway unavailable"))):
            response = self.client.post(self.url + "/upload", files=self.files(("bukti_transfer",)))
        self.assertEqual(response.status_code, 502)
        state = self.client.get(self.url).json()
        for key in ("data", "evidence", "sources", "confidence", "revision"):
            self.assertEqual(state[key], original[key], key)

    def test_replacement_evidence_updates_vision_facts_and_removes_absent_facts(self):
        original_extract = LLMGatewayService.extract
        amount_path = "tahap4.daftar_penyelenggara_terlapor.0.daftar_rincian_transaksi.0.nominal_transaksi"
        transfer_count = 0

        async def replacement_extract(gateway, kind, data, mime):
            nonlocal transfer_count
            result = await original_extract(gateway, kind, data, mime)
            if kind == "bukti_transfer":
                transfer_count += 1
                result.simulated = False
                if transfer_count > 1:
                    result.values[TARGET_ACCOUNT] = "1111111111"
                    result.values.pop(amount_path)
                    result.confidence.pop(amount_path)
            return result

        with patch.object(LLMGatewayService, "extract", replacement_extract):
            state = self.upload()
            self.assertEqual(get_path(state["data"], TARGET_ACCOUNT), "0000000001")
            self.assertEqual(state["sources"][TARGET_ACCOUNT], "vision:bukti_transfer")
            state = self.upload(("bukti_transfer",))
        self.assertEqual(get_path(state["data"], TARGET_ACCOUNT), "1111111111")
        self.assertIsNone(get_path(state["data"], amount_path))
        self.assertNotIn(amount_path, state["confidence"])
        self.assertNotIn(amount_path, state["sources"])
        self.assertIn(amount_path, {item["path"] for item in state["missing_slots"]})
        self.assertEqual(state["state"], IntakeState.DELTA)

    def test_replacement_evidence_preserves_manual_account_correction(self):
        self.upload()
        response = self.client.post(self.url + "/chat", json={"values": {TARGET_ACCOUNT: "9999999999"}})
        self.assertEqual(response.status_code, 200)
        original_extract = LLMGatewayService.extract

        async def replacement_extract(gateway, kind, data, mime):
            result = await original_extract(gateway, kind, data, mime)
            result.simulated = False
            result.values[TARGET_ACCOUNT] = "1111111111"
            return result

        with patch.object(LLMGatewayService, "extract", replacement_extract):
            state = self.upload(("bukti_transfer",))
        self.assertEqual(get_path(state["data"], TARGET_ACCOUNT), "9999999999")
        self.assertEqual(state["sources"][TARGET_ACCOUNT], "manual")
        self.assertEqual(state["confidence"][TARGET_ACCOUNT], 1.0)

    def test_remote_chat_retains_uncertainty_until_direct_human_confirmation(self):
        self.upload()
        response = self.client.post(self.url + "/chat", json={"values": {PHONE: "800000000000"}})
        self.assertEqual(response.status_code, 200)
        extraction = ExtractionResult(values={EMAIL: "pelapor.dummy@example.com"}, confidence={EMAIL: 0.5}, simulated=False)
        with patch.object(LLMGatewayService, "extract_chat", new=AsyncMock(return_value=extraction)):
            response = self.client.post(self.url + "/chat", json={"text": "email saya pelapor.dummy@example.com"})
        self.assertEqual(response.status_code, 200, response.text)
        state = response.json()
        self.assertEqual(state["state"], IntakeState.DELTA)
        self.assertEqual(state["confidence"][EMAIL], 0.5)
        self.assertEqual(state["sources"][EMAIL], "chat_ai")
        self.assertIn({"path": EMAIL, "reason": "low_confidence"}, [{"path": item["path"], "reason": item["reason"]} for item in state["missing_slots"]])
        self.assertEqual(self.client.post(self.url + "/chat", json={"confirm": True}).status_code, 409)
        response = self.client.post(self.url + "/chat", json={"values": {EMAIL: "pelapor.dummy@example.com"}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], IntakeState.CONFIRM)
        self.assertEqual(response.json()["confidence"][EMAIL], 1.0)

    def test_passport_to_ktp_requires_valid_nik_in_same_atomic_patch(self):
        response = self.client.post(self.url + "/chat", json={"values": {"tahap1.jenis_identitas": "Paspor", "tahap1.nomor_identitas": "A12345"}})
        self.assertEqual(response.status_code, 200, response.text)
        original = response.json()
        response = self.client.post(self.url + "/chat", json={"values": {"tahap1.jenis_identitas": "KTP", EMAIL: "changed@example.com"}})
        self.assertEqual(response.status_code, 422)
        state = self.client.get(self.url).json()
        for key in ("data", "sources", "confidence", "revision"):
            self.assertEqual(state[key], original[key], key)
        response = self.client.post(self.url + "/chat", json={"values": {"tahap1.jenis_identitas": "KTP", "tahap1.nomor_identitas": "0000000000000000"}})
        self.assertEqual(response.status_code, 200, response.text)

    def test_unresolved_ocr_location_has_zero_confidence_and_needs_confirmation(self):
        city_path, province_path = "tahap1.kota_domisili_pelapor", "tahap1.provinsi_domisili_pelapor"
        original_extract = LLMGatewayService.extract

        async def unresolved_location(gateway, kind, data, mime):
            result = await original_extract(gateway, kind, data, mime)
            if kind == "ktp":
                result.values[province_path] = "Provinsi Contoh Belum Terpetakan"
                result.values[city_path] = "Kota Contoh Belum Terpetakan"
                result.simulated = False
            return result

        with patch.object(LLMGatewayService, "extract", unresolved_location):
            self.upload()
        state = self.fill_contacts()
        self.assertEqual(state["state"], IntakeState.DELTA)
        errors = {item["path"]: item for item in state["missing_slots"]}
        for path in (city_path, province_path):
            self.assertEqual(state["confidence"][path], 0.0)
            self.assertEqual(errors[path]["reason"], "low_confidence")
            self.assertIn("konfirmasi", errors[path]["question"])
        response = self.client.post(self.url + "/chat", json={"values": {province_path: "DKI Jakarta", city_path: "Kota Adm. Jakarta Pusat"}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], IntakeState.CONFIRM)

    def test_known_city_with_mismatched_manual_province_is_rejected_atomically(self):
        self.upload()
        original = self.client.get(self.url).json()
        response = self.client.post(self.url + "/chat", json={"values": {"tahap1.provinsi_domisili_pelapor": "Jawa Barat", "tahap1.kota_domisili_pelapor": "Kota Adm. Jakarta Pusat", EMAIL: "changed@example.com"}})
        self.assertEqual(response.status_code, 422)
        state = self.client.get(self.url).json()
        for key in ("data", "sources", "confidence", "revision"):
            self.assertEqual(state[key], original[key], key)

    def test_sessions_are_isolated_expire_and_delete_with_files(self):
        self.upload(("ktp",))
        file_url = self.state["evidence"][0]["url"]
        other = self.new_session()
        self.assertEqual(other["data"]["tahap1"], {})
        self.assertEqual(other["evidence"], [])
        self.assertEqual(self.client.delete(self.url).status_code, 204)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.get(file_url).status_code, 404)
        other_id = other["session_id"]
        SESSIONS[other_id].touched -= SESSION_TTL + 1
        self.assertEqual(self.client.get("/api/v1/session/" + other_id).status_code, 404)
        self.assertNotIn(other_id, SESSIONS)

    def test_external_webhook_denied_before_network(self):
        self.ready()
        for url in ("https://iasc.ojk.go.id/api/report", "http://example.com/report", "http://user:pass@127.0.0.1/report", "http://127.0.0.1/report?redirect=https://example.com"):
            with self.subTest(url=url), patch.dict(os.environ, {"IASC_WEBHOOK_URL": url}), patch.object(main.httpx.AsyncClient, "post", new=AsyncMock()) as network:
                response = self.client.post(self.url + "/submit", json=self.submit_body("webhook"))
                self.assertEqual(response.status_code, 403, response.text)
                network.assert_not_called()

    def test_wrong_origin_and_untrusted_host_are_rejected(self):
        response = self.client.post(self.url + "/chat", json={"values": {EMAIL: "private@example.com"}}, headers={"Origin": "https://example.com"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get(self.url, headers={"Host": "example.com"}).status_code, 400)
        self.assertEqual(self.client.post(self.url + "/chat", json={"values": {EMAIL: "private-invalid-value"}}).status_code, 422)
        self.assertNotIn("private-invalid-value", self.client.post(self.url + "/chat", json={"unknown": "private-invalid-value"}).text)


if __name__ == "__main__":
    unittest.main()
