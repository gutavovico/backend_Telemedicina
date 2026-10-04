"""Resolve explicit CU22 periods locally before asking the provider for preferences."""

import calendar
import re
from datetime import date

from .catalog import MAX_PERIOD_DAYS


MONTHS = {
    name: index for index, name in enumerate((
        "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
        "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ), 1)
}

# Input has already been case-folded and stripped of accents by interpretation_service.
DAY_WORDS = {
    "un": 1, "una": 1, "uno": 1, "primer": 1, "primera": 1, "primero": 1,
    "dos": 2, "segundo": 2, "tres": 3, "tercero": 3, "cuatro": 4,
    "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
    "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
    "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18,
    "diecinueve": 19, "veinte": 20, "veintiun": 21, "veintiuna": 21,
    "veintiuno": 21, "veintidos": 22, "veintitres": 23,
    "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
    "treinta": 30, "treinta y un": 31, "treinta y una": 31,
    "treinta y uno": 31,
}

_MONTH = "(?:" + "|".join(MONTHS) + ")"
_DAY = "(?:\\d{1,2}|" + "|".join(
    re.escape(word).replace(r"\ ", r"\s+")
    for word in sorted(DAY_WORDS, key=len, reverse=True)
) + ")"


def _dated(prefix: str) -> str:
    return (rf"(?P<{prefix}_day>{_DAY})\s+de\s+(?P<{prefix}_month>{_MONTH})"
            rf"(?:\s+de\s+(?P<{prefix}_year>\d{{4}}))?")


_FULL_RANGE = re.compile(
    rf"\b(?:desde\s+(?:el\s+)?|del\s+){_dated('start')}"
    rf"\s+(?:hasta\s+(?:el\s+)?|al\s+){_dated('end')}\b"
)
_SHARED_MONTH_RANGE = re.compile(
    rf"\b(?:desde\s+(?:el\s+)?|del\s+)(?P<start_day>{_DAY})"
    rf"\s+(?:hasta\s+(?:el\s+)?|al\s+)(?P<end_day>{_DAY})"
    rf"\s+de\s+(?P<month>{_MONTH})\s+de\s+(?P<year>\d{{4}})\b"
)
_DAY_WITH_MONTH = re.compile(rf"\b{_DAY}\s+de\s+{_MONTH}\b")
_MONTH_WORD = re.compile(rf"\b{_MONTH}\b")


def _day_number(value: str) -> int:
    return int(value) if value.isdigit() else DAY_WORDS[value]


def _valid(start: date, end: date) -> tuple[date, date] | None:
    if start <= end and (end - start).days + 1 <= MAX_PERIOD_DAYS:
        return start, end
    return None


def _spanish_range(text: str) -> tuple[date, date] | None:
    matches = [(match, False) for match in _FULL_RANGE.finditer(text)]
    matches += [(match, True) for match in _SHARED_MONTH_RANGE.finditer(text)]
    if len(matches) != 1:
        return None
    match, shared_month = matches[0]
    # Additional date words or years outside this range make the period ambiguous.
    rest = text[:match.start()] + " " + text[match.end():]
    if _MONTH_WORD.search(rest) or re.search(r"\b\d{4}\b", rest):
        return None
    if len(_MONTH_WORD.findall(text)) != (1 if shared_month else 2):
        return None
    groups = match.groupdict()
    if shared_month:
        start_year = end_year = groups["year"]
        start_month = end_month = groups["month"]
    else:
        start_year = groups["start_year"] or groups["end_year"]
        end_year = groups["end_year"] or groups["start_year"]
        start_month, end_month = groups["start_month"], groups["end_month"]
    if not start_year or not end_year:
        return None
    try:
        start = date(int(start_year), MONTHS[start_month], _day_number(groups["start_day"]))
        end = date(int(end_year), MONTHS[end_month], _day_number(groups["end_day"]))
    except ValueError:
        return None
    return _valid(start, end)


def resolve_period(text: str, reference: date | None) -> tuple[date, date] | None:
    """Return an unambiguous inclusive range, never filling a missing year from today."""
    dates = re.findall(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", text)
    if dates:
        if len(dates) != 2:
            return None
        try:
            return _valid(*(date.fromisoformat(value) for value in dates))
        except ValueError:
            return None

    spanish = _spanish_range(text)
    if spanish is not None:
        return spanish
    # A malformed/partial range must not silently become its final whole month.
    if re.search(r"\b(?:desde|hasta|al)\b", text) and _MONTH_WORD.search(text):
        return None
    if re.search(r"\beste mes\b", text):
        if reference is None:
            return None
        last = calendar.monthrange(reference.year, reference.month)[1]
        return date(reference.year, reference.month, 1), date(reference.year, reference.month, last)

    month_pattern = rf"\b({_MONTH})\s+(?:de\s+)?(\d{{4}})\b"
    matches = re.findall(month_pattern, text)
    if len(matches) != 1 or _DAY_WITH_MONTH.search(text):
        return None
    month, year_text = matches[0]
    year = int(year_text)
    if not 1 <= year <= 9999:
        return None
    number = MONTHS[month]
    return date(year, number, 1), date(year, number, calendar.monthrange(year, number)[1])
