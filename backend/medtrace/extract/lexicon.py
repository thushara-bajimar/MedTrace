"""Small, explicit lexicons used by the rules-based extractor.

They are used for *recognition and normalisation only*. The text as written is always
stored alongside any normalised name. Extending coverage = adding entries here."""
from __future__ import annotations

import re

# normalised generic name -> aliases (lower case; brand names are synthetic/common examples)
MEDICATIONS: dict[str, list[str]] = {
    "metformin": ["metformin", "glycomet"],
    "glimepiride": ["glimepiride", "amaryl"],
    "sitagliptin": ["sitagliptin", "januvia"],
    "insulin glargine": ["insulin glargine", "glargine", "lantus"],
    "amlodipine": ["amlodipine", "amlong", "norvasc"],
    "telmisartan": ["telmisartan", "telma"],
    "losartan": ["losartan"],
    "ramipril": ["ramipril"],
    "enalapril": ["enalapril"],
    "atenolol": ["atenolol"],
    "metoprolol": ["metoprolol"],
    "hydrochlorothiazide": ["hydrochlorothiazide", "hctz"],
    "atorvastatin": ["atorvastatin", "atorva", "lipitor"],
    "rosuvastatin": ["rosuvastatin", "rosuvas"],
    "aspirin": ["aspirin", "ecosprin"],
    "clopidogrel": ["clopidogrel", "clopilet"],
    "warfarin": ["warfarin"],
    "enoxaparin": ["enoxaparin"],
    "pantoprazole": ["pantoprazole", "pan 40", "pantocid"],
    "omeprazole": ["omeprazole"],
    "ondansetron": ["ondansetron", "emeset"],
    "paracetamol": ["paracetamol", "acetaminophen", "dolo", "crocin"],
    "ibuprofen": ["ibuprofen", "brufen"],
    "diclofenac": ["diclofenac"],
    "tramadol": ["tramadol"],
    "amoxicillin-clavulanate": ["amoxicillin-clavulanate", "amoxicillin clavulanate", "co-amoxiclav", "augmentin"],
    "amoxicillin": ["amoxicillin", "amoxycillin"],
    "azithromycin": ["azithromycin", "azithral"],
    "ceftriaxone": ["ceftriaxone"],
    "cefuroxime": ["cefuroxime"],
    "ciprofloxacin": ["ciprofloxacin"],
    "doxycycline": ["doxycycline"],
    "cotrimoxazole": ["cotrimoxazole", "co-trimoxazole", "sulfamethoxazole-trimethoprim"],
    "levothyroxine": ["levothyroxine", "thyronorm", "eltroxin"],
    "salbutamol": ["salbutamol", "albuterol", "asthalin"],
    "budesonide": ["budesonide"],
    "montelukast": ["montelukast"],
    "prednisolone": ["prednisolone"],
    "furosemide": ["furosemide", "frusemide", "lasix"],
    "spironolactone": ["spironolactone"],
    "cetirizine": ["cetirizine"],
    "cholecalciferol": ["cholecalciferol", "vitamin d3"],
    "calcium carbonate": ["calcium carbonate", "shelcal"],
    "ferrous sulfate": ["ferrous sulfate", "ferrous sulphate"],
    "folic acid": ["folic acid"],
    "gabapentin": ["gabapentin"],
    "sertraline": ["sertraline"],
}

ALLERGENS: dict[str, list[str]] = {
    "penicillin": ["penicillin", "penicillins"],
    "amoxicillin": ["amoxicillin"],
    "sulfonamides": ["sulfa", "sulpha", "sulfonamide", "sulfonamides", "sulpha drugs", "sulfa drugs"],
    "aspirin": ["aspirin"],
    "nsaids": ["nsaid", "nsaids"],
    "ibuprofen": ["ibuprofen"],
    "codeine": ["codeine"],
    "iodinated contrast": ["iodinated contrast", "contrast dye", "iv contrast"],
    "latex": ["latex"],
    "peanuts": ["peanut", "peanuts"],
    "shellfish": ["shellfish", "prawns"],
    "egg": ["egg", "eggs"],
    "cephalosporins": ["cephalosporin", "cephalosporins"],
}

# canonical test -> (aliases regex fragments, category)
TESTS: dict[str, tuple[list[str], str]] = {
    "haemoglobin": ([r"ha?emoglobin", r"\bhb\b(?!a1c)"], "laboratory"),
    "hba1c": ([r"hba1c", r"glycated ha?emoglobin", r"glycosylated ha?emoglobin"], "laboratory"),
    "fasting plasma glucose": ([r"fasting (?:plasma |blood )?(?:glucose|sugar)", r"\bfbs\b", r"\bfpg\b"], "laboratory"),
    "postprandial glucose": ([r"post[- ]?prandial (?:plasma |blood )?(?:glucose|sugar)", r"\bppbs\b"], "laboratory"),
    "random glucose": ([r"random (?:plasma |blood )?(?:glucose|sugar)", r"\brbs\b"], "laboratory"),
    "creatinine": ([r"(?:serum )?creatinine"], "laboratory"),
    "egfr": ([r"\begfr\b"], "laboratory"),
    "urea": ([r"blood urea(?: nitrogen)?", r"\bbun\b", r"\burea\b"], "laboratory"),
    "sodium": ([r"(?:serum )?sodium", r"\bna\+?\b"], "laboratory"),
    "potassium": ([r"(?:serum )?potassium", r"\bk\+?\b"], "laboratory"),
    "total cholesterol": ([r"total cholesterol", r"cholesterol,? total", r"serum cholesterol"], "laboratory"),
    "ldl cholesterol": ([r"ldl(?:[- ]cholesterol| ?-?c)?\b"], "laboratory"),
    "hdl cholesterol": ([r"hdl(?:[- ]cholesterol| ?-?c)?\b"], "laboratory"),
    "triglycerides": ([r"triglycerides?"], "laboratory"),
    "tsh": ([r"\btsh\b", r"thyroid stimulating hormone"], "laboratory"),
    "free t4": ([r"free t4", r"\bft4\b"], "laboratory"),
    "white cell count": ([r"total (?:wbc|leucocyte|leukocyte) count", r"\bwbc(?: count)?\b", r"\btlc\b"], "laboratory"),
    "platelet count": ([r"platelet(?: count)?s?"], "laboratory"),
    "alt": ([r"\balt\b", r"\bsgpt\b"], "laboratory"),
    "ast": ([r"\bast\b", r"\bsgot\b"], "laboratory"),
    "vitamin d": ([r"25[- ]?(?:oh|hydroxy) vitamin d", r"vitamin d(?: total)?"], "laboratory"),
    "vitamin b12": ([r"vitamin b12"], "laboratory"),
    "inr": ([r"\binr\b"], "laboratory"),
    "crp": ([r"c[- ]reactive protein", r"\bcrp\b"], "laboratory"),
    "esr": ([r"\besr\b"], "laboratory"),
    "chest x-ray": ([r"chest x-?ray", r"x-?ray chest", r"\bcxr\b"], "imaging"),
    "ultrasound abdomen": ([r"(?:usg|ultrasound|ultrasonography) (?:of )?(?:the )?(?:whole )?abdomen"], "imaging"),
    "echocardiogram": ([r"2d echo(?:cardiogra(?:m|phy))?", r"echocardiogra(?:m|phy)"], "imaging"),
    "ecg": ([r"\becg\b", r"electrocardiogra(?:m|phy)"], "imaging"),
    "ct scan": ([r"\bct (?:scan )?(?:of )?(?:the )?\w+", r"computed tomography"], "imaging"),
    "mri": ([r"\bmri\b"], "imaging"),
}

UNITS = [
    r"x\s?10\^?9/L", r"x\s?10\^?3/[uµ]L", r"10\^3/[uµ]L", r"10\^9/L", r"mL/min/1\.73\s?m(?:2|²)", r"mmol/mol", r"mmol/L",
    r"[uµμ]mol/L", r"nmol/L", r"pmol/L", r"mg/dL", r"mg/dl", r"g/dL", r"g/dl", r"g/L", r"mEq/L", r"mIU/L", r"[uµμ]IU/mL",
    r"ng/mL", r"ng/dL", r"pg/mL", r"U/L", r"IU/L", r"cells/[uµμ]L", r"/cumm", r"/mm3", r"lakhs?/cumm", r"mm/hr", r"mg/L", r"%",
]
RX_UNIT = re.compile(r"(?<![A-Za-z])(" + "|".join(UNITS) + r")(?![A-Za-z])", re.I)

# Explicit, documented conversion rules (display-only; originals are never replaced).
# key: (canonical test, unit lower) -> (target unit, factor or callable, rule text)
CONVERSIONS: dict[tuple[str, str], tuple[str, object, str]] = {
    ("fasting plasma glucose", "mg/dl"): ("mmol/L", 1 / 18.016, "glucose mg/dL / 18.016 = mmol/L"),
    ("fasting plasma glucose", "mmol/l"): ("mg/dL", 18.016, "glucose mmol/L x 18.016 = mg/dL"),
    ("random glucose", "mg/dl"): ("mmol/L", 1 / 18.016, "glucose mg/dL / 18.016 = mmol/L"),
    ("random glucose", "mmol/l"): ("mg/dL", 18.016, "glucose mmol/L x 18.016 = mg/dL"),
    ("postprandial glucose", "mg/dl"): ("mmol/L", 1 / 18.016, "glucose mg/dL / 18.016 = mmol/L"),
    ("postprandial glucose", "mmol/l"): ("mg/dL", 18.016, "glucose mmol/L x 18.016 = mg/dL"),
    ("creatinine", "mg/dl"): ("µmol/L", 88.42, "creatinine mg/dL x 88.42 = µmol/L"),
    ("creatinine", "µmol/l"): ("mg/dL", 1 / 88.42, "creatinine µmol/L / 88.42 = mg/dL"),
    ("creatinine", "umol/l"): ("mg/dL", 1 / 88.42, "creatinine µmol/L / 88.42 = mg/dL"),
    ("haemoglobin", "g/dl"): ("g/L", 10.0, "haemoglobin g/dL x 10 = g/L"),
    ("haemoglobin", "g/l"): ("g/dL", 0.1, "haemoglobin g/L / 10 = g/dL"),
    ("total cholesterol", "mg/dl"): ("mmol/L", 1 / 38.67, "cholesterol mg/dL / 38.67 = mmol/L"),
    ("total cholesterol", "mmol/l"): ("mg/dL", 38.67, "cholesterol mmol/L x 38.67 = mg/dL"),
    ("ldl cholesterol", "mg/dl"): ("mmol/L", 1 / 38.67, "cholesterol mg/dL / 38.67 = mmol/L"),
    ("ldl cholesterol", "mmol/l"): ("mg/dL", 38.67, "cholesterol mmol/L x 38.67 = mg/dL"),
    ("hdl cholesterol", "mg/dl"): ("mmol/L", 1 / 38.67, "cholesterol mg/dL / 38.67 = mmol/L"),
    ("hdl cholesterol", "mmol/l"): ("mg/dL", 38.67, "cholesterol mmol/L x 38.67 = mg/dL"),
    ("triglycerides", "mg/dl"): ("mmol/L", 1 / 88.57, "triglycerides mg/dL / 88.57 = mmol/L"),
    ("triglycerides", "mmol/l"): ("mg/dL", 88.57, "triglycerides mmol/L x 88.57 = mg/dL"),
    ("hba1c", "%"): ("mmol/mol", lambda v: (v - 2.15) * 10.929, "IFCC: (NGSP % - 2.15) x 10.929 = mmol/mol"),
    ("hba1c", "mmol/mol"): ("%", lambda v: v / 10.929 + 2.15, "NGSP: mmol/mol / 10.929 + 2.15 = %"),
}


def normalise_unit_key(unit: str) -> str:
    return unit.lower().replace("μ", "µ").replace(" ", "")


def convert(test: str | None, value: float | None, unit: str | None):
    if test is None or value is None or unit is None:
        return None
    rule = CONVERSIONS.get((test, normalise_unit_key(unit)))
    if rule is None:
        return None
    target, factor, text = rule
    converted = factor(value) if callable(factor) else value * factor  # type: ignore[operator]
    return round(converted, 2), target, text


def _compile_alias_map(d: dict[str, list[str]]) -> list[tuple[re.Pattern, str]]:
    items = []
    for canon, aliases in d.items():
        for a in aliases:
            items.append((len(a), re.compile(r"(?<![A-Za-z])" + re.escape(a) + r"(?![A-Za-z])", re.I), canon))
    items.sort(key=lambda t: -t[0])  # longest alias first ("amoxicillin-clavulanate" before "amoxicillin")
    return [(rx, canon) for _, rx, canon in items]


MED_PATTERNS = _compile_alias_map(MEDICATIONS)
ALLERGEN_PATTERNS = _compile_alias_map(ALLERGENS)
TEST_PATTERNS = sorted(
    [(re.compile(r"(?<![A-Za-z])" + a, re.I), canon, cat) for canon, (aliases, cat) in TESTS.items() for a in aliases],
    key=lambda t: -len(t[0].pattern),
)


def find_medications(text: str) -> list[tuple[int, int, str, str]]:
    """Return (start, end, text_as_written, normalised) for non-overlapping medication mentions."""
    out, taken = [], []
    for rx, canon in MED_PATTERNS:
        for m in rx.finditer(text):
            if all(m.end() <= a or m.start() >= b for a, b in taken):
                out.append((m.start(), m.end(), m.group(0), canon))
                taken.append((m.start(), m.end()))
    return sorted(out)


def find_allergens(text: str) -> list[tuple[int, int, str, str]]:
    out, taken = [], []
    for rx, canon in ALLERGEN_PATTERNS:
        for m in rx.finditer(text):
            if all(m.end() <= a or m.start() >= b for a, b in taken):
                out.append((m.start(), m.end(), m.group(0), canon))
                taken.append((m.start(), m.end()))
    return sorted(out)


_FUZZY_ALIASES: dict[int, list[tuple[str, str]]] = {}


def fuzzy_find(text: str, table: dict[str, list[str]], threshold: float = 0.86) -> list[tuple[int, int, str, str]]:
    """OCR-tolerant lookup: compare 1-3 word windows (spaces removed) with aliases of >= 6 letters.
    Used only on OCR lines when exact matching fails; results are flagged as fuzzy by callers."""
    import difflib

    key = id(table)
    if key not in _FUZZY_ALIASES:
        _FUZZY_ALIASES[key] = [(re.sub(r"[^a-z]", "", a), canon) for canon, aliases in table.items() for a in aliases
                               if len(re.sub(r"[^a-z]", "", a)) >= 6]
    words = list(re.finditer(r"[A-Za-z][A-Za-z\-]*", text))
    out, taken = [], []
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            s, e = words[i].start(), words[i + n - 1].end()
            if any(not (e <= a or s >= b) for a, b in taken):
                continue
            cand = re.sub(r"[^a-z]", "", text[s:e].lower())
            if len(cand) < 6:
                continue
            best = max(((difflib.SequenceMatcher(None, cand, a).ratio(), canon) for a, canon in _FUZZY_ALIASES[key]), default=(0, None))
            if best[0] >= threshold:
                out.append((s, e, text[s:e], best[1]))
                taken.append((s, e))
    return sorted(out)


def find_test(text: str) -> tuple[int, int, str, str, str] | None:
    best = None
    for rx, canon, cat in TEST_PATTERNS:
        m = rx.search(text)
        if m and (best is None or m.start() < best[0] or (m.start() == best[0] and m.end() > best[1])):
            best = (m.start(), m.end(), m.group(0), canon, cat)
    return best
