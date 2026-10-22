"""Local intake prototype. There is deliberately no IASC submission client."""

import asyncio
import io
import os
from pathlib import Path
import re
import secrets
import shutil
import time
import warnings
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from services.image_processor import ImageProcessingError, local_ocr_text
from services.guardrails import GuardrailViolation, REFUSAL_MESSAGE, check_user_input, is_within_reporting_scope, looks_like_ktp

ROOT = Path(__file__).resolve().parent
JAKARTA = timezone(timedelta(hours=7))
MAX_UPLOAD = 3 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 12_000_000
SESSIONS = {}
SESSION_TTL = 30 * 60
OCR_LIMIT = asyncio.Semaphore(2)


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    pelapor_nama: str | None = Field(None, min_length=2, max_length=120)
    pelapor_email: str | None = Field(None, max_length=200, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    pelapor_telepon: str | None = Field(None, pattern=r"^\+?[0-9]{8,15}$")
    pelapor_nik: str | None = Field(None, pattern=r"^[0-9]{16}$")
    pelapor_alamat: str | None = Field(None, min_length=3, max_length=500)
    terlapor_nama: str | None = Field(None, min_length=2, max_length=120)
    terlapor_kontak: str | None = Field(None, min_length=3, max_length=200)
    kategori_modus: str | None = Field(None, pattern=r"^(BELANJA_ONLINE|PHISHING|APK_MALWARE|INVESTASI|LAINNYA)$")
    kronologi: str | None = Field(None, min_length=20, max_length=4000)
    bank_pengirim: str | None = Field(None, min_length=2, max_length=100)
    rekening_pengirim: str | None = Field(None, pattern=r"^[0-9]{6,30}$")
    bank_penerima: str | None = Field(None, min_length=2, max_length=100)
    rekening_penerima: str | None = Field(None, pattern=r"^[0-9]{6,30}$")
    nominal: int | None = Field(None, strict=True, gt=0, le=10_000_000_000_000)
    waktu_transaksi: str | None = Field(None, max_length=40)
    rrn: str | None = Field(None, pattern=r"^[0-9A-Za-z-]{6,40}$")


FIELDS = [
    ("pelapor_nama", "Nama pelapor", 1, "text", "Siapa nama pelapornya? Gunakan nama dummy untuk mencoba.", "PELAPOR DUMMY"),
    ("pelapor_email", "Email pelapor", 1, "email", "Ke email mana pembaruan dapat ditujukan? Untuk demo, gunakan example.com.", "pelapor.dummy@example.com"),
    ("pelapor_telepon", "Nomor telepon", 1, "tel", "Berapa nomor telepon pelapor? Isi angka tanpa spasi.", "080000000000"),
    ("pelapor_nik", "NIK pelapor", 1, "text", "Isi 16 digit NIK dummy. PoC ini tidak memverifikasi identitas.", "0000000000000000"),
    ("pelapor_alamat", "Alamat pelapor", 1, "text", "Alamat pelapor", "Alamat Dummy, Kota Contoh"),
    ("terlapor_nama", "Nama terlapor", 2, "text", "Apa nama pihak terlapor yang tercantum dalam bukti?", "TERLAPOR DUMMY"),
    ("terlapor_kontak", "Kontak / akun terlapor", 2, "text", "Kontak terlapor", "akun-dummy.example"),
    ("kategori_modus", "Modus kejadian", 3, "select", "Bagaimana modusnya? Pilih kategori yang paling sesuai.", "BELANJA_ONLINE"),
    ("kronologi", "Kronologi singkat", 3, "textarea", "Ceritakan singkat bagaimana kejadian bermula dan apa yang terjadi setelah transfer.", "DATA DUMMY: Saya memesan barang di situs contoh, lalu melakukan transfer fiktif. Barang dalam skenario ini tidak diterima. Tidak ada kejadian nyata."),
    ("bank_pengirim", "Bank pengirim", 4, "text", "Dari bank atau layanan apa transfer dilakukan?", "BANK DEMO A"),
    ("rekening_pengirim", "Rekening pengirim", 4, "text", "Berapa nomor rekening pengirim?", "0000000000"),
    ("bank_penerima", "Bank penerima", 4, "text", "Apa bank atau layanan penerimanya?", "BANK DEMO B"),
    ("rekening_penerima", "Rekening penerima", 4, "text", "Berapa nomor rekening penerima? Periksa setiap digitnya.", "0000000001"),
    ("nominal", "Nominal transaksi", 4, "text", "Berapa nominal transfer dalam rupiah? Contoh: 100.000.", "100000"),
    ("waktu_transaksi", "Waktu transaksi (WIB)", 4, "datetime-local", "Kapan transfer dilakukan? Gunakan format 2026-10-19 10:00, dalam WIB.", "2026-10-19T10:00"),
    ("rrn", "Nomor referensi / RRN", 4, "text", "Nomor referensi transaksi", "000000000001"),
]
OPTIONAL = {"pelapor_alamat", "terlapor_kontak", "rrn"}
REQUIRED = [key for key, *_ in FIELDS if key not in OPTIONAL]
FIELD_MAP = {row[0]: row for row in FIELDS}
CHOICES = {"BELANJA_ONLINE": "Belanja online", "PHISHING": "Tautan phishing", "APK_MALWARE": "Aplikasi APK", "INVESTASI": "Investasi", "LAINNYA": "Lainnya"}
ALIASES = {
    "bank pengirim": "bank_pengirim", "rekening pengirim": "rekening_pengirim",
    "bank penerima": "bank_penerima", "rekening penerima": "rekening_penerima",
    "nama penerima": "terlapor_nama", "nominal": "nominal", "tanggal": "waktu_transaksi", "rrn": "rrn",
}


def normalize(key, value):
    if value is None or value == "":
        return None
    if key == "nominal":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        match = re.fullmatch(r"(?:Rp\s*)?([0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+)(?:,00)?", str(value).strip(), re.I)
        if not match:
            raise ValueError("Nominal harus rupiah bulat, misalnya 100000 atau Rp100.000.")
        return int(match[1].replace(".", ""))
    if not isinstance(value, str):
        raise ValueError("Isi harus berupa teks.")
    value = value.strip()
    if key == "waktu_transaksi":
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2})?(?:Z|[+-][0-9]{2}:[0-9]{2})?", value):
            raise ValueError("Isi tanggal dan jam lengkap: YYYY-MM-DD HH:mm.")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError("Gunakan tanggal dan jam: YYYY-MM-DD HH:mm.") from None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=JAKARTA)
        if parsed > datetime.now(JAKARTA):
            raise ValueError("Waktu transaksi tidak boleh di masa depan.")
        return parsed.astimezone(JAKARTA).isoformat(timespec="seconds")
    if key == "kategori_modus":
        reverse = {label.casefold(): key for key, label in CHOICES.items()}
        return reverse.get(value.casefold(), value.upper())
    return value


def validated(data):
    try:
        return Draft.model_validate({k: normalize(k, v) for k, v in data.items()}).model_dump()
    except (ValidationError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            key = str(exc.errors()[0]["loc"][0])
            label = FIELD_MAP.get(key, (key, key))[1]
            raise HTTPException(422, f"Periksa {label}. Format atau panjang isian belum sesuai.") from None
        raise HTTPException(422, str(exc)) from None


def get_session(token):
    now = time.monotonic()
    for expired in [key for key, value in SESSIONS.items() if now - value["touched"] > SESSION_TTL]:
        del SESSIONS[expired]
    session = SESSIONS.get(token)
    if session is None:
        raise HTTPException(404, "Sesi berakhir atau tidak ditemukan. Mulai sesi baru.")
    session["touched"] = now
    return session


def question(data):
    missing = [key for key in REQUIRED if data.get(key) is None]
    return FIELD_MAP[missing[0]][4] if missing else "Data inti sudah lengkap. Tinjau hasil OCR dan koreksi nomor rekening, nominal, serta waktu sebelum mengunduh draft."


def state(session):
    return {
        "data": session["data"], "sources": session["sources"], "evidence": session["evidence"],
        "missing": [key for key in REQUIRED if session["data"].get(key) is None],
        "question": question(session["data"]), "submission_enabled": False,
    }


def apply_values(session, patch, source, only_empty=False):
    if only_empty:
        patch = {k: v for k, v in patch.items() if session["data"].get(k) is None and v is not None}
    # Validate the entire patch before modifying the session, so failed edits never lose data.
    merged = validated({**session["data"], **patch})
    session["data"] = merged
    for key, value in patch.items():
        if value is None or value == "":
            session["sources"].pop(key, None)
        else:
            session["sources"][key] = source


def image_png(raw):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in {"PNG", "JPEG", "WEBP"}:
                    raise HTTPException(415, "Gunakan gambar PNG, JPG, atau WebP.")
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                clean = ImageOps.exif_transpose(image).convert("RGB")
                clean.thumbnail((3000, 3000))
                buffer = io.BytesIO()
                clean.save(buffer, "PNG")
                return buffer.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning, ValueError):
        raise HTTPException(422, "Gambar rusak atau terlalu besar. Coba gambar lain.") from None


def local_ocr(png):
    try:
        return local_ocr_text(png)
    except ImageProcessingError as exc:
        raise HTTPException(503, str(exc)) from None


def extract_local(text):
    # shortcut: local extraction recognizes labelled receipts; enable a tested VLM for varied bank layouts.
    patch = {}
    for line in text.splitlines():
        label, separator, value = line.partition(":")
        key = ALIASES.get(label.strip().casefold())
        if separator and key and key not in patch:
            try:
                normalized = normalize(key, value)
                Draft.model_validate({key: normalized})
                patch[key] = normalized
            except (ValueError, ValidationError):
                continue
    return patch


def remote_enabled():
    # The retired draft API stays local; cloud extraction has one guarded gateway.
    return False


async def gateway_extract(text, png=None, *, context=None):
    """The legacy endpoint cannot bypass the guarded API v1 extractor."""
    raise HTTPException(403, REFUSAL_MESSAGE)


app = FastAPI(title="IASC Intake Lab", version="0.1.0", docs_url=None, redoc_url=None, description="PoC lokal. Tidak ada pengiriman laporan atau pemblokiran rekening.")


@app.middleware("http")
async def response_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    nonce = getattr(request.state, "csp_nonce", None)
    nonce_source = " 'nonce-" + nonce + "'" if nonce else ""
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'" + nonce_source + "; style-src 'self'" + nonce_source + "; img-src 'self' blob: data:; "
        "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'self'; frame-ancestors "
        + os.getenv("EMBED_ORIGINS", "'self' http://localhost:* http://127.0.0.1:*")
    )
    return response


@app.get("/api/config")
def config():
    return {"mode": "remote" if remote_enabled() else "local", "ocr_available": bool(shutil.which("tesseract")),
            "submission_enabled": False, "fields": [dict(zip(("key", "label", "phase", "type", "question", "example"), row), required=row[0] in REQUIRED) for row in FIELDS], "choices": CHOICES}


@app.post("/api/sessions", status_code=201)
def create_session():
    # shortcut: process memory, one worker; use an authenticated TTL store before multi-user deployment.
    now = time.monotonic()
    for key in [k for k, v in SESSIONS.items() if now - v["touched"] > SESSION_TTL]:
        del SESSIONS[key]
    if len(SESSIONS) >= 200:
        raise HTTPException(503, "Sesi demo sedang penuh. Coba lagi nanti.")
    token = secrets.token_urlsafe(32)
    session = {"data": Draft().model_dump(), "sources": {}, "evidence": None, "touched": now}
    SESSIONS[token] = session
    return {"session_id": token, **state(session)}


@app.get("/api/sessions/{token}")
def read_session(token: str):
    return state(get_session(token))


class Patch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict = Field(max_length=16)


@app.patch("/api/sessions/{token}")
def edit_session(token: str, patch: Patch):
    session = get_session(token)
    try:
        for key in patch.values:
            check_user_input(key, allow_scalar=True)
        values = {key: check_user_input(value, allow_scalar=key != "kronologi") if isinstance(value, str) else value for key, value in patch.values.items()}
    except GuardrailViolation:
        return {**state(session), "reply": REFUSAL_MESSAGE, "question": REFUSAL_MESSAGE}
    apply_values(session, values, "manual")
    return state(session)


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)


@app.post("/api/sessions/{token}/messages")
async def message(token: str, message: Message):
    session = get_session(token)
    missing = [key for key in REQUIRED if session["data"].get(key) is None]
    try:
        text = check_user_input(message.text, allow_scalar=bool(missing) and missing[0] != "kronologi")
    except GuardrailViolation:
        return {**state(session), "reply": REFUSAL_MESSAGE, "question": REFUSAL_MESSAGE}
    if not missing:
        return {**state(session), "reply": "Data inti sudah lengkap. Gunakan tombol edit pada ringkasan untuk memperbaiki isian."}
    apply_values(session, {missing[0]: text}, "chat")
    return {**state(session), "reply": "Terima kasih, sudah dicatat. " + question(session["data"])}


@app.post("/api/sessions/{token}/evidence")
async def evidence(token: str, request: Request):
    session = get_session(token)
    if len(request.headers.get("content-type", "")) > 100 or request.headers.get("content-type", "").split(";")[0] not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(415, "Unggah gambar PNG, JPG, atau WebP, maksimum 3 MB.")
    if request.headers.get("content-length", "").isdigit() and int(request.headers["content-length"]) > MAX_UPLOAD:
        raise HTTPException(413, "Ukuran gambar maksimum 3 MB.")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_UPLOAD:
            raise HTTPException(413, "Ukuran gambar maksimum 3 MB.")
    async with OCR_LIMIT:
        png = await run_in_threadpool(image_png, bytes(raw))
        text = await run_in_threadpool(local_ocr, png)
        if not is_within_reporting_scope(text) or looks_like_ktp(text):
            return {**state(session), "reply": REFUSAL_MESSAGE, "question": REFUSAL_MESSAGE}
        patch, source = extract_local(text), "ocr"
    before = dict(session["data"])
    apply_values(session, patch, source, only_empty=True)
    changed = [k for k, v in session["data"].items() if v != before[k]]
    session["evidence"] = {"text": text, "fields_found": len(changed), "review_required": True}
    reply = (f"{len(changed)} isian baru terbaca dari bukti. Hasil ekstraksi perlu Anda periksa. " if changed else "Belum ada isian baru yang terbaca. Anda dapat melengkapi data lewat chat. ") + question(session["data"])
    return {**state(session), "reply": reply}


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewed: bool


@app.post("/api/sessions/{token}/draft")
def export_draft(token: str, review: Review):
    session = get_session(token)
    if not review.reviewed or state(session)["missing"]:
        raise HTTPException(422, "Lengkapi data wajib dan tinjau isian sebelum mengunduh draft.")
    return JSONResponse({"schema_version": "poc-0.1", "mode": "DRAFT_ONLY", "submitted": False,
                         "identity_verified": False, "user_reviewed": True,
                         "generated_at": datetime.now(JAKARTA).isoformat(), "data": session["data"], "sources": session["sources"]},
                        headers={"Content-Disposition": 'attachment; filename="iasc-draft-dummy.json"'})


@app.delete("/api/sessions/{token}", status_code=204)
def delete_session(token: str):
    get_session(token)
    del SESSIONS[token]


@app.get("/assistant")
@app.get("/widget")
def index():
    return RedirectResponse("/Guest/LaporanV2?assistant=1", status_code=307)


@app.get("/")
@app.get("/Guest")
def replica_home():
    return FileResponse(ROOT / "static/replica/home.html")


@app.get("/Guest/LaporanV2")
def replica_report():
    return FileResponse(ROOT / "static/replica/report.html")


@app.get("/Guest/CekLaporan")
def replica_check():
    return FileResponse(ROOT / "static/replica/check.html")


@app.get("/integration")
def integration():
    return FileResponse(ROOT / "static/integration.html")


@app.get("/docs")
def docs():
    return FileResponse(ROOT / "static/docs.html")


@app.get("/fixtures/bukti-dummy.png")
def dummy_image():
    return FileResponse(ROOT / "fixtures/bukti-dummy.png")


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
