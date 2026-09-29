import json
import time

from app.errors import NotFound
from app.services.brain import BrainService
from app.services.context import build_chat_messages, select_context
from app.services.conversation import ConversationService
from app.services.llm import LLMClient, LLMError
from app.services.memory_update import extract_messages, extract_rules, parse_extraction
from app.services.observability import ObservabilityService
from app.services.profile import ProfileService

FALLBACK = "I'm having trouble reaching the model right now. Please try again in a moment."


class ChatOrchestrator:
    def __init__(self, conn, llm: LLMClient):
        self.conn = conn
        self.llm = llm
        self.profiles = ProfileService(conn)
        self.conversation = ConversationService(conn)
        self.brain = BrainService(conn)
        self.obs = ObservabilityService(conn)

    def chat(self, user_id: str, message: str, session_id: str | None = None) -> dict:
        started = time.perf_counter()
        user = self.profiles.get(user_id)
        if user is None:
            raise NotFound("User not found. Create one with POST /users.")

        if session_id:
            session = self.conversation.get_session(session_id)
            if session is None or session["user_id"] != user_id:
                raise NotFound("Session not found.")
        else:
            session = self.conversation.create_session(user_id)
            session_id = session["id"]

        self.conversation.add_message(session_id, "user", message)
        recent = self.conversation.recent_messages(session_id)
        selection = select_context(
            message,
            user,
            self.brain.active_memories(user_id),
            self.obs.latest_context(session_id),
            has_prior_messages=len(recent) > 1,
        )

        status = "ok"
        try:
            result = self.llm.complete(build_chat_messages(message, recent, selection))
            self.obs.log_success(user_id, session_id, "chat", result)
            response_text = result.text.strip() or FALLBACK
        except LLMError as exc:
            status = "llm_error"
            self._log_failure(user_id, session_id, "chat", exc)
            response_text = FALLBACK

        self._update_memory(user_id, session_id, message)
        self.conversation.add_message(session_id, "assistant", response_text)
        self.obs.log_request(
            user_id=user_id,
            session_id=session_id,
            latency_ms=int((time.perf_counter() - started) * 1000),
            context_used=selection["context_used"],
            status=status,
        )
        return {
            "response": response_text,
            "user_id": user_id,
            "session_id": session_id,
            "context_used": selection["context_used"],
        }

    def _update_memory(self, user_id: str, session_id: str, message: str) -> None:
        facts, profile = self._extract(user_id, session_id, message)
        if profile:
            updated = self.profiles.update(user_id, **profile)
            if updated and "date_of_birth" in profile and updated.get("sun_sign"):
                self.brain.remember_sign(user_id, updated["sun_sign"])
        for fact in facts:
            self.brain.remember(user_id, fact)

    def _extract(self, user_id: str, session_id: str, message: str) -> tuple[list[dict], dict]:
        try:
            result = self.llm.complete(extract_messages(message), json_mode=True)
            self.obs.log_success(user_id, session_id, "extract", result)
        except LLMError as exc:
            self._log_failure(user_id, session_id, "extract", exc)
            return extract_rules(message)

        try:
            facts, profile = parse_extraction(result.text)
        except (json.JSONDecodeError, TypeError, ValueError):
            facts, profile = [], {}
        if not facts and not profile:
            return extract_rules(message)
        return facts, profile

    def _log_failure(self, user_id: str, session_id: str, step: str, exc: LLMError) -> None:
        self.obs.log_llm_call(
            user_id=user_id,
            session_id=session_id,
            step=step,
            model=exc.model or getattr(self.llm, "model", ""),
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=exc.latency_ms,
            status="error",
            error=str(exc),
        )
