"""Image-only intake: validate bytes, remove metadata and fit the strictest limit."""

from dataclasses import dataclass
import hashlib
import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_RAW_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 12_000_000
TARGET_BYTES = 900_000
ALLOWED_MIME = {"image/jpeg": "JPEG", "image/jpg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


class ImageProcessingError(ValueError):
    pass


@dataclass(frozen=True)
class ProcessedFile:
    data: bytes
    filename: str
    mime_type: str
    size: int
    sha256: str


# One stored object can satisfy multiple form fields without duplicating uploads.
SMART_POINTERS = {
    "ktp": ("tahap1.upload_kartu_identitas_korban",),
    "bukti_chat": (
        "tahap2.daftar_informasi_terlapor.0.upload_bukti_komunikasi",
        "tahap2.daftar_sumber_media_penipuan.0.upload_bukti_sumber_media",
        "tahap3.upload_bukti_pendukung_kejadian",
    ),
    "bukti_transfer": (
        "tahap4.daftar_penyelenggara_terlapor.0.daftar_rincian_transaksi.0.upload_bukti_pendukung_kejadian",
    ),
    "bukti_rekening_korban": ("tahap4.bukti_kepemilikan_rekening_akun_korban",),
}


def evidence_pointer_map(kind: str) -> tuple[str, ...]:
    if kind not in SMART_POINTERS:
        raise ValueError("Jenis bukti tidak dikenal.")
    return SMART_POINTERS[kind]


def smart_file_reuse(kind: str, metadata: object) -> dict[str, object]:
    return dict.fromkeys(evidence_pointer_map(kind), metadata)


def process_image(raw: bytes, filename: str, content_type: str) -> ProcessedFile:
    """Return a clean JPEG below 900 kB; never trust a filename or MIME header."""
    if not raw or len(raw) > MAX_RAW_BYTES:
        raise ImageProcessingError("Ukuran unggahan harus 1 byte sampai 10 MiB.")
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime not in ALLOWED_MIME:
        raise ImageProcessingError("Unggah JPG, PNG, atau WebP. Ekstraksi PDF belum didukung; ubah halaman menjadi gambar.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != ALLOWED_MIME[mime]:
                    raise ImageProcessingError("Isi gambar tidak cocok dengan jenis file unggahan.")
                if image.width * image.height > MAX_PIXELS:
                    raise ImageProcessingError("Resolusi gambar melebihi 12 megapiksel.")
                if getattr(image, "n_frames", 1) != 1:
                    raise ImageProcessingError("Gunakan gambar diam, bukan gambar animasi.")
                image.verify()
            with Image.open(io.BytesIO(raw)) as source:
                oriented = ImageOps.exif_transpose(source).convert("RGBA")
                clean = Image.new("RGB", oriented.size, "white")
                clean.paste(oriented, mask=oriented.getchannel("A"))
        clean.thumbnail((4000, 4000), Image.Resampling.LANCZOS)
        while True:
            for quality in (92, 86, 80, 74):
                buffer = io.BytesIO()
                clean.save(buffer, "JPEG", quality=quality, optimize=True, progressive=True)
                data = buffer.getvalue()
                if len(data) < TARGET_BYTES:
                    digest = hashlib.sha256(data).hexdigest()
                    return ProcessedFile(data, f"evidence-{digest[:16]}.jpg", "image/jpeg", len(data), digest)
            if max(clean.size) <= 640:
                raise ImageProcessingError("Gambar tidak dapat dikompresi dengan aman. Unggah potongan yang lebih jelas.")
            clean.thumbnail((max(1, int(clean.width * 0.82)), max(1, int(clean.height * 0.82))), Image.Resampling.LANCZOS)
    except ImageProcessingError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageProcessingError("Gambar rusak, tidak valid, atau terlalu besar.") from None
