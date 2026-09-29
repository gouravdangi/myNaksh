import sqlite3

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.db import connect, init_db
from app.errors import NotFound
from app.orchestrator import ChatOrchestrator
from app.schemas import ChatIn, ChatOut, MemoryOut, MessageOut, SessionIn, SessionOut, UserIn, UserOut
from app.services.brain import BrainService
from app.services.conversation import ConversationService
from app.services.llm import OllamaClient
from app.services.observability import ObservabilityService
from app.services.profile import ProfileService


def create_app(database_path: str | None = None, llm=None) -> FastAPI:
    settings = Settings.from_env()
    path = database_path or settings.database_path
    init_db(path)
    if llm is None:
        llm = OllamaClient(settings.ollama_host, settings.ollama_model)

    app = FastAPI(title="MyNaksh", version="1.0.0")
    app.state.database_path = path
    app.state.llm = llm

    def get_conn():
        conn = connect(path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @app.exception_handler(NotFound)
    async def not_found(_request: Request, exc: NotFound):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(sqlite3.Error)
    async def database_error(_request: Request, _exc: sqlite3.Error):
        return JSONResponse(status_code=500, content={"detail": "The database is unavailable."})

    @app.get("/health")
    def health():
        return {"status": "ok", "ollama": "up" if app.state.llm.healthy() else "down"}

    @app.post("/users", response_model=UserOut, status_code=201)
    def create_user(body: UserIn, conn=Depends(get_conn)):
        try:
            user = ProfileService(conn).create(**body.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _sync_sign(conn, user)
        return user

    @app.get("/users/{user_id}", response_model=UserOut)
    def get_user(user_id: str, conn=Depends(get_conn)):
        user = ProfileService(conn).get(user_id)
        if user is None:
            raise NotFound("User not found.")
        return user

    @app.patch("/users/{user_id}", response_model=UserOut)
    def update_user(user_id: str, body: UserIn, conn=Depends(get_conn)):
        if ProfileService(conn).get(user_id) is None:
            raise NotFound("User not found.")
        try:
            user = ProfileService(conn).update(user_id, **body.model_dump(exclude_unset=True))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _sync_sign(conn, user)
        return user

    @app.post("/sessions", response_model=SessionOut, status_code=201)
    def create_session(body: SessionIn, conn=Depends(get_conn)):
        if ProfileService(conn).get(body.user_id) is None:
            raise NotFound("User not found.")
        return ConversationService(conn).create_session(body.user_id)

    @app.post("/chat", response_model=ChatOut)
    def chat(body: ChatIn, conn=Depends(get_conn)):
        return ChatOrchestrator(conn, app.state.llm).chat(body.user_id, body.message, body.session_id)

    @app.get("/users/{user_id}/memories", response_model=list[MemoryOut])
    def memories(user_id: str, conn=Depends(get_conn)):
        if ProfileService(conn).get(user_id) is None:
            raise NotFound("User not found.")
        return BrainService(conn).active_memories(user_id)

    @app.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
    def messages(session_id: str, conn=Depends(get_conn)):
        if ConversationService(conn).get_session(session_id) is None:
            raise NotFound("Session not found.")
        return ConversationService(conn).list_messages(session_id)

    @app.get("/observability/requests")
    def request_logs(limit: int = Query(default=50, ge=1, le=200), conn=Depends(get_conn)):
        return ObservabilityService(conn).list_requests(limit)

    @app.get("/observability/llm-calls")
    def llm_calls(limit: int = Query(default=50, ge=1, le=200), conn=Depends(get_conn)):
        return ObservabilityService(conn).list_llm_calls(limit)

    return app


def _sync_sign(conn, user: dict | None) -> None:
    if user and user.get("sun_sign"):
        BrainService(conn).remember_sign(user["id"], user["sun_sign"])


app = create_app()
