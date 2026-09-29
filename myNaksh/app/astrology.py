"""Sun sign from a birth date. Tropical ranges, no ephemeris."""

from datetime import date, datetime

SIGNS = (
    ((1, 1), (1, 19), "Capricorn"),
    ((1, 20), (2, 18), "Aquarius"),
    ((2, 19), (3, 20), "Pisces"),
    ((3, 21), (4, 19), "Aries"),
    ((4, 20), (5, 20), "Taurus"),
    ((5, 21), (6, 20), "Gemini"),
    ((6, 21), (7, 22), "Cancer"),
    ((7, 23), (8, 22), "Leo"),
    ((8, 23), (9, 22), "Virgo"),
    ((9, 23), (10, 22), "Libra"),
    ((10, 23), (11, 21), "Scorpio"),
    ((11, 22), (12, 21), "Sagittarius"),
    ((12, 22), (12, 31), "Capricorn"),
)

MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


def sun_sign(iso_date: str) -> str | None:
    parsed = _parse_iso(iso_date)
    if parsed is None:
        return None
    month, day = parsed.month, parsed.day
    for (start_m, start_d), (end_m, end_d), name in SIGNS:
        if (month, day) >= (start_m, start_d) and (month, day) <= (end_m, end_d):
            return name
    return None


def parse_birth_date(value: str) -> str | None:
    """Return YYYY-MM-DD or None."""
    text = value.strip()
    iso = _parse_iso(text)
    if iso:
        return iso.isoformat()
    parts = text.replace(",", " ").split()
    if len(parts) != 3:
        return None
    if parts[0].isdigit() and parts[2].isdigit():
        day, month_name, year = int(parts[0]), parts[1].lower(), int(parts[2])
    elif parts[1].isdigit() and parts[2].isdigit():
        month_name, day, year = parts[0].lower(), int(parts[1]), int(parts[2])
    else:
        return None
    month = MONTHS.get(month_name)
    if not month:
        return None
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _parse_iso(value: str) -> date | None:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None
