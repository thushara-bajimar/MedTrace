"""Upload validation: allow-listed formats, magic-byte checks, size/page limits,
active-content rejection and filename sanitisation (display only; storage names are UUIDs)."""
from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass

from PIL import Image

ALLOWED = {
    ".pdf": ("pdf", "application/pdf"),
    ".png": ("png", "image/png"),
    ".jpg": ("jpeg", "image/jpeg"),
    ".jpeg": ("jpeg", "image/jpeg"),
}
MAGIC = {"pdf": [b"%PDF-"], "png": [b"\x89PNG\r\n\x1a\n"], "jpeg": [b"\xff\xd8\xff"]}
# PDF features that can carry active content. MedTrace never executes PDF content, but
# rejecting these reduces risk if a reviewer later opens the original in another viewer.
PDF_ACTIVE_MARKERS = [b"/JavaScript", b"/JS ", b"/JS(", b"/Launch", b"/EmbeddedFile", b"/RichMedia", b"/XFA"]
MAX_IMAGE_PIXELS = 40_000_000


class UploadRejected(ValueError):
    pass


@dataclass
class ValidatedUpload:
    display_name: str
    file_format: str
    mime_type: str
    data: bytes
    sha256: str
    page_count: int


def sanitize_filename(name: str) -> str:
    name = unicodedata.normalize("NFKC", name or "document")
    name = name.replace("\\", "/").split("/")[-1]           # drop any path components
    name = re.sub(r"[^A-Za-z0-9._ ()-]", "_", name).strip(" .")
    name = re.sub(r"\.{2,}", ".", name)
    return (name or "document")[:120]


def validate_upload(filename: str, data: bytes, max_bytes: int, max_pages: int) -> ValidatedUpload:
    display = sanitize_filename(filename)
    ext = ("." + display.rsplit(".", 1)[-1].lower()) if "." in display else ""
    if ext not in ALLOWED:
        raise UploadRejected(f"Unsupported file type '{ext or 'none'}'. Allowed: PDF, PNG, JPG, JPEG.")
    if len(data) == 0:
        raise UploadRejected("The file is empty.")
    if len(data) > max_bytes:
        raise UploadRejected(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit.")
    fmt, mime = ALLOWED[ext]
    if not any(data.startswith(m) for m in MAGIC[fmt]):
        raise UploadRejected("File content does not match its extension.")

    page_count = 1
    if fmt == "pdf":
        page_count = _validate_pdf(data, max_pages)
    else:
        _validate_image(data, fmt)
    return ValidatedUpload(display, fmt, mime, data, hashlib.sha256(data).hexdigest(), page_count)


def _validate_pdf(data: bytes, max_pages: int) -> int:
    import pymupdf as fitz

    for marker in PDF_ACTIVE_MARKERS:
        if marker in data:
            raise UploadRejected("PDF contains active content (scripts, launch actions or embedded files) and was rejected.")
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        raise UploadRejected("PDF could not be parsed.") from exc
    try:
        if doc.needs_pass or doc.is_encrypted:
            raise UploadRejected("Encrypted PDFs are not supported.")
        if doc.page_count == 0:
            raise UploadRejected("PDF has no pages.")
        if doc.page_count > max_pages:
            raise UploadRejected(f"PDF has {doc.page_count} pages; the limit is {max_pages}.")
        return doc.page_count
    finally:
        doc.close()


def _validate_image(data: bytes, fmt: str) -> None:
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            expected = {"png": "PNG", "jpeg": "JPEG"}[fmt]
            if im.format != expected:
                raise UploadRejected("Image format does not match its extension.")
            if im.width * im.height > MAX_IMAGE_PIXELS:
                raise UploadRejected("Image dimensions are too large.")
    except UploadRejected:
        raise
    except Exception as exc:  # noqa: BLE001  (includes DecompressionBombError)
        raise UploadRejected("Image could not be decoded safely.") from exc
