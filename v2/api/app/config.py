"""앱 전역 설정. .env를 로드하고, API 키가 없으면 목업 모드로 동작한다."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY: str | None = (
    os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or None
)
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_EMBEDDING_MODEL: str = os.getenv(
    "GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-2"
)

# API 키가 없으면 목업 모드: LLM/임베딩 호출 없이 전체 플로우를 검증할 수 있다.
MOCK_MODE: bool = GEMINI_API_KEY is None

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
CHROMA_DIR = DATA_DIR / "chroma"
SQLITE_PATH = DATA_DIR / "app.sqlite3"

# API 비용 추정용 단가 (USD / 1M 토큰, 2026-08 gemini-3.5-flash 기준. env로 조정 가능)
PRICE_INPUT_PER_1M: float = float(os.getenv("PRICE_INPUT_PER_1M", "1.50"))
PRICE_OUTPUT_PER_1M: float = float(os.getenv("PRICE_OUTPUT_PER_1M", "9.00"))
USD_KRW: float = float(os.getenv("USD_KRW", "1400"))

CORS_ORIGINS: list[str] = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
]

for _dir in (DATA_DIR, UPLOAD_DIR, CHROMA_DIR):
    _dir.mkdir(parents=True, exist_ok=True)
