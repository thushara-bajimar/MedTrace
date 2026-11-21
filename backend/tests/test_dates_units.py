"""Date ambiguity handling and unit preservation / explicit conversions."""
from medtrace.extract.dates import declared_convention, find_dates, first_date
from medtrace.extract.lexicon import convert


def test_unambiguous_numeric_dates():
    assert first_date("25/07/2023").iso == "2023-07-25"          # day > 12 => DD/MM
    assert first_date("07/25/2023").iso == "2023-07-25"          # month position > 12 => MM/DD
    assert first_date("07/25/2023").method == "numeric_mdy"


def test_ambiguous_numeric_date_is_not_guessed():
    d = first_date("Date: 05/06/2023")
    assert d.status == "ambiguous"
    assert d.iso is None
    assert set(d.candidates) == {"2023-06-05", "2023-05-06"}
    assert d.text == "05/06/2023"                                 # original preserved


def test_declared_convention_resolves_ambiguity():
    text = "All dates in this document are in DD/MM/YYYY format.\nDate of admission: 03/02/2024"
    conv = declared_convention(text)
    assert conv == "DMY"
    d = first_date("03/02/2024", conv)
    assert d.iso == "2024-02-03" and d.method == "declared_convention_dmy"


def test_textual_iso_and_partial_dates():
    assert first_date("12 March 2024").iso == "2024-03-12"
    assert first_date("March 8, 2024").iso == "2024-03-08"
    assert first_date("12-Apr-2023").iso == "2023-04-12"
    assert first_date("2023-04-20").iso == "2023-04-20"
    m = first_date("in August 2023")
    assert m.iso == "2023-08" and m.precision == "month" and m.status == "partial"
    y = first_date("Appendicectomy in 2010")
    assert y.iso == "2010" and y.precision == "year"


def test_two_digit_year_and_invalid_dates_flagged():
    assert first_date("01/02/24").status == "ambiguous"
    assert find_dates("31/31/2023")[0].status == "invalid"


def test_same_day_month_is_unambiguous():
    assert first_date("04/04/2024").iso == "2024-04-04"


def test_unit_conversion_is_explicit_and_documented():
    v, unit, rule = convert("creatinine", 1.3, "mg/dL")
    assert unit == "µmol/L" and abs(v - 114.95) < 0.01 and "88.42" in rule
    v, unit, rule = convert("hba1c", 6.9, "%")
    assert unit == "mmol/mol" and abs(v - 51.91) < 0.01
    v, unit, _ = convert("haemoglobin", 125, "g/L")
    assert unit == "g/dL" and v == 12.5
    assert convert("tsh", 6.8, "mIU/L") is None                  # no rule => no conversion
    assert convert("creatinine", 1.0, "mmol/L") is None          # unknown unit pair => no conversion
