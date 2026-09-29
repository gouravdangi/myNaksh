from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.llm import LLMError, LLMResult, LLMUsage


class FakeLLM:
    def __init__(self, reply="Based on your career goals, prepare for the switch.", fail=False):
        self.reply = reply
        self.fail = fail
        self.model = "fake"
        self.calls = []

    def complete(self, messages, *, json_mode=False):
        self.calls.append({"messages": messages, "json_mode": json_mode})
        if self.fail:
            raise LLMError("ollama unavailable", latency_ms=5, model=self.model)
        if json_mode:
            text = '{"facts": [], "profile": {}}'
            usage = LLMUsage(3, 2, 5)
        else:
            text = self.reply
            usage = LLMUsage(10, 8, 18)
        return LLMResult(text=text, model=self.model, usage=usage, latency_ms=4)

    def healthy(self):
        return not self.fail


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def client(tmp_path, fake_llm):
    app = create_app(database_path=str(tmp_path / "test.db"), llm=fake_llm)
    with TestClient(app) as test_client:
        yield test_client


def _user(client, **fields):
    response = client.post("/users", json=fields)
    assert response.status_code == 201
    return response.json()


def _chat(client, user_id, message, session_id=None):
    body = {"user_id": user_id, "message": message}
    if session_id:
        body["session_id"] = session_id
    response = client.post("/chat", json=body)
    assert response.status_code == 200, response.text
    return response.json()


INTRO = (
    "My name is Rahul. I was born on 15 August 1995 in Delhi. "
    "I'm planning to switch jobs next year."
)


def test_new_user_profile_and_sun_sign(client):
    user = _user(client, name="Rahul", date_of_birth="1995-08-15", birth_place="Delhi")
    assert user["sun_sign"] == "Leo"
    fetched = client.get(f"/users/{user['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Rahul"
    labels = [item["label"] for item in client.get(f"/users/{user['id']}/memories").json()]
    assert "Leo" in labels

    bad_date = client.post("/users", json={"date_of_birth": "not-a-date"})
    assert bad_date.status_code == 422


def test_creating_a_long_term_memory(client):
    user = _user(client)
    _chat(client, user["id"], INTRO)
    profile = client.get(f"/users/{user['id']}").json()
    assert profile["name"] == "Rahul"
    assert profile["date_of_birth"] == "1995-08-15"
    assert profile["birth_place"] == "Delhi"
    assert profile["sun_sign"] == "Leo"

    memories = client.get(f"/users/{user['id']}/memories").json()
    goal = next(item for item in memories if item["relation"] == "HAS_GOAL")
    assert goal["label"] == "Career Change"
    assert goal["attributes"]["timeframe"] == "next year"
    assert goal["attributes"]["target_year"] == date.today().year + 1


def test_retrieving_a_memory_in_a_new_session(client):
    user = _user(client)
    first = _chat(client, user["id"], INTRO)
    second = _chat(client, user["id"], "What do you remember about my career goals?")
    assert second["session_id"] != first["session_id"]
    assert "career_goal" in second["context_used"]
    assert "user_profile" in second["context_used"]
    assert "interest" not in second["context_used"]


def test_follow_up_uses_recent_conversation(client, fake_llm):
    user = _user(client)
    _chat(client, user["id"], INTRO)
    career = _chat(client, user["id"], "What should I focus on for my career?")
    follow = _chat(client, user["id"], "Why do you say that?", career["session_id"])
    assert "recent_conversation" in follow["context_used"]
    assert "career_goal" in follow["context_used"]

    chat_prompts = [
        call["messages"][-1]["content"]
        for call in fake_llm.calls
        if not call["json_mode"]
    ]
    assert fake_llm.reply in chat_prompts[-1]
    assert "Why do you say that?" in chat_prompts[-1]


def test_irrelevant_memory_is_left_out(client):
    user = _user(client)
    _chat(client, user["id"], INTRO)
    _chat(client, user["id"], "I am interested in gardening.")
    reply = _chat(client, user["id"], "What should I focus on for my career?")
    joined = " ".join(reply["context_used"]).lower()
    assert "career_goal" in reply["context_used"]
    assert "gardening" not in joined


def test_correction_supersedes_old_goal(client):
    user = _user(client)
    _chat(client, user["id"], INTRO)
    _chat(
        client,
        user["id"],
        "Actually, my career goal is career growth, not switching jobs.",
    )
    memories = client.get(f"/users/{user['id']}/memories").json()
    labels = [item["label"] for item in memories]
    assert "Career Growth" in labels
    assert "Career Change" not in labels

    import sqlite3

    conn = sqlite3.connect(client.app.state.database_path)
    row = conn.execute(
        "SELECT status FROM brain_nodes WHERE label = ?",
        ("Career Change",),
    ).fetchone()
    conn.close()
    assert row[0] == "superseded"


def test_missing_profile_still_answers(client, fake_llm):
    user = _user(client)
    reply = _chat(client, user["id"], "Hello")
    assert reply["response"] == fake_llm.reply
    assert "user_profile" not in reply["context_used"]
    assert client.get(f"/users/{user['id']}/memories").json() == []


def test_llm_failure_is_logged_and_falls_back(tmp_path):
    llm = FakeLLM(fail=True)
    app = create_app(database_path=str(tmp_path / "down.db"), llm=llm)
    with TestClient(app) as client:
        user = _user(client)
        reply = _chat(client, user["id"], "Hello")
        assert reply["response"].startswith("I'm having trouble reaching the model")
        calls = client.get("/observability/llm-calls").json()
        assert calls
        assert all(item["status"] == "error" for item in calls)
        requests = client.get("/observability/requests").json()
        assert requests[0]["status"] == "llm_error"
        assert requests[0]["latency_ms"] >= 0


def test_observability_records_tokens(client):
    user = _user(client)
    _chat(client, user["id"], "Hello")
    calls = client.get("/observability/llm-calls").json()
    chat_call = next(item for item in calls if item["step"] == "chat")
    assert chat_call["status"] == "ok"
    assert chat_call["prompt_tokens"] == 10
    assert chat_call["completion_tokens"] == 8
    assert chat_call["total_tokens"] == 18
    assert chat_call["latency_ms"] >= 0


def test_invalid_input_and_unknown_ids(client):
    missing = client.post("/chat", json={"user_id": "nobody", "message": "Hi"})
    assert missing.status_code == 404
    blank = client.post("/chat", json={"user_id": "x", "message": "   "})
    assert blank.status_code == 422
    unknown = client.get("/users/missing")
    assert unknown.status_code == 404

    user = _user(client)
    other = _user(client)
    session = client.post("/sessions", json={"user_id": user["id"]})
    assert session.status_code == 201
    stolen = client.post(
        "/chat",
        json={"user_id": other["id"], "session_id": session.json()["id"], "message": "Hi"},
    )
    assert stolen.status_code == 404

    used = _chat(client, user["id"], "Hello", session.json()["id"])
    messages = client.get(f"/sessions/{used['session_id']}/messages")
    assert messages.status_code == 200
    assert [item["role"] for item in messages.json()] == ["user", "assistant"]

    health = client.get("/health")
    assert health.json() == {"status": "ok", "ollama": "up"}
