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
    STATUS = "PELAPOR_STATUS"
    KTP = "KTP_UPLOAD"
    PELAPOR = "PELAPOR_DETAILS"
    CONTACT = "CONTACT_INPUT"
    CHAT = "CHAT_EVIDENCE_UPLOAD"
    TERLAPOR = "TERLAPOR_DETAILS"
    CHAT_MORE = "CHAT_MORE"
    CHRONOLOGY = "CHRONOLOGY_INPUT"
    KEJADIAN = "KEJADIAN_DETAILS"
    POLICE = "POLICE_REPORT_OPTIONAL"
    ACCOUNT = "ACCOUNT_PROOF_UPLOAD"
    ACCOUNT_DETAILS = "ACCOUNT_DETAILS"
    TRANSFER = "TRANSFER_UPLOAD"
    TRANSFER_DETAILS = "TRANSFER_DETAILS"
    TRANSFER_MORE = "TRANSFER_MORE"
    CONFIRM = "FINAL_CONFIRMATION"
    COMPLETED = "COMPLETED"


UPLOAD_STATES = {
    IntakeState.KTP: "ktp", IntakeState.CHAT: "bukti_chat",
    IntakeState.POLICE: "laporan_kepolisian", IntakeState.ACCOUNT: "bukti_rekening_korban",
    IntakeState.TRANSFER: "bukti_transfer",
}
TURN_STEPS = {
    IntakeState.STATUS: 1, IntakeState.KTP: 1, IntakeState.PELAPOR: 1, IntakeState.CONTACT: 1,
    IntakeState.CHAT: 2, IntakeState.TERLAPOR: 2, IntakeState.CHAT_MORE: 2,
    IntakeState.CHRONOLOGY: 3, IntakeState.KEJADIAN: 3, IntakeState.POLICE: 3,
    IntakeState.ACCOUNT: 4, IntakeState.ACCOUNT_DETAILS: 4, IntakeState.TRANSFER: 4,
    IntakeState.TRANSFER_DETAILS: 4, IntakeState.TRANSFER_MORE: 4,
    IntakeState.CONFIRM: 5, IntakeState.COMPLETED: 5,
}
CONTACT_FIELDS = {"tahap1.nomor_telepon_pelapor", "tahap1.email_pelapor"}


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
        return format(value, "f")
    return value


@dataclass
class IntakeSession:
    session_id: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    data: dict = field(default_factory=lambda: {f"tahap{i}": {} for i in range(1, 6)})
    confidence: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    files: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    state: IntakeState = IntakeState.STATUS
    confirmed: bool = False
    ekyc: dict = field(default_factory=lambda: {"verified": False, "simulated": True})
    challenge: tuple = field(default_factory=lambda: (secrets.randbelow(80) + 10, secrets.randbelow(10)))
    captcha_attempts: int = 0
    revision: int = 0
    dispatch: dict | None = None
    observed_identity_name: str | None = None
    observed_account_name: str | None = None
    chronology_received: bool = False
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
        question = f"Mohon {'periksa dan konfirmasi' if error['reason'] == 'low_confidence' else 'lengkapi'} {label}."
        if error["reason"] != "low_confidence":
            if error["path"].endswith(".sumber_media_informasi_penipuan"):
                question = "Melalui media apa penipuan terjadi? Misalnya WhatsApp, Instagram, Telegram, atau Website."
            elif error["path"].endswith(".detail_sumber_media_informasi_penipuan"):
                media = get_path(session.data, error["path"].rsplit(".", 1)[0] + ".sumber_media_informasi_penipuan")
                question = f"Media {media or 'penipuan'} sudah tercatat. Sekarang ketik nomor kontak pelaku, username seperti @akun_contoh, atau tautan lengkap seperti https://example.com."
        result.append({**error, "label": label, "question": question})
    return result


def errors_for(session, stage, *, exclude=(), prefix=None):
    return [item for item in stage_errors(session) if item["path"].startswith(stage + ".")
            and item["path"] not in exclude and (prefix is None or item["path"].startswith(prefix))]


def advance(session):
    """Resolve only the current turn; future stages never prompt for missing fields early."""
    if session.state == IntakeState.PELAPOR and not errors_for(session, "tahap1", exclude=CONTACT_FIELDS):
        session.state = IntakeState.CONTACT
    if session.state == IntakeState.CONTACT and not errors_for(session, "tahap1"):
        session.state = IntakeState.CHAT
    if session.state == IntakeState.TERLAPOR and not errors_for(session, "tahap2"):
        session.state = IntakeState.CHAT_MORE
    if session.state == IntakeState.KEJADIAN and not errors_for(session, "tahap3"):
        session.state = IntakeState.POLICE
    if session.state == IntakeState.ACCOUNT_DETAILS and not account_errors(session):
        session.state = IntakeState.TRANSFER
    if session.state == IntakeState.TRANSFER_DETAILS and not errors_for(session, "tahap4"):
        session.state = IntakeState.TRANSFER_MORE
    if session.state == IntakeState.CONFIRM:
        missing = stage_errors(session)
        if missing:
            stage = int(missing[0]["path"][5])
            session.state = {1: IntakeState.PELAPOR, 2: IntakeState.TERLAPOR,
                             3: IntakeState.KEJADIAN, 4: IntakeState.TRANSFER_DETAILS}[stage]


def account_errors(session):
    return [item for item in errors_for(session, "tahap4") if not item["path"].startswith("tahap4.daftar_penyelenggara_terlapor")]


def current_errors(session):
    if session.state == IntakeState.PELAPOR:
        return errors_for(session, "tahap1", exclude=CONTACT_FIELDS)
    if session.state == IntakeState.CONTACT:
        return errors_for(session, "tahap1")
    if session.state == IntakeState.TERLAPOR:
        return errors_for(session, "tahap2")
    if session.state == IntakeState.KEJADIAN:
        return errors_for(session, "tahap3")
    if session.state == IntakeState.ACCOUNT_DETAILS:
        return account_errors(session)
    if session.state == IntakeState.TRANSFER_DETAILS:
        return errors_for(session, "tahap4")
    return []


def summary(session):
    t = session.data["tahap4"]
    return {
        "ringkasan_sumber_transaksi_korban": {"penyelenggara_layanan": t.get("nama_penyelenggara_layanan_korban"), "pemilik_rekening": t.get("nama_pemilik_rekening_akun_korban"), "nomor_rekening_akun": t.get("nomor_rekening_akun_korban")},
        "ringkasan_lembaga_terlapor": [{"penyelenggara_layanan": row.get("nama_penyelenggara"), "pemilik_rekening": row.get("nama_pemilik_rekening_akun"), "nomor_rekening_akun": row.get("nomor_rekening_akun")} for row in t.get("daftar_penyelenggara_terlapor", [])],
    }


def prepare_confirmation(session):
    session.state = IntakeState.CONFIRM
    advance(session)
    if session.state == IntakeState.CONFIRM:
        session.confirmed = True
        session.data["tahap5"] = {**summary(session), "setuju_syarat_dan_ketentuan": False,
                                  "captcha_question": session.captcha_question}


def changed_patches(before, after):
    """Files are atomic references; table columns remain individual progressive patches."""
    result = []
    def walk(old, value, path):
        if old == value:
            return
        if isinstance(value, dict) and "file_id" not in value:
            for key, item in value.items():
                walk(old.get(key) if isinstance(old, dict) else None, item, f"{path}.{key}" if path else key)
            if isinstance(old, dict):
                for key in old.keys() - value.keys():
                    walk(old[key], None, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(old[index] if isinstance(old, list) and index < len(old) else None, item, f"{path}.{index}")
        elif path:
            result.append({"op": "set", "path": path, "value": deepcopy(value), "step": int(path[5])})
    walk(before, after, "")
    return result


def turn_message(session, missing):
    state = session.state
    if missing and (session.state != IntakeState.CONTACT or len(missing) == 1 or missing[0]["reason"] == "low_confidence"):
        if missing[0]["reason"] == "low_confidence":
            value = get_path(session.data, missing[0]["path"])
            return f"{missing[0]['question']} Hasil yang terbaca: {value}. Jika berbeda, ketik nilai yang benar.", []
        return missing[0]["question"], []
    name = get_path(session.data, "tahap1.nama_pelapor", "pelapor")
    transfer_message = "Bukti transfer sudah ditambahkan ke daftar transaksi. Ada bukti transfer lain, atau lanjut ke Tahap 5?"
    latest_id = session.evidence.get("bukti_transfer", {}).get("file_id")
    for row in session.data["tahap4"].get("daftar_penyelenggara_terlapor", []):
        for item in row.get("daftar_rincian_transaksi", []):
            if item.get("upload_bukti_pendukung_kejadian", {}).get("file_id") == latest_id:
                amount = format(Decimal(str(item["nominal_transaksi"])), ",f").replace(",", "_").replace(".", ",").replace("_", ".")
                transfer_message = f"Transfer sebesar Rp{amount} ke {row.get('nama_penyelenggara')} ({row.get('nomor_rekening_akun')}) sudah saya tambahkan. Ada bukti transfer lain, atau lanjut ke Tahap 5?"
    messages = {
        IntakeState.STATUS: "Halo, selamat datang di Help Center IASC OJK versi simulasi lokal. Jangan panik, saya akan memandu dan mengisi formulir dummy secara otomatis. Apakah Anda sendiri yang mengalami penipuan ini?",
        IntakeState.KTP: "Baik. Untuk mengisi biodata di Tahap 1, silakan kirim foto KTP melalui tombol lampiran. Demo lokal: gunakan gambar dummy, bukan identitas asli.",
        IntakeState.CONTACT: f"Data KTP atas nama {name} sudah saya masukkan ke Tahap 1. Sekarang ketik nomor telepon aktif dan alamat email Anda, misalnya 08123456789, nama@example.com.",
        IntakeState.CHAT: "Tahap 1 lengkap! Kita masuk Tahap 2. Silakan kirim screenshot bukti chat / komunikasi dengan pelaku melalui tombol lampiran.",
        IntakeState.CHAT_MORE: "Informasi terlapor dan media sudah terisi di Tahap 2. Ada bukti chat lain, atau lanjut ke Tahap 3?",
        IntakeState.CHRONOLOGY: "Sekarang Tahap 3. Ceritakan singkat bagaimana penipuan terjadi serta tanggal dan jamnya. Saya akan merapikan cerita Anda tanpa menambah fakta.",
        IntakeState.POLICE: "Apakah Anda memiliki file Laporan Kepolisian? Unggah gambar melalui lampiran atau pilih Lewati / Belum Ada.",
        IntakeState.ACCOUNT: "Kita masuk Tahap 4. Kirim foto atau screenshot bukti kepemilikan rekening Anda, misalnya info rekening m-banking atau buku tabungan.",
        IntakeState.TRANSFER: "Rekening Anda sudah tercatat. Sekarang kirim screenshot bukti transfer ke rekening pelaku.",
        IntakeState.TRANSFER_MORE: transfer_message,
        IntakeState.CONFIRM: f"Tahap 1–4 lengkap. Periksa ringkasan. Dengan mengirim jawaban CAPTCHA {session.captcha_question}, saya menyetujui S&K simulasi lokal dan menyelesaikan laporan dummy. Tiket yang dihasilkan hanya lokal; tidak ada pengiriman resmi atau pemblokiran dana.",
        IntakeState.COMPLETED: "Laporan dummy selesai. Tiket simulasi lokal sudah dibuat; laporan resmi tidak dikirim dan tidak ada dana diblokir.",
    }
    replies = {
        IntakeState.STATUS: [("Ya, saya sendiri", "Ya, saya sendiri"), ("Tidak, saya mewakili korban", "Tidak, saya mewakili korban")],
        IntakeState.CHAT_MORE: [("+ Upload Bukti Chat Lain", "more_chat"), ("Lanjut ke Tahap 3", "continue")],
        IntakeState.POLICE: [("Lewati / Belum Ada", "skip_police")],
        IntakeState.TRANSFER_MORE: [("+ Upload Bukti Transfer Lain", "more_transfer"), ("Lanjut ke Tahap 5", "continue")],
    }
    return messages.get(state, "Silakan lengkapi informasi yang diminta."), [{"label": label, "value": value} for label, value in replies.get(state, [])]


def snapshot(session, *, simulated=True, before=None):
    advance(session)
    missing = current_errors(session)
    message, replies = turn_message(session, missing)
    if missing and missing[0]["reason"] == "low_confidence":
        replies = [{"label": "Sudah sesuai", "value": "confirm_value"}]
    return {
        "session_id": session.session_id, "state": session.state, "current_state": session.state,
        "active_wizard_step": TURN_STEPS[session.state], "expected_upload_type": UPLOAD_STATES.get(session.state),
        "assistant_message": message, "reply": message, "question": message, "quick_replies": replies,
        "dom_patches": changed_patches(before, session.data) if before is not None else [],
        "data": deepcopy(session.data), "missing_slots": missing,
        "missing_evidence": [kind for kind in EVIDENCE_KINDS if kind not in session.evidence],
        "next_slot": missing[0]["path"] if missing else None,
        "ready_for_confirmation": session.state == IntakeState.CONFIRM, "confirmed": session.confirmed,
        "confidence": dict(session.confidence), "sources": dict(session.sources), "ekyc": session.ekyc,
        "evidence": [{"kind": kind, **meta} for kind, meta in session.evidence.items()],
        "captcha_question": session.captcha_question, "simulation": simulated,
        "integration_mode": "dom", "external_dispatch_enabled": False, "submitted": False,
        "elapsed_seconds": round(time.monotonic() - session.started, 2), "revision": session.revision,
        "result": session.dispatch,
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
