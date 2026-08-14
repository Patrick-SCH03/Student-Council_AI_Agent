"""앱 전역 설정. .env를 로드하고, API 키가 없으면 목업 모드로 동작한다."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY: str | None = (
    os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or None
)
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
GEMINI_EMBEDDING_MODEL: str = os.getenv(
    "GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-2"
)

# API 키가 없으면 목업 모드: LLM/임베딩 호출 없이 전체 플로우를 검증할 수 있다.
MOCK_MODE: bool = GEMINI_API_KEY is None

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
CHROMA_DIR = DATA_DIR / "chroma"
SQLITE_PATH = DATA_DIR / "app.sqlite3"

# 일일 질의 상한 기본값 (0 = 무제한). 실제 값은 SQLite settings 테이블에 저장되며
# 관리자 대시보드에서 조절한다. 아래는 최초 실행 시 적용되는 기본값이다.
DEFAULT_LIMITS: dict[str, int] = {
    "daily_limit_total": int(os.getenv("DAILY_LIMIT_TOTAL", "300")),
    "daily_limit_per_user": int(os.getenv("DAILY_LIMIT_PER_USER", "20")),
    # 동일 질문 재사용 시간(시간). 0이면 캐시 사용 안 함.
    # 규정은 자주 바뀌지 않지만 문서를 새로 색인하면 캐시를 비워야 하므로
    # 너무 길게 두지 않는다.
    "cache_ttl_hours": int(os.getenv("CACHE_TTL_HOURS", "24")),
}

# 관리자 API(문서 관리·운영 지표) 보호용 토큰.
# 미설정 시 해당 엔드포인트는 503으로 차단된다 (공개 배포 시 사고 방지).
ADMIN_TOKEN: str | None = os.getenv("ADMIN_TOKEN") or None

# API 비용 추정용 단가 (USD / 1M 토큰). env로 조정 가능.
# gemini-3.7-flash 도입 할인가 (~2026-12-31). 2027-01-01부터 1.50 / 7.50으로 환원되므로
# 그 시점에 아래 기본값 또는 환경변수를 갱신해야 대시보드 비용이 정확하다.
PRICE_INPUT_PER_1M: float = float(os.getenv("PRICE_INPUT_PER_1M", "0.75"))
PRICE_OUTPUT_PER_1M: float = float(os.getenv("PRICE_OUTPUT_PER_1M", "3.75"))
USD_KRW: float = float(os.getenv("USD_KRW", "1400"))

CORS_ORIGINS: list[str] = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
]

for _dir in (DATA_DIR, UPLOAD_DIR, CHROMA_DIR):
    _dir.mkdir(parents=True, exist_ok=True)
