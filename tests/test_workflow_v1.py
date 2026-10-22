"""Sequential ASGI workflow and safety checks; official reporting is never invoked."""

from copy import deepcopy
import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import main
from services.llm_gateway import GatewayError, LLMGatewayService
from services.image_processor import ImageProcessingError
from services.orchestrator import IntakeState, SESSIONS, SESSION_TTL, MAX_SESSIONS, get_path

PHONE = "tahap1.nomor_telepon_pelapor"
EMAIL = "tahap1.email_pelapor"
TARGET_ACCOUNT = "tahap4.daftar_penyelenggara_terlapor.0.nomor_rekening_akun"
STORY = "Pada 19 Oktober 2026 pukul 10:00, saya membeli sepatu lewat WhatsApp tetapi barang tidak dikirim."


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(main.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def setUp(self):
        env = patch.dict(os.environ, {"AI_MODE": "simulation", "AI_API_KEY": "", "IASC_WEBHOOK_URL": ""})
        env.start()
        self.addCleanup(env.stop)
        SESSIONS.clear()
        self.addCleanup(SESSIONS.clear)
        self.state = self.new_session()
        self.session_id = self.state["session_id"]
        self.url = "/api/v1/session/" + self.session_id

    def new_session(self):
        response = self.client.post("/api/v1/session/init", json={})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def send(self, text="", **body):
        response = self.client.post(self.url + "/chat", json={"text": text, **body})
        self.assertEqual(response.status_code, 200, response.text)
        self.state = response.json()
        return self.state

    def file(self, kind="ktp"):
        return {"file": (kind + ".png", (main.ROOT / "fixtures/v1" / (kind + ".png")).read_bytes(), "image/png")}

    def upload(self, kind):
        response = self.client.post(self.url + "/upload", files=self.file(kind))
        self.assertEqual(response.status_code, 200, response.text)
        self.state = response.json()
        return self.state

    def phase2(self):
        self.send("Ya, saya sendiri")
        self.upload("ktp")
        return self.send("08123456789, pelapor.dummy@example.com")

    def phase3(self):
        self.phase2()
        self.upload("bukti_chat")
        return self.send(action="continue")

    def phase4(self):
        self.phase3()
        self.send(STORY)
        self.send(action="skip_police")
        return self.upload("bukti_rekening_korban")

    def ready(self):
        self.phase4()
        self.upload("bukti_transfer")
        return self.send(action="continue")

    def answer(self):
        left, _, right, _ = self.state["captcha_question"].split()
        return str(int(left) + int(right))

    def submit_body(self, mode="dom", **updates):
        return {"setuju_syarat_dan_ketentuan": True, "captcha_answer": self.answer(), "integration_mode": mode, **updates}

    def assert_atomic(self, before):
        after = self.client.get(self.url).json()
        for key in ("state", "data", "confidence", "sources", "evidence", "revision", "result"):
            self.assertEqual(after[key], before[key], key)

    def test_happy_path_progressive_fields_and_typed_local_captcha(self):
        self.assertEqual(self.state["state"], IntakeState.STATUS)
        self.assertEqual(self.state["active_wizard_step"], 1)
        self.assertIsNone(self.state["expected_upload_type"])
        self.assertEqual(self.state["dom_patches"], [])
        status = self.send("Ya, saya sendiri")
        self.assertEqual(status["expected_upload_type"], "ktp")
        self.assertEqual([patch["path"] for patch in status["dom_patches"]], ["tahap1.apakah_mengalami_sendiri"])
        ktp = self.upload("ktp")
        self.assertEqual(ktp["state"], IntakeState.CONTACT)
        self.assertEqual(ktp["data"]["tahap4"], {})
        self.assertTrue(all(item["step"] == 1 for item in ktp["dom_patches"]))
        self.assertIn("tahap1.upload_kartu_identitas_korban", [item["path"] for item in ktp["dom_patches"]])
        contact = self.send("08123456789, pelapor.dummy@example.com")
        self.assertEqual(contact["active_wizard_step"], 2)
        self.assertEqual(len(contact["dom_patches"]), 4)
        self.assertEqual(contact["data"]["tahap1"]["konfirmasi_nomor_telepon_pelapor"], "8123456789")
        chat = self.upload("bukti_chat")
        self.assertEqual(chat["state"], IntakeState.CHAT_MORE)
        self.assertEqual(chat["data"]["tahap3"], {})
        proof = chat["data"]["tahap2"]["daftar_informasi_terlapor"][0]["upload_bukti_komunikasi"]
        self.assertEqual(proof, chat["data"]["tahap2"]["daftar_sumber_media_penipuan"][0]["upload_bukti_sumber_media"])
        self.send(action="continue")
        story = self.send(STORY)
        self.assertEqual(story["active_wizard_step"], 3)
        self.assertIn("sepatu", story["data"]["tahap3"]["kronologi_kejadian_penipuan"])
        self.assertEqual(story["data"]["tahap3"]["upload_bukti_pendukung_kejadian"], proof)
        self.send("Lewati / Belum Ada")
        self.upload("bukti_rekening_korban")
        self.upload("bukti_transfer")
        final = self.send("Lanjut ke Tahap 5")
        self.assertEqual(final["state"], IntakeState.CONFIRM)
        self.assertEqual(final["active_wizard_step"], 5)
        self.assertFalse(final["data"]["tahap5"]["setuju_syarat_dan_ketentuan"])
        self.assertNotIn("captcha_answer", final["data"]["tahap5"])
        with patch.object(main.httpx.AsyncClient, "post", new=AsyncMock()) as network:
            completed = self.send(self.answer())
            network.assert_not_called()
        self.assertEqual(completed["state"], IntakeState.COMPLETED)
        self.assertTrue(completed["result"]["ticket_number"].startswith("SIM-"))
        self.assertFalse(completed["result"]["submitted"])
        self.assertTrue(completed["data"]["tahap5"]["setuju_syarat_dan_ketentuan"])
        self.assertFalse(completed["ekyc"]["verified"])
        self.assertEqual({p["path"] for p in completed["dom_patches"]}, {"tahap5.setuju_syarat_dan_ketentuan", "tahap5.captcha_answer"})

    def test_stage_transitions_cannot_be_skipped_or_choose_client_upload_kind(self):
        before = deepcopy(self.state)
        self.assertEqual(self.client.post(self.url + "/upload", files=self.file()).status_code, 409)
        self.assertEqual(self.client.post(self.url + "/chat", json={"action": "continue"}).status_code, 422)
        self.assertEqual(self.client.post(self.url + "/submit", json=self.submit_body()).status_code, 409)
        self.assertEqual(self.client.post(self.url + "/verify-ekyc", json={"simulate": True}).status_code, 409)
        self.assert_atomic(before)
        self.send("Ya, saya sendiri")
        response = self.client.post(self.url + "/upload", files={"ktp": self.file()["file"]})
        self.assertEqual(response.status_code, 422)

    def test_representative_status_is_not_overwritten_by_ktp_extraction(self):
        self.send("Tidak, saya mewakili korban")
        self.upload("ktp")
        self.assertEqual(self.state["data"]["tahap1"]["apakah_mengalami_sendiri"], "Tidak, saya mewakili korban")

    def test_get_snapshot_returns_all_draft_patches_for_recovery(self):
        self.phase2()
        response = self.client.get(self.url).json()
        self.assertTrue(response["dom_patches"])
        self.assertIn("tahap1.nama_pelapor", {item["path"] for item in response["dom_patches"]})
        self.assertTrue(all(".file_id" not in item["path"] for item in response["dom_patches"]))

    def test_missing_chat_digits_are_requested_before_more_chat_choice(self):
        self.phase2()
        original = LLMGatewayService.extract
        path = "tahap2.daftar_informasi_terlapor.0.nomor_terlapor"
        async def absent(gateway, kind, data, mime):
            result = await original(gateway, kind, data, mime)
            result.values.pop(path, None)
            result.confidence.pop(path, None)
            return result
        with patch.object(LLMGatewayService, "extract", absent):
            self.upload("bukti_chat")
        self.assertEqual(self.state["state"], IntakeState.TERLAPOR)
        self.assertEqual(self.state["next_slot"], path)
        self.assertIsNone(self.state["expected_upload_type"])
        self.send("081111111111")
        self.assertEqual(self.state["state"], IntakeState.CHAT_MORE)

    def test_low_confidence_account_cannot_advance_until_human_confirmation(self):
        self.phase4()
        original = LLMGatewayService.extract
        async def uncertain(gateway, kind, data, mime):
            result = await original(gateway, kind, data, mime)
            result.confidence[TARGET_ACCOUNT] = 0.6
            return result
        with patch.object(LLMGatewayService, "extract", uncertain):
            self.upload("bukti_transfer")
        self.assertEqual(self.state["state"], IntakeState.TRANSFER_DETAILS)
        self.assertEqual(self.state["next_slot"], TARGET_ACCOUNT)
        self.assertIn(get_path(self.state["data"], TARGET_ACCOUNT), self.state["assistant_message"])
        self.send(action="confirm_value")
        self.assertEqual(self.state["state"], IntakeState.TRANSFER_MORE)
        self.assertEqual(self.state["confidence"][TARGET_ACCOUNT], 1.0)
        detail = get_path(self.state["data"], "tahap4.daftar_penyelenggara_terlapor.0.daftar_rincian_transaksi.0")
        self.assertGreaterEqual(detail["extraction_confidence"], 0.85)

    def test_chronology_without_time_requests_actual_incident_date(self):
        self.phase3()
        self.send("Saya ditipu ketika membeli sepatu di Instagram.")
        self.assertEqual(self.state["state"], IntakeState.KEJADIAN)
        self.assertEqual(self.state["next_slot"], "tahap3.tanggal_dan_waktu_kejadian")
        self.assertNotIn("tanggal_dan_waktu_kejadian", self.state["data"]["tahap3"])
        self.send("19 Oktober 2026 09:15")
        self.assertEqual(self.state["state"], IntakeState.POLICE)
        self.assertIn("sepatu", self.state["data"]["tahap3"]["kronologi_kejadian_penipuan"])

    def test_optional_police_image_upload_attaches_without_ocr(self):
        self.phase3()
        self.send(STORY)
        with patch.object(LLMGatewayService, "extract", new=AsyncMock()) as ocr:
            self.upload("bukti_chat")
            ocr.assert_not_called()
        self.assertEqual(self.state["state"], IntakeState.ACCOUNT)
        self.assertTrue(self.state["data"]["tahap3"]["upload_laporan_kepolisian"]["file_id"])
        self.assertEqual(self.state["dom_patches"][0]["path"], "tahap3.upload_laporan_kepolisian")

    def test_extra_chat_appends_rows_and_reuses_each_corresponding_file(self):
        self.phase2()
        first = self.upload("bukti_chat")
        first_id = first["evidence"][-1]["file_id"]
        self.send(action="more_chat")
        second = self.upload("bukti_chat")
        rows = second["data"]["tahap2"]["daftar_informasi_terlapor"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["upload_bukti_komunikasi"]["file_id"], first_id)
        self.assertNotEqual(rows[0]["upload_bukti_komunikasi"]["file_id"], rows[1]["upload_bukti_komunikasi"]["file_id"])
        self.assertTrue(all(".1." in item["path"] for item in second["dom_patches"]))

    def test_extra_transfer_same_recipient_appends_transaction_not_overwrites(self):
        self.phase4()
        first = self.upload("bukti_transfer")
        first_detail = deepcopy(get_path(first["data"], "tahap4.daftar_penyelenggara_terlapor.0.daftar_rincian_transaksi.0"))
        self.send(action="more_transfer")
        second = self.upload("bukti_transfer")
        rows = second["data"]["tahap4"]["daftar_penyelenggara_terlapor"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]["daftar_rincian_transaksi"]), 2)
        self.assertEqual(rows[0]["daftar_rincian_transaksi"][0], first_detail)
        self.assertNotEqual(rows[0]["daftar_rincian_transaksi"][1]["upload_bukti_pendukung_kejadian"]["file_id"], first_detail["upload_bukti_pendukung_kejadian"]["file_id"])
        self.assertTrue(all("daftar_rincian_transaksi.1." in item["path"] for item in second["dom_patches"]))

    def test_extra_transfer_new_recipient_appends_recipient(self):
        self.phase4()
        self.upload("bukti_transfer")
        self.send(action="more_transfer")
        original = LLMGatewayService.extract
        async def another(gateway, kind, data, mime):
            result = await original(gateway, kind, data, mime)
            result.values[TARGET_ACCOUNT] = "1111111111"
            return result
        with patch.object(LLMGatewayService, "extract", another):
            self.upload("bukti_transfer")
        rows = self.state["data"]["tahap4"]["daftar_penyelenggara_terlapor"]
        self.assertEqual([row["nomor_rekening_akun"] for row in rows], ["0000000001", "1111111111"])

    def test_manual_correction_is_preserved_and_invalid_update_is_atomic(self):
        self.send(values={"tahap1.nama_pelapor": "NAMA KOREKSI"})
        self.send("Ya, saya sendiri")
        self.upload("ktp")
        self.assertEqual(self.state["data"]["tahap1"]["nama_pelapor"], "NAMA KOREKSI")
        before = deepcopy(self.state)
        response = self.client.post(self.url + "/chat", json={"values": {EMAIL: "changed@example.com", TARGET_ACCOUNT: "bad digits"}})
        self.assertEqual(response.status_code, 422)
        self.assert_atomic(before)

    def test_manual_edit_invalidates_ticket_and_requires_new_typed_completion(self):
        self.ready()
        completed = self.send(self.answer())
        old_ticket = completed["result"]["ticket_number"]
        edited = self.send(values={EMAIL: "changed@example.com"})
        self.assertEqual(edited["state"], IntakeState.CONFIRM)
        self.assertIsNone(edited["result"])
        self.assertFalse(edited["data"]["tahap5"]["setuju_syarat_dan_ketentuan"])
        self.assertIn({"op": "set", "path": "tahap5.captcha_answer", "value": None, "step": 5}, edited["dom_patches"])
        self.assertFalse(edited["ekyc"]["verified"])
        self.send(self.answer())
        self.assertNotEqual(self.state["result"]["ticket_number"], old_ticket)

    def test_bad_image_and_failed_gateway_roll_back_entire_upload(self):
        self.send("Ya, saya sendiri")
        before = deepcopy(self.state)
        response = self.client.post(self.url + "/upload", files={"file": ("bad.png", b"<script>invalid</script>", "image/png")})
        self.assertEqual(response.status_code, 422)
        self.assert_atomic(before)
        with patch("main.extract_ktp_locally", side_effect=ImageProcessingError("OCR unavailable")):
            response = self.client.post(self.url + "/upload", files=self.file())
        self.assertEqual(response.status_code, 422)
        self.assert_atomic(before)
        self.assertEqual(SESSIONS[self.session_id].files, {})
        self.upload("ktp")
        self.send("08123456789, pelapor.dummy@example.com")
        before = deepcopy(self.state)
        with patch.object(LLMGatewayService, "extract", new=AsyncMock(side_effect=GatewayError("Gateway unavailable"))):
            response = self.client.post(self.url + "/upload", files=self.file("bukti_chat"))
        self.assertEqual(response.status_code, 502)
        self.assert_atomic(before)

    def test_evidence_owned_by_session_and_forged_reference_rejected(self):
        self.ready()
        proof = self.state["evidence"][0]
        self.assertEqual(self.client.get(proof["url"]).status_code, 200)
        other = self.new_session()
        self.assertEqual(self.client.get(f'/api/v1/session/{other["session_id"]}/files/{proof["file_id"]}').status_code, 404)
        self.assertEqual(self.client.post(self.url + "/chat", json={"values": {"tahap1.upload_kartu_identitas_korban": proof}}).status_code, 422)
        SESSIONS[self.session_id].data["tahap1"]["upload_kartu_identitas_korban"]["sha256"] = "0" * 64
        response = self.client.post(self.url + "/chat", json={"text": self.answer()})
        self.assertEqual(response.status_code, 422)
        self.assertIn("Lampiran", response.json()["detail"])

    def test_captcha_attempt_limit_and_explicit_local_consent(self):
        self.ready()
        self.assertEqual(self.client.post(self.url + "/submit", json=self.submit_body(setuju_syarat_dan_ketentuan=False)).status_code, 422)
        self.assertEqual(self.client.post(self.url + "/submit", json=self.submit_body(setuju_syarat_dan_ketentuan="true")).status_code, 422)
        for _ in range(5):
            self.assertEqual(self.client.post(self.url + "/chat", json={"text": "999"}).status_code, 422)
        self.assertEqual(self.client.post(self.url + "/chat", json={"text": self.answer()}).status_code, 429)
        self.assertIsNone(self.client.get(self.url).json()["result"])
        self.assertFalse(self.client.get(self.url).json()["data"]["tahap5"]["setuju_syarat_dan_ketentuan"])

    def test_submit_endpoint_returns_idempotent_local_result(self):
        self.ready()
        response = self.client.post(self.url + "/submit", json=self.submit_body("dom"))
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        self.assertEqual(result["dom_mapping"]["target"], "LOCAL_REPLICA_ONLY")
        self.assertFalse(result["dom_mapping"]["submit_automatically"])
        repeated = self.client.post(self.url + "/submit", json=self.submit_body("dom"))
        self.assertEqual(repeated.json()["result"], result)
        self.assertFalse(result["submitted"])

    def test_optional_ekyc_is_never_a_production_identity_claim(self):
        self.ready()
        self.assertEqual(self.client.post(self.url + "/verify-ekyc", json={"simulate": False}).status_code, 501)
        self.assertEqual(self.client.post(self.url + "/verify-ekyc", json={"simulate": True, "liveness_score": 0.89}).status_code, 422)
        verified = self.client.post(self.url + "/verify-ekyc", json={"simulate": True}).json()
        self.assertTrue(verified["ekyc"]["verified"])
        self.assertFalse(verified["ekyc"]["identity_verified_for_production"])
        self.send(values={"tahap1.nama_pelapor": "NAMA DIUBAH", "tahap4.nama_pemilik_rekening_akun_korban": "NAMA DIUBAH"})
        self.assertEqual(self.client.post(self.url + "/verify-ekyc", json={"simulate": True}).status_code, 422)

    def test_external_webhook_denied_before_network(self):
        self.ready()
        for url in ("https://iasc.ojk.go.id/api/report", "http://example.com/report", "http://user:pass@127.0.0.1/report", "http://127.0.0.1/report?redirect=https://example.com"):
            with self.subTest(url=url), patch.dict(os.environ, {"IASC_WEBHOOK_URL": url}), patch.object(main.httpx.AsyncClient, "post", new=AsyncMock()) as network:
                response = self.client.post(self.url + "/submit", json=self.submit_body("webhook"))
                self.assertEqual(response.status_code, 403, response.text)
                network.assert_not_called()
        self.assertIsNone(self.client.get(self.url).json()["result"])

    def test_local_webhook_mock_still_available(self):
        self.ready()
        response = self.client.post(self.url + "/submit", json=self.submit_body("webhook"))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["result"]["freeze_status"], "SIMULATED_NO_BANK_ACTION")
        self.assertFalse(response.json()["result"]["submitted"])

    def test_passport_to_ktp_and_mismatched_location_rejected_atomically(self):
        self.send(values={"tahap1.jenis_identitas": "Paspor", "tahap1.nomor_identitas": "A12345"})
        before = deepcopy(self.state)
        self.assertEqual(self.client.post(self.url + "/chat", json={"values": {"tahap1.jenis_identitas": "KTP", EMAIL: "changed@example.com"}}).status_code, 422)
        self.assert_atomic(before)
        self.assertEqual(self.client.post(self.url + "/chat", json={"values": {"tahap1.provinsi_domisili_pelapor": "Jawa Barat", "tahap1.kota_domisili_pelapor": "Kota Adm. Jakarta Pusat"}}).status_code, 422)
        self.assert_atomic(before)

    def test_sessions_expire_delete_files_and_enforce_limits(self):
        self.send("Ya, saya sendiri")
        self.upload("ktp")
        file_url = self.state["evidence"][0]["url"]
        self.assertEqual(self.client.delete(self.url).status_code, 204)
        self.assertEqual(self.client.get(file_url).status_code, 404)
        other = self.new_session()
        SESSIONS[other["session_id"]].touched -= SESSION_TTL + 1
        self.assertEqual(self.client.get("/api/v1/session/" + other["session_id"]).status_code, 404)
        for _ in range(MAX_SESSIONS):
            self.new_session()
        self.assertEqual(self.client.post("/api/v1/session/init", json={}).status_code, 503)

    def test_upload_count_and_mutation_rate_limits(self):
        self.send("Ya, saya sendiri")
        oversized = self.client.post(self.url + "/upload", content=b"", headers={"Content-Length": str(12 * 1024 * 1024)})
        self.assertEqual(oversized.status_code, 413)
        session = SESSIONS[self.session_id]
        session.files = {str(i): {} for i in range(12)}
        self.assertEqual(self.client.post(self.url + "/upload", files=self.file()).status_code, 413)
        session.files.clear()
        session.mutations = [session.touched] * 60
        self.assertEqual(self.client.post(self.url + "/chat", json={"text": "hello"}).status_code, 429)

    def test_cross_origin_untrusted_host_and_private_error_echo_rejected(self):
        response = self.client.post(self.url + "/chat", json={"values": {EMAIL: "private@example.com"}}, headers={"Origin": "https://example.com"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get(self.url, headers={"Host": "example.com"}).status_code, 400)
        response = self.client.post(self.url + "/chat", json={"unknown": "private-invalid-value"})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("private-invalid-value", response.text)


if __name__ == "__main__":
    unittest.main()
