"""Deterministic intake state; LLM output is evidence, never workflow authority."""

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
import secrets
import time
import re

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from schemas import (
    FileMetadata, LaporanIASC, Tahap1InformasiPihakPelapor,
    Tahap2InformasiPihakTerlapor, Tahap3InformasiKejadian,
    Tahap4InformasiTransaksi, validate_slot_value,
)
from services.normalizer import normalize_bank, normalize_location, normalize_media


class IntakeState(StrEnum):
    EVIDENCE = "STATE_1_EVIDENCE_UPLOAD"
    DELTA = "STATE_2_DELTA_SLOT_FILLING"
    CONFIRM = "STATE_3_CONFIRMATION_CARD"
    EKYC = "STATE_4_EKYC_VERIFICATION"
    DISPATCH = "STATE_5_DISPATCH_FREEZE"


STAGES = {
    "tahap1": Tahap1InformasiPihakPelapor, "tahap2": Tahap2InformasiPihakTerlapor,
    "tahap3": Tahap3InformasiKejadian, "tahap4": Tahap4InformasiTransaksi,
}
EVIDENCE_KINDS = ("ktp", "bukti_transfer", "bukti_chat", "bukti_rekening_korban")
LABELS = {
    "nomor_telepon_pelapor": "Nomor HP pelapor", "email_pelapor": "Email pelapor",
    "kronologi_kejadian_penipuan": "Kronologi kejadian", "nomor_rekening_akun": "Nomor rekening terlapor",
    "nomor_identitas": "Nomor identitas", "tanggal_dan_waktu_kejadian": "Tanggal dan waktu kejadian",
}
SESSION_TTL = 3600
MAX_SESSIONS = 20


def get_path(data, path, default=None):
    try:
        for part in path.split("."):
            data = data[int(part)] if isinstance(data, list) else data[part]
        return data
    except (KeyError, IndexError, TypeError, ValueError):
        return default


def set_path(data, path, value):
    parts = path.split(".")
    for i, part in enumerate(parts[:-1]):
        next_list = parts[i + 1].isdigit()
        if isinstance(data, list):
            index = int(part)
            if index >= 20:
                raise ValueError("Maksimal 20 baris per daftar pada PoC.")
            while len(data) <= index:
                data.append({})
            data = data[index]
        else:
            data = data.setdefault(part, [] if next_list else {})
    if isinstance(data, list):
        raise ValueError("Isi kolom daun, bukan seluruh daftar.")
    data[parts[-1]] = value


def flattened(data, prefix=""):
    if isinstance(data, (dict, list)):
        entries = data.items() if isinstance(data, dict) else enumerate(data)
        for key, value in entries:
            yield from flattened(value, f"{prefix}.{key}" if prefix else str(key))
    else:
        yield prefix, data


def public_value(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


@dataclass
class IntakeSession:
    session_id: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    data: dict = field(default_factory=lambda: {f"tahap{i}": {} for i in range(1, 6)})
    confidence: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    files: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    state: IntakeState = IntakeState.EVIDENCE
    confirmed: bool = False
    ekyc: dict = field(default_factory=lambda: {"verified": False, "simulated": True})
    challenge: tuple = field(default_factory=lambda: (secrets.randbelow(80) + 10, secrets.randbelow(10)))
    captcha_attempts: int = 0
    revision: int = 0
    dispatch: dict | None = None
    observed_identity_name: str | None = None
    observed_account_name: str | None = None
    touched: float = field(default_factory=time.monotonic)
    started: float = field(default_factory=time.monotonic)
    mutations: list = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def captcha_question(self):
        return f"{self.challenge[0]} + {self.challenge[1]} ="


# shortcut: a bounded, expiring single-worker store; replace with authenticated Redis before deployment.
SESSIONS: dict[str, IntakeSession] = {}


def prune():
    now = time.monotonic()
    for token in [key for key, session in SESSIONS.items() if now - session.touched > SESSION_TTL and not session.lock.locked()]:
        del SESSIONS[token]


def new_session():
    prune()
    if len(SESSIONS) >= MAX_SESSIONS:
        raise HTTPException(503, "Sesi demo penuh. Tutup sesi lama atau tunggu masa berlakunya habis.")
    session = IntakeSession()
    SESSIONS[session.session_id] = session
    return session


def session_for(token):
    prune()
    session = SESSIONS.get(token)
    if not session:
        raise HTTPException(404, "Sesi tidak ditemukan atau sudah berakhir.")
    session.touched = time.monotonic()
    return session


def rate_limit(session):
    now = time.monotonic()
    session.mutations = [t for t in session.mutations if now - t < 60]
    if len(session.mutations) >= 60:
        raise HTTPException(429, "Terlalu banyak permintaan. Tunggu satu menit.")
    session.mutations.append(now)


def invalidate(session):
    session.confirmed = False
    session.ekyc = {"verified": False, "simulated": True}
    session.dispatch = None
    session.revision += 1
    session.data["tahap5"] = {}


def sync_derived(session):
    p = session.data["tahap1"]
    for source, target in (("nomor_telepon_pelapor", "konfirmasi_nomor_telepon_pelapor"), ("email_pelapor", "konfirmasi_email_pelapor")):
        if p.get(source):
            p[target] = p[source]
    t = session.data["tahap4"]
    if p.get("nama_pelapor") and (not t.get("nama_pemilik_rekening_akun_korban") or session.sources.get("tahap4.nama_pemilik_rekening_akun_korban") == "default"):
        path = "tahap4.nama_pemilik_rekening_akun_korban"
        t["nama_pemilik_rekening_akun_korban"] = p["nama_pelapor"]
        session.sources[path] = "default"
        session.confidence[path] = 0.0
    for i, row in enumerate(t.get("daftar_penyelenggara_terlapor", [])):
        for j, detail in enumerate(row.get("daftar_rincian_transaksi", [])):
            parent = f"tahap4.daftar_penyelenggara_terlapor.{i}."
            prefix = parent + f"daftar_rincian_transaksi.{j}."
            confidences = [value for key, value in session.confidence.items() if (key.startswith(prefix) or key in {parent + "nama_penyelenggara", parent + "nomor_rekening_akun", parent + "nama_pemilik_rekening_akun"}) and not key.endswith(".extraction_confidence")]
            detail["extraction_confidence"] = min(confidences, default=0.0)


def normalize_patch(values):
    normalized = {}
    for path, value in values.items():
        if path.endswith((".nama_penyelenggara", ".nama_penyelenggara_layanan_korban")):
            value = normalize_bank(value)
            if value is None:
                continue
        if path.endswith(".sumber_media_informasi_penipuan"):
            value = normalize_media(value)
            if value is None:
                continue
        normalized[path] = value
    city_key, province_key = "tahap1.kota_domisili_pelapor", "tahap1.provinsi_domisili_pelapor"
    if city_key in normalized or province_key in normalized:
        province, city = normalize_location(normalized.get(city_key, ""), normalized.get(province_key))
        if province:
            normalized[province_key] = province
        if city:
            normalized[city_key] = city
    return normalized


def apply_patch(session, values, confidence, source, *, manual=False):
    """Validate all fields before committing; provider failure never corrupts a draft."""
    from services.llm_gateway import _path_allowed

    validated = {}
    normalized = normalize_patch(values)
    if manual and set(values) - set(normalized):
        raise HTTPException(422, "Nama bank/media belum dikenali. Pilih nilai pada dropdown replika.")
    for path, value in normalized.items():
        if not _path_allowed(path):
            raise HTTPException(422, "Field tidak dikenal atau tidak dapat diedit melalui chat.")
        old = get_path(session.data, path)
        if not manual and old is not None and session.sources.get(path) in {"manual", "chat"}:
            continue
        try:
            validated[path] = public_value(validate_slot_value(path, value))
            if path == "tahap1.nomor_identitas" and normalized.get("tahap1.jenis_identitas", get_path(session.data, "tahap1.jenis_identitas", "KTP")) == "KTP":
                if not re.fullmatch(r"[0-9]{16}", validated[path]):
                    raise ValueError("NIK harus 16 digit")
        except (ValueError, TypeError, ValidationError):
            label = LABELS.get(path.split(".")[-1], path.split(".")[-1].replace("_", " "))
            raise HTTPException(422, f"Periksa format {label}.") from None
    if not validated:
        return
    candidate = deepcopy(session.data)
    for path, value in validated.items():
        set_path(candidate, path, value)
    if get_path(candidate, "tahap1.jenis_identitas", "KTP") == "KTP" and get_path(candidate, "tahap1.nomor_identitas") is not None and not re.fullmatch(r"[0-9]{16}", get_path(candidate, "tahap1.nomor_identitas")):
        raise HTTPException(422, "Nomor KTP harus 16 digit. Koreksi jenis dan nomor identitas bersama-sama.")
    city_path, province_path = "tahap1.kota_domisili_pelapor", "tahap1.provinsi_domisili_pelapor"
    if city_path in validated or province_path in validated:
        current_city, current_province = get_path(candidate, city_path), get_path(candidate, province_path)
        province, city = normalize_location(current_city or "", current_province)
        if not manual and (not city or not province):
            for path in (city_path, province_path):
                if path in validated:
                    confidence[path] = 0.0
        if manual and current_city and current_province:
            independent_province, independent_city = normalize_location(current_city)
            if independent_city and independent_province != current_province:
                raise HTTPException(422, "Kota dan provinsi berbeda. Koreksi keduanya dalam satu permintaan.")
    session.data = candidate
    invalidate(session)
    for path in validated:
        session.confidence[path] = 1.0 if manual else confidence.get(path, 0.0)
        session.sources[path] = source
    sync_derived(session)


def stage_errors(session):
    errors = []
    for name, model in STAGES.items():
        try:
            model.model_validate(session.data[name])
        except ValidationError as exc:
            for error in exc.errors(include_input=False):
                path = ".".join([name, *(str(part) for part in error["loc"])])
                if path.endswith((".konfirmasi_email_pelapor", ".konfirmasi_nomor_telepon_pelapor")):
                    continue
                errors.append({"path": path, "reason": "missing" if error["type"] == "missing" else "invalid"})
    for path, confidence in session.confidence.items():
        if confidence < 0.85 and get_path(session.data, path) is not None and not path.endswith(".extraction_confidence"):
            errors.append({"path": path, "reason": "low_confidence"})
    result = []
    seen = set()
    for error in errors:
        if error["path"] in seen:
            continue
        seen.add(error["path"])
        label = LABELS.get(error["path"].split(".")[-1], error["path"].split(".")[-1].replace("_", " ").capitalize())
        result.append({**error, "label": label, "question": f"Mohon {'periksa dan konfirmasi' if error['reason'] == 'low_confidence' else 'lengkapi'} {label}."})
    return result


def advance(session):
    if not all(kind in session.evidence for kind in EVIDENCE_KINDS):
        session.state = IntakeState.EVIDENCE
    elif stage_errors(session):
        session.state = IntakeState.DELTA
    elif not session.confirmed:
        session.state = IntakeState.CONFIRM
    elif not session.ekyc.get("verified"):
        session.state = IntakeState.EKYC
    else:
        session.state = IntakeState.DISPATCH


def snapshot(session, *, simulated=True):
    advance(session)
    missing = stage_errors(session)
    absent_evidence = [kind for kind in EVIDENCE_KINDS if kind not in session.evidence]
    question = "Unggah bukti: " + ", ".join(absent_evidence) + "." if absent_evidence else (missing[0]["question"] if missing else "Tinjau seluruh ringkasan sebelum melanjutkan.")
    if not missing and not session.data["tahap5"]:
        t = session.data["tahap4"]
        session.data["tahap5"] = {
            "ringkasan_sumber_transaksi_korban": {"penyelenggara_layanan": t["nama_penyelenggara_layanan_korban"], "pemilik_rekening": t["nama_pemilik_rekening_akun_korban"], "nomor_rekening_akun": t["nomor_rekening_akun_korban"]},
            "ringkasan_lembaga_terlapor": [{"penyelenggara_layanan": row["nama_penyelenggara"], "pemilik_rekening": row["nama_pemilik_rekening_akun"], "nomor_rekening_akun": row["nomor_rekening_akun"]} for row in t["daftar_penyelenggara_terlapor"]],
            "setuju_syarat_dan_ketentuan": False, "captcha_question": session.captcha_question,
        }
    return {
        "session_id": session.session_id, "state": session.state, "data": session.data,
        "missing_slots": missing, "missing_evidence": absent_evidence,
        "question": question, "next_slot": missing[0]["path"] if missing else None,
        "ready_for_confirmation": not missing and not absent_evidence, "confirmed": session.confirmed,
        "confidence": session.confidence, "sources": session.sources, "ekyc": session.ekyc,
        "evidence": [{"kind": kind, **meta} for kind, meta in session.evidence.items()],
        "captcha_question": session.captcha_question, "simulation": simulated,
        "integration_mode": "dom", "external_dispatch_enabled": False,
        "elapsed_seconds": round(time.monotonic() - session.started, 2), "revision": session.revision,
    }


def build_report(session, consent, captcha_answer):
    t = session.data["tahap4"]
    stage5 = {
        "ringkasan_sumber_transaksi_korban": {"penyelenggara_layanan": t.get("nama_penyelenggara_layanan_korban"), "pemilik_rekening": t.get("nama_pemilik_rekening_akun_korban"), "nomor_rekening_akun": t.get("nomor_rekening_akun_korban")},
        "ringkasan_lembaga_terlapor": [{"penyelenggara_layanan": row.get("nama_penyelenggara"), "pemilik_rekening": row.get("nama_pemilik_rekening_akun"), "nomor_rekening_akun": row.get("nomor_rekening_akun")} for row in t.get("daftar_penyelenggara_terlapor", [])],
        "setuju_syarat_dan_ketentuan": consent, "captcha_question": session.captcha_question,
        "captcha_answer": captcha_answer,
    }
    payload = LaporanIASC.model_validate({**session.data, "tahap5": stage5})
    # Never accept a forged file ID, URL, hash or metadata supplied by an AI/client.
    def check_files(value):
        if isinstance(value, FileMetadata):
            stored = session.files.get(value.file_id)
            if not stored or stored["metadata"] != value.model_dump(mode="json"):
                raise HTTPException(422, "Lampiran tidak cocok dengan file milik sesi ini.")
        elif isinstance(value, BaseModel):
            for item in value.__dict__.values():
                check_files(item)
        elif isinstance(value, list):
            for item in value:
                check_files(item)
    check_files(payload)
    return payload
