"""앱 전역 설정. .env를 로드하고, API 키가 없으면 목업 모드로 동작한다."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY") or None
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5-mini")
OPENAI_EMBEDDING_MODEL: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

# API 키가 없으면 목업 모드: LLM/임베딩 호출 없이 전체 플로우를 검증할 수 있다.
MOCK_MODE: bool = OPENAI_API_KEY is None

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
CHROMA_DIR = DATA_DIR / "chroma"
SQLITE_PATH = DATA_DIR / "app.sqlite3"

CORS_ORIGINS: list[str] = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
]

for _dir in (DATA_DIR, UPLOAD_DIR, CHROMA_DIR):
    _dir.mkdir(parents=True, exist_ok=True)
