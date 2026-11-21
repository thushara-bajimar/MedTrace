"""Date mention extraction that preserves the original text and refuses to guess.

Rules
* ISO ``YYYY-MM-DD`` and textual months (``12 March 2024``) parse unambiguously.
* Numeric ``a/b/yyyy``: if a > 12 it must be DD/MM; if b > 12 it must be MM/DD. If both are
  <= 12 and differ, the date is **ambiguous** unless the document itself declares its
  convention (the literal text ``DD/MM/YYYY`` or ``MM/DD/YYYY``). Ambiguous dates keep
  both candidates and get no ``iso`` value.
* Two-digit years are flagged (``two_digit_year``) and never expanded silently.
* Partial dates keep their precision (``month`` / ``year``)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

RX_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
RX_NUM = re.compile(r"\b(\d{1,2})([/.\-])(\d{1,2})\2(\d{4}|\d{2})\b")
RX_DMY_TEXT = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+" + _MON + r"\.?,?[\s\-]+(\d{4})\b", re.I)
RX_MDY_TEXT = re.compile(r"\b" + _MON + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I)
RX_MY_TEXT = re.compile(r"\b" + _MON + r"\.?[\s\-,]+(\d{4})\b", re.I)
RX_MY_NUM = re.compile(r"(?<![\d/.\-])(\d{1,2})/(\d{4})\b")
RX_YEAR_CTX = re.compile(r"\b(?:in|since|year|during|from|circa|c\.)\s+((?:19|20)\d{2})\b", re.I)


@dataclass
class DateMention:
    text: str
    start: int
    end: int
    iso: str | None
    precision: str | None          # day | month | year
    status: str                    # parsed | ambiguous | partial | invalid
    method: str                    # iso | textual_month | numeric_dmy | numeric_mdy | declared_convention | ...
    candidates: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"text": self.text, "iso": self.iso, "precision": self.precision, "status": self.status,
                "method": self.method, "candidates": self.candidates}


def declared_convention(full_text: str) -> str | None:
    t = full_text.upper()
    has_dmy, has_mdy = "DD/MM/YYYY" in t or "DD-MM-YYYY" in t, "MM/DD/YYYY" in t or "MM-DD-YYYY" in t
    if has_dmy and not has_mdy:
        return "DMY"
    if has_mdy and not has_dmy:
        return "MDY"
    return None


def _valid(y: int, m: int, d: int) -> bool:
    try:
        date(y, m, d)
        return True
    except ValueError:
        return False


def _iso(y: int, m: int, d: int | None = None) -> str:
    return f"{y:04d}-{m:02d}" + (f"-{d:02d}" if d else "")


def find_dates(text: str, convention: str | None = None) -> list[DateMention]:
    found: list[DateMention] = []
    taken: list[tuple[int, int]] = []

    def free(s: int, e: int) -> bool:
        return all(e <= a or s >= b for a, b in taken)

    def add(dm: DateMention) -> None:
        if free(dm.start, dm.end):
            found.append(dm)
            taken.append((dm.start, dm.end))

    for m in RX_ISO.finditer(text):
        y, mo, d = map(int, m.groups())
        if _valid(y, mo, d):
            add(DateMention(m.group(0), m.start(), m.end(), _iso(y, mo, d), "day", "parsed", "iso"))
    for m in RX_DMY_TEXT.finditer(text):
        d, mon, y = int(m.group(1)), MONTHS[m.group(2).lower()[:3]], int(m.group(3))
        if _valid(y, mon, d):
            add(DateMention(m.group(0), m.start(), m.end(), _iso(y, mon, d), "day", "parsed", "textual_month"))
    for m in RX_MDY_TEXT.finditer(text):
        mon, d, y = MONTHS[m.group(1).lower()[:3]], int(m.group(2)), int(m.group(3))
        if _valid(y, mon, d):
            add(DateMention(m.group(0), m.start(), m.end(), _iso(y, mon, d), "day", "parsed", "textual_month"))
    for m in RX_NUM.finditer(text):
        a, b, ytxt = int(m.group(1)), int(m.group(3)), m.group(4)
        if len(ytxt) == 2:
            add(DateMention(m.group(0), m.start(), m.end(), None, None, "ambiguous", "two_digit_year",
                            [f"two-digit year '{ytxt}' not expanded"]))
            continue
        y = int(ytxt)
        dmy_ok, mdy_ok = _valid(y, b, a), _valid(y, a, b)
        if not dmy_ok and not mdy_ok:
            add(DateMention(m.group(0), m.start(), m.end(), None, None, "invalid", "numeric"))
        elif dmy_ok and not mdy_ok:
            add(DateMention(m.group(0), m.start(), m.end(), _iso(y, b, a), "day", "parsed", "numeric_dmy"))
        elif mdy_ok and not dmy_ok:
            add(DateMention(m.group(0), m.start(), m.end(), _iso(y, a, b), "day", "parsed", "numeric_mdy"))
        elif a == b:
            add(DateMention(m.group(0), m.start(), m.end(), _iso(y, a, b), "day", "parsed", "numeric_same_day_month"))
        elif convention == "DMY":
            add(DateMention(m.group(0), m.start(), m.end(), _iso(y, b, a), "day", "parsed", "declared_convention_dmy"))
        elif convention == "MDY":
            add(DateMention(m.group(0), m.start(), m.end(), _iso(y, a, b), "day", "parsed", "declared_convention_mdy"))
        else:
            add(DateMention(m.group(0), m.start(), m.end(), None, "day", "ambiguous", "numeric_ambiguous",
                            [_iso(y, b, a), _iso(y, a, b)]))
    for m in RX_MY_TEXT.finditer(text):
        mon, y = MONTHS[m.group(1).lower()[:3]], int(m.group(2))
        add(DateMention(m.group(0), m.start(), m.end(), _iso(y, mon), "month", "partial", "textual_month_year"))
    for m in RX_MY_NUM.finditer(text):
        mo, y = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            add(DateMention(m.group(0), m.start(), m.end(), _iso(y, mo), "month", "partial", "numeric_month_year"))
    for m in RX_YEAR_CTX.finditer(text):
        add(DateMention(m.group(1), m.start(1), m.end(1), m.group(1), "year", "partial", "contextual_year"))
    found.sort(key=lambda dm: dm.start)
    return found


def first_date(text: str, convention: str | None = None) -> DateMention | None:
    ds = [d for d in find_dates(text, convention) if d.status != "invalid"]
    return ds[0] if ds else None


def sort_key(iso: str | None) -> str:
    """Sortable key for partial ISO dates; partial dates sort at the start of their period."""
    if not iso:
        return "9999-99-99"
    return (iso + "-00-00")[:10] if len(iso) < 10 else iso
