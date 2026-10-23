"""Conservative normalization against the same dropdown values as the local replica."""

import ast
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
import re
import unicodedata

from schemas import MONTHS, to_indonesian_date


def _master_constant(name):
    source = (Path(__file__).resolve().parents[1] / "static/replica/report-core.mjs").read_text()
    match = re.search(r"export const " + re.escape(name) + r" = (.*?);", source, re.DOTALL)
    if not match:
        raise RuntimeError(f"Master data {name} tidak tersedia")
    return ast.literal_eval(match.group(1))


BANKS = tuple(_master_constant("BANKS"))
PROVINCES = tuple(_master_constant("PROVINCES"))
CITIES = _master_constant("CITIES")
MEDIA = ("Website", "WhatsApp", "Instagram", "Telegram", "Facebook", "TikTok", "SMS", "Telepon", "Email", "Lainnya", "Tokopedia", "Shopee", "Media Lainnya")


def _key(text):
    if not isinstance(text, str):
        return ""
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper()).split())


def _match(text, values, aliases=None):
    key = _key(text)
    if not key:
        return None
    candidates = {_key(value): value for value in values}
    candidates.update({_key(alias): canonical for alias, canonical in (aliases or {}).items() if canonical in values})
    if key in candidates:
        return candidates[key]
    ranks = sorted(((SequenceMatcher(None, key, candidate).ratio(), canonical) for candidate, canonical in candidates.items()), reverse=True)
    # shortcut: fuzzy matches require a unique strong winner; expand aliases after reviewing real OCR errors.
    if ranks and ranks[0][0] >= 0.92 and len(key) >= 5:
        others = [score for score, value in ranks if value != ranks[0][1]]
        if not others or ranks[0][0] - max(others) >= 0.08:
            return ranks[0][1]
    return None


def normalize_bank(text: str) -> str | None:
    key = re.sub(r"\b(PT|PERSERO|TBK|PERSEROAN TERBATAS)\b", " ", _key(text))
    return _match(key, BANKS, {
        "BANK NEGARA INDONESIA": "BNI", "BANK BNI": "BNI",
        "BANK CENTRAL ASIA": "BCA", "BANK BCA": "BCA",
        "BANK RAKYAT INDONESIA": "BRI", "BANK BRI": "BRI", "MANDIRI": "Bank Mandiri",
        "BANK TABUNGAN NEGARA": "BTN", "BANK SYARIAH INDONESIA": "BSI",
        "PERMATA": "Bank Permata", "GOPAY": "Gopay", "GO PAY": "Gopay", "SHOPEE PAY": "Shopeepay",
    })


def normalize_location(city: str, province: str | None = None) -> tuple[str | None, str | None]:
    normalized_province = _match(province, PROVINCES, {"JAKARTA": "DKI Jakarta", "DKI": "DKI Jakarta", "DIY": "Daerah Istimewa Yogyakarta", "YOGYAKARTA": "Daerah Istimewa Yogyakarta"}) if province else None
    if province and normalized_province is None:
        return None, None
    found = []
    for candidate_province, values in CITIES.items():
        aliases = {}
        if candidate_province == "DKI Jakarta":
            aliases = {value.replace("Kota Adm. ", ""): value for value in values if value.startswith("Kota Adm.")}
            aliases["KEPULAUAN SERIBU"] = "Kabupaten Adm. Kep. Seribu"
        value = _match(city, values, aliases)
        if value:
            found.append((candidate_province, value))
    if len(found) == 1 and (not normalized_province or normalized_province == found[0][0]):
        return found[0]
    # shortcut: replica city master covers Jakarta and selected West Java cities; unknown cities need an authoritative catalog.
    return normalized_province, None


def normalize_media(text: str) -> str | None:
    return _match(text, MEDIA, {"WA": "WhatsApp", "WHATS APP": "WhatsApp", "IG": "Instagram", "WEB": "Website", "SITUS WEB": "Website", "TIK TOK": "TikTok", "E MAIL": "Email", "PANGGILAN TELEPON": "Telepon"})


def _document_amount(value):
    if not isinstance(value, str):
        return value
    value = re.sub(r"^(?:Rp\.?|IDR)\s*", "", value.strip(), flags=re.I)
    value = re.sub(r"[.,]-$", "", value)
    if re.fullmatch(r"[0-9]{1,3}(?:[ \t\u00a0][0-9]{3})+(?:[.,][0-9]{1,2})?", value):
        value = re.sub(r"[ \t\u00a0]", "", value)
    if re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{3})+(?:,[0-9]{1,2})?", value):
        return value.replace(".", "").replace(",", ".")
    if re.fullmatch(r"[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]{1,2})?", value):
        return value.replace(",", "")
    if re.fullmatch(r"[0-9]+(?:[.,][0-9]{1,2})?", value):
        return value.replace(",", ".")
    raise ValueError("Nominal pada bukti belum terbaca jelas")


def _document_time(value: str, *, seconds: bool) -> str:
    if not isinstance(value, str) or (seconds and not re.search(r"[0-9]{1,2}[:.][0-9]{2}:[0-9]{2}", value)):
        raise ValueError("Komponen waktu pada bukti harus tertulis lengkap")
    numeric = re.fullmatch(r"([0-9]{1,2})([-/.])([0-9]{1,2})\2([0-9]{4})[, ]+(?:(?:pukul|jam)\s+)?([0-9]{1,2})[:.]([0-9]{2})(?::([0-9]{2}))?", value.strip(), re.I)
    named = re.fullmatch(r"([0-9]{1,2})\s+([A-Za-z]+)\.?\s+([0-9]{4})[, ]+(?:(?:pukul|jam)\s+)?([0-9]{1,2})[:.]([0-9]{2})(?::([0-9]{2}))?", value.strip(), re.I)
    if numeric:
        day, _, month, year, hour, minute, second = numeric.groups()
        value = datetime(int(year), int(month), int(day), int(hour), int(minute), int(second or 0))
    elif named:
        day, month, year, hour, minute, second = named.groups()
        months = {name.casefold(): index for index, name in enumerate(MONTHS, 1)}
        months.update({name[:3].casefold(): index for index, name in enumerate(MONTHS, 1)})
        months.update({"aug": 8, "oct": 10, "dec": 12, "may": 5})
        if month.casefold() not in months:
            raise ValueError("Bulan pada bukti belum dikenali")
        value = datetime(int(year), months[month.casefold()], int(day), int(hour), int(minute), int(second or 0))
    return to_indonesian_date(value, with_time=True, seconds=seconds)


def normalize_report_slot(path: str, value, *, document=False):
    if path.endswith((".nama_penyelenggara", ".nama_penyelenggara_layanan_korban")):
        normalized = normalize_bank(value)
        if normalized is None:
            raise ValueError("Bank belum dikenali")
        return normalized
    if path.endswith(".sumber_media_informasi_penipuan"):
        normalized = normalize_media(value)
        if normalized is None:
            raise ValueError("Media belum dikenali")
        return normalized
    if document and path.endswith((".waktu_transaksi", ".tanggal_dan_waktu_kejadian")):
        return _document_time(value, seconds=path.endswith(".waktu_transaksi"))
    if document and path.endswith(".nominal_transaksi"):
        return _document_amount(value)
    return normalize_ktp_slot(path, value) if document else value


def is_supported_by_evidence(path: str, value, text: str) -> bool:
    """Conservative grounding: unsupported facts require a manual answer."""
    from schemas import validate_slot_value

    if path.endswith(".extraction_confidence"):
        return True  # Derived server-side from slot confidence, not a reporting fact.
    if path.endswith(".nominal_transaksi"):
        if re.search(r"\b(?:USD|EUR|SGD|MYR|AUD|GBP)\b|\$", text, re.I):
            return False  # The report contract is IDR; currency conversion is not extraction.
        number = r"[0-9]+(?:[., \t\u00a0][0-9]+)*(?:[.,]-)?"
        amounts = re.findall(r"(?:\bRp\.?|\bIDR|nominal(?:_transaksi)?|amount|sebesar|total\s+transfer|jumlah)\s*[:=]?\s*(?:(?:Rp\.?|IDR)\s*)?(" + number + r")", text, re.I)
        amounts += re.findall(r"(?<![\w.,])(" + number + r")\s*(?:IDR|rupiah)\b", text, re.I)
        for raw in amounts:
            try:
                if validate_slot_value(path, _document_amount(raw.rstrip(".,"))) == value:
                    return True
            except (ValueError, TypeError):
                continue
        return False
    if "nomor_rekening" in path or path.endswith((".nomor_terlapor", ".nomor_telepon_pelapor")):
        date = r"(?:[0-9]{4}[-/.][0-9]{1,2}[-/.][0-9]{1,2}|[0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{4}|[0-9]{1,2}\s+[A-Za-z]{3,12}\.?\s+[0-9]{4})"
        time = r"[0-9]{1,2}[:.][0-9]{2}(?::[0-9]{2})?(?:Z|[+-][0-9]{2}:?[0-9]{2})?"
        amount = r"[0-9]+(?:[., \t\u00a0][0-9]+)*(?:[.,]-)?"
        non_identifiers = (
            r"(?<![0-9])" + date + r"(?:[ T,]+(?:(?:pukul|jam)\s+)?" + time + r")?(?![0-9])",
            r"\b(?:Rp\.?|IDR|USD|EUR|SGD|MYR|AUD|GBP|nominal(?:_transaksi)?|amount|sebesar|total\s+transfer|jumlah)\s*[:=]?\s*(?:(?:Rp\.?|IDR)\s*)?" + amount,
            r"(?<!\w)" + amount + r"\s*(?:IDR|rupiah|USD|EUR|SGD|MYR|AUD|GBP)\b",
        )
        numeric = list(text)
        for pattern in non_identifiers:
            for match in re.finditer(pattern, text, re.I):
                # Delimiters stop adjacent digits from swallowing a removed date/amount.
                numeric[match.start():match.end()] = "#" * len(match[0])
        candidates = re.findall(r"(?<![\w])[+]?[0-9](?:[ .()-]?[0-9]){5,29}(?![\w])", "".join(numeric))
        for raw in candidates:
            digits = re.sub(r"\D", "", raw)
            if digits == str(value):
                return True
            if path.endswith((".nomor_terlapor", ".nomor_telepon_pelapor")):
                if (digits[2:] if digits.startswith("62") else digits.lstrip("0")) == str(value):
                    return True
        return False
    key = _key(str(value))
    if key and re.search(r"(?<!\w)" + re.escape(key) + r"(?!\w)", _key(text)):
        return True
    if path.endswith((".nama_penyelenggara", ".nama_penyelenggara_layanan_korban", ".sumber_media_informasi_penipuan")):
        normalizer = normalize_media if path.endswith(".sumber_media_informasi_penipuan") else normalize_bank
        return any(normalizer(line.partition(":")[2] or line) == value for line in text.splitlines())
    if path.endswith((".waktu_transaksi", ".tanggal_dan_waktu_kejadian")):
        timestamp = r"(?:[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]|[0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{4}[, ]+|[0-9]{1,2}\s+[A-Za-z]+\.?\s+[0-9]{4}[, ]+)(?:(?:pukul|jam)\s+)?[0-9]{1,2}[:.][0-9]{2}(?::[0-9]{2})?(?:Z|[+-][0-9]{2}:[0-9]{2})?"
        for raw in re.findall(timestamp, text, re.I):
            try:
                if normalize_report_slot(path, raw, document=True) == value:
                    return True
            except ValueError:
                continue
    return False


def normalize_ktp_slot(path: str, value):
    """Normalize document spelling/format only; never guess identity digits."""
    if not isinstance(value, str):
        return value
    value = value.strip()
    choices = {
        "tahap1.jenis_kelamin": ("Laki-laki", "Perempuan"),
        "tahap1.agama_pelapor": ("Islam", "Kristen", "Protestan", "Katolik", "Hindu", "Buddha", "Konghucu", "Tidak Diketahui"),
        "tahap1.jenis_identitas": ("KTP", "Paspor", "KITAS"),
    }
    if path in choices:
        return next((choice for choice in choices[path] if _key(choice) == _key(value)), value)
    if path == "tahap1.kewarganegaraan_pelapor" and _key(value) in {"WNI", "INDONESIA"}:
        return "Indonesia"
    if path == "tahap1.nomor_identitas":
        if not re.fullmatch(r"[0-9]+(?:[\s-]+[0-9]+)*", value):
            raise ValueError("NIK KTP belum terbaca lengkap")
        digits = re.sub(r"[\s-]", "", value)
        if len(digits) != 16:
            raise ValueError("NIK KTP harus tepat 16 digit")
        return digits
    if path == "tahap1.tanggal_lahir_pelapor":
        numeric = re.fullmatch(r"([0-9]{1,2})([-/])([0-9]{1,2})\2([0-9]{4})", value)
        if numeric:
            value = date(int(numeric[4]), int(numeric[3]), int(numeric[1]))
        else:
            literal = re.fullmatch(r"([0-9]{1,2})\s+([A-Za-z]+)\s+([0-9]{4})", value)
            if literal:
                month = next((month for month in MONTHS if month.casefold() == literal[2].casefold()), None)
                if month:
                    value = f"{int(literal[1])} {month} {literal[3]}"
        return to_indonesian_date(value)
    return value
