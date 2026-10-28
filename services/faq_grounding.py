"""Small curated FAQ retrieval; text and model output never control the form."""

import re
import unicodedata
from typing import Literal

from services.guardrails import detect_prompt_injection, is_clearly_out_of_scope


TurnIntent = Literal["SLOT_INPUT", "IASC_FAQ_QUESTION", "MIXED_INPUT_AND_QUESTION", "OUT_OF_CONTEXT"]

# Local form guidance is explicitly attributed: it is not an OJK platform promise.
IASC_FAQ_KNOWLEDGE_BASE = [
    {
        "id": "faq_bukti_rekening_digital",
        "question": "Pakai bank digital tanpa buku tabungan, unggah apa?",
        "answer": "Panduan formulir aplikasi ini: untuk Blu, Jago, SeaBank, Jenius atau e-wallet, gunakan tangkapan layar profil rekening yang menampilkan nama pemilik dan nomor rekening, kepala e-statement, atau detail kartu digital yang memuat keduanya; lampiran formulir PDF/JPG/PNG maksimal 2 MB, sedangkan chat menerima gambar dan belum menerima PDF.",
        "keywords": ("bank digital", "buku tabungan", "blu", "jago", "seabank", "jenius", "e wallet", "ewallet", "dompet digital", "e statement", "kartu digital", "kepemilikan rekening"),
        "states": ("ACCOUNT_PROOF_UPLOAD", "ACCOUNT_DETAILS"),
        "provenance": "Panduan aplikasi dari formulir rekening; contoh dokumen bukan ketentuan tersurat FAQ resmi.",
    },
    {
        "id": "faq_jaminan_uang_kembali",
        "question": "Apakah uang saya pasti kembali?",
        "answer": "IASC tidak menjamin uang kembali 100%; koordinasi penundaan transaksi mengupayakan penyelamatan dana yang masih tersisa, sehingga hasilnya bergantung pada kecepatan pelaporan dan keberadaan dana.",
        "keywords": ("uang kembali", "dana kembali", "dijamin", "jaminan", "menjamin", "100 persen", "refund", "pengembalian dana"),
        "states": (),
        "provenance": "FAQ resmi: kepastian pengembalian dana dan pelaporan cepat.",
    },
    {
        "id": "faq_laporan_polisi_opsional",
        "question": "Apakah wajib unggah laporan polisi sekarang?",
        "answer": "Unggah Laporan Polisi dapat dilewati pada tahap awal aplikasi ini; untuk jalur hukum, panduan resmi IASC tetap mewajibkan laporan ke polisi selain laporan finansial ke IASC.",
        "keywords": ("polisi", "kepolisian", "lp", "surat laporan", "jalur hukum"),
        "states": ("POLICE_REPORT_OPTIONAL", "CHRONOLOGY_INPUT", "KEJADIAN_DETAILS"),
        "provenance": "FAQ resmi tentang kewajiban dua jalur; opsi melewati unggahan hanya perilaku aplikasi lokal.",
    },
    {
        "id": "faq_batas_ukuran_file",
        "question": "Berapa batas ukuran file KTP dan bukti?",
        "answer": "Panduan formulir aplikasi ini: KTP maksimal 1 MB dan bukti komunikasi, media, pendukung serta rekening maksimal 2 MB dalam PDF/JPG/PNG; chat menerima JPG/PNG/WebP, mengompresi gambar secara otomatis di bawah 900 KB, dan meminta halaman PDF diubah menjadi gambar.",
        "keywords": ("ukuran", "mb", "kb", "format", "pdf", "jpg", "png", "webp", "kompres", "file besar", "terlalu besar", "batas file", "limit file"),
        "states": ("KTP_UPLOAD", "CHAT_EVIDENCE_UPLOAD", "ACCOUNT_PROOF_UPLOAD", "TRANSFER_UPLOAD"),
        "provenance": "Batas formulir replika dan layanan gambar lokal; bukan verifikasi batas portal resmi.",
    },
    {
        "id": "faq_mewakili_korban",
        "question": "Bagaimana melapor mewakili keluarga?",
        "answer": "Pilih 'Tidak, saya mewakili korban' pada tahap 1 aplikasi ini dan lengkapi identitas serta rekening yang diminta; panduan resmi mensyaratkan Surat Kuasa dan identitas korban untuk perwakilan.",
        "keywords": ("mewakili", "perwakilan", "atas nama", "surat kuasa", "keluarga", "orang lain"),
        "states": ("PELAPOR_STATUS", "PELAPOR_DETAILS", "KTP_UPLOAD"),
        "provenance": "Persiapan resmi bagi perwakilan; pilihan tahap 1 dari aplikasi lokal.",
    },
    {
        "id": "faq_waktu_golden_period",
        "question": "Apa arti timer 60 menit dan Golden Period?",
        "answer": "Segera laporkan karena dana dapat cepat dipindahkan pelaku; Golden Period berarti kesempatan penanganan dini, sedangkan timer 60 menit adalah masa sesi aplikasi ini, bukan jaminan pengembalian atau batas waktu penanganan IASC.",
        "keywords": ("golden period", "timer", "60 menit", "satu jam", "batas waktu", "cepat melapor", "segera melapor", "terlambat", "kedaluwarsa", "kadaluarsa"),
        "states": (),
        "provenance": "Urgensi dari FAQ resmi; timer dari SESSION_TTL aplikasi lokal.",
    },
    {
        "id": "faq_rekening_terlapor_banyak",
        "question": "Bagaimana melapor beberapa rekening atau transfer?",
        "answer": "Aplikasi ini dapat mencatat beberapa transaksi dan rekening terlapor pada tahap 4; portal resmi menyebut transfer ke rekening penipu berbeda mungkin memerlukan laporan terpisah.",
        "keywords": ("beberapa rekening", "banyak rekening", "lebih dari satu rekening", "dua rekening", "beberapa transfer", "banyak transfer", "beberapa transaksi", "transfer berkali", "transfer berulang", "laporan terpisah"),
        "states": ("TRANSFER_UPLOAD", "TRANSFER_DETAILS", "TRANSFER_MORE"),
        "provenance": "Persiapan transaksi resmi dan dukungan beberapa baris pada aplikasi lokal.",
    },
    {
        "id": "faq_keamanan_data_ktp",
        "question": "Mengapa KTP diperlukan dan apakah data aman?",
        "answer": "IASC meminta identitas untuk verifikasi dan menyatakan perlindungan data sesuai UU PDP; OCR KTP lokal serta e-KYC simulasi pada aplikasi ini bukan verifikasi identitas produksi OJK.",
        "keywords": ("data aman", "keamanan", "privasi", "pdp", "ktp diperlukan", "perlu ktp", "kenapa ktp", "mengapa ktp", "e kyc", "ekyc", "verifikasi identitas", "data pribadi", "nik"),
        "states": ("KTP_UPLOAD", "PELAPOR_DETAILS", "FINAL_CONFIRMATION"),
        "provenance": "Kebijakan privasi resmi; OCR lokal dan e-KYC simulasi dari implementasi aplikasi.",
    },
    {
        "id": "faq_arti_status_laporan",
        "question": "Bagaimana cek status tiket setelah laporan dikirim?",
        "answer": "Pada portal resmi, simpan nomor laporan lalu gunakan Cek Laporan di iasc.ojk.go.id untuk memantau tindak lanjut; penyelesaian simulasi aplikasi ini bukan bukti pengiriman ke OJK.",
        "keywords": ("status", "tiket", "cek laporan", "lacak", "setelah submit", "setelah kirim", "setelah melapor", "sesudah melapor", "nomor laporan"),
        "states": ("FINAL_CONFIRMATION", "COMPLETED"),
        "provenance": "Langkah pelaporan portal resmi; pengiriman aplikasi harus dibedakan dari tiket resmi.",
    },
    {
        "id": "faq_bukti_chat_terhapus",
        "question": "Chat dihapus atau saya diblokir, bukti apa yang bisa disiapkan?",
        "answer": "Panduan aplikasi ini: simpan bukti yang masih tersedia seperti transfer, profil atau nomor pelaku, sumber iklan dan tangkapan layar yang tersisa, lalu jelaskan chat yang terhapus atau pemblokiran dalam kronologi; jangan membuat percakapan pengganti, dan kelengkapan bukti tetap perlu diperiksa.",
        "keywords": ("chat terhapus", "chat dihapus", "percakapan terhapus", "percakapan dihapus", "dihapus", "terhapus", "diblokir", "blokir whatsapp", "chat hilang", "bukti hilang"),
        "states": ("CHAT_EVIDENCE_UPLOAD", "CHAT_MORE", "CHRONOLOGY_INPUT"),
        "provenance": "Panduan aplikasi berdasarkan jenis bukti; bukan pengecualian syarat bukti resmi.",
    },
    {
        "id": "faq_bukti_transfer",
        "question": "Apa yang harus terlihat pada bukti transfer?",
        "answer": "Siapkan bukti transfer berhasil beserta rekening asal dan tujuan, waktu serta nominal; panduan aplikasi ini meminta gambar terbaca agar isinya dapat diperiksa.",
        "keywords": ("bukti transfer", "bukti transaksi", "struk", "transfer berhasil", "nominal transfer"),
        "states": ("TRANSFER_UPLOAD", "TRANSFER_DETAILS"),
        "provenance": "Daftar persiapan transaksi dan bukti resmi; keterbacaan dari validasi aplikasi.",
    },
    {
        "id": "faq_kabar_pengembalian_dana",
        "question": "Siapa yang mengabari jika dana bisa dikembalikan?",
        "answer": "Jika dana dapat dikembalikan, pemberitahuan resmi datang dari Bank/PJP tempat Anda melakukan transfer.",
        "keywords": ("siapa menghubungi", "siapa yang menghubungi", "siapa mengabari", "siapa yang mengabari", "kabar dana", "kabar pengembalian", "dihubungi", "pemberitahuan"),
        "states": ("FINAL_CONFIRMATION", "COMPLETED"),
        "provenance": "FAQ resmi: pihak yang mengabari hasil penyelamatan dana.",
    },
]
for _entry in IASC_FAQ_KNOWLEDGE_BASE:
    _entry.update(source_url="https://iasc.ojk.go.id/", reviewed_on="2026-10-28")

_BY_ID = {entry["id"]: entry for entry in IASC_FAQ_KNOWLEDGE_BASE}
_QUESTION = re.compile(r"\b(?:apa(?:kah)?|bagaimana|gimana|gmn|mengapa|kenapa|berapa|kapan|siapa|mana|kalau|kalo|wajib|boleh|bisa\s+(?:gak|ga|nggak|tidak))\b", re.I)
_REPORT = re.compile(r"\b(?:iasc|ojk|bank|rekening|uang|dana|laporan|lapor|melapor|pelaporan|penipuan|penipu|korban|bukti|ktp|nik|sim|transfer|transaksi|email|hp|unggah|upload|diupload|chat|polisi|kepolisian|lp|dokumen|timer|tiket|e.?kyc|e.?wallet)\b", re.I)
_REPORTED = re.compile(r"\b(?:pelaku|penipu|penjual|dia|scammer)\b[^.!?\n]{0,100}\b(?:bertanya|menanyakan|berkata|mengatakan|menjanjikan|bilang|tanya|meminta|asked|said)\b|\b(?:saya|aku)\s+(?:(?:sempat|pernah|telah|lalu)\s+)?(?:bertanya|menanyakan)\b", re.I)
_SLOT_DECLARATION = re.compile(r"(?:\b(?:nomor\s+)?(?:hp|telepon|email)\s+(?:saya\s+)?(?:[:=]\s*)?\S*\d|\bemail\s+(?:saya\s+)?(?:[:=]\s*)?[\w.+-]+@[\w.-]+|\b(?:saya|aku)\s+(?:sudah\s+)?(?:transfer|mentransfer|membayar|ditipu|tertipu|membeli)|\bpada\s+\d)", re.I)
_SCALAR_DECLARATION = re.compile(
    r"^(?:(?:jam|pukul)\s*\d|(?:Rp\.?\s*)?\d|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|saya\s+bernama\s+\S|"
    r"(?:nama|bank\s+saya|nominal|tanggal|captcha)(?:\s+saya)?\s*[:=]?\s+\S|"
    r"(?:nomor\s+)?rekening(?:\s+(?:saya|korban|terlapor))?\s*[:=]?\s*\d)", re.I,
)
_REPORT_QUESTION = re.compile(r"\b(?:bagaimana|gimana|cara|bisa|boleh)\s+(?:(?:saya|aku|untuk)\s+)*(?:melapor|lapor|melaporkan|mengisi|unggah|mengunggah)\b", re.I)
_OTHER_REQUEST = re.compile(
    r"\b(?:sarankan|rekomendasi(?:kan)?|sebaiknya|baguskah|prediksi|saran)\b[^.!?]{0,80}\b(?:bitcoin|btc|kripto|crypto)\b"
    r"|\b(?:bitcoin|btc|kripto|crypto)\b[^.!?]{0,80}\b(?:sebaiknya|baguskah|prediksi|rekomendasi|saran)\b"
    r"|^(?:\s*(?:tolong|mohon)\s+)?(?:beli|jual|trading|investasi)\b[^.!?]{0,50}\b(?:bitcoin|btc|kripto|crypto)\b"
    r"|\b(?:pr|soal|tugas)\s+matematika\b", re.I,
)


def _unquoted(message: str) -> str:
    return re.sub(r'"[^"\n]*"|“[^”\n]*”|\x27[^\x27\n]*\x27', lambda match: " " * len(match[0]), message)


def _unsafe(message: str) -> bool:
    if detect_prompt_injection(message):
        return True
    text = _unquoted(message)
    for clause in re.split(r"[.!?;,\n]|\b(?:dan|lalu|tapi)\s+(?=(?:tolong|mohon|buat(?:kan)?|tulis(?:kan)?|jelaskan|ajarkan|write|create|explain)\b)", text, flags=re.I):
        if _REPORTED.search(clause):
            continue
        if _OTHER_REQUEST.search(clause) or (is_clearly_out_of_scope(clause) and not _REPORT_QUESTION.search(clause)):
            return True
    return False


def split_question_from_input(message: str) -> tuple[str, str]:
    """Separate explicit declarations only; an example inside a question is not data."""
    if not isinstance(message, str) or not message.strip():
        return "", ""
    message = message.strip()
    visible = _unquoted(message)
    last_question = visible.rfind("?")
    trailing = message[last_question + 1:].strip() if last_question >= 0 else ""
    if trailing and (_SLOT_DECLARATION.match(trailing) or _SCALAR_DECLARATION.match(trailing)) and not _QUESTION.search(_unquoted(trailing)):
        return trailing, message[:last_question + 1].strip()
    question_index = None
    for match in _QUESTION.finditer(visible):
        clause = re.split(r"[.!?\n]", visible[:match.start()])[-1]
        if not _REPORTED.search(clause):
            question_index = match.start()
            break
    if question_index is None:
        if "?" not in visible or any(_REPORTED.search(clause) for clause in re.split(r"[.!?\n]", visible)):
            return message, ""
        question_index = 0
    prefix = message[:question_index].rstrip(" ,;:.\n")
    prefix = re.sub(r"\s+(?:dan|lalu|tapi)$", "", prefix, flags=re.I)
    if _REPORT_QUESTION.match(message[question_index:]) and not re.search(r"[,;.!]\s*$", message[:question_index]) and not _SCALAR_DECLARATION.match(prefix):
        return "", message
    if prefix and (_SLOT_DECLARATION.search(prefix) or _SCALAR_DECLARATION.match(prefix)):
        return prefix, message[question_index:].strip()
    # shortcut: ambiguous clauses stay questions; add explicit slot forms when needed.
    return "", message


def classify_user_turn_intent(message: str, current_state: str, has_extracted_slots: bool) -> TurnIntent:
    if not isinstance(message, str) or _unsafe(message):
        return "OUT_OF_CONTEXT"
    _, question = split_question_from_input(message)
    if question:
        if _REPORT.search(message) or retrieve_faq_context(message, current_state):
            return "MIXED_INPUT_AND_QUESTION" if has_extracted_slots else "IASC_FAQ_QUESTION"
        return "OUT_OF_CONTEXT"
    return "SLOT_INPUT"


def _normalized(message: str) -> str:
    aliases = {"duit": "uang", "balik": "kembali", "balikin": "kembali"}
    return " ".join(aliases.get(token, token) for token in re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", message).lower()) if token not in {"saya", "aku", "bisa", "akan", "pasti"})


def retrieve_faq_context(message: str, current_state: str, top_k: int = 2) -> list[dict]:
    if not isinstance(message, str) or top_k <= 0 or _unsafe(message):
        return []
    text = " " + _normalized(message) + " "
    tokens = set(text.split())
    scored = []
    for entry in IASC_FAQ_KNOWLEDGE_BASE:
        if entry["id"] == "faq_bukti_chat_terhapus" and "rekening" in tokens and not tokens.intersection({"chat", "percakapan", "whatsapp", "telegram", "pelaku", "penipu"}):
            continue
        aliases = [alias for alias in entry["keywords"] if " " + _normalized(alias) + " " in text]
        if not aliases:
            continue
        score = sum(2 + len(alias.split()) for alias in aliases)
        score += len(tokens.intersection(_normalized(entry["question"]).split())) * 0.15
        score += 0.5 if current_state in entry["states"] else 0
        scored.append((score, entry))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [dict(entry) for _, entry in scored[:min(top_k, 2)]]


def build_grounded_response_with_pivot(message: str, intent: str, matched_faqs: list[dict], active_step_prompt: str) -> dict:
    if _unsafe(message):
        intent = "OUT_OF_CONTEXT"
    selected = []
    if intent in {"IASC_FAQ_QUESTION", "MIXED_INPUT_AND_QUESTION"}:
        for match in matched_faqs:
            entry = _BY_ID.get(match.get("id")) if isinstance(match, dict) else None
            if entry and entry not in selected:
                selected.append(entry)
            if len(selected) == 2:
                break
    if intent == "OUT_OF_CONTEXT":
        answer = "Saya hanya dapat membantu pelaporan penipuan keuangan IASC."
    elif selected:
        answer = " ".join(entry["answer"] for entry in selected)
    else:
        answer = "Panduan yang tersedia belum memuat jawaban terverifikasi untuk pertanyaan ini."
    reply = " ".join(part for part in (answer, active_step_prompt) if part)
    return {
        "assistant_message": reply, "reply": reply, "question": reply,
        "turn_intent": intent, "grounded_faq_ids": [entry["id"] for entry in selected],
        "guardrail_triggered": intent == "OUT_OF_CONTEXT",
    }


def contextual_faq_chips(current_state: str) -> list[dict]:
    ids = {
        "PELAPOR_STATUS": ("faq_mewakili_korban", "faq_jaminan_uang_kembali"),
        "KTP_UPLOAD": ("faq_keamanan_data_ktp", "faq_batas_ukuran_file"),
        "PELAPOR_DETAILS": ("faq_mewakili_korban",),
        "CONTACT_INPUT": ("faq_jaminan_uang_kembali", "faq_waktu_golden_period"),
        "CHAT_EVIDENCE_UPLOAD": ("faq_bukti_chat_terhapus", "faq_batas_ukuran_file"),
        "TERLAPOR_DETAILS": ("faq_bukti_chat_terhapus",),
        "CHAT_MORE": ("faq_bukti_chat_terhapus",),
        "CHRONOLOGY_INPUT": ("faq_laporan_polisi_opsional", "faq_bukti_chat_terhapus"),
        "KEJADIAN_DETAILS": ("faq_laporan_polisi_opsional",),
        "POLICE_REPORT_OPTIONAL": ("faq_laporan_polisi_opsional", "faq_waktu_golden_period"),
        "ACCOUNT_PROOF_UPLOAD": ("faq_bukti_rekening_digital", "faq_batas_ukuran_file"),
        "ACCOUNT_DETAILS": ("faq_bukti_rekening_digital",),
        "TRANSFER_UPLOAD": ("faq_bukti_transfer", "faq_rekening_terlapor_banyak"),
        "TRANSFER_DETAILS": ("faq_rekening_terlapor_banyak",),
        "TRANSFER_MORE": ("faq_rekening_terlapor_banyak",),
        "FINAL_CONFIRMATION": ("faq_arti_status_laporan", "faq_jaminan_uang_kembali"),
        "COMPLETED": ("faq_arti_status_laporan", "faq_kabar_pengembalian_dana"),
    }.get(current_state, ())
    return [{"label": "❓ " + _BY_ID[id_]["question"], "text": _BY_ID[id_]["question"]} for id_ in ids]
