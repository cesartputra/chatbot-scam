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
from services.llm_gateway import GatewayError, LLMGatewayService
from services.orchestrator import (
    EVIDENCE_KINDS, IntakeState, SESSIONS, advance, apply_patch, build_report,
    flattened, get_path, invalidate, new_session, rate_limit, session_for,
    set_path, snapshot, stage_errors, sync_derived,
)

app.title = "IASC Local Replica · Hybrid AI Intake"
app.version = "1.0.0-poc"
app.description = "Lima tahap formulir dan Hybrid OCR + Chat. Seluruh tiket dan freeze adalah simulasi lokal."
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
        maximum = 42 * 1024 * 1024 if request.url.path.endswith("/upload") else 128 * 1024
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


def view(session):
    return snapshot(session, simulated=getattr(session, "simulated_extraction", True))


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ChatInput(InputModel):
    text: str = Field(default="", max_length=8000)
    values: dict[str, object] = Field(default_factory=dict, max_length=100)
    confirm: StrictBool = False


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
        return view(session)


@app.delete("/api/v1/session/{session_id}", status_code=204)
async def delete_session_v1(session_id: str):
    session = session_for(session_id)
    async with session.lock:
        del SESSIONS[session_id]


@app.post("/api/v1/session/{session_id}/upload")
async def upload_evidence(
    session_id: str,
    ktp: UploadFile | None = File(None), bukti_transfer: UploadFile | None = File(None),
    bukti_chat: UploadFile | None = File(None), bukti_rekening_korban: UploadFile | None = File(None),
):
    session = session_for(session_id)
    uploads = {key: value for key, value in locals().items() if key in EVIDENCE_KINDS and value is not None}
    if not uploads:
        raise HTTPException(422, "Pilih minimal satu gambar bukti.")
    async with session.lock:
        rate_limit(session)
        if len(session.files) + len(uploads) > 12:
            raise HTTPException(413, "Batas 12 unggahan per sesi. Mulai sesi baru untuk mengganti seluruh bukti.")
        llm = gateway()
        async def extract_one(kind, file):
            async with UPLOAD_CONCURRENCY:
                try:
                    raw = await file.read(10 * 1024 * 1024 + 1)
                    image = await run_in_threadpool(process_image, raw, file.filename or "bukti", file.content_type or "")
                    result = await llm.extract(kind, image.data, image.mime_type)
                    return kind, image, result
                finally:
                    await file.close()
        try:
            results = await asyncio.gather(*(extract_one(kind, file) for kind, file in uploads.items()), return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    raise result
        except (ImageProcessingError, GatewayError) as exc:
            raise HTTPException(422 if isinstance(exc, ImageProcessingError) else 502, str(exc)) from None
        candidate = copy(session)
        for name in ("data", "confidence", "sources", "files", "evidence"):
            setattr(candidate, name, deepcopy(getattr(session, name)))
        invalidate(candidate)
        for kind, image, result in results:
            file_id = secrets.token_urlsafe(24)
            metadata = FileMetadata(file_id=file_id, filename=image.filename, content_type=image.mime_type, size_bytes=image.size, sha256=image.sha256, url=f"/api/v1/session/{session_id}/files/{file_id}").model_dump(mode="json")
            candidate.files[file_id] = {"metadata": metadata, "data": image.data}
            candidate.evidence[kind] = metadata
            # Replacement evidence invalidates its old extracted facts, preserving human corrections.
            for path in list(candidate.sources):
                if candidate.sources[path].endswith(":" + kind):
                    set_path(candidate.data, path, None)
                    candidate.confidence.pop(path, None)
                    candidate.sources.pop(path, None)
            source = ("simulation:" if result.simulated else "vision:") + kind
            apply_patch(candidate, result.values, result.confidence, source)
            for path, file in smart_file_reuse(kind, metadata).items():
                set_path(candidate.data, path, file)
            if kind == "ktp":
                candidate.observed_identity_name = result.values.get("tahap1.nama_pelapor")
            if kind == "bukti_rekening_korban":
                candidate.observed_account_name = result.values.get("tahap4.nama_pemilik_rekening_akun_korban")
        sync_derived(candidate)
        for name in ("data", "confidence", "sources", "files", "evidence", "confirmed", "ekyc", "revision", "dispatch", "observed_identity_name", "observed_account_name"):
            setattr(session, name, getattr(candidate, name))
        session.simulated_extraction = llm.simulated
        return {**view(session), "reply": "Bukti telah diproses. " + ("Hasil dummy terprogram; bukan OCR nyata. " if llm.simulated else "Periksa hasil ekstraksi gambar. ")}


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
        if body.confirm:
            if body.values:
                raise HTTPException(422, "Simpan koreksi terlebih dahulu, lalu konfirmasikan ringkasan.")
            advance(session)
            if session.state != IntakeState.CONFIRM:
                raise HTTPException(409, "Lengkapi seluruh bukti, kolom, dan confidence sebelum konfirmasi.")
            session.confirmed = True
            return view(session)
        if body.values:
            apply_patch(session, body.values, {}, "manual", manual=True)
        elif body.text:
            missing = [item["path"] for item in stage_errors(session)]
            from services.llm_gateway import _path_allowed
            allowed = [path for path in missing if _path_allowed(path)]
            if not allowed:
                raise HTTPException(409, "Unggah bukti yang masih kurang atau tinjau ringkasan.")
            try:
                result = await gateway().extract_chat(body.text, allowed, {"values": dict(flattened(session.data))})
            except GatewayError as exc:
                raise HTTPException(422, str(exc)) from None
            # A direct field edit confirms a value; an LLM interpretation retains its uncertainty.
            apply_patch(session, result.values, result.confidence, "chat" if result.simulated else "chat_ai", manual=result.simulated)
        else:
            raise HTTPException(422, "Isi jawaban atau koreksi kolom.")
        return view(session)


def normalized_name(value):
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", unicodedata.normalize("NFKC", value or "").upper()).split())


@app.post("/api/v1/session/{session_id}/verify-ekyc")
async def verify_ekyc(session_id: str, body: EKYCInput):
    session = session_for(session_id)
    async with session.lock:
        rate_limit(session)
        advance(session)
        if session.state != IntakeState.EKYC:
            raise HTTPException(409, "Konfirmasikan ringkasan lengkap sebelum verifikasi.")
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
        "note": "Adapter merender fase dan baris modal dari payload bertipe. Consent/CAPTCHA host tidak diisi. Selector/ID backend resmi memerlukan kontrak dari pemilik ASP.NET.",
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


@app.post("/api/v1/session/{session_id}/submit")
async def submit_v1(session_id: str, body: SubmitInput):
    session = session_for(session_id)
    async with session.lock:
        rate_limit(session)
        advance(session)
        if session.state != IntakeState.DISPATCH or not session.ekyc.get("verified"):
            raise HTTPException(409, "Konfirmasi ringkasan dan verifikasi simulasi terlebih dahulu.")
        if body.setuju_syarat_dan_ketentuan is not True:
            raise HTTPException(422, "Persetujuan simulasi wajib dicentang oleh pengguna.")
        if session.captcha_attempts >= 5:
            raise HTTPException(429, "Batas percobaan CAPTCHA tercapai. Mulai sesi baru.")
        if body.captcha_answer != str(sum(session.challenge)):
            session.captcha_attempts += 1
            raise HTTPException(422, "Jawaban CAPTCHA lokal salah.")
        if session.dispatch and session.dispatch["integration_mode"] == body.integration_mode:
            return session.dispatch
        try:
            payload = build_report(session, body.setuju_syarat_dan_ketentuan, body.captcha_answer).model_dump(mode="json")
        except ValidationError:
            raise HTTPException(422, "Laporan belum sesuai kontrak lengkap lima tahap.") from None
        if body.integration_mode == "dom":
            result = {"mode": "DOM_AUTOFILL", "dom_mapping": dom_mapping(payload), "submitted": False, "simulated": True, "freeze_status": "NOT_REQUESTED"}
        else:
            result = {"mode": "WEBHOOK_MOCK", **await dispatch_webhook(payload, session)}
        session.data["tahap5"] = payload["tahap5"]
        session.dispatch = {**result, "integration_mode": body.integration_mode, "data": payload, "ekyc": session.ekyc}
        return session.dispatch


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
