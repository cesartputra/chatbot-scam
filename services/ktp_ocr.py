"""Local Tesseract KTP extraction. Neither document pixels nor OCR text leave the server."""

from io import BytesIO
import re

from PIL import Image, ImageOps, UnidentifiedImageError

from schemas import validate_slot_value
from services.image_processor import ImageProcessingError, local_ocr_text
from services.normalizer import normalize_ktp_slot, normalize_location


_FIELDS = (
    "nama_pelapor", "tempat_lahir_pelapor", "tanggal_lahir_pelapor", "jenis_kelamin",
    "agama_pelapor", "pekerjaan_pelapor", "kewarganegaraan_pelapor", "jenis_identitas",
    "nomor_identitas", "provinsi_domisili_pelapor", "kota_domisili_pelapor", "alamat_pelapor",
)
_CANONICAL = re.compile(
    r"^(?:tahap1[.\s])?(" + "|".join(field.replace("_", r"[_\s]+") for field in _FIELDS)
    + r")(?:\s*[:=]\s*|\s+)(.+)$", re.IGNORECASE,
)
_LABELS = (
    (r"N[I1]K", "nomor_identitas"),
    (r"Nama", "nama_pelapor"),
    (r"Tempat\s*[/,]\s*(?:Tgl\.?|Tanggal)\s*Lahir", "birthplace_date"),
    (r"Jenis\s+Kelamin", "jenis_kelamin"),
    (r"Alamat", "alamat_pelapor"),
    (r"RT\s*[/,I]\s*RW", "rt_rw"),
    (r"Kel\.?\s*[/,]?\s*Desa", "kelurahan"),
    (r"Kecamatan", "kecamatan"),
    (r"Agama", "agama_pelapor"),
    (r"Pekerjaan", "pekerjaan_pelapor"),
    (r"Kewarganegaraan", "kewarganegaraan_pelapor"),
    (r"Provinsi", "provinsi_domisili_pelapor"),
    (r"(?:Kabupaten|Kota)(?:\s*/\s*Kota)?", "kota_domisili_pelapor"),
)
_LABEL_PATTERNS = tuple(
    (re.compile(r"^" + label + r"(?:\s*_?\s*[:=]\s*|\s+)(.+)$", re.IGNORECASE), field)
    for label, field in _LABELS
)
_BIRTH_DATE = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2}|\d{1,2}[-/]\d{1,2}[-/]\d{4}|"
    r"\d{1,2}\s+[A-Za-z]+\s+\d{4})[\s.,|]*$"
)


def _ocr_image(image_bytes: bytes, *, body_only=False) -> bytes:
    """Enlarge small cards for Tesseract without creating persistent identity files."""
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image = ImageOps.autocontrast(ImageOps.grayscale(ImageOps.exif_transpose(image)))
            if body_only:
                # Standard landscape KTP puts identity labels left of the portrait.
                image = image.crop((0, 0, round(image.width * 0.68), image.height))
            if image.width < 1400:
                image = image.resize((1400, round(image.height * 1400 / image.width)), Image.Resampling.LANCZOS)
            image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ImageProcessingError("Gambar KTP tidak dapat dibaca. Gunakan JPG/PNG yang jelas atau isi lewat chat.") from None


def _parse_ktp_text(text: str) -> tuple[dict, dict]:
    values, confidence = {}, {}
    conflicts = set()
    parts = {}
    provinces, cities = [], []
    after_province_header = False

    def put(field, raw):
        path = "tahap1." + field
        if path in conflicts:
            return
        try:
            value = validate_slot_value(path, normalize_ktp_slot(path, raw))
        except (TypeError, ValueError):
            return  # One unreadable field must not discard the other local OCR results.
        if field == "jenis_identitas" and value != "KTP":
            return
        if path in values and values[path] != value:
            values.pop(path, None)
            confidence.pop(path, None)
            conflicts.add(path)  # Conflicting readable values require a human answer.
            return
        values[path] = value
        # This is a conservative parsing heuristic, not a calibrated OCR probability.
        confidence[path] = 0.90

    def part(field, raw):
        raw = raw.strip(" :;|\t")
        if field == "rt_rw" and not re.fullmatch(r"[0-9]{1,3}\s*/\s*[0-9]{1,3}", raw):
            return
        if field in parts and parts[field] != raw:
            parts[field] = ""  # Do not choose between inconsistent address fragments.
        else:
            parts[field] = raw

    for line in text.splitlines():
        line = " ".join(line.strip(" |\t‘’'\"_").split())
        if not line:
            continue
        match = _CANONICAL.fullmatch(line)
        if match:
            field = re.sub(r"[\s_]+", "_", match[1].lower())
            raw = match[2].strip()
            header = False
        else:
            matched = next(((match, field) for pattern, field in _LABEL_PATTERNS if (match := pattern.fullmatch(line))), None)
            if not matched:
                if after_province_header:
                    cities.append(line)
                after_province_header = False
                continue
            match, field = matched
            raw = match[1].strip()
            header = field == "provinsi_domisili_pelapor"
        after_province_header = header
        if field == "provinsi_domisili_pelapor":
            provinces.append(raw)
        elif field == "kota_domisili_pelapor":
            cities.append(raw)
        elif field == "birthplace_date":
            date_match = _BIRTH_DATE.search(raw)
            if date_match:
                birthplace = raw[:date_match.start()].strip(" ,;:")
                if birthplace:
                    put("tempat_lahir_pelapor", birthplace)
                put("tanggal_lahir_pelapor", date_match["date"])
        elif field == "jenis_kelamin":
            # On KTP, blood type is printed on the same row as gender.
            gender = re.split(r"\s+Gol(?:ongan)?\.?\s*(?:Darah)?\b", raw, maxsplit=1, flags=re.IGNORECASE)[0]
            put(field, gender.strip())
        elif field in {"alamat_pelapor", "rt_rw", "kelurahan", "kecamatan"}:
            part(field, raw)
        else:
            put(field, raw)

    normalized_provinces = {province for raw in provinces if (province := normalize_location("", raw)[0])}
    if len(normalized_provinces) <= 1:
        province = next(iter(normalized_provinces), None)
        normalized_cities = {location for raw in cities if (location := normalize_location(raw, province))[1]}
        if len(normalized_cities) == 1:
            province, city = normalized_cities.pop()
            put("kota_domisili_pelapor", city)
        if province:
            put("provinsi_domisili_pelapor", province)

    if address := parts.get("alamat_pelapor"):
        for field, label in (("rt_rw", "RT/RW"), ("kelurahan", "Kel/Desa"), ("kecamatan", "Kecamatan")):
            fragment = parts.get(field)
            if fragment and fragment.casefold() not in address.casefold():
                address += f", {label} {fragment}"
        put("alamat_pelapor", address)
    return values, confidence


def extract_ktp_locally(image_bytes: bytes) -> tuple[dict, dict]:
    """Return validated tahap1.* values and heuristic confidence using only local OCR.

    Missing/invalid/ambiguous fields remain missing for delta slot filling. This
    blocking function belongs in asyncio.to_thread; it never calls an AI provider.
    """
    text = local_ocr_text(_ocr_image(image_bytes))
    values, confidence = _parse_ktp_text(text)
    # A second local crop can recover fields hidden by portrait/background noise.
    # Never apply it to schema-label fixtures, arbitrary uploads, or portrait pages.
    standard_card = re.search(r"^\s*N[I1]K(?:\s|:)", text, re.IGNORECASE | re.MULTILINE) and re.search(r"Tempat\s*[/,]", text, re.IGNORECASE)
    with Image.open(BytesIO(image_bytes)) as image:
        landscape = image.width >= image.height * 1.2
    expected = {"tahap1." + field for field in _FIELDS if field != "jenis_identitas"}
    if standard_card and landscape and expected - values.keys():
        try:
            cropped, _ = _parse_ktp_text(local_ocr_text(_ocr_image(image_bytes, body_only=True)))
        except ImageProcessingError:
            cropped = {}  # Keep usable first-pass results if the optional pass fails.
        for path, value in cropped.items():
            if path not in values:
                values[path], confidence[path] = value, 0.85
            elif values[path] != value:
                confidence[path] = 0.70  # Different local readings require confirmation.
    return values, confidence
