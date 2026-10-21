"""Conservative normalization against the same dropdown values as the local replica."""

import ast
from datetime import date
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
