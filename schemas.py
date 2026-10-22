"""The requested five-stage IASC PoC contract, independent of any live API."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Annotated, Literal, get_args, get_origin
from zoneinfo import ZoneInfo

from pydantic import (
    AfterValidator, BaseModel, BeforeValidator, ConfigDict, EmailStr, Field,
    PlainSerializer, StrictBool, StrictInt, StringConstraints, TypeAdapter, model_validator,
)

MONTHS = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
          "Agustus", "September", "Oktober", "November", "Desember")
JAKARTA = ZoneInfo("Asia/Jakarta")
IDENTITY_LIMIT = 1_048_576
EVIDENCE_LIMIT = 2_097_152


def _indonesian_date(value: str, kind: str) -> str:
    suffix = {"date": "", "minute": r" ([0-9]{2}):([0-9]{2})", "second": r" ([0-9]{2}):([0-9]{2}):([0-9]{2})"}[kind]
    match = re.fullmatch(r"([1-9]|[12][0-9]|3[01]) (" + "|".join(MONTHS) + r") ([0-9]{4})" + suffix, value)
    if not match:
        raise ValueError("Gunakan tanggal Indonesia, misalnya 19 Oktober 2026" + {"date": "", "minute": " 10:00", "second": " 10:00:00"}[kind])
    day, month, year, *clock = match.groups()
    parsed = datetime(int(year), MONTHS.index(month) + 1, int(day), *(int(part) for part in clock), tzinfo=JAKARTA)
    is_future = parsed.date() > datetime.now(JAKARTA).date() if kind == "date" else parsed > datetime.now(JAKARTA)
    if is_future:
        raise ValueError("Tanggal tidak boleh berada di masa depan")
    return value


def to_indonesian_date(value: str | date | datetime, *, with_time: bool = False, seconds: bool = False) -> str:
    """Convert ISO values at the intake boundary; contract fields retain the stated format."""
    if isinstance(value, str):
        if re.match(r"^[0-9]{4}-", value):
            if (with_time or seconds) and not re.search(r"[T ][0-9]{2}:[0-9]{2}", value):
                raise ValueError("Tanggal dan jam wajib disertakan")
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            return _indonesian_date(value, "second" if seconds else "minute" if with_time else "date")
    if isinstance(value, datetime) and value.tzinfo:
        value = value.astimezone(JAKARTA)
    text = f"{value.day} {MONTHS[value.month - 1]} {value.year:04d}"
    if with_time or seconds:
        if not isinstance(value, datetime):
            raise ValueError("Tanggal dan jam wajib disertakan")
        text += value.strftime(" %H:%M:%S" if seconds else " %H:%M")
    return _indonesian_date(text, "second" if seconds else "minute" if with_time else "date")


def _amount(value) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Nominal harus berupa angka rupiah")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Nominal harus berupa angka rupiah") from exc
    if not amount.is_finite() or amount <= 0 or amount > Decimal("10000000000000") or amount.as_tuple().exponent < -2:
        raise ValueError("Nominal harus positif, hingga 10 triliun rupiah dengan maksimal dua desimal")
    return amount


def _confidence(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("Confidence harus angka antara 0 dan 1")
    if not math.isfinite(float(value)) or not 0 <= value <= 1:
        raise ValueError("Confidence harus angka antara 0 dan 1")
    return float(value)


def _filename(value: str) -> str:
    name = re.split(r"[/\\]", value)[-1]
    name = "".join(char for char in name if char.isprintable()).strip()
    if not name or name in {".", ".."}:
        raise ValueError("Nama file tidak valid")
    return name[:180]


def _religion(value):
    return "Kristen" if value == "Protestan" else value


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{8,15}$")]
Account = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{6,30}$")]
IndonesianDate = Annotated[str, AfterValidator(lambda value: _indonesian_date(value, "date"))]
IndonesianMinute = Annotated[str, AfterValidator(lambda value: _indonesian_date(value, "minute"))]
IndonesianSecond = Annotated[str, AfterValidator(lambda value: _indonesian_date(value, "second"))]
Amount = Annotated[Decimal, BeforeValidator(_amount), PlainSerializer(lambda value: format(value, "f"), return_type=str, when_used="json")]
Confidence = Annotated[float, BeforeValidator(_confidence)]
Religion = Annotated[Literal["Islam", "Kristen", "Katolik", "Hindu", "Buddha", "Konghucu", "Tidak Diketahui"], BeforeValidator(_religion)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True, str_strip_whitespace=True, allow_inf_nan=False)


class LLMExtractionSlot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    field: str = Field(min_length=1, max_length=200)
    value: Annotated[str, Field(max_length=4000)] | int | float | None
    confidence: float = Field(ge=0, le=1)


class LLMExtractionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    slots: list[LLMExtractionSlot] = Field(max_length=200)
    is_relevant_to_scam_report: StrictBool
    injection_detected: StrictBool


class FileMetadata(ContractModel):
    file_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{16,128}$")]
    filename: Annotated[str, AfterValidator(_filename)]
    content_type: Literal["application/pdf", "image/jpeg", "image/png"]
    size_bytes: Annotated[StrictInt, Field(gt=0, le=EVIDENCE_LIMIT)]
    sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    url: Annotated[str, StringConstraints(pattern=r"^/api/v1/session/[A-Za-z0-9_-]{16,128}/files/[A-Za-z0-9_-]{16,128}$")] | None = None


IdentityFile = Annotated[FileMetadata, AfterValidator(lambda value: _identity_file(value))]


def _identity_file(value: FileMetadata) -> FileMetadata:
    if value.size_bytes > IDENTITY_LIMIT:
        raise ValueError("Kartu identitas korban maksimal 1 MB")
    return value


class Tahap1InformasiPihakPelapor(ContractModel):
    apakah_mengalami_sendiri: Literal["Ya, saya sendiri", "Tidak, saya mewakili korban"]
    upload_kartu_identitas_korban: IdentityFile
    jenis_kelamin: Literal["Laki-laki", "Perempuan"]
    kewarganegaraan_pelapor: Name = "Indonesia"
    nama_pelapor: Name
    tempat_lahir_pelapor: Name
    tanggal_lahir_pelapor: IndonesianDate
    agama_pelapor: Religion
    pekerjaan_pelapor: Name
    kode_negara_telepon_pelapor: Name = "Indonesia (+62)"
    nomor_telepon_pelapor: Phone
    konfirmasi_nomor_telepon_pelapor: Phone
    email_pelapor: EmailStr
    konfirmasi_email_pelapor: EmailStr
    jenis_identitas: Literal["KTP", "Paspor", "KITAS"] = "KTP"
    nomor_identitas: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=30, pattern=r"^[A-Za-z0-9]+$")]
    provinsi_domisili_pelapor: Name
    kota_domisili_pelapor: Name
    alamat_pelapor: Text

    @model_validator(mode="before")
    @classmethod
    def copy_confirmations(cls, data):
        if isinstance(data, dict):
            data = dict(data)
            for source, confirmation in (("nomor_telepon_pelapor", "konfirmasi_nomor_telepon_pelapor"), ("email_pelapor", "konfirmasi_email_pelapor")):
                if confirmation not in data:
                    data[confirmation] = data.get(source)
        return data

    @model_validator(mode="after")
    def validate_identity_and_confirmations(self):
        if self.jenis_identitas == "KTP" and not re.fullmatch(r"[0-9]{16}", self.nomor_identitas):
            raise ValueError("Nomor KTP harus 16 digit dan disimpan sebagai teks")
        if self.nomor_telepon_pelapor != self.konfirmasi_nomor_telepon_pelapor:
            raise ValueError("Konfirmasi nomor telepon tidak sama")
        if self.email_pelapor != self.konfirmasi_email_pelapor:
            raise ValueError("Konfirmasi email tidak sama")
        return self


class ItemInformasiTerlapor(ContractModel):
    kode_nomor_terlapor: Name = "Indonesia (+62)"
    nomor_terlapor: Phone
    nama_terlapor: Name
    upload_bukti_komunikasi: FileMetadata


class ItemSumberMediaPenipuan(ContractModel):
    sumber_media_informasi_penipuan: Name
    detail_sumber_media_informasi_penipuan: Text
    upload_bukti_sumber_media: FileMetadata


class Tahap2InformasiPihakTerlapor(ContractModel):
    daftar_informasi_terlapor: Annotated[list[ItemInformasiTerlapor], Field(min_length=1, max_length=50)]
    daftar_sumber_media_penipuan: Annotated[list[ItemSumberMediaPenipuan], Field(min_length=1, max_length=50)]


class Tahap3InformasiKejadian(ContractModel):
    tanggal_dan_waktu_kejadian: IndonesianMinute
    kronologi_kejadian_penipuan: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    upload_bukti_pendukung_kejadian: FileMetadata
    upload_laporan_kepolisian: FileMetadata | None = None


class SubItemTransaksi(ContractModel):
    waktu_transaksi: IndonesianSecond
    nominal_transaksi: Amount
    upload_bukti_pendukung_kejadian: FileMetadata
    extraction_confidence: Confidence


class ItemPenyelenggaraTerlapor(ContractModel):
    nama_penyelenggara: Name
    nomor_rekening_akun: Account
    nama_pemilik_rekening_akun: Name
    daftar_rincian_transaksi: Annotated[list[SubItemTransaksi], Field(min_length=1, max_length=100)]


class Tahap4InformasiTransaksi(ContractModel):
    nama_penyelenggara_layanan_korban: Name
    nomor_rekening_akun_korban: Account
    nama_pemilik_rekening_akun_korban: Name
    bukti_kepemilikan_rekening_akun_korban: FileMetadata
    daftar_penyelenggara_terlapor: Annotated[list[ItemPenyelenggaraTerlapor], Field(min_length=1, max_length=50)]


class RingkasanRekening(ContractModel):
    penyelenggara_layanan: Name
    pemilik_rekening: Name
    nomor_rekening_akun: Account


class Tahap5KesediaanMelapor(ContractModel):
    ringkasan_sumber_transaksi_korban: RingkasanRekening
    ringkasan_lembaga_terlapor: Annotated[list[RingkasanRekening], Field(min_length=1, max_length=50)]
    setuju_syarat_dan_ketentuan: StrictBool
    captcha_question: Annotated[str, StringConstraints(pattern=r"^[0-9]{1,2} \+ [0-9]{1,2} =$", max_length=12)]
    captcha_answer: Annotated[str, StringConstraints(pattern=r"^[0-9]{1,3}$")]

    @model_validator(mode="after")
    def consent_is_explicit(self):
        if self.setuju_syarat_dan_ketentuan is not True:
            raise ValueError("Persetujuan pelapor wajib diberikan secara eksplisit")
        # The challenge and answer must also be checked against server-owned session data.
        left, _, right, _ = self.captcha_question.split()
        if int(self.captcha_answer) != int(left) + int(right):
            raise ValueError("Jawaban CAPTCHA salah")
        return self


class LaporanIASC(ContractModel):
    tahap1: Tahap1InformasiPihakPelapor
    tahap2: Tahap2InformasiPihakTerlapor
    tahap3: Tahap3InformasiKejadian
    tahap4: Tahap4InformasiTransaksi
    tahap5: Tahap5KesediaanMelapor

    @model_validator(mode="before")
    @classmethod
    def default_victim_owner(cls, data):
        if isinstance(data, dict) and isinstance(data.get("tahap1"), dict) and isinstance(data.get("tahap4"), dict):
            data = dict(data)
            data["tahap4"] = dict(data["tahap4"])
            if not data["tahap4"].get("nama_pemilik_rekening_akun_korban"):
                data["tahap4"]["nama_pemilik_rekening_akun_korban"] = data["tahap1"].get("nama_pelapor")
        return data

    @model_validator(mode="after")
    def summaries_match_transactions(self):
        t = self.tahap4
        source = RingkasanRekening(penyelenggara_layanan=t.nama_penyelenggara_layanan_korban, pemilik_rekening=t.nama_pemilik_rekening_akun_korban, nomor_rekening_akun=t.nomor_rekening_akun_korban)
        targets = [RingkasanRekening(penyelenggara_layanan=row.nama_penyelenggara, pemilik_rekening=row.nama_pemilik_rekening_akun, nomor_rekening_akun=row.nomor_rekening_akun) for row in t.daftar_penyelenggara_terlapor]
        if self.tahap5.ringkasan_sumber_transaksi_korban != source or self.tahap5.ringkasan_lembaga_terlapor != targets:
            raise ValueError("Ringkasan tahap 5 harus sama dengan transaksi tahap 4")
        return self


def validate_slot_value(path: str, value):
    """Validate one model path for a partial draft without inventing missing slots."""
    parts = path.split(".")
    model = LaporanIASC
    index = 0
    while index < len(parts):
        field = model.model_fields.get(parts[index])
        if field is None:
            raise ValueError("Field laporan tidak dikenal")
        index += 1
        annotation = field.annotation
        if index == len(parts):
            if get_origin(annotation) is list or (isinstance(annotation, type) and issubclass(annotation, BaseModel)) or isinstance(value, (dict, list)):
                raise ValueError("Hanya field skalar yang boleh diisi melalui slot")
            return TypeAdapter(Annotated[annotation, *field.metadata] if field.metadata else annotation).validate_python(value)
        if get_origin(annotation) is list:
            if not parts[index].isdigit() or int(parts[index]) >= 100:
                raise ValueError("Indeks daftar tidak valid")
            annotation = get_args(annotation)[0]
            index += 1
        if not isinstance(annotation, type) or not issubclass(annotation, BaseModel):
            raise ValueError("Field laporan bukan objek")
        model = annotation
    raise ValueError("Path field tidak lengkap")
