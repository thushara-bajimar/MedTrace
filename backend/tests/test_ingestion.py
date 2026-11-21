"""Document processing: validation, PDF text extraction, OCR, classification."""
import io
from pathlib import Path

import pymupdf as fitz
import pytest
from PIL import Image, ImageDraw, ImageFont

from medtrace.ingest.classify import classify_document
from medtrace.ingest.text_extraction import extract_text
from medtrace.ingest.validation import UploadRejected, sanitize_filename, validate_upload

DATASET = Path(__file__).resolve().parents[2] / "dataset" / "documents"
MB = 1024 * 1024


def _pdf(text="Laboratory report\nHaemoglobin 13.2 g/dL") -> bytes:
    d = fitz.open()
    p = d.new_page()
    y = 72
    for line in text.splitlines():
        p.insert_text((72, y), line, fontsize=11)
        y += 16
    return d.tobytes()


def test_rejects_unsupported_extension_and_mismatched_magic():
    with pytest.raises(UploadRejected):
        validate_upload("report.exe", b"MZ....", 15 * MB, 60)
    with pytest.raises(UploadRejected, match="does not match"):
        validate_upload("report.pdf", b"\x89PNG\r\n\x1a\nxxxx", 15 * MB, 60)
    with pytest.raises(UploadRejected, match="empty"):
        validate_upload("report.pdf", b"", 15 * MB, 60)


def test_rejects_oversize_and_active_pdf_content():
    with pytest.raises(UploadRejected, match="limit"):
        validate_upload("a.pdf", b"%PDF-" + b"0" * (2 * MB), 1 * MB, 60)
    malicious = _pdf().replace(b"%%EOF", b"<< /S /JavaScript /JS (app.alert(1)) >>\n%%EOF")
    with pytest.raises(UploadRejected, match="active content"):
        validate_upload("a.pdf", malicious, 15 * MB, 60)
    with pytest.raises(UploadRejected, match="parsed"):
        validate_upload("broken.pdf", b"%PDF-1.7 garbage", 15 * MB, 60)


def test_rejects_corrupt_image():
    with pytest.raises(UploadRejected):
        validate_upload("x.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 50, 15 * MB, 60)


def test_filename_sanitisation_blocks_path_traversal():
    assert sanitize_filename("../../etc/passwd.pdf") == "passwd.pdf"
    assert sanitize_filename("..\\..\\win.ini.pdf") == "win.ini.pdf"
    assert "/" not in sanitize_filename("a/b/c<script>.pdf")


def test_valid_pdf_metadata():
    up = validate_upload("lab.pdf", _pdf(), 15 * MB, 60)
    assert up.file_format == "pdf" and up.page_count == 1 and len(up.sha256) == 64


def test_native_pdf_text_extraction_with_line_boxes():
    res = extract_text(_pdf("LABORATORY REPORT\nHaemoglobin 13.2 g/dL\nSerum Creatinine 0.9 mg/dL"), "pdf")
    assert res.ocr_status == "not_required" and res.text_source_summary == "native"
    lines = res.pages[0].lines
    assert [l.text for l in lines] == ["LABORATORY REPORT", "Haemoglobin 13.2 g/dL", "Serum Creatinine 0.9 mg/dL"]
    assert all(l.bbox[2] > l.bbox[0] and l.source == "native" for l in lines)


def test_ocr_on_image_upload():
    img = Image.new("RGB", (1000, 260), "white")
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("arial.ttf", 30)
    except OSError:
        f = ImageFont.load_default(size=30)
    d.text((30, 40), "PRESCRIPTION", fill="black", font=f)
    d.text((30, 120), "Tab. Metformin 500 mg twice daily", fill="black", font=f)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    up = validate_upload("rx.png", buf.getvalue(), 15 * MB, 60)
    res = extract_text(up.data, up.file_format)
    assert res.ocr_status == "completed" and res.text_source_summary == "ocr"
    text = res.pages[0].text.lower()
    assert "metformin" in text and "500" in text
    assert res.ocr_mean_confidence is not None and res.ocr_mean_confidence > 0.8


def test_scanned_pdf_uses_ocr():
    data = (DATASET / "patient_A" / "A4_prescription_scanned_2023-07-25.pdf").read_bytes()
    res = extract_text(data, "pdf")
    assert res.text_source_summary == "ocr" and res.ocr_status == "completed"
    assert "sitagliptin" in res.pages[0].text.lower()


def test_classification():
    assert classify_document("Riverside\nDISCHARGE SUMMARY\nDate of admission: x\nDate of discharge: y")[0] == "discharge_summary"
    assert classify_document("Lab\nLABORATORY REPORT\nTest Result Unit Reference Range")[0] == "lab_report"
    assert classify_document("Clinic\nPRESCRIPTION\nRx:\nTab. X 5 mg OD")[0] == "prescription"
    assert classify_document("Radiology\nCHEST X-RAY\nImpression: normal")[0] == "imaging_report"
    assert classify_document("Clinic\nCONSULTATIONNOTE\nChief complaints:")[0] == "consultation_note"   # OCR-merged words
    assert classify_document("hello world")[0] == "unclassified"
