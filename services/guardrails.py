"""Deterministic input policy. The model cannot grant itself permission."""

from html import unescape
import re
import unicodedata
from urllib.parse import unquote


ALLOWED_LLM_TASKS = {
    "extract_report_fields", "extract_transfer_proof",
    "extract_victim_account_proof", "extract_chat_proof",
}
MAX_USER_TEXT = 2000
REFUSAL_MESSAGE = (
    "Maaf, asisten ini hanya memproses data pelaporan penipuan keuangan IASC "
    "(kronologi kejadian, data rekening, dan bukti transaksi). Mohon masukkan "
    "informasi atau unggah bukti yang berkaitan dengan laporan Anda."
)


class GuardrailViolation(ValueError):
    """A safe refusal that never echoes user data or instructions."""


def require_allowed_task(task: str) -> None:
    if not isinstance(task, str) or task not in ALLOWED_LLM_TASKS:
        raise GuardrailViolation(REFUSAL_MESSAGE)


def _normalized(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return "".join(char for char in text if not unicodedata.category(char).startswith("C") or char in "\n\t")


def sanitize_user_text(text: str) -> str:
    if not isinstance(text, str) or not 0 < len(text) <= MAX_USER_TEXT:
        raise GuardrailViolation(REFUSAL_MESSAGE)
    text = _normalized(text).strip()
    if not text or len(text) > MAX_USER_TEXT:
        raise GuardrailViolation(REFUSAL_MESSAGE)
    return text


_INJECTION = re.compile(
    r"\b(?:ignore|disregard|forget|override|bypass)\s+(?:(?:all|the|any)\s+)?"
    r"(?:(?:previous|prior|earlier|above|system|developer|safety)\s+)*(?:instructions?|rules?|polic(?:y|ies)|prompts?)\b"
    r"|\b(?:abaikan|lupakan|langgar|lewati)\s+(?:(?:semua|seluruh|segala)\s+)?(?:instruksi|aturan|perintah|kebijakan|batasan)\b"
    r"|\b(?:jangan|tidak\s+perlu)\s+(?:ikuti|patuhi)\s+(?:instruksi|aturan|perintah)\b"
    r"|\b(?:system\s+prompt|prompt\s+sistem|act\s+as|berperan\s+sebagai|pretend\s+to\s+be|"
    r"jailbreak|developer\s+mode|mode\s+developer|roleplay|you\s+are\s+now|anda\s+sekarang\s+adalah)\b"
    r"|<\s*/?\s*(?:system|user|assistant|developer|untrusted_user_report)\b"
    r"|<\|\s*(?:im_start|im_end|system|assistant|user)\s*\|>"
    r"|```|<\s*(?:script|iframe|object|embed)\b|\bjavascript\s*:|\bdata\s*:\s*text/html"
    r"|<[^>\n]{1,500}\bon[a-z]+\s*="
    r"|(?:\([^()\n]{0,100}\)|\b[A-Za-z_$][\w$]*)\s*=>"
    r"|\b(?:DROP|TRUNCATE|ALTER)\s+(?:TABLE|DATABASE|SCHEMA)\b|\bDELETE\s+FROM\b"
    r"|\bUPDATE\s+\w+\s+SET\b|\bINSERT\s+INTO\b"
    r"|(?:^|[\r\n])\s*(?:SYSTEM|DEVELOPER|ASSISTANT|USER)\s*:"
    r"|(?:^|\n)\s*(?:import\s+\w|from\s+\w+[.\w]*\s+import\b|def\s+\w+\s*\(|"
    r"function\s+\w*\s*\(|(?:const|let|var)\s+\w+\s*=|SELECT\s+.+\s+FROM\b)"
    r"|\b(?:os\.system|subprocess\.(?:run|Popen)|eval|exec)\s*\(|\brm\s+-[a-z]*rf\b",
    re.IGNORECASE,
)
_REQUEST = r"(?:buat(?:kan)?|tulis(?:kan)?|jelaskan|ajarkan|ceritakan|generate|write|create|explain|teach|tell\s+me|give\s+me|help\s+me)"
_UNRELATED = r"(?:kode|coding|pemrograman|algoritma|algorithm|program(?:ming)?|script|python|javascript|typescript|sql|html|css|puisi|pantun|lelucon|joke|poem|resep|recipe|politik|presiden|president|pemilu|election|cuaca|weather|ibu\s+kota|capital\s+city|horoskop|horoscope)"
_UNRELATED_REQUEST = re.compile(
    r"\b" + _REQUEST + r"\b[^.!?]{0,100}\b" + _UNRELATED + r"\b"
    r"|\b(?:siapa|apa|bagaimana|berapa|who|what|how)\b[^.!?]{0,80}\b" + _UNRELATED + r"\b"
    r"|\b(?:apa\s+kabar|how\s+are\s+you|siapa\s+kamu|who\s+are\s+you)\b",
    re.IGNORECASE,
)
_GREETING = re.compile(r"\s*(?:halo|hello|hai|hi|hey|selamat\s+(?:pagi|siang|sore|malam)|saya\s+bingung|tidak\s+mengerti|bantuan|help)[\s.!?]*", re.IGNORECASE)
_GENERAL_FINANCE_QUESTION = re.compile(r"^\s*(?:apa\s+itu|what\s+is|jelaskan\s+(?:apa\s+itu\s+)?)\s+(?:rekening|bank|uang|transfer|money|banking)\b", re.IGNORECASE)
_QUESTION_START = re.compile(r"^(?:apa|siapa|kapan|di\s+mana|bagaimana|mengapa|kenapa|berapa|what|who|when|where|how|why|can\s+you|could\s+you)\b", re.IGNORECASE)
_REPORT = re.compile(
    r"\b(?:penipuan|penipu|ditipu|tertipu|pelaku|korban|pelapor|terlapor|laporan|melapor|pelaporan|kronologi|"
    r"rekening|transaksi|transfer|mentransfer|ditransfer|bukti|scam|fraud|receipt|transaction|payment|"
    r"bayar|membayar|pembayaran|refund|saldo|bank|rrn|phishing|investasi|uang|dana)\b",
    re.IGNORECASE,
)
_MISSING_PURCHASE = re.compile(r"\b(?:membeli|memesan|beli|bought|ordered)\b.*\b(?:tidak|belum|never|not)\b.*\b(?:dikirim|diterima|sampai|delivered|received)\b", re.IGNORECASE | re.DOTALL)


def detect_prompt_injection(text: str) -> bool:
    if not isinstance(text, str):
        return False
    # Decode common transport disguises before checking; no remote classifier sees it.
    decoded = unicodedata.normalize("NFKC", unescape(unquote(text)))
    normalized = _normalized(decoded)
    spaced = "".join(" " if unicodedata.category(char).startswith("C") else char for char in decoded)
    return any(_INJECTION.search(value) for value in (decoded, normalized, spaced, re.sub(r"[_-]+", " ", normalized)))


def looks_like_ktp(text: str) -> bool:
    """Detect identity-card labels locally before any image may leave the server."""
    if not isinstance(text, str):
        return False
    text = _normalized(text)
    if re.search(r"\bkartu\s+tanda\s+penduduk\b|\bnomor[_\s]+identitas\b|\bjenis[_\s]+identitas\s*[:=]\s*ktp\b", text, re.IGNORECASE):
        return True
    if re.search(r"\bN[I1]K\s*[:=]?\s*(?:[0-9][ -]*){16}(?![0-9])", text, re.IGNORECASE):
        return True
    labels = (
        r"\btempat\s*[/,]\s*(?:tgl\.?|tanggal)\s+lahir\b",
        r"\bjenis[_\s]+kelamin\b", r"\bagama\b",
        r"\brt\s*/\s*rw\b", r"\bkewarganegaraan\b",
    )
    return bool(re.search(r"\bprovinsi\b", text, re.IGNORECASE) and sum(bool(re.search(label, text, re.IGNORECASE)) for label in labels) >= 2)


def is_clearly_out_of_scope(text: str) -> bool:
    if not isinstance(text, str):
        return True
    text = _normalized(text)
    return bool(_GREETING.fullmatch(text) or _UNRELATED_REQUEST.search(text) or _GENERAL_FINANCE_QUESTION.search(text))


def is_within_reporting_scope(text: str) -> bool:
    if not isinstance(text, str) or not 0 < len(text) <= MAX_USER_TEXT:
        return False
    text = _normalized(text)
    if detect_prompt_injection(text) or is_clearly_out_of_scope(text):
        return False
    # shortcut: lexical scope checks are conservative; ambiguous narratives need human clarification.
    return bool(_REPORT.search(text) or _MISSING_PURCHASE.search(text))


def check_user_input(text: str, *, allow_scalar: bool = False) -> str:
    original = text
    text = sanitize_user_text(text)
    if detect_prompt_injection(original) or detect_prompt_injection(text) or is_clearly_out_of_scope(text):
        raise GuardrailViolation(REFUSAL_MESSAGE)
    if is_within_reporting_scope(text):
        return text
    if allow_scalar and len(text) <= 500 and "?" not in text and not _QUESTION_START.search(text) and not re.search(r"\b" + _REQUEST + r"\b", text, re.IGNORECASE):
        return text
    raise GuardrailViolation(REFUSAL_MESSAGE)


def require_reporting_text(text: str) -> str:
    return check_user_input(text)
