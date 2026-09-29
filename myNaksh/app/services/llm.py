import time
from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class LLMResult:
    text: str
    model: str
    usage: LLMUsage
    latency_ms: int


class LLMError(Exception):
    def __init__(self, message: str, *, latency_ms: int = 0, model: str = ""):
        super().__init__(message)
        self.latency_ms = latency_ms
        self.model = model


class LLMClient(Protocol):
    def complete(self, messages: list[dict], *, json_mode: bool = False) -> LLMResult: ...

    def healthy(self) -> bool: ...


class OllamaClient:
    def __init__(self, host: str, model: str):
        import ollama

        self._client = ollama.Client(host=host)
        self.model = model

    def complete(self, messages: list[dict], *, json_mode: bool = False) -> LLMResult:
        started = time.perf_counter()
        kwargs = {"model": self.model, "messages": messages, "stream": False}
        if json_mode:
            kwargs["format"] = "json"
        try:
            response = self._client.chat(**kwargs)
        except Exception as exc:
            elapsed = _elapsed_ms(started)
            raise LLMError(str(exc), latency_ms=elapsed, model=self.model) from exc

        text, prompt_tokens, completion_tokens = _read_response(response)
        usage = LLMUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )
        return LLMResult(
            text=text,
            model=self.model,
            usage=usage,
            latency_ms=_elapsed_ms(started),
        )

    def healthy(self) -> bool:
        try:
            self._client.list()
            return True
        except Exception:
            return False


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _read_response(response) -> tuple[str, int, int]:
    if isinstance(response, dict):
        message = response.get("message") or {}
        text = message.get("content") or ""
        prompt_tokens = int(response.get("prompt_eval_count") or 0)
        completion_tokens = int(response.get("eval_count") or 0)
        return text, prompt_tokens, completion_tokens

    message = getattr(response, "message", None)
    text = getattr(message, "content", "") or ""
    prompt_tokens = int(getattr(response, "prompt_eval_count", 0) or 0)
    completion_tokens = int(getattr(response, "eval_count", 0) or 0)
    return text, prompt_tokens, completion_tokens
