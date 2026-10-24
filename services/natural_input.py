"""Deterministic parsing of explicit Indonesian money, dates, and times."""

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
import re

from schemas import JAKARTA, MONTHS
from services.privacy import sensitive_kind


def parse_private_reply(path: str, text: str) -> str | None:
    """Extract an obvious private scalar; leave prose for the masked interpreter."""
    if not isinstance(text, str) or not text.strip() or "?" in text:
        return None
    value = text.strip()
    kind = sensitive_kind(path)
    if kind == "NIK":
        return value if re.fullmatch(r"[0-9]{16}", value) else None
    if kind == "REKENING":
        account = re.fullmatch(
            r"(?:(?:(?:nomor|no\.?)\s+)?(?:rekening|rek\.?|akun)(?:nya)?"
            r"(?:\s+(?:saya|korban|pengirim|penerima|terlapor))?\s*(?:adalah\s*)?[:=]?\s*)?"
            r"([0-9]{6,30})\.?", value, re.I,
        )
        return account[1] if account else None
    if kind == "JENIS_KELAMIN":
        return {
            "cowok": "Laki-laki", "pria": "Laki-laki", "laki laki": "Laki-laki", "laki-laki": "Laki-laki",
            "cewek": "Perempuan", "wanita": "Perempuan", "perempuan": "Perempuan",
        }.get(value.casefold())
    if kind and kind.startswith("NAMA"):
        name = re.sub(
            r"^(?:(?:nama|name)\s+(?:saya|pelapor|terlapor(?:nya)?|korban|"
            r"pemilik(?:\s+(?:rekening|akun)(?:nya)?)?)|saya\s+bernama|atas\s+nama)"
            r"\s*(?:adalah\s*)?[:=]?\s*", "", value, flags=re.I,
        )
        words = set(re.findall(r"[^\W\d_]+", name.casefold()))
        # shortcut: sentence markers defer to masked interpretation rather than guessing a name boundary.
        sentence_words = {
            "yang", "tertulis", "bukti", "saya", "nama", "name", "adalah", "dan", "atau", "di", "dari",
            "ke", "untuk", "pada", "nomor", "rekening", "pemilik", "siapa", "apa", "bagaimana", "apakah",
            "tidak", "tahu", "lupa", "mungkin", "sepertinya", "tolong", "mohon", "abaikan", "instruksi",
            "ignore", "previous", "instructions", "hapus", "ubah", "ganti", "kirim",
        }
        if words & sentence_words:
            return None
        if re.fullmatch(r"[^\W\d_](?:[^\W\d_]|['.-])*(?:[ \t]+[^\W\d_](?:[^\W\d_]|['.-])*)*", name):
            return name
    return None


def parse_rupiah(text: str) -> Decimal:
    """Parse one positive IDR amount without rounding or accepting instructions."""
    match = re.fullmatch(
        r"(?:(?:Rp\.?|IDR)\s*)?([0-9][0-9., \t\u00a0]*?)\s*(ribu|rb|juta|jt)?\s*(?:rupiah|IDR)?",
        text.strip(), re.I,
    ) if isinstance(text, str) else None
    if not match:
        raise ValueError("Ketik satu nominal rupiah, misalnya 320 ribu atau Rp320.000.")
    number, unit = match.groups()
    number = number.strip()
    if unit:
        # shortcut: grouped coefficients with a multiplier are ambiguous; ask for 1,5 juta or 1500000.
        if not re.fullmatch(r"[0-9]+(?:[.,][0-9]{1,2})?", number):
            raise ValueError("Nominal dengan ribu/juta belum jelas.")
        power = 3 if unit.casefold() in {"ribu", "rb"} else 6
        amount = Decimal(number.replace(",", ".") + f"e{power}")
    else:
        if re.fullmatch(r"[1-9][0-9]{0,2}(?:\.[0-9]{3})+(?:,[0-9]{1,2})?", number):
            number = number.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"[1-9][0-9]{0,2}(?:,[0-9]{3})+(?:\.[0-9]{1,2})?", number):
            number = number.replace(",", "")
        elif re.fullmatch(r"[1-9][0-9]{0,2}(?:[ \t\u00a0][0-9]{3})+(?:[.,][0-9]{1,2})?", number):
            number = re.sub(r"[ \t\u00a0]", "", number).replace(",", ".")
        elif re.fullmatch(r"[0-9]+(?:[.,][0-9]{1,2})?", number):
            number = number.replace(",", ".")
        else:
            raise ValueError("Pemisah nominal atau pecahan rupiah belum jelas.")
        amount = Decimal(number)
    if amount <= 0 or amount.as_tuple().exponent < -2:
        raise ValueError("Nominal harus positif dengan maksimal dua desimal.")
    return amount


@dataclass(frozen=True)
class ParsedDateTime:
    date: date | None = None
    time: time | None = None

    def format(self, *, seconds: bool = False) -> str:
        """Format complete components; the caller validates the reporting slot."""
        if self.date is None or self.time is None:
            raise ValueError("Tanggal dan jam wajib disertakan.")
        clock = self.time.strftime("%H:%M:%S" if seconds else "%H:%M")
        return f"{self.date.day} {MONTHS[self.date.month - 1]} {self.date.year:04d} {clock}"


_MONTH_NUMBERS = {name.casefold(): index for index, name in enumerate(MONTHS, 1)}
_MONTH_NUMBERS.update({name[:3].casefold(): index for index, name in enumerate(MONTHS, 1)})
_MONTH_PATTERN = "|".join(sorted(_MONTH_NUMBERS, key=len, reverse=True))
_ISO_TIMESTAMP = re.compile(
    r"(?<![\w])\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})(?![\d:.])", re.I,
)
_DATE_PATTERNS = (
    re.compile(r"(?<![\w])(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})(?![\d-])"),
    re.compile(r"(?<![\w])(?P<day>\d{1,2})(?P<sep>[-/.])(?P<month>\d{1,2})(?P=sep)(?P<year>\d{4})(?!\d)"),
    re.compile(r"(?<![\w])(?P<day>\d{1,2})\s+(?P<month>" + _MONTH_PATTERN + r")\.?\s+(?P<year>\d{4})(?!\d)", re.I),
)
_CLOCK = re.compile(
    r"(?<![\w:.-])(?:(?P<label>jam|pukul)\s*)?(?P<hour>\d{1,2})"
    r"(?:(?P<sep>[:.])(?P<minute>\d{2})(?:(?P=sep)(?P<second>\d{2}))?)?\s*"
    r"(?P<part>pagi|siang|sore|malam|dini\s*hari|a\.?m\.?|p\.?m\.?)?(?![\w:]|[.,]\d)", re.I,
)


def _explicit_components(text: str) -> tuple[set[date], set[time]]:
    dates, times = set(), set()
    if re.search(r"\d{1,2}:\d{2}:\d{2}[.,]\d+", text):
        raise ValueError("Pecahan detik belum didukung; ketik waktu hingga detik.")
    remaining = text
    for match in _ISO_TIMESTAMP.finditer(remaining):
        value = datetime.fromisoformat(match[0].upper().replace("Z", "+00:00"))
        if value.tzinfo:
            value = value.astimezone(JAKARTA)
        dates.add(value.date())
        times.add(value.time())
    remaining = _ISO_TIMESTAMP.sub(" ", remaining)
    remaining = re.sub(r"(?<=\d)T(?=\d)", " ", remaining, flags=re.I)
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(remaining):
            month = match["month"].casefold()
            dates.add(date(int(match["year"]), int(month) if month.isdigit() else _MONTH_NUMBERS[month], int(match["day"])))
        remaining = pattern.sub(" ", remaining)
    for match in _CLOCK.finditer(remaining):
        if not (match["label"] or match["sep"] or match["part"]):
            continue
        hour = int(match["hour"])
        part = re.sub(r"[\s.]", "", match["part"].casefold()) if match["part"] else None
        if part:
            if not 1 <= hour <= 12:
                raise ValueError("Jam dengan pagi/siang/sore/malam harus antara 1 dan 12.")
            if part in {"am", "pagi", "dinihari"}:
                hour %= 12
            elif part == "siang":
                hour = hour + 12 if hour < 11 else hour
            elif part == "malam":
                hour = 0 if hour == 12 else hour + 12
            else:
                hour = hour % 12 + 12
        times.add(time(hour, int(match["minute"] or 0), int(match["second"] or 0)))
    return dates, times


def parse_report_datetime(text: str, context_text: str = "") -> ParsedDateTime:
    """Collect explicit components only; conflicting dates/times require clarification."""
    dates, times = set(), set()
    for source in (text, context_text):
        if not isinstance(source, str):
            raise ValueError("Tanggal dan jam harus berupa teks.")
        found_dates, found_times = _explicit_components(source)
        dates.update(found_dates)
        times.update(found_times)
    if len(dates) > 1 or len(times) > 1:
        raise ValueError("Ada beberapa tanggal atau jam; ketik satu waktu yang dimaksud.")
    if not dates and not times:
        raise ValueError("Tanggal atau jam belum dikenali.")
    return ParsedDateTime(next(iter(dates), None), next(iter(times), None))
