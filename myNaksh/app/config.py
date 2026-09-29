import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class Settings:
    ollama_host: str
    ollama_model: str
    database_path: str

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2"),
            database_path=os.getenv("DATABASE_PATH", "data/mynaksh.db"),
        )
