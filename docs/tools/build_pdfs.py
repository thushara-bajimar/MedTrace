"""Build the MedTrace PDFs from the Markdown documentation.

MedTrace_Technical_Documentation.pdf = TECHNICAL_DOCUMENTATION.md + topic documents + measured evaluation report (appendices)
MedTrace_Project_Report.pdf          = PROJECT_REPORT.md

Rendering: python-markdown -> HTML with print CSS -> headless Microsoft Edge/Chrome via Playwright (page.pdf).
Images (SVG diagrams, PNG screenshots) are resolved from docs/ via a file:// base URL.

Usage: python docs/tools/build_pdfs.py [--private]   (--private also builds a PDF of private-notes/, kept out of Git)
"""
from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

DOCS = Path(__file__).resolve().parents[1]
ROOT = DOCS.parent
OUT = DOCS / "pdf"

CSS = """
@page { size: A4; margin: 18mm 16mm 18mm 16mm; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 10.2pt; line-height: 1.45; color: #1e293b; }
h1 { font-size: 20pt; color: #0f4844; border-bottom: 2px solid #1f8a83; padding-bottom: 4px; margin-top: 0; }
h2 { font-size: 14pt; color: #135c57; margin-top: 18px; border-bottom: 1px solid #d5ecea; padding-bottom: 2px; }
h3 { font-size: 11.5pt; color: #0f172a; }
.chapter { page-break-before: always; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 8.8pt; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th, td { border: 1px solid #cbd5e1; padding: 3px 6px; vertical-align: top; text-align: left; }
th { background: #eef7f6; }
code { font-family: Consolas, 'Courier New', monospace; font-size: 8.6pt; background: #f1f5f9; padding: 0 2px; border-radius: 2px; }
pre { background: #f8fafc; border: 1px solid #e2e8f0; padding: 6px 8px; font-size: 8pt; white-space: pre-wrap; word-break: break-word; }
pre code { background: none; }
img { max-width: 100%; border: 1px solid #e2e8f0; margin: 6px 0; page-break-inside: avoid; }
blockquote { border-left: 3px solid #f59e0b; background: #fffbeb; margin: 8px 0; padding: 4px 10px; }
a { color: #17716b; text-decoration: none; }
.title { height: 245mm; display: flex; flex-direction: column; justify-content: center; text-align: center; }
.title h1 { border: none; font-size: 30pt; margin-bottom: 4px; }
.title .tag { font-size: 14pt; color: #17716b; }
.title .meta { margin-top: 30px; color: #475569; font-size: 10.5pt; line-height: 1.8; }
.title .notice { margin: 40px auto 0; max-width: 140mm; font-size: 9pt; color: #92400e; background: #fffbeb; border: 1px solid #fcd34d; padding: 8px; }
.toc { page-break-after: always; }
.toc ul { list-style: none; padding-left: 14px; } .toc > ul { padding-left: 0; }
.toc li { margin: 2px 0; }
"""


def md_to_html(text: str) -> tuple[str, str]:
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists"], extension_configs={"toc": {"toc_depth": "2"}})
    html = md.convert(text)
    return html, md.toc


def chapter(path: Path, demote_title: bool = False) -> str:
    text = path.read_text(encoding="utf-8")
    # links to other markdown docs are meaningless inside the PDF: keep the text only
    text = re.sub(r"\[([^\]]+)\]\((?!https?:)[^)]+\.md(#[^)]*)?\)", r"\1", text)
    return text


def build(name: str, title: str, subtitle: str, parts: list[Path], browser, footer_label: str) -> Path:
    body_md = []
    for i, p in enumerate(parts):
        t = chapter(p)
        if i > 0:
            t = f"\n\n<div class='chapter'></div>\n\n" + t
        body_md.append(t)
    html, toc = md_to_html("\n\n".join(body_md))
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title><style>{CSS}</style></head><body>
<div class="title"><h1>{title}</h1><div class="tag">{subtitle}</div>
<div class="meta">Data Engineering &amp; Distributed Systems (applied AI)<br>Version 1.0 · extractor rules-1.0.0<br>Generated {date.today().isoformat()}</div>
<div class="notice">MedTrace is a records organisation and evidence-retrieval system. It does not diagnose, interpret results clinically or recommend treatment.
All patients and records shown are synthetic. All reported metrics were measured by the project's evaluation runner; the review-time figure is an automated estimate, not a human study.</div></div>
<div class="toc"><h2>Contents</h2>{toc}</div>
{html}</body></html>"""
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = DOCS / f"_{name}.html"  # in docs/ so relative image paths resolve
    tmp.write_text(doc, encoding="utf-8")
    page = browser.new_page()
    page.goto(tmp.as_uri())
    page.wait_for_load_state("networkidle")
    out = OUT / f"{name}.pdf"
    page.pdf(path=str(out), format="A4", print_background=True, display_header_footer=True,
             header_template="<div></div>",
             footer_template=f"<div style='font-size:8px;width:100%;text-align:center;color:#64748b'>{footer_label} · page <span class='pageNumber'></span> of <span class='totalPages'></span></div>",
             margin={"top": "16mm", "bottom": "16mm", "left": "14mm", "right": "14mm"})
    page.close()
    tmp.unlink()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--private", action="store_true")
    a = ap.parse_args()
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge")
        except Exception:  # noqa: BLE001
            browser = p.chromium.launch(channel="chrome")
        tech = [DOCS / "TECHNICAL_DOCUMENTATION.md"] + [DOCS / f for f in (
            "ARCHITECTURE.md", "DATA_MODEL.md", "EXTRACTION_AND_PROVENANCE.md", "TIMELINE_AND_CONTRADICTIONS.md",
            "RECORDS_QA.md", "SECURITY_AND_PRIVACY.md", "API_DOCUMENTATION.md", "TESTING_AND_EVALUATION.md")] + [DOCS / "evaluation" / "EVALUATION_REPORT.md"]
        print(build("MedTrace_Technical_Documentation", "MedTrace — Technical Documentation", "Every Medical Fact, Traced to Its Source",
                    tech, browser, "MedTrace Technical Documentation"))
        print(build("MedTrace_Project_Report", "MedTrace — Project Report", "One Patient, Many Records",
                    [DOCS / "PROJECT_REPORT.md"], browser, "MedTrace Project Report"))
        if a.private:
            priv = ROOT / "private-notes"
            files = sorted(priv.glob("*.md")) + sorted((priv / "folder-guides").glob("*.md")) + sorted((priv / "presentation").glob("*.md"))
            if files:
                global OUT
                OUT = priv / "pdf"
                print(build("MedTrace_Private_Revision_Notes", "MedTrace — Private Revision Notes", "Personal learning material (not for publication)",
                            files, browser, "MedTrace private notes"))
        browser.close()


if __name__ == "__main__":
    main()
