"""Request-local pseudonyms; their originals never leave the server."""

import json
import re


class PrivacyError(ValueError):
    """Safe error without personal data or provider output."""


_TOKEN = re.compile(r"\[[A-Z][A-Z0-9_]*_[0-9]+\]")
_KINDS = {
    "NAMA_PELAPOR", "NAMA_TERLAPOR", "NAMA", "NIK", "IDENTITAS", "REKENING",
    "EMAIL", "TELEPON", "ALAMAT", "TANGGAL_LAHIR", "TEMPAT_LAHIR", "AGAMA",
    "JENIS_KELAMIN", "PEKERJAAN", "KEWARGANEGARAAN", "LOKASI", "IDENTIFIER", "RAHASIA",
}
_RESERVED = re.compile(r"\[(?:" + "|".join(sorted(_KINDS)) + r")_", re.I)
_EMAIL = re.compile(r"(?<![\w@])[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+(?![\w@])")
_NAME_WORD = r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'.-]*"
_NAME = re.compile(
    r"\b(?:nama\s+(?:saya|pelapor|terlapor|korban|pemilik(?:\s+rekening)?)|saya\s+bernama|"
    r"atas\s+nama|a\s*[./]\s*n\.?|bernama|dihubungi\s+oleh|bapak|ibu|sdr\.?|sdri\.?)\s*[:=]?\s*"
    r"(" + _NAME_WORD + r"(?:[ \t]+" + _NAME_WORD + r"){0,5})", re.I,
)
_NAME_STOP = frozenset((
    "dan", "dengan", "nomor", "no", "alamat", "email", "telepon", "hp", "tanggal",
    "tgl", "lahir", "saya", "telah", "mentransfer", "transfer", "melakukan", "pada",
    "yang", "ke", "dari", "untuk", "sebesar", "adalah", "kemudian", "lalu", "rekening",
))
_CAPITAL_NAME = re.compile(r"(?<![\w])([A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'.-]+(?:[ \t]+[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'.-]+){1,3})(?![\w])")
_PUBLIC_PREFIXES = frozenset(("bank", "pt", "kota", "kabupaten", "provinsi", "jalan", "jl", "dki", "jawa", "sumatera", "sulawesi", "kalimantan", "nusa", "kepulauan", "papua", "whatsapp", "telegram", "instagram"))
_LABEL_NUMBER = re.compile(
    r"\b(nik|(?:nomor|no\.?)\s+identitas|(?:nomor|no\.?)?\s*(?:rekening|rek\.?|akun)|"
    r"(?:nomor|no\.?)?\s*(?:telepon|telp\.?|ponsel|hp|wa)|phone|account)\s*[:=]?\s*"
    r"([+]?[0-9][0-9 ().-]{3,35}[0-9])", re.I,
)
_NUMBER = re.compile(r"(?<![\w@])(?:\+?62|0)?[0-9](?:[ ().-]?[0-9]){6,29}(?![\w@])")
_IDENTIFIER = re.compile(r"\b(?:rrn|referensi|ref(?:erence)?|id\s+transaksi|transaction\s+id)\s*[:=]?\s*([A-Z0-9][A-Z0-9-]{4,39})", re.I)
_SECRET = re.compile(r"\b(?:password|kata\s+sandi|pin|otp|cvv|api[ _-]?key|token)\b(?:\s+saya)?\s*[:=]?\s*(?:\"([^\"\n]+)\"|'([^'\n]+)'|([^\s,;]+))", re.I)
_ADDRESS = re.compile(r"\b(?:Jl\.?|Jalan|Gg\.?|Gang)\s+[^\n;\"']{2,250}", re.I)
_LABEL_ADDRESS = re.compile(r"\balamat(?:\s+(?:saya|pelapor|korban))?\s*[:=]\s*([^\n;\"']{2,250})|\balamat\s+(?:saya|pelapor|korban)\s+([^\n;\"']{2,250})", re.I)
_ADDRESS_END = re.compile(r"\b(?:email|nomor\s+(?:hp|telepon|rekening)|telepon|kemudian|lalu\s+saya|dan\s+saya|saya\s+(?:transfer|mentransfer|mengirim|membayar)|pada\s+(?:tanggal|[0-9]+)|tanggal\s+lahir)\b", re.I)
_DATE_TIME = re.compile(r"(?<![0-9])[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}(?:[ T][0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?(?:Z|[+-][0-9]{2}:?[0-9]{2})?)?(?![0-9])|(?<![0-9])[0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{4}(?![0-9])")
_DOB = re.compile(
    r"\b(?:tanggal\s+lahir|tgl\.?\s+lahir|dob|lahir)\s*[:=]?\s*"
    r"([0-9]{4}-[0-9]{1,2}-[0-9]{1,2}|[0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{4}|"
    r"[0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})", re.I,
)
_AMOUNT_BEFORE = re.compile(
    r"(?:\brp\.?|\bidr|\brupiah|\bnominal(?:_transaksi)?[\"']?|\bsebesar|\bsenilai|\bseharga|"
    r"\bjumlah(?:nya)?|\b(?:mentransfer|transfer|kirim|membayar|pembayaran)(?:\s+uang)?)\s*[:=]?\s*$", re.I,
)


def placeholders(value) -> set[str]:
    """Read tokens in JSON values, for checks that a summary retained the facts."""
    if isinstance(value, str):
        return set(_TOKEN.findall(value))
    if isinstance(value, dict):
        return set().union(*(placeholders(item) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(placeholders(item) for item in value)) if value else set()
    return set()


def sensitive_kind(path: str) -> str | None:
    field = path.rsplit(".", 1)[-1].lower()
    if field in {"nama_pelapor", "victim_name", "reporter_name", "nama_pemilik_rekening_akun_korban", "pelapor_nama", "korban_nama", "nama_pengirim"}:
        return "NAMA_PELAPOR"
    if field in {"nama_terlapor", "suspect_name", "nama_pemilik_rekening_akun", "terlapor_nama", "nama_penerima"}:
        return "NAMA_TERLAPOR"
    if field in {"nomor_identitas", "reporter_id", "korban_nik", "pelapor_nik"}:
        return "NIK"
    if field in {"victim_account", "suspect_account", "rekening_pengirim", "rekening_penerima"} or "nomor_rekening" in field:
        return "REKENING"
    if "email" in field:
        return "EMAIL"
    if field in {"phone", "nomor_terlapor", "pelapor_telepon"} or "nomor_telepon" in field:
        return "TELEPON"
    if field == "address" or "alamat" in field:
        return "ALAMAT"
    for part, kind in (("tanggal_lahir", "TANGGAL_LAHIR"), ("tempat_lahir", "TEMPAT_LAHIR"), ("agama", "AGAMA"), ("jenis_kelamin", "JENIS_KELAMIN"), ("pekerjaan", "PEKERJAAN"), ("kewarganegaraan", "KEWARGANEGARAAN")):
        if part in field:
            return kind
    if "domisili" in field:
        return "LOKASI"
    if field in {"password", "kata_sandi", "pin", "otp", "cvv", "api_key", "token"}:
        return "RAHASIA"
    return None


class PrivacyMasker:
    def __init__(self, context: dict | None = None):
        self._originals: dict[str, str] = {}
        self._by_value: dict[str, str] = {}
        self._counts: dict[str, int] = {}
        self._issued: set[str] = set()
        values = (context or {}).get("values", context or {})
        if isinstance(values, dict):
            self._seed(values)

    @property
    def tokens(self) -> frozenset[str]:
        return frozenset(self._issued)

    def _seed(self, values: dict, prefix: str = ""):
        for field, value in values.items():
            path = f"{prefix}.{field}" if prefix else str(field)
            if isinstance(value, dict):
                self._seed(value, path)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    if isinstance(item, dict):
                        self._seed(item, f"{path}.{index}")
            elif isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip() and (kind := sensitive_kind(path)):
                self._register(str(value), kind)

    def _register(self, value: str, kind: str) -> str:
        if _TOKEN.search(value) or _RESERVED.search(value):
            raise PrivacyError("Pesan mengandung penanda privasi cadangan. Hapus penanda tersebut lalu coba lagi.")
        normalized = value.strip().casefold()
        if normalized in self._by_value:
            return self._by_value[normalized]
        self._counts[kind] = self._counts.get(kind, 0) + 1
        token = f"[{kind}_{self._counts[kind]}]"
        self._originals[token] = value.strip()
        self._by_value[normalized] = token
        return token

    def mask_text(self, text: str) -> str:
        if not isinstance(text, str):
            raise PrivacyError("Teks untuk perlindungan data tidak valid.")
        if _TOKEN.search(text) or _RESERVED.search(text):
            raise PrivacyError("Pesan mengandung penanda privasi cadangan. Hapus penanda tersebut lalu coba lagi.")
        spans = []

        def add(start: int, end: int, kind: str):
            while end > start and text[end - 1].isspace():
                end -= 1
            if end > start:
                spans.append((start, end, self._register(text[start:end], kind)))

        for token, original in list(self._originals.items()):
            if not original:
                continue
            for variant in {original, json.dumps(original, ensure_ascii=False)[1:-1]}:
                pattern = re.compile(r"(?<!\w)" + re.escape(variant) + r"(?!\w)", re.I)
                spans.extend((match.start(), match.end(), token) for match in pattern.finditer(text))
        for match in _EMAIL.finditer(text):
            add(match.start(), match.end(), "EMAIL")
        numeric = list(text)
        for date in _DATE_TIME.finditer(text):
            numeric[date.start():date.end()] = "#" * len(date[0])
        numeric = "".join(numeric)
        for match in _LABEL_NUMBER.finditer(numeric):
            label = match[1].lower()
            kind = "NIK" if "nik" in label or "identitas" in label else "REKENING" if re.search(r"rek|akun|account", label) else "TELEPON"
            add(match.start(2), match.end(2), kind)
        for match in _IDENTIFIER.finditer(text):
            add(match.start(1), match.end(1), "IDENTIFIER")
        for match in _SECRET.finditer(text):
            group = next(index for index in (1, 2, 3) if match[index] is not None)
            add(match.start(group), match.end(group), "RAHASIA")
        for match in _NUMBER.finditer(numeric):
            before, after = text[max(0, match.start() - 90):match.start()], text[match.end():match.end() + 12]
            if _AMOUNT_BEFORE.search(before) or re.match(r"\s*(?:rupiah|idr)\b", after, re.I):
                continue
            digits = re.sub(r"\D", "", match[0])
            kind = "NIK" if len(digits) == 16 else "TELEPON" if re.match(r"(?:\+?62|08)", match[0]) else "IDENTIFIER"
            add(match.start(), match.end(), kind)
        for match in _NAME.finditer(text):
            words = list(re.finditer(_NAME_WORD, match[1]))
            stop = next((word.start() for word in words[1:] if word[0].casefold().strip(".") in _NAME_STOP), len(match[1]))
            add(match.start(1), match.start(1) + stop, "NAMA")
        # shortcut: unknown lowercase names need a name label or session context; add local NER if free-form recall is required.
        for match in _CAPITAL_NAME.finditer(text):
            words = list(re.finditer(_NAME_WORD, match[1]))
            if words[0][0].casefold().strip(".") in _PUBLIC_PREFIXES | _NAME_STOP:
                continue
            stop = next((index for index, word in enumerate(words[1:], 1) if word[0].casefold().strip(".") in _NAME_STOP), len(words))
            if stop >= 2:
                add(match.start(1), match.start(1) + words[stop - 1].end(), "NAMA")
        for match in _ADDRESS.finditer(text):
            tail = _ADDRESS_END.search(match[0])
            add(match.start(), match.start() + tail.start() if tail else match.end(), "ALAMAT")
        for match in _LABEL_ADDRESS.finditer(text):
            group = 1 if match[1] is not None else 2
            tail = _ADDRESS_END.search(match[group])
            add(match.start(group), match.start(group) + tail.start() if tail else match.end(group), "ALAMAT")
        for match in _DOB.finditer(text):
            add(match.start(1), match.end(1), "TANGGAL_LAHIR")
        chosen, end = [], -1
        for start, stop, token in sorted(spans, key=lambda item: (item[0], -(item[1] - item[0]))):
            if start >= end:
                chosen.append((start, stop, token))
                end = stop
        result, cursor = [], 0
        for start, stop, token in chosen:
            result.extend((text[cursor:start], token))
            self._issued.add(token)
            cursor = stop
        result.append(text[cursor:])
        return "".join(result)

    def restore(self, value):
        if isinstance(value, dict):
            return {key: self.restore(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.restore(item) for item in value]
        if not isinstance(value, str):
            return value
        if placeholders(value) - self.tokens:
            raise PrivacyError("AI mengembalikan penanda data yang tidak dikenal. Mohon coba kembali.")
        result = _TOKEN.sub(lambda match: self._originals[match[0]], value)
        if _RESERVED.search(result):
            raise PrivacyError("AI mengembalikan penanda data tidak lengkap. Mohon coba kembali.")
        return result
