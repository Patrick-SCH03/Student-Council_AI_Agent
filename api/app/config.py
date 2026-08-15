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

# 키가 없으면 LLM·임베딩 호출 없이 전체 플로우를 검증하는 목업 모드로 동작한다.
MOCK_MODE: bool = GEMINI_API_KEY is None

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
CHROMA_DIR = DATA_DIR / "chroma"
SQLITE_PATH = DATA_DIR / "app.sqlite3"
# Gemini OCR은 같은 PDF에도 매번 다른 텍스트를 내놓는다. 결과를 남겨 재색인 시 재사용한다.
OCR_CACHE_DIR = DATA_DIR / "ocr_cache"

# 최초 실행 시 적용되는 기본값 (0 = 무제한).
# 이후 값은 settings 테이블에 저장되며 관리자 대시보드에서 조절한다.
DEFAULT_LIMITS: dict[str, int] = {
    "daily_limit_total": int(os.getenv("DAILY_LIMIT_TOTAL", "300")),
    "daily_limit_per_user": int(os.getenv("DAILY_LIMIT_PER_USER", "20")),
    # visitor_id는 저장소를 비우면 초기화되므로 IP 기준으로 한 번 더 막는다.
    # 학내 공용 Wi-Fi를 고려해 사용자당 한도보다 여유 있게 잡았다.
    "daily_limit_per_ip": int(os.getenv("DAILY_LIMIT_PER_IP", "60")),
    # 동일 질문 재사용 시간. 문서를 새로 색인하면 캐시를 비우므로 길게 두지 않는다.
    "cache_ttl_hours": int(os.getenv("CACHE_TTL_HOURS", "24")),
}

# 미설정 시 관리자 엔드포인트를 열어두지 않고 503으로 차단한다 (공개 배포 사고 방지).
ADMIN_TOKEN: str | None = os.getenv("ADMIN_TOKEN") or None

# IP 원문은 저장하지 않고 이 값을 섞은 해시만 남긴다.
IP_HASH_SALT: str = os.getenv("IP_HASH_SALT") or ADMIN_TOKEN or "inha-sc-local"

# 비용 추정 단가 (USD / 1M 토큰).
# gemini-3.7-flash 도입 할인가로, 2027-01-01부터 1.50 / 7.50으로 환원된다.
PRICE_INPUT_PER_1M: float = float(os.getenv("PRICE_INPUT_PER_1M", "0.75"))
PRICE_OUTPUT_PER_1M: float = float(os.getenv("PRICE_OUTPUT_PER_1M", "3.75"))
USD_KRW: float = float(os.getenv("USD_KRW", "1400"))

CORS_ORIGINS: list[str] = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
]

for _dir in (DATA_DIR, UPLOAD_DIR, CHROMA_DIR, OCR_CACHE_DIR):
    _dir.mkdir(parents=True, exist_ok=True)
