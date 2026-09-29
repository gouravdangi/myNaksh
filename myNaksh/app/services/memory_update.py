import json
import re
from datetime import date

from app.astrology import parse_birth_date
from app.services.brain import KIND_RELATION

LANGUAGES = (
    "hindi",
    "english",
    "tamil",
    "telugu",
    "bengali",
    "marathi",
    "gujarati",
    "kannada",
    "malayalam",
    "punjabi",
    "urdu",
)

EXTRACT_SYSTEM = """Extract durable facts about the user from the message.
Return JSON only, with this shape:
{"facts":[{"kind":"goal|preference|interest|memory|life_area|astrology","relation":"HAS_GOAL|PREFERS|INTERESTED_IN|HAS_MEMORY|HAS_LIFE_AREA|HAS_ZODIAC","label":"short name","attributes":{},"action":"add|replace","replaces":null}],"profile":{"name":null,"date_of_birth":null,"time_of_birth":null,"birth_place":null,"language":null}}
Store goals, preferences, interests, birth details, and corrections of those facts.
Do not store greetings, questions, or one-off chatter.
Use action "replace" and "replaces" when the user corrects an existing fact.
If nothing is worth keeping, return empty facts and null profile fields."""


def extract_messages(message: str) -> list[dict]:
    return [
        {"role": "system", "content": EXTRACT_SYSTEM},
        {"role": "user", "content": message},
    ]


def parse_extraction(text: str) -> tuple[list[dict], dict]:
    payload = text.strip()
    if payload.startswith("```"):
        payload = re.sub(r"^```(?:json)?", "", payload).strip()
        payload = payload.removesuffix("```").strip()
    data = json.loads(payload)
    facts = []
    for raw in data.get("facts") or []:
        fact = _clean_fact(raw)
        if fact:
            facts.append(fact)
    profile = {}
    for key in ("name", "date_of_birth", "time_of_birth", "birth_place", "language"):
        value = (data.get("profile") or {}).get(key)
        if isinstance(value, str) and value.strip():
            profile[key] = value.strip()
    if "date_of_birth" in profile:
        parsed = parse_birth_date(profile["date_of_birth"])
        if parsed is None:
            profile.pop("date_of_birth")
        else:
            profile["date_of_birth"] = parsed
    return facts, profile


def extract_rules(message: str, today: date | None = None) -> tuple[list[dict], dict]:
    today = today or date.today()
    facts: list[dict] = []
    profile: dict = {}

    correction = re.search(r"\bmy career goal is\s+([^,\n.]+)", message, re.I)
    if correction and re.search(r"\bactually\b", message, re.I):
        label = _title(correction.group(1))
        replaces = None
        if re.search(r"\bnot\b.+\b(switch(?:ing)? jobs|career change)\b", message, re.I):
            replaces = "Career Change"
        facts.append(
            _fact("goal", "HAS_GOAL", label, action="replace", replaces=replaces)
        )
    else:
        plan = re.search(r"\b(?:i'm|i am|im)\s+(?:planning to|preparing for)\s+(.+)", message, re.I)
        if plan:
            label, attributes = _goal_from_clause(plan.group(1), today)
            if label:
                facts.append(_fact("goal", "HAS_GOAL", label, attributes))

    interest = re.search(r"\binterested in\s+([^.\n]+)", message, re.I)
    if interest:
        label = interest.group(1).strip(" .")
        if label:
            facts.append(_fact("interest", "INTERESTED_IN", _title(label)))

    language = _language(message)
    if language:
        profile["language"] = language
        facts.append(
            _fact("preference", "PREFERS", language, action="replace")
        )

    name = re.search(r"\bmy name is\s+([A-Za-z]+(?:\s+[A-Za-z]+){0,2})", message, re.I)
    if name:
        profile["name"] = name.group(1).strip().title()

    born_on = re.search(r"\bborn on\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})", message, re.I)
    if born_on:
        parsed = parse_birth_date(born_on.group(1))
        if parsed:
            profile["date_of_birth"] = parsed

    place = re.search(
        r"\bborn (?:on\s+(?:\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})\s+)?in\s+"
        r"([A-Za-z]+(?:\s+[A-Za-z]+){0,2})",
        message,
        re.I,
    )
    if place:
        profile["birth_place"] = place.group(1).strip().title()

    explicit_place = re.search(
        r"\bbirth place is\s+([A-Za-z]+(?:\s+[A-Za-z]+){0,2})",
        message,
        re.I,
    )
    if explicit_place:
        profile["birth_place"] = explicit_place.group(1).strip().title()

    return facts, profile


def _goal_from_clause(clause: str, today: date) -> tuple[str, dict]:
    raw = clause.strip().rstrip(".")
    attributes = {}
    for phrase, label, year_delta in (
        ("next year", "next year", 1),
        ("next month", "next month", None),
        ("this year", "this year", 0),
    ):
        if phrase in raw.lower():
            attributes["timeframe"] = label
            raw = re.sub(re.escape(phrase), "", raw, flags=re.I).strip(" .,")
            if year_delta is not None:
                attributes["target_year"] = today.year + year_delta
            break
    lowered = raw.lower()
    if "switch" in lowered and "job" in lowered:
        raw = "Career Change"
    else:
        raw = _title(raw)
    return raw, attributes


def _language(message: str) -> str | None:
    listed = "|".join(LANGUAGES)
    match = re.search(
        rf"\b(?:i prefer|preferred language is)\s+({listed})\b",
        message,
        re.I,
    )
    if not match:
        return None
    return match.group(1).title()


def _title(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split())


def _fact(kind, relation, label, attributes=None, action="add", replaces=None) -> dict:
    return {
        "kind": kind,
        "relation": relation or KIND_RELATION[kind],
        "label": label,
        "attributes": attributes or {},
        "action": action,
        "replaces": replaces,
        "confidence": 0.85,
    }


def _clean_fact(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    label = raw.get("label")
    if kind not in KIND_RELATION or not isinstance(label, str) or not label.strip():
        return None
    relation = raw.get("relation") or KIND_RELATION[kind]
    if relation not in KIND_RELATION.values():
        relation = KIND_RELATION[kind]
    attributes = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {}
    action = raw.get("action") if raw.get("action") in {"add", "replace", "update"} else "add"
    if action == "update":
        action = "add"
    replaces = raw.get("replaces")
    if not isinstance(replaces, str) or not replaces.strip():
        replaces = None
    return _fact(kind, relation, label.strip(), attributes, action, replaces)
