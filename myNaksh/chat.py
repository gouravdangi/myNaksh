import argparse

from app.config import Settings
from app.db import connect, init_db
from app.orchestrator import ChatOrchestrator
from app.services.conversation import ConversationService
from app.services.llm import OllamaClient
from app.services.profile import ProfileService


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with MyNaksh in the terminal.")
    parser.add_argument("--user-id", help="Continue as an existing user, or create this id.")
    args = parser.parse_args()

    settings = Settings.from_env()
    init_db(settings.database_path)
    conn = connect(settings.database_path)
    try:
        profiles = ProfileService(conn)
        if args.user_id:
            user = profiles.get(args.user_id) or profiles.create(user_id=args.user_id)
        else:
            user = profiles.create()
        session = ConversationService(conn).create_session(user["id"])
        conn.commit()

        orchestrator = ChatOrchestrator(
            conn,
            OllamaClient(settings.ollama_host, settings.ollama_model),
        )
        print("Hello, how may I help you?")
        while True:
            try:
                text = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if text.lower() in {"exit", "quit"}:
                break
            if not text:
                continue
            reply = orchestrator.chat(user["id"], text, session["id"])
            conn.commit()
            print(reply["response"])
    finally:
        conn.close()


if __name__ == "__main__":
    main()
