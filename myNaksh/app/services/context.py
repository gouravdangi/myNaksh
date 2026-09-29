import json
import re

STOP_WORDS = {
    "the",
    "and",
    "for",
    "you",
    "your",
    "are",
    "was",
    "what",
    "should",
    "how",
    "may",
    "help",
    "about",
    "please",
    "this",
    "that",
    "with",
    "have",
    "from",
    "focus",
}

RELATION_HINTS = {
    "HAS_GOAL": {"career", "job", "jobs", "work", "goal", "goals", "interview", "switch"},
    "PREFERS": {"prefer", "prefers", "language", "hindi", "english"},
    "INTERESTED_IN": {"interest", "interests", "hobby", "hobbies", "like"},
    "HAS_ZODIAC": {"zodiac", "sign", "astrology", "horoscope", "sun"},
    "HAS_MEMORY": {"memory", "memories", "remember"},
    "HAS_LIFE_AREA": {"family", "health", "life"},
}

PROFILE_LABELS = (
    ("name", "Name"),
    ("date_of_birth", "Date of birth"),
    ("time_of_birth", "Time of birth"),
    ("birth_place", "Birth place"),
    ("sun_sign", "Sun sign"),
    ("language", "Language"),
)


def select_context(
    message: str,
    profile: dict | None,
    memories: list[dict],
    previous_context: list[str],
    has_prior_messages: bool,
) -> dict:
    card = profile_card(profile)
    used: list[str] = []
    if card:
        used.append("user_profile")

    if is_followup(message):
        chosen = _from_previous(memories, previous_context)
    elif is_broad_recall(message):
        chosen = memories[:5]
    else:
        query = tokens(message)
        scored = []
        for memory in memories:
            score = _score(memory, query)
            if score > 0:
                scored.append((score, memory))
        scored.sort(key=lambda item: item[0], reverse=True)
        chosen = [memory for _, memory in scored[:5]]

    for memory in chosen:
        used.extend(context_keys(memory))
    if has_prior_messages:
        used.append("recent_conversation")

    return {
        "profile_card": card,
        "memories": chosen,
        "context_used": _dedupe(used),
    }


def profile_card(profile: dict | None) -> str:
    if not profile:
        return ""
    lines = []
    for key, label in PROFILE_LABELS:
        value = profile.get(key)
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def build_chat_messages(message: str, recent: list[dict], selection: dict) -> list[dict]:
    sections = []
    if selection["profile_card"]:
        sections.append("Profile:\n" + selection["profile_card"])
    if selection["memories"]:
        lines = []
        for memory in selection["memories"]:
            extra = ""
            if memory["attributes"]:
                extra = " " + json.dumps(memory["attributes"], ensure_ascii=True)
            lines.append(f"- {memory['relation']}: {memory['label']}{extra}")
        sections.append("Relevant memories:\n" + "\n".join(lines))
    history = _history_without_current(recent, message)
    if history:
        lines = [f"{item['role']}: {item['content']}" for item in history]
        sections.append("Recent conversation:\n" + "\n".join(lines))
    sections.append("User message:\n" + message)
    return [
        {
            "role": "system",
            "content": (
                "You are MyNaksh, a concise astrology companion. "
                "Use only the profile and memories provided. "
                "Do not invent facts about the user. "
                "If something important is missing, say so briefly and still answer helpfully."
            ),
        },
        {"role": "user", "content": "\n\n".join(sections)},
    ]


def context_keys(memory: dict) -> list[str]:
    keys = [f"{memory['kind']}:{memory['label']}"]
    text = memory["label"].lower()
    relation = memory["relation"]
    if relation == "HAS_GOAL" and any(word in text for word in ("career", "job")):
        keys.append("career_goal")
    elif relation == "HAS_GOAL":
        keys.append("goal")
    elif relation == "PREFERS":
        keys.append("preference")
    elif relation == "INTERESTED_IN":
        keys.append("interest")
    elif relation == "HAS_ZODIAC":
        keys.append("zodiac")
    elif relation == "HAS_MEMORY":
        keys.append("memory")
    return keys


def is_followup(message: str) -> bool:
    words = re.findall(r"[a-z']+", message.lower())
    if not words or len(words) > 8:
        return False
    return any(word in words for word in ("why", "that", "it"))


def is_broad_recall(message: str) -> bool:
    if "remember" not in message.lower() and "recall" not in message.lower():
        return False
    topical = tokens(message) - {"remember", "recall", "know"}
    return not topical


def tokens(text: str) -> set[str]:
    found = set(re.findall(r"[a-z0-9]+", text.lower()))
    return {word for word in found if len(word) > 2 and word not in STOP_WORDS}


def _score(memory: dict, query: set[str]) -> int:
    blob = memory["label"] + " " + " ".join(str(value) for value in memory["attributes"].values())
    overlap = len(tokens(blob) & query)
    hints = RELATION_HINTS.get(memory["relation"], set())
    boost = 2 if hints & query else 0
    return overlap + boost


def _from_previous(memories: list[dict], previous_context: list[str]) -> list[dict]:
    chosen = []
    previous = set(previous_context)
    for memory in memories:
        if any(key in previous for key in context_keys(memory)):
            chosen.append(memory)
    return chosen[:5]


def _history_without_current(recent: list[dict], message: str) -> list[dict]:
    if recent and recent[-1]["role"] == "user" and recent[-1]["content"] == message:
        return recent[:-1]
    return recent


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
