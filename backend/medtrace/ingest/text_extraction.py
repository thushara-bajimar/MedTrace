"""Text extraction: native PDF text layer first, local OCR only when a page has no usable
text layer (scanned PDF) or the upload is an image.

Every page is returned as ordered *lines* with bounding boxes so that each extracted fact
can later be linked to an exact page region (evidence highlighting)."""
from __future__ import annotations

import io
import logging
import threading
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from ..config import get_settings

log = logging.getLogger("medtrace.ocr")
OCR_DPI = 200


@dataclass
class Line:
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float | None
    source: str  # native | ocr


@dataclass
class PageText:
    page_number: int
    source: str  # native | ocr | empty
    width: float
    height: float
    lines: list[Line] = field(default_factory=list)
    ocr_confidence: float | None = None

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines)


@dataclass
class ExtractionResult:
    pages: list[PageText]
    ocr_status: str            # not_required | completed | partial | failed | unavailable
    text_source_summary: str   # native | ocr | mixed | empty
    ocr_mean_confidence: float | None


# ---------------------------------------------------------------- OCR engine (lazy singleton)
_engine = None
_engine_lock = threading.Lock()
_engine_error: str | None = None


def get_ocr_engine():
    global _engine, _engine_error
    if get_settings().ocr_engine == "none":
        return None
    with _engine_lock:
        if _engine is None and _engine_error is None:
            try:
                logging.getLogger("RapidOCR").setLevel(logging.WARNING)
                from rapidocr import RapidOCR

                _engine = RapidOCR()
            except Exception as exc:  # noqa: BLE001
                _engine_error = str(exc)
                log.warning("OCR engine unavailable: %s", exc)
        return _engine


def ocr_image(img: Image.Image, scale: float = 1.0) -> tuple[list[Line], float | None]:
    """Run local OCR. ``scale`` converts pixel coordinates back to page coordinates."""
    engine = get_ocr_engine()
    if engine is None:
        raise RuntimeError("OCR engine unavailable")
    arr = np.array(img.convert("RGB"))
    with _engine_lock:  # onnxruntime sessions are not guaranteed thread-safe here
        res = engine(arr)
    boxes = getattr(res, "boxes", None)
    txts = getattr(res, "txts", None)
    scores = getattr(res, "scores", None)
    if boxes is None or txts is None or len(txts) == 0:
        return [], None
    fragments = []
    for box, txt, sc in zip(boxes, txts, scores):
        pts = np.array(box, dtype=float)
        x0, y0 = pts[:, 0].min() / scale, pts[:, 1].min() / scale
        x1, y1 = pts[:, 0].max() / scale, pts[:, 1].max() / scale
        fragments.append((x0, y0, x1, y1, str(txt).strip(), float(sc)))
    lines = _merge_fragments(fragments, source="ocr")
    mean = float(np.mean([f[5] for f in fragments])) if fragments else None
    return lines, mean


def _merge_fragments(frags: list[tuple], source: str) -> list[Line]:
    """Merge text fragments that sit on the same visual row into one line (left to right).
    Large horizontal gaps are kept as two spaces so table columns stay distinguishable."""
    frags = [f for f in frags if f[4]]
    frags.sort(key=lambda f: ((f[1] + f[3]) / 2, f[0]))
    rows: list[list[tuple]] = []
    for f in frags:
        cy, h = (f[1] + f[3]) / 2, max(f[3] - f[1], 1.0)
        if rows:
            last = rows[-1]
            lcy = sum((g[1] + g[3]) / 2 for g in last) / len(last)
            lh = max(max(g[3] - g[1] for g in last), 1.0)
            if abs(cy - lcy) <= 0.5 * min(h, lh):
                last.append(f)
                continue
        rows.append([f])
    out: list[Line] = []
    for row in rows:
        row.sort(key=lambda g: g[0])
        parts, prev_x1 = [], None
        for g in row:
            if prev_x1 is not None:
                gap = g[0] - prev_x1
                parts.append("  " if gap > 12 else " ")
            parts.append(g[4])
            prev_x1 = g[2]
        confs = [g[5] for g in row if g[5] is not None]
        out.append(Line(
            text="".join(parts).strip(),
            bbox=(min(g[0] for g in row), min(g[1] for g in row), max(g[2] for g in row), max(g[3] for g in row)),
            confidence=(sum(confs) / len(confs)) if confs else None,
            source=source,
        ))
    return out


# ---------------------------------------------------------------- PDF
def _native_lines(page) -> list[Line]:
    d = page.get_text("dict")
    frags = []
    for block in d.get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(s.get("text", "") for s in line.get("spans", [])).strip()
            if text:
                x0, y0, x1, y1 = line["bbox"]
                frags.append((x0, y0, x1, y1, text, None))
    return _merge_fragments(frags, source="native")


def extract_pdf(data: bytes) -> ExtractionResult:
    import pymupdf as fitz

    s = get_settings()
    pages: list[PageText] = []
    ocr_used, ocr_failed, confs = 0, 0, []
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        for i, page in enumerate(doc, start=1):
            w, h = page.rect.width, page.rect.height
            lines = _native_lines(page)
            if sum(len(l.text) for l in lines) >= s.native_text_min_chars:
                pages.append(PageText(i, "native", w, h, lines))
                continue
            # No usable text layer -> render and OCR.
            zoom = OCR_DPI / 72
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            try:
                olines, conf = ocr_image(img, scale=zoom)
                ocr_used += 1
                if conf is not None:
                    confs.append(conf)
                pages.append(PageText(i, "ocr", w, h, olines, conf))
            except Exception as exc:  # noqa: BLE001
                log.warning("OCR failed on page %s: %s", i, exc)
                ocr_failed += 1
                pages.append(PageText(i, "empty", w, h, lines))
    finally:
        doc.close()
    return _summarise(pages, ocr_used, ocr_failed, confs)


def extract_image(data: bytes) -> ExtractionResult:
    img = Image.open(io.BytesIO(data))
    img.load()
    try:
        lines, conf = ocr_image(img, scale=1.0)
        page = PageText(1, "ocr", float(img.width), float(img.height), lines, conf)
        return _summarise([page], 1, 0, [conf] if conf is not None else [])
    except Exception as exc:  # noqa: BLE001
        log.warning("OCR failed on image: %s", exc)
        page = PageText(1, "empty", float(img.width), float(img.height), [])
        return _summarise([page], 0, 1, [])


def _summarise(pages, ocr_used, ocr_failed, confs) -> ExtractionResult:
    sources = {p.source for p in pages}
    if ocr_used == 0 and ocr_failed == 0:
        ocr_status = "not_required"
    elif ocr_failed and get_ocr_engine() is None:
        ocr_status = "unavailable"
    elif ocr_failed and ocr_used:
        ocr_status = "partial"
    elif ocr_failed:
        ocr_status = "failed"
    else:
        ocr_status = "completed"
    if sources == {"native"}:
        summary = "native"
    elif sources == {"ocr"}:
        summary = "ocr"
    elif sources == {"empty"}:
        summary = "empty"
    else:
        summary = "mixed"
    mean = round(sum(confs) / len(confs), 4) if confs else None
    return ExtractionResult(pages, ocr_status, summary, mean)


def extract_text(data: bytes, file_format: str) -> ExtractionResult:
    if file_format == "pdf":
        return extract_pdf(data)
    return extract_image(data)


def render_page_png(data: bytes, file_format: str, page_number: int, zoom: float = 1.5) -> bytes:
    """Render a page for the evidence viewer."""
    if file_format == "pdf":
        import pymupdf as fitz

        doc = fitz.open(stream=data, filetype="pdf")
        try:
            if not 1 <= page_number <= doc.page_count:
                raise ValueError("page out of range")
            pix = doc[page_number - 1].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            return pix.tobytes("png")
        finally:
            doc.close()
    if page_number != 1:
        raise ValueError("page out of range")
    img = Image.open(io.BytesIO(data)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
