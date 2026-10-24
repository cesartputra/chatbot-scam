"""AI chronology uses session evidence and refreshes only drafts it generated."""

from copy import deepcopy
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import main
from schemas import LaporanIASC
from services.llm_gateway import ExtractionResult, GatewayError
from services.orchestrator import IntakeState, SESSIONS, get_path, new_session
from test_schemas_v1 import valid_payload


STORY = "tahap3.kronologi_kejadian_penipuan"
INCIDENT = "tahap3.tanggal_dan_waktu_kejadian"
RAW = "Pada 19 Oktober 2020 pukul 10:00 saya membeli sepatu, tetapi barang tidak dikirim."
GENERATED = "Pada 19 Oktober 2020 pukul 10:00, pelapor membeli sepatu melalui WhatsApp dari TERLAPOR DUMMY. Barang yang dipesan tidak dikirim."
FINAL = GENERATED + " Bukti transfer mencatat pembayaran Rp100.000 ke rekening BCA milik TERLAPOR DUMMY."
AMOUNT = "tahap4.daftar_penyelenggara_terlapor.0.daftar_rincian_transaksi.0.nominal_transaksi"


def result(story):
    return ExtractionResult(values={STORY: story}, confidence={STORY: 1.0}, simulated=False)


class ChronologyWorkflowTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"AI_MODE": "remote", "AI_API_KEY": "synthetic-test-key", "AI_BASE_URL": "https://example.test/v1"})
        env.start()
        self.addCleanup(env.stop)
        SESSIONS.clear()
        self.addCleanup(SESSIONS.clear)
        self.client = self.enterContext(TestClient(main.app))
        state = self.client.post("/api/v1/session/init", json={}).json()
        self.session = SESSIONS[state["session_id"]]
        self.url = "/api/v1/session/" + state["session_id"]
        self.session.data = LaporanIASC.model_validate(valid_payload()).model_dump(mode="json")
        self.session.data["tahap5"] = {}
        self.session.data["tahap3"]["kronologi_kejadian_penipuan"] = GENERATED
        self.session.sources[STORY] = "chronology_ai"
        self.session.confidence[STORY] = 1.0
        self.session.raw_chronology = RAW
        self.session.evidence_facts = {"chat-file": ["Penjual menawarkan sepatu melalui WhatsApp."]}
        self.session.evidence["bukti_chat"] = deepcopy(self.session.data["tahap2"]["daftar_informasi_terlapor"][0]["upload_bukti_komunikasi"])
        self.session.state = IntakeState.TRANSFER_MORE
        self.ai = SimpleNamespace(simulated=False, synthesize_chronology=AsyncMock(return_value=result(FINAL)))

    def send(self, **body):
        with patch.object(main, "gateway", return_value=self.ai):
            return self.client.post(self.url + "/chat", json=body)

    def assert_unchanged(self, before):
        for name, value in before.items():
            self.assertEqual(getattr(self.session, name), value, name)

    def test_initial_synthesis_preserves_raw_input_and_uses_own_session_facts(self):
        self.session.state = IntakeState.CHRONOLOGY
        self.session.data["tahap3"].pop("kronologi_kejadian_penipuan")
        self.session.raw_chronology = ""
        other = new_session()
        other.evidence_facts = {"other-file": ["PRIVATE OTHER SESSION FACT"]}
        response = self.send(text=RAW)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.session.raw_chronology, RAW)
        self.assertEqual(get_path(response.json()["data"], STORY), FINAL)
        self.assertEqual(self.session.sources[STORY], "chronology_ai")
        supplied, context = self.ai.synthesize_chronology.await_args.args
        self.assertEqual(supplied, RAW)
        self.assertEqual(context["evidence_facts"], self.session.evidence_facts["chat-file"])
        self.assertNotIn("PRIVATE OTHER SESSION FACT", str(context))
        self.assertEqual(context["values"][AMOUNT], "100000")
        self.assertNotIn("raw_chronology", response.json())
        self.assertNotIn("evidence_facts", response.json())

    def test_final_confirmation_refreshes_using_raw_story_and_transaction_context(self):
        response = self.send(action="continue")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], IntakeState.CONFIRM)
        self.assertEqual(get_path(response.json()["data"], STORY), FINAL)
        self.ai.synthesize_chronology.assert_awaited_once()
        supplied, context = self.ai.synthesize_chronology.await_args.args
        self.assertEqual(supplied, RAW)
        self.assertEqual(context["values"][AMOUNT], "100000")
        self.assertEqual(self.session.raw_chronology, RAW)

    def test_manual_story_is_not_overwritten_during_final_confirmation(self):
        self.session.sources[STORY] = "manual"
        response = self.send(action="continue")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(get_path(response.json()["data"], STORY), GENERATED)
        self.ai.synthesize_chronology.assert_not_awaited()

    def test_final_fact_correction_refreshes_once_with_corrected_values(self):
        self.session.state = IntakeState.CONFIRM
        bank = "tahap4.daftar_penyelenggara_terlapor.0.nama_penyelenggara"
        response = self.send(values={bank: "BRI"})
        self.assertEqual(response.status_code, 200, response.text)
        self.ai.synthesize_chronology.assert_awaited_once()
        self.assertEqual(self.ai.synthesize_chronology.await_args.args[1]["values"][bank], "BRI")

    def test_corrected_incident_and_amount_are_supplied_without_overwriting_manual_time(self):
        self.session.state = IntakeState.CONFIRM
        corrected = "20 Oktober 2020 11:00"
        self.ai.synthesize_chronology.return_value = ExtractionResult(
            values={STORY: FINAL, INCIDENT: "19 Oktober 2020 10:00"},
            confidence={STORY: 1.0, INCIDENT: 1.0}, simulated=False,
        )
        response = self.send(values={INCIDENT: corrected, AMOUNT: "320000"})
        self.assertEqual(response.status_code, 200, response.text)
        context = self.ai.synthesize_chronology.await_args.args[1]["values"]
        self.assertEqual(context[INCIDENT], corrected)
        self.assertEqual(context[AMOUNT], "320000")
        self.assertEqual(get_path(response.json()["data"], INCIDENT), corrected)
        self.assertEqual(self.session.sources[INCIDENT], "manual")

    def test_manual_story_in_same_correction_is_preserved_without_refresh(self):
        self.session.state = IntakeState.CONFIRM
        response = self.send(values={STORY: RAW, "tahap4.nama_penyelenggara_layanan_korban": "BRI"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(get_path(response.json()["data"], STORY), RAW)
        self.assertEqual(self.session.sources[STORY], "manual")
        self.ai.synthesize_chronology.assert_not_awaited()

    def test_failed_final_synthesis_preserves_entire_draft(self):
        before = {name: deepcopy(getattr(self.session, name)) for name in (
            "data", "sources", "confidence", "revision", "state", "raw_chronology", "evidence_facts", "confirmed", "dispatch",
        )}
        self.ai.synthesize_chronology.side_effect = GatewayError("Layanan AI tidak tersedia.")
        response = self.send(action="continue")
        self.assertEqual(response.status_code, 422, response.text)
        self.assert_unchanged(before)

    def test_failed_initial_synthesis_does_not_store_raw_story_or_advance(self):
        self.session.state = IntakeState.CHRONOLOGY
        self.session.raw_chronology = ""
        self.session.data["tahap3"].pop("kronologi_kejadian_penipuan")
        before = {name: deepcopy(getattr(self.session, name)) for name in ("data", "revision", "state", "raw_chronology")}
        self.ai.synthesize_chronology.side_effect = GatewayError("Layanan AI tidak tersedia.")
        response = self.send(text=RAW)
        self.assertEqual(response.status_code, 422, response.text)
        self.assert_unchanged(before)

    def test_chat_upload_keeps_visible_facts_private_and_attached_to_its_file(self):
        self.session.state = IntakeState.CHAT
        self.session.data["tahap2"] = {}
        facts = ["Penjual meminta pembayaran untuk pesanan sepatu."]
        self.ai.extract = AsyncMock(return_value=SimpleNamespace(values={}, confidence={}, simulated=False, evidence_facts=facts))
        fixture = main.ROOT / "fixtures/v1/bukti_chat.png"
        with patch.object(main, "gateway", return_value=self.ai):
            response = self.client.post(self.url + "/upload", files={"file": (fixture.name, fixture.read_bytes(), "image/png")})
        self.assertEqual(response.status_code, 200, response.text)
        file_id = self.session.evidence["bukti_chat"]["file_id"]
        self.assertEqual(self.session.evidence_facts[file_id], facts)
        self.assertNotIn("evidence_facts", response.json())
        self.assertEqual(self.session.files[file_id]["metadata"]["file_id"], file_id)

    def test_candidate_evidence_facts_are_isolated_from_session(self):
        candidate = main.candidate_session(self.session)
        candidate.evidence_facts["chat-file"].append("New fact")
        self.assertEqual(len(self.session.evidence_facts["chat-file"]), 1)


if __name__ == "__main__":
    unittest.main()
