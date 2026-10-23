"""Run with uvicorn main:app. Official reporting and bank actions are disabled."""

import asyncio
from copy import copy, deepcopy
import hashlib
import os
from pathlib import Path
import re
import secrets
import unicodedata
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import File, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)

from app import app  # Reuse the existing replica, assets and legacy draft API.
from schemas import FileMetadata, LaporanIASC
from services.image_processor import ImageProcessingError, process_image, smart_file_reuse
from services.ktp_ocr import extract_ktp_locally
from services.llm_gateway import ExtractionResult, GatewayError, LLMGatewayService
from services.guardrails import (
    GuardrailViolation, check_user_input, detect_prompt_injection,
    is_clearly_out_of_scope, is_reporting_help, sanitize_user_text,
)
from services.orchestrator import (
    EVIDENCE_KINDS, IntakeState, SESSIONS, advance, apply_patch, build_report,
    flattened, get_path, invalidate, new_session, rate_limit, session_for,
    set_path, snapshot, stage_errors, sync_derived, UPLOAD_STATES, current_errors,
    prepare_confirmation, normalize_patch, guardrail_refusal, reporting_guidance,
)

app.title = "IASC Local Replica · Hybrid AI Intake"
app.version = "1.0.0-poc"
app.description = "Help Center percakapan dengan pengisian formulir lima tahap secara progresif. Seluruh tiket adalah simulasi lokal tanpa tindakan bank."
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])
UPLOAD_CONCURRENCY = asyncio.Semaphore(2)


@app.exception_handler(RequestValidationError)
async def safe_validation_error(request, exc):
    # Validation responses must not echo NIK, contact data, evidence or provider output.
    return JSONResponse({"detail": "Format permintaan belum sesuai.", "fields": [".".join(map(str, item["loc"])) for item in exc.errors()]}, status_code=422)


@app.middleware("http")
async def local_boundaries(request: Request, call_next):
    if request.method in {"POST", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Gunakan API dari origin layanan intake yang sama."}, status_code=403)
        maximum = 11 * 1024 * 1024 if request.url.path.endswith("/upload") else 128 * 1024
        length = request.headers.get("content-length")
        if length is None and request.method != "DELETE":
            return JSONResponse({"detail": "Content-Length wajib disertakan."}, status_code=411)
        if length is not None and (not length.isdigit() or int(length) > maximum):
            return JSONResponse({"detail": "Ukuran permintaan melewati batas."}, status_code=413)
    return await call_next(request)


def gateway():
    try:
        return LLMGatewayService()
    except GatewayError as exc:
        raise HTTPException(503, str(exc)) from None


def view(session, before=None):
    return snapshot(session, simulated=getattr(session, "simulated_extraction", True), before=before)


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ChatInput(InputModel):
    text: str = Field(default="", max_length=2000)
    values: dict[str, object] = Field(default_factory=dict, max_length=100)
    confirm: StrictBool = False
    action: str = Field(default="", max_length=40)


class EKYCInput(InputModel):
    simulate: StrictBool = True
    liveness_score: float = Field(default=0.98, ge=0, le=1, allow_inf_nan=False)


class SubmitInput(InputModel):
    setuju_syarat_dan_ketentuan: StrictBool
    captcha_answer: str = Field(min_length=1, max_length=3, pattern=r"^[0-9]+$")
    integration_mode: str = Field(default="dom", pattern=r"^(dom|webhook)$")


@app.post("/api/v1/session/init", status_code=201)
async def initialize():
    llm = gateway()
    session = new_session()
    session.simulated_extraction = llm.simulated
    return view(session)


@app.get("/api/v1/session/{session_id}")
async def read_session_v1(session_id: str):
    session = session_for(session_id)
    async with session.lock:
        return view(session, before={})


@app.delete("/api/v1/session/{session_id}", status_code=204)
async def delete_session_v1(session_id: str):
    session = session_for(session_id)
    async with session.lock:
        del SESSIONS[session_id]


def candidate_session(session):
    candidate = copy(session)
    for name in ("data", "confidence", "sources", "files", "evidence", "ekyc", "dispatch"):
        setattr(candidate, name, deepcopy(getattr(session, name)))
    return candidate


def commit_session(session, candidate):
    for name, value in candidate.__dict__.items():
        if name not in {"lock", "mutations", "touched"}:
            setattr(session, name, value)


def remap_evidence(session, kind, values, confidences, metadata):
    """Append new evidence rows; a second transfer must not replace the first."""
    pointers = smart_file_reuse(kind, metadata)
    if kind == "bukti_chat":
        values = {path: value for path, value in values.items() if path.startswith("tahap2.")}
        pointers = {path: value for path, value in pointers.items() if path.startswith("tahap2.")}
        offsets = {name: len(session.data["tahap2"].get(name, [])) for name in ("daftar_informasi_terlapor", "daftar_sumber_media_penipuan")}
        def target(path):
            parts = path.split(".")
            parts[2] = str(int(parts[2]) + offsets[parts[1]])
            return ".".join(parts)
    elif kind == "bukti_transfer":
        prefix = "tahap4.daftar_penyelenggara_terlapor."
        values = {path: value for path, value in values.items() if path.startswith(prefix)}
        normalized = normalize_patch(values)
        rows = session.data["tahap4"].get("daftar_penyelenggara_terlapor", [])
        bank = normalized.get(prefix + "0.nama_penyelenggara")
        account = normalized.get(prefix + "0.nomor_rekening_akun")
        row_index = next((index for index, row in enumerate(rows) if bank and account and row.get("nama_penyelenggara") == bank and row.get("nomor_rekening_akun") == account), len(rows))
        detail_index = len(rows[row_index].get("daftar_rincian_transaksi", [])) if row_index < len(rows) else 0
        if row_index < len(rows):
            values = {path: value for path, value in values.items()
                      if ".daftar_rincian_transaksi." in path or get_path(session.data, prefix + str(row_index) + "." + path.split(".")[-1]) is None}
        def target(path):
            parts = path.split(".")
            parts[2] = str(row_index + int(parts[2]))
            if len(parts) > 4 and parts[3] == "daftar_rincian_transaksi":
                parts[4] = str(detail_index + int(parts[4]))
            return ".".join(parts)
    else:
        stage = "tahap1." if kind == "ktp" else "tahap4."
        values = {path: value for path, value in values.items() if path.startswith(stage) and path != "tahap1.apakah_mengalami_sendiri"}
        target = lambda path: path
    return ({target(path): value for path, value in values.items()},
            {target(path): confidences[path] for path in values},
            {target(path): value for path, value in pointers.items()})


@app.post("/api/v1/session/{session_id}/upload")
async def upload_evidence(session_id: str, file: UploadFile = File(...)):
    session = session_for(session_id)
    async with session.lock:
        rate_limit(session)
        kind = UPLOAD_STATES.get(session.state)
        if not kind:
            await file.close()
            raise HTTPException(409, "Jawab pertanyaan saat ini terlebih dahulu; belum ada dokumen yang diminta.")
        if len(session.files) >= 12:
            await file.close()
            raise HTTPException(413, "Batas 12 unggahan per sesi. Mulai sesi baru untuk bukti tambahan.")
        llm = None if kind in {"ktp", "laporan_kepolisian"} else gateway()
        try:
            async with UPLOAD_CONCURRENCY:
                raw = await file.read(10 * 1024 * 1024 + 1)
                image = await run_in_threadpool(process_image, raw, file.filename or "bukti", file.content_type or "")
                if kind == "ktp":
                    values, confidence = await run_in_threadpool(extract_ktp_locally, image.data)
                    result = ExtractionResult(values=values, confidence=confidence, simulated=False)
                else:
                    result = None if kind == "laporan_kepolisian" else await llm.extract(kind, image.data, image.mime_type)
        except GuardrailViolation:
            return guardrail_refusal(session, simulated=getattr(session, "simulated_extraction", True))
        except (ImageProcessingError, GatewayError) as exc:
            raise HTTPException(422 if isinstance(exc, ImageProcessingError) else 502, str(exc)) from None
        finally:
            await file.close()
        candidate = candidate_session(session)
        before = deepcopy(session.data)
        invalidate(candidate)
        file_id = secrets.token_urlsafe(24)
        metadata = FileMetadata(file_id=file_id, filename=image.filename, content_type=image.mime_type, size_bytes=image.size, sha256=image.sha256, url=f"/api/v1/session/{session_id}/files/{file_id}").model_dump(mode="json")
        candidate.files[file_id] = {"metadata": deepcopy(metadata), "data": image.data}
        candidate.evidence[kind] = metadata
        if result:
            values, confidence, pointers = remap_evidence(candidate, kind, result.values, result.confidence, metadata)
            source = "simulation:" if result.simulated else "local_ocr:" if kind == "ktp" else "vision:"
            apply_patch(candidate, values, confidence, source + kind)
        else:
            pointers = smart_file_reuse(kind, metadata)
        for path, reference in pointers.items():
            set_path(candidate.data, path, reference)
        if kind == "ktp":
            candidate.observed_identity_name = result.values.get("tahap1.nama_pelapor")
            for path, value in {"tahap1.kewarganegaraan_pelapor": "Indonesia", "tahap1.kode_negara_telepon_pelapor": "Indonesia (+62)", "tahap1.jenis_identitas": "KTP"}.items():
                if not get_path(candidate.data, path):
                    set_path(candidate.data, path, value)
            candidate.state = IntakeState.PELAPOR
        elif kind == "bukti_chat":
            candidate.state = IntakeState.TERLAPOR
        elif kind == "bukti_rekening_korban":
            candidate.observed_account_name = result.values.get("tahap4.nama_pemilik_rekening_akun_korban")
            if not get_path(candidate.data, "tahap4.nama_pemilik_rekening_akun_korban"):
                path = "tahap4.nama_pemilik_rekening_akun_korban"
                set_path(candidate.data, path, get_path(candidate.data, "tahap1.nama_pelapor"))
                candidate.confidence[path] = 0.0
                candidate.sources[path] = "default"
            candidate.state = IntakeState.ACCOUNT_DETAILS
        elif kind == "bukti_transfer":
            candidate.state = IntakeState.TRANSFER_DETAILS
        else:
            candidate.state = IntakeState.ACCOUNT
        if llm is not None:
            candidate.simulated_extraction = llm.simulated
        sync_derived(candidate)
        advance(candidate)
        response = view(candidate, before)
        commit_session(session, candidate)
        return response


@app.get("/api/v1/session/{session_id}/files/{file_id}")
async def evidence_file(session_id: str, file_id: str):
    session = session_for(session_id)
    stored = session.files.get(file_id)
    if not stored:
        raise HTTPException(404, "File tidak ditemukan dalam sesi ini.")
    return Response(stored["data"], media_type=stored["metadata"]["content_type"], headers={"Content-Disposition": "inline"})


@app.post("/api/v1/session/{session_id}/chat")
async def chat_v1(session_id: str, body: ChatInput):
    session = session_for(session_id)
    async with session.lock:
        rate_limit(session)
        try:
            text = sanitize_user_text(body.text) if body.text else ""
            if text and (detect_prompt_injection(body.text) or detect_prompt_injection(text) or is_clearly_out_of_scope(text)):
                raise GuardrailViolation()
            action = check_user_input(body.action, allow_scalar=True) if body.action else ""
            for path in body.values:
                check_user_input(path, allow_scalar=True)
            values = {path: check_user_input(value, allow_scalar=not path.endswith(".kronologi_kejadian_penipuan"), allow_report_context=path.endswith(".kronologi_kejadian_penipuan")) if isinstance(value, str) else value for path, value in body.values.items()}
            # Clarification belongs to the local workflow, never to an account/name slot.
            continuation = text.casefold().strip(" .!?") in {"lanjut", "lanjutkan", "boleh lanjut", "sudah cukup"}
            if text and not body.values and not body.action and not body.confirm:
                if continuation and session.state in {IntakeState.CHAT_MORE, IntakeState.TRANSFER_MORE}:
                    action = "continue"
                elif continuation or is_reporting_help(text):
                    return reporting_guidance(session, text, simulated=getattr(session, "simulated_extraction", True))
            if text and not (continuation and action == "continue"):
                text = check_user_input(text, allow_scalar=session.state != IntakeState.CHRONOLOGY,
                                        allow_report_context=session.state == IntakeState.CHRONOLOGY)
            if body.action:
                allowed_states = {
                    "continue": {IntakeState.CHAT_MORE, IntakeState.TRANSFER_MORE},
                    "more_chat": {IntakeState.CHAT_MORE}, "more_transfer": {IntakeState.TRANSFER_MORE},
                    "skip_police": {IntakeState.POLICE},
                }
                missing = current_errors(session)
                confirm_current = action == "confirm_value" and missing and missing[0]["reason"] == "low_confidence"
                if not confirm_current and session.state not in allowed_states.get(action, set()):
                    raise HTTPException(422, reporting_guidance(session, text)["assistant_message"])
            action = action or text
            candidate = candidate_session(session)
            before = deepcopy(session.data)
            advance(candidate)
            normalized = action.casefold()
            if body.values:
                if body.confirm:
                    raise HTTPException(422, "Simpan koreksi terlebih dahulu sebelum konfirmasi.")
                was_final = candidate.state in {IntakeState.CONFIRM, IntakeState.COMPLETED}
                apply_patch(candidate, values, {}, "manual", manual=True)
                if was_final:
                    prepare_confirmation(candidate)
            elif candidate.state == IntakeState.STATUS:
                if normalized in {"ya, saya sendiri", "ya", "sendiri", "saya sendiri"}:
                    status = "Ya, saya sendiri"
                elif normalized in {"tidak, saya mewakili korban", "tidak", "mewakili", "saya mewakili korban"}:
                    status = "Tidak, saya mewakili korban"
                else:
                    raise HTTPException(422, "Pilih apakah Anda mengalami sendiri atau mewakili korban.")
                apply_patch(candidate, {"tahap1.apakah_mengalami_sendiri": status}, {}, "manual", manual=True)
                candidate.state = IntakeState.KTP
            elif current_errors(candidate) and action == "confirm_value" and current_errors(candidate)[0]["reason"] == "low_confidence":
                path = current_errors(candidate)[0]["path"]
                apply_patch(candidate, {path: get_path(candidate.data, path)}, {}, "manual", manual=True)
            elif candidate.state == IntakeState.CONTACT:
                result = await gateway().extract_contacts(text)
                if not result.values:
                    raise HTTPException(422, "Ketik nomor telepon aktif dan email Anda.")
                apply_patch(candidate, result.values, result.confidence, "chat" if result.simulated else "chat_ai", manual=result.simulated)
            elif candidate.state == IntakeState.CHAT_MORE:
                if action == "more_chat" or "bukti chat lain" in normalized:
                    candidate.state = IntakeState.CHAT
                elif action == "continue" or "lanjut" in normalized:
                    candidate.state = IntakeState.CHRONOLOGY
                else:
                    raise HTTPException(422, "Pilih bukti chat lain atau lanjut ke Tahap 3.")
                candidate.revision += 1
            elif candidate.state == IntakeState.CHRONOLOGY:
                result = await gateway().synthesize_chronology(text, {"values": dict(flattened(candidate.data))})
                if not result.values.get("tahap3.kronologi_kejadian_penipuan"):
                    raise HTTPException(422, "Ceritakan kronologi singkat Anda terlebih dahulu.")
                apply_patch(candidate, result.values, result.confidence, "chat" if result.simulated else "chat_ai", manual=result.simulated)
                set_path(candidate.data, "tahap3.upload_bukti_pendukung_kejadian", candidate.evidence["bukti_chat"])
                candidate.chronology_received = True
                candidate.state = IntakeState.KEJADIAN
            elif candidate.state == IntakeState.POLICE:
                if action == "skip_police" or any(word in normalized for word in ("lewati", "belum", "tidak ada")):
                    candidate.data["tahap3"]["upload_laporan_kepolisian"] = None
                    candidate.state = IntakeState.ACCOUNT
                    candidate.revision += 1
                else:
                    raise HTTPException(422, "Unggah gambar laporan polisi melalui lampiran atau pilih Lewati / Belum Ada.")
            elif candidate.state == IntakeState.TRANSFER_MORE:
                if action == "more_transfer" or "transfer lain" in normalized:
                    candidate.state = IntakeState.TRANSFER
                elif action == "continue" or "lanjut" in normalized:
                    prepare_confirmation(candidate)
                else:
                    raise HTTPException(422, "Pilih bukti transfer lain atau lanjut ke Tahap 5.")
                candidate.revision += 1
            elif candidate.state == IntakeState.CONFIRM:
                if body.confirm:
                    candidate.confirmed = True
                else:
                    await finish_local(candidate, text)
            elif candidate.state == IntakeState.COMPLETED:
                raise HTTPException(409, "Laporan dummy sudah selesai. Buat sesi baru untuk laporan lain.")
            elif current_errors(candidate):
                item = current_errors(candidate)[0]
                path = item["path"]
                if action == "confirm_value" and item["reason"] == "low_confidence":
                    apply_patch(candidate, {path: get_path(candidate.data, path)}, {}, "manual", manual=True)
                else:
                    result = await gateway().extract_chat(text, [path], {"values": dict(flattened(candidate.data))})
                    revision = candidate.revision
                    apply_patch(candidate, result.values, result.confidence, "chat" if result.simulated else "chat_ai", manual=result.simulated)
                    if candidate.revision == revision:
                        raise HTTPException(422, "Saya belum menemukan jawaban untuk kolom ini. " + item["question"])
            else:
                raise HTTPException(409, "Silakan unggah satu dokumen yang sedang diminta melalui tombol lampiran.")
        except GuardrailViolation:
            return guardrail_refusal(session, simulated=getattr(session, "simulated_extraction", True))
        except GatewayError as exc:
            raise HTTPException(422, str(exc)) from None
        advance(candidate)
        response = view(candidate, before)
        commit_session(session, candidate)
        return response


def normalized_name(value):
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", unicodedata.normalize("NFKC", value or "").upper()).split())


@app.post("/api/v1/session/{session_id}/verify-ekyc")
async def verify_ekyc(session_id: str, body: EKYCInput):
    session = session_for(session_id)
    async with session.lock:
        rate_limit(session)
        advance(session)
        if session.state not in {IntakeState.CONFIRM, IntakeState.COMPLETED}:
            raise HTTPException(409, "Lengkapi ringkasan terlebih dahulu untuk pemeriksaan simulasi opsional.")
        if not body.simulate:
            raise HTTPException(501, "Adapter e-KYC nyata belum dikonfigurasi. Skor browser tidak boleh dianggap biometrik asli.")
        if get_path(session.data, "tahap1.apakah_mengalami_sendiri") != "Ya, saya sendiri":
            raise HTTPException(422, "Pelaporan perwakilan membutuhkan verifikasi korban dan kuasa melalui formulir manual.")
        identity = normalized_name(session.observed_identity_name)
        account = normalized_name(session.observed_account_name)
        if body.liveness_score < 0.90 or not identity or not account or identity != account:
            raise HTTPException(422, "Simulasi gagal: skor minimal 0,90 dan nama pada bukti identitas/rekening harus cocok.")
        if identity != normalized_name(get_path(session.data, "tahap1.nama_pelapor")) or account != normalized_name(get_path(session.data, "tahap4.nama_pemilik_rekening_akun_korban")):
            raise HTTPException(422, "Nama pada ringkasan berbeda dari bukti. Periksa dokumen kembali.")
        session.ekyc = {"verified": True, "simulated": True, "liveness_score": body.liveness_score, "names_match": True, "identity_verified_for_production": False}
        return view(session)


LOCAL_FIELDS = {
    "tahap1.jenis_kelamin": "pelapor.jenis_kelamin",
    "tahap1.kewarganegaraan_pelapor": "pelapor.kewarganegaraan",
    "tahap1.nama_pelapor": "pelapor.nama", "tahap1.tempat_lahir_pelapor": "pelapor.tempat_lahir",
    "tahap1.tanggal_lahir_pelapor": "pelapor.tanggal_lahir", "tahap1.agama_pelapor": "pelapor.agama",
    "tahap1.pekerjaan_pelapor": "pelapor.pekerjaan", "tahap1.nomor_telepon_pelapor": "pelapor.telepon",
    "tahap1.konfirmasi_nomor_telepon_pelapor": "pelapor.konfirmasi_telepon",
    "tahap1.email_pelapor": "pelapor.email", "tahap1.konfirmasi_email_pelapor": "pelapor.konfirmasi_email",
    "tahap1.jenis_identitas": "pelapor.jenis_identitas", "tahap1.nomor_identitas": "pelapor.nomor_identitas",
    "tahap1.provinsi_domisili_pelapor": "pelapor.provinsi", "tahap1.kota_domisili_pelapor": "pelapor.kota",
    "tahap1.alamat_pelapor": "pelapor.alamat", "tahap3.tanggal_dan_waktu_kejadian": "kejadian.tanggal",
    "tahap3.kronologi_kejadian_penipuan": "kejadian.kronologi",
    "tahap4.nama_penyelenggara_layanan_korban": "transaksi.bank",
    "tahap4.nomor_rekening_akun_korban": "transaksi.rekening",
    "tahap4.nama_pemilik_rekening_akun_korban": "transaksi.nama",
}
LOCAL_FILES = {
    "tahap1.upload_kartu_identitas_korban": "files.identitas",
    "tahap3.upload_bukti_pendukung_kejadian": "files.kejadian",
    "tahap3.upload_laporan_kepolisian": "files.polisi",
    "tahap4.bukti_kepemilikan_rekening_akun_korban": "files.rekening",
}


def dom_mapping(payload):
    selectors = [{"path": path, "phase": int(path[5]), "selector": f'[data-field="{name}"]', "value": get_path(payload, path)} for path, name in LOCAL_FIELDS.items()]
    selectors.extend([
        {"path": "tahap1.apakah_mengalami_sendiri", "phase": 1, "selector": '[name="sendiri"]', "value": payload["tahap1"]["apakah_mengalami_sendiri"], "control": "radio"},
        {"path": "tahap1.kode_negara_telepon_pelapor", "phase": 1, "selector": '[data-field="pelapor.kode_telepon"]', "value": payload["tahap1"]["kode_negara_telepon_pelapor"]},
    ])
    return {
        "target": "LOCAL_REPLICA_ONLY", "submit_automatically": False,
        "selectors": selectors,
        "attachments": [{"path": path, "phase": int(path[5]), "selector": f'[data-file="{name}"]', "file": get_path(payload, path)} for path, name in LOCAL_FILES.items() if get_path(payload, path)],
        "collections": {"informasi_terlapor": payload["tahap2"]["daftar_informasi_terlapor"], "sumber_media": payload["tahap2"]["daftar_sumber_media_penipuan"], "penyelenggara_terlapor": payload["tahap4"]["daftar_penyelenggara_terlapor"]},
        "adapter_event": "iasc-intake:apply-v1",
        "note": "Adapter merender fase dan baris modal dari payload bertipe. Consent/CAPTCHA hanya untuk simulasi lokal. Selector/ID backend resmi memerlukan kontrak dari pemilik ASP.NET.",
    }


@app.post("/api/v1/mock-aspnet/reports")
async def mock_aspnet(payload: LaporanIASC, idempotency_key: str = Header(default="", max_length=128)):
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", idempotency_key):
        raise HTTPException(422, "Kunci idempotensi demo wajib disertakan.")
    ticket = "SIM-" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:12].upper()
    return {"ticket_number": ticket, "freeze_status": "SIMULATED_NO_BANK_ACTION", "simulated": True, "submitted": False, "amount_ring_fencing": "NOT_EXECUTED", "multi_hop_tracing": "NOT_EXECUTED"}


async def dispatch_webhook(payload, session):
    url = os.getenv("IASC_WEBHOOK_URL", "").strip()
    if url:
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise HTTPException(403, "PoC hanya mengizinkan webhook mock pada IP loopback. Endpoint resmi/eksternal dinonaktifkan.")
        transport = None
    else:
        url, transport = "http://testserver/api/v1/mock-aspnet/reports", httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False, timeout=10) as client:
            response = await client.post(url, json=payload, headers={"Idempotency-Key": session.session_id + "_" + str(session.revision)})
            response.raise_for_status()
            result = response.json()
        if not result.get("simulated") or result.get("submitted") is not False or not str(result.get("ticket_number", "")).startswith("SIM-") or result.get("freeze_status") != "SIMULATED_NO_BANK_ACTION":
            raise ValueError("Untrusted dispatch result")
        return result
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise HTTPException(502, "Webhook mock gagal. Status belum dianggap selesai; ulangi dengan sesi yang sama.") from None


async def finish_local(session, answer, *, mode="local"):
    if session.captcha_attempts >= 5:
        raise HTTPException(429, "Batas percobaan CAPTCHA tercapai. Mulai sesi baru.")
    if not re.fullmatch(r"[0-9]{1,3}", answer) or answer != str(sum(session.challenge)):
        # Attempts are committed even when the remainder of the turn fails.
        SESSIONS[session.session_id].captcha_attempts += 1
        raise HTTPException(422, "Jawaban CAPTCHA simulasi lokal salah.")
    if session.dispatch:
        return
    if stage_errors(session) or not session.chronology_received:
        raise HTTPException(409, "Lengkapi seluruh tahap dan kronologi sebelum menyelesaikan demo.")
    try:
        payload = build_report(session, True, answer).model_dump(mode="json")
    except ValidationError:
        raise HTTPException(422, "Laporan belum sesuai kontrak lengkap lima tahap.") from None
    if mode == "webhook":
        result = await dispatch_webhook(payload, session)
    else:
        ticket = "SIM-" + hashlib.sha256((session.session_id + "_" + str(session.revision)).encode()).hexdigest()[:12].upper()
        result = {"ticket_number": ticket, "freeze_status": "SIMULATED_NO_BANK_ACTION", "simulated": True, "submitted": False, "amount_ring_fencing": "NOT_EXECUTED", "multi_hop_tracing": "NOT_EXECUTED"}
    session.data["tahap5"] = payload["tahap5"]
    session.revision += 1
    session.dispatch = {**result, "integration_mode": mode}
    if mode == "dom":
        session.dispatch["dom_mapping"] = dom_mapping(payload)
    session.state = IntakeState.COMPLETED


@app.post("/api/v1/session/{session_id}/submit")
async def submit_v1(session_id: str, body: SubmitInput):
    session = session_for(session_id)
    async with session.lock:
        rate_limit(session)
        if session.state not in {IntakeState.CONFIRM, IntakeState.COMPLETED}:
            raise HTTPException(409, "Lengkapi lima tahap percakapan terlebih dahulu.")
        if body.setuju_syarat_dan_ketentuan is not True:
            raise HTTPException(422, "Persetujuan simulasi wajib diberikan oleh pengguna.")
        before = deepcopy(session.data)
        candidate = candidate_session(session)
        await finish_local(candidate, body.captcha_answer, mode=body.integration_mode)
        response = view(candidate, before)
        commit_session(session, candidate)
        return response


@app.get("/api/v1/session/{session_id}/status")
async def dispatch_status(session_id: str):
    session = session_for(session_id)
    return {"state": session.state, "result": session.dispatch, "simulated": True, "submitted": False}


@app.get("/api/v1/schema")
async def final_schema():
    return LaporanIASC.model_json_schema()


@app.get("/health")
async def health():
    return {"status": "ok", "version": app.version, "simulation": gateway().simulated, "external_dispatch_enabled": False}


@app.get("/widget/iasc-ai-widget.html", response_class=HTMLResponse)
async def widget_html(request: Request):
    nonce = secrets.token_urlsafe(24)
    request.state.csp_nonce = nonce
    source = (ROOT / "widget/iasc-ai-widget.html").read_text()
    source = source.replace("<script>", f'<script nonce="{nonce}">').replace("<style>", f'<style nonce="{nonce}">')
    return HTMLResponse(source)


@app.get("/fixtures/v1/{kind}.png")
async def dummy_fixture(kind: str):
    if kind not in EVIDENCE_KINDS:
        raise HTTPException(404, "Jenis contoh tidak ditemukan.")
    return FileResponse(ROOT / "fixtures/v1" / (kind + ".png"))
