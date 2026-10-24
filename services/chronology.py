"""Conservative checks for a masked chronology draft; not semantic verification."""

import json
import re

from services.natural_input import _CLOCK, _DATE_PATTERNS, _ISO_TIMESTAMP, _explicit_components, parse_report_datetime, parse_rupiah
from services.privacy import PrivacyMasker, placeholders


_ERROR = "Kronologi AI memuat rincian yang belum didukung bukti. Mohon coba lagi atau koreksi secara manual."
_FORBIDDEN = re.compile(
    r"\[(?:NIK|IDENTITAS|ALAMAT|TANGGAL_LAHIR|TEMPAT_LAHIR|AGAMA|"
    r"JENIS_KELAMIN|PEKERJAAN|KEWARGANEGARAAN|LOKASI|RAHASIA)_"
)
_REFERENCE = re.compile(r"https?://[^\s<>\"']+|(?<![\w@])@[\w.-]+", re.I)
_NUMBER = r"[0-9]+(?:[., \t\u00a0][0-9]+)*(?:[.,]-)?"
_UNIT = r"(?:ribu|rb|juta|jt)\b"
_MONEY = re.compile(
    r"(?:\b(?P<currency>Rp\.?|IDR|USD|EUR|SGD|MYR|AUD|GBP)|(?P<dollar>\$)|"
    r"\b(?:nominal(?:_transaksi)?|amount|sebesar|senilai|seharga|jumlah|total\s+transfer|"
    r"(?:mem)?bayar(?:kan)?|(?:men)?transfer))"
    r"[\s\"':=]*(?:(?:Rp\.?|IDR)\s*)?(?P<prefix>" + _NUMBER + r"(?:\s*" + _UNIT + r")?)"
    r"|(?P<suffix>" + _NUMBER + r"\s*(?:" + _UNIT + r"(?:\s*rupiah)?|rupiah|IDR))", re.I,
)
_EVENTS = (
    re.compile(r"\b(?:[a-z]*transfer|(?:mem|pem|di)?bayar(?:kan|an)?|(?:mengirim|kirim)(?:kan)?\s+(?:uang|dana))\b", re.I),
    re.compile(r"\b(?:mem|di)?blokir\b", re.I),
    re.compile(r"\b(?:(?:di|ter)kirim(?:kan)?|mengirim(?:kan)?|diterima|menerima|sampai|tiba)\b(?!\s+(?:uang|dana)\b)", re.I),
    re.compile(r"\b(?:refund|pengembalian(?:\s+(?:uang|dana))?|dikembalikan|mengembalikan)\b", re.I),
)
_GOODS = re.compile(r"\b(?:barang|pesanan|paket|produk|sepatu|tiket)\b", re.I)
_NEGATIVE = re.compile(
    r"\b(?:tidak|belum|tak|nggak|enggak|gak|ga|tanpa)\b"
    r"(?:\s+(?:pernah|juga|kunjung|sama|sekali|melakukan|menerima|ada|mendapatkan|berhasil|bisa|dapat|saya|kami|sempat)){0,4}\s*$", re.I,
)


def _facts(text: str):
    amounts = set()

    def amount(match):
        raw = match["prefix"] or match["suffix"]
        currency = (match["currency"] or match["dollar"] or "IDR").upper().rstrip(".")
        amounts.add(("IDR" if currency == "RP" else currency, parse_rupiah(raw.rstrip(".,-"))))
        return " " * len(match[0])

    remaining = _MONEY.sub(amount, text)
    for token in placeholders(remaining):
        remaining = remaining.replace(token, " ")
    dates, times = _explicit_components(remaining)
    remaining = _ISO_TIMESTAMP.sub(" ", remaining)
    remaining = re.sub(r"(?<=\d)T(?=\d)", " ", remaining, flags=re.I)
    for pattern in _DATE_PATTERNS:
        remaining = pattern.sub(" ", remaining)
    remaining = _CLOCK.sub(lambda match: " " if match["label"] or match["sep"] or match["part"] else match[0], remaining)
    return amounts, dates, times, set(re.findall(r"\d+", remaining))


def _event_states(text: str, pattern, *, delivery=False):
    states = set()
    for clause in re.split(r"[.!?\n;,]|\b(?:tetapi|namun|tapi)\b", text):
        for match in pattern.finditer(clause):
            if delivery and not _GOODS.search(clause):
                continue
            states.add(bool(_NEGATIVE.search(clause[:match.start()])))
    return states


def _recorded_transfer(source: str) -> bool:
    try:
        context = json.loads(source.rsplit("\n", 1)[-1])
    except json.JSONDecodeError:
        return False
    if not isinstance(context, dict):
        return False
    for path, value in context.items():
        if re.fullmatch(r"tahap4\.daftar_penyelenggara_terlapor\.\d+\.daftar_rincian_transaksi\.\d+\.nominal_transaksi", path):
            try:
                parse_rupiah(str(value))
                timestamp = parse_report_datetime(context.get(path.removesuffix("nominal_transaksi") + "waktu_transaksi", ""))
                if timestamp.date is not None and timestamp.time is not None:
                    return True
            except ValueError:
                continue
    return False


def validate_chronology(narrative: str, source: str, allowed_tokens: set[str]) -> None:
    """Reject identifiable inventions before restoring the request-local tokens."""
    if not isinstance(narrative, str) or not narrative.strip() or len(narrative) > 4000:
        raise ValueError(_ERROR)
    if placeholders(narrative) - allowed_tokens or _FORBIDDEN.search(narrative):
        raise ValueError(_ERROR)
    references = lambda text: {match[0].rstrip(".,);]") for match in _REFERENCE.finditer(text)}
    if references(narrative) - references(source):
        raise ValueError(_ERROR)
    try:
        if any(proposed - known for proposed, known in zip(_facts(narrative), _facts(source))):
            raise ValueError(_ERROR)
        private_text = _REFERENCE.sub(" ", _MONEY.sub(" ", narrative))
        for token in placeholders(private_text):
            private_text = private_text.replace(token, "#")
        if placeholders(PrivacyMasker().mask_text(private_text)):
            raise ValueError(_ERROR)
    except (ValueError, OverflowError):
        raise ValueError(_ERROR) from None
    # shortcut: action/negation checks cover common scam events; human review still checks meaning and attribution.
    for index, pattern in enumerate(_EVENTS):
        known = _event_states(source, pattern, delivery=index == 2)
        if index == 0 and _recorded_transfer(source):
            known.add(False)
        if _event_states(narrative, pattern, delivery=index == 2) - known:
            raise ValueError(_ERROR)
