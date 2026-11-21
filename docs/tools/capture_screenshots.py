"""Capture real screenshots of the running MedTrace app (synthetic data) for the documentation.

Prerequisites: backend running on http://127.0.0.1:8000 with frontend/dist built and the synthetic
dataset seeded. Uses the locally installed Microsoft Edge (or Chrome) through Playwright.

Usage: python docs/tools/capture_screenshots.py
"""
from __future__ import annotations

import os
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "screenshots"
BASE = os.environ.get("MEDTRACE_URL", "http://127.0.0.1:8000")


def env_value(key: str) -> str:
    if os.environ.get(key):
        return os.environ[key]
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"{key} not configured")


def wait_for_server() -> None:
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/api/health", timeout=2)
            return
        except Exception:  # noqa: BLE001
            time.sleep(1)
    raise SystemExit("server not reachable")


def main() -> None:
    wait_for_server()
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge")
        except Exception:  # noqa: BLE001
            browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page.goto(BASE + "/login")
        page.screenshot(path=str(OUT / "01_login.png"))
        page.fill("#u", env_value("MEDTRACE_ADMIN_USERNAME"))
        page.fill("#p", env_value("MEDTRACE_ADMIN_PASSWORD"))
        page.click("button:has-text('Sign in')")
        page.wait_for_selector("text=Dashboard")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / "02_dashboard.png"))

        page.goto(BASE + "/patients")
        page.wait_for_selector("text=Arjun Menon")
        page.screenshot(path=str(OUT / "03_patients.png"))
        pids = page.eval_on_selector_all("a[href^='/patients/pat_']", "els => els.map(e => [e.textContent, e.getAttribute('href')])")
        pid = {name.split("(Synthetic ")[1][0]: href.split("/")[2] for name, href in pids if "(Synthetic" in name}

        def shot(path: str, name: str, wait: str, full: bool = False, pause: int = 900):
            page.goto(BASE + path)
            page.wait_for_selector(wait)
            page.wait_for_timeout(pause)
            page.screenshot(path=str(OUT / name), full_page=full)

        shot(f"/patients/{pid['A']}/documents", "04_documents.png", "text=Upload documents")
        shot(f"/patients/{pid['A']}/timeline", "05_timeline.png", "text=Ordered by documented event dates")
        shot(f"/patients/{pid['A']}/medications", "06_medication_history.png", "text=metformin")
        shot(f"/patients/{pid['B']}/allergies", "07_allergies_conflict.png", "text=Conflicting allergy statements")
        shot(f"/patients/{pid['C']}/investigations", "08_investigations_units.png", "text=Converted (display only)")
        shot(f"/patients/{pid['B']}/conflicts", "09_contradiction_centre.png", "text=Record review")
        shot(f"/patients/{pid['D']}/duplicates", "10_duplicates.png", "text=exact duplicate")
        page.goto(BASE + f"/patients/{pid['E']}/review")
        page.wait_for_selector("text=Date ambiguities")
        page.click("button:has-text('Date ambiguities')")
        page.wait_for_timeout(700)
        page.screenshot(path=str(OUT / "11_review_centre.png"))

        # evidence viewer from the medication tab
        page.goto(BASE + f"/patients/{pid['A']}/medications")
        page.wait_for_selector("text=Amoxicillin-clavulanate")
        page.click("td:has-text('Amoxicillin-clavulanate')")
        page.wait_for_selector("text=Version history")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "12_evidence_viewer.png"))
        page.keyboard.press("Escape")

        # document viewer with OCR document
        page.goto(BASE + f"/patients/{pid['D']}/documents")
        page.wait_for_selector("text=D6_consultation")
        page.click("a:has-text('D6_consultation')")
        page.wait_for_selector("text=Findings on this page")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "13_document_viewer_ocr.png"))

        # records-only questions
        for name, patient, q in (("14_qa_answer.png", "A", "Were any medication changes documented?"),
                                 ("15_qa_conflict_abstain.png", "B", "Is the patient allergic to penicillin?"),
                                 ("16_qa_declined.png", "A", "Should the patient increase the metformin dose?")):
            page.goto(BASE + f"/patients/{pid[patient]}/ask")
            page.wait_for_selector("input[aria-label='Question']")
            page.fill("input[aria-label='Question']", q)
            page.click("button:has-text('Ask')")
            page.wait_for_selector("text=Answers are assembled only")
            page.wait_for_timeout(600)
            page.screenshot(path=str(OUT / name))

        shot("/evaluation", "17_evaluation.png", "text=F1 by finding type", pause=1800)
        shot("/evaluation", "18_evaluation_full.png", "text=F1 by finding type", full=True, pause=1800)
        shot(f"/patients/{pid['E']}/overview", "19_overview_gaps.png", "text=Documentation gaps")
        browser.close()
    print("screenshots written to", OUT)


if __name__ == "__main__":
    main()
