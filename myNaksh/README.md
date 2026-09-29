# MyNaksh

A small personalized astrology chat. It keeps a short conversation window, stores durable facts in a shared brain, and answers with Ollama.

## Run

Ollama needs to be running locally, with a model pulled:

```bash
ollama pull llama3.2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

In another terminal:

```bash
python chat.py
```

The program prints `Hello, how may I help you?` and reads lines until `exit`. Add `--user-id user-123` to keep the same person across runs.

Optional environment variables (see `.env.example`):

- `OLLAMA_HOST` default `http://localhost:11434`
- `OLLAMA_MODEL` default `llama3.2`
- `DATABASE_PATH` default `data/mynaksh.db`

Tests do not call Ollama:

```bash
pytest
```

## Architecture

One process. The API and the terminal both call `ChatOrchestrator`. Profile, conversation, brain, and observability each own their own tables. They do not call each other over HTTP, so any of them can later move behind its own service without changing the pipeline.

```
chat.py  ─┐
          ├─ ChatOrchestrator ─ Profile
POST /chat┘         │          ─ Conversation   (short-term messages)
                    │          ─ Brain           (long-term nodes and edges)
                    │          ─ Context selector
                    │          ─ Ollama client
                    └──────── Observability
                              SQLite (WAL)
```

Each chat turn:

1. Save the user message.
2. Load the last 6 messages, the profile, and active memories.
3. Select only the relevant slice.
4. Ask the model for a reply.
5. Ask the model what is worth keeping. If that call fails or finds nothing, simple rules catch the obvious phrases.
6. Save the reply and write timing and token rows.

A fact learned in the current sentence is available on the next turn, not inside the same model call. The current sentence is already in the prompt.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/users` | Create a profile |
| `GET` | `/users/{user_id}` | Read a profile |
| `PATCH` | `/users/{user_id}` | Update a profile |
| `POST` | `/sessions` | Open a conversation |
| `POST` | `/chat` | Send a message. `session_id` is optional |
| `GET` | `/users/{user_id}/memories` | Active shared-brain facts |
| `GET` | `/sessions/{session_id}/messages` | Short-term transcript |
| `GET` | `/observability/requests` | One row per chat |
| `GET` | `/observability/llm-calls` | Tokens, latency, and failures per model call |
| `GET` | `/health` | Process up, and whether Ollama responds |

Missing JSON fields return 422. An unknown user or session returns 404. If the model is down, `/chat` still returns 200 with a short fallback, and the failure is stored. An empty profile or an empty brain still answers from the current message.

## Database

SQLite file, WAL mode. There is no graph database.

`users` holds the profile: name, date of birth, time of birth, birth place, language, sun sign.

`sessions` and `messages` are short-term. Messages are not copied into long-term memory.

`brain_nodes` and `brain_edges` are the shared brain. A node is a fact (`goal`, `preference`, `interest`, `memory`, `life_area`, `astrology`) with a label, JSON attributes (`timeframe`, `target_year`), a confidence, and a status (`active` or `superseded`). An edge hangs off the user id, because the user already lives in `users`. `from_node_id` is null. Relations are `HAS_GOAL`, `INTERESTED_IN`, `PREFERS`, `HAS_MEMORY`, `HAS_LIFE_AREA`, and `HAS_ZODIAC`.

```
User (users.id)
  ├── HAS_GOAL → Career Change   {timeframe: next year, target_year: 2027}
  ├── INTERESTED_IN → Gardening
  ├── PREFERS → Hindi
  └── HAS_ZODIAC → Leo
```

Retrieval is one indexed query: active nodes for this user, joined to their edge. The selector then keeps a handful. That is the whole traversal. Neo4j, Kuzu, and the embedded graph engines (KGLite, GestaltDB) are a better fit once facts point at other facts and you need multi-hop queries or many writers. graphify is a coding-assistant skill that maps a repository, not a runtime user memory. Packaged agent memories (Dory, Ariadne, and similar) would hide the extraction and update rules this service is meant to show.

`llm_calls` stores each model call: step (`chat` or `extract`), model, prompt tokens, completion tokens, total tokens, latency in milliseconds, status, and error text. Token counts come from Ollama's `prompt_eval_count` and `eval_count`.

`request_logs` stores one row per chat: total latency, the `context_used` list, and status (`ok` or `llm_error`).

## Memory

Short-term context is the last 6 messages in the session. That is what makes "Why do you say that?" work.

Long-term memory is a fact that will still matter in a new session: goals, preferences, interests, birth details, and corrections of those. Greetings, questions, and one-off chatter are not stored.

The extractor returns JSON facts. A matching active label is updated. A correction marks the old node `superseded` and writes a new one. "I'm planning to switch jobs next year" becomes `Career Change` with `timeframe` next year and `target_year` set to next calendar year. Name, birth date, birth place, and language also update `users`. Sun sign is a fixed tropical range from the birth date (15 August is Leo), then a `HAS_ZODIAC` node.

If the extractor call fails, returns junk, or returns nothing, rules look for `my name is`, `born on`, `born in`, `planning to`, `preparing for`, `interested in`, a preferred language, and `actually, my career goal is`.

## Context selection

The model does not receive the full brain or the full transcript.

- The profile card is included when any profile field is set.
- Memories are scored by word overlap with the message, plus a bump when the wording matches the relation (`career` or `job` toward `HAS_GOAL`, and the same idea for preferences, interests, and zodiac). The top 5 with a score above zero are kept.
- "What do you remember about me?" with no other topic loads up to 5 active facts.
- A short follow-up (`why`, `that`, `it`) reuses the previous turn's selected facts instead of searching again, and the recent messages go in the prompt.
- Anything not selected is left out. `context_used` names what was sent, for example `user_profile`, `career_goal`, and `recent_conversation`.

## LLM

`LLMClient` is the only interface the orchestrator uses: `complete(messages, json_mode=False)` and `healthy()`. `OllamaClient` is the production implementation. Tests use a fake. Swapping provider means a new class with that same shape.

The chat prompt is a system line plus the profile card, the selected memories, the recent turns, and the current message.

## How to judge it

No separate evaluation harness. The automated tests cover a new user, storing a memory, recalling it in a new session, a follow-up, an unrelated hobby staying out of a career answer, a correction that supersedes the old goal, a user with no profile, and a down model. Read `context_used` on `/chat` and the rows in `/observability/llm-calls` when you want to see what the model actually received and what it cost.

In a longer trial, compare answers with the brain connected and with an empty brain: the career answer should mention the stored goal, a new session should still know it, a "why" follow-up should stay on the previous reply, and a gardening fact should not show up in a career question.

## Trade-offs

SQLite is one writer, which is enough for this assignment and for `chat.py` plus the API on one machine. WAL lets those two share the file. The brain is a property graph in two tables because every fact is one hop from the user. Moving the same nodes and edges to Neo4j later does not change the orchestrator.

Sun sign is a date table, not a birth chart. Time and place are stored so a real calculator can use them later.

Services are modules, not network services, so the core path stays easy to run in three hours. The split is already where the HTTP boundary would go.

## Sample

```bash
curl -s -X POST localhost:8000/users -H 'content-type: application/json' -d '{"name":"Rahul"}'

curl -s -X POST localhost:8000/chat -H 'content-type: application/json' -d '{
  "user_id": "USER_ID",
  "message": "My name is Rahul. I was born on 15 August 1995 in Delhi. I am planning to switch jobs next year."
}'

curl -s -X POST localhost:8000/chat -H 'content-type: application/json' -d '{
  "user_id": "USER_ID",
  "message": "What should I focus on for my career?"
}'
```

The second chat, in a new session, looks like:

```json
{
  "response": "Based on your career goals, prepare for the switch.",
  "user_id": "USER_ID",
  "session_id": "SESSION_ID",
  "context_used": ["user_profile", "goal:Career Change", "career_goal"]
}
```

`GET /users/USER_ID/memories` then includes `HAS_GOAL` / `Career Change` and `HAS_ZODIAC` / `Leo`.
