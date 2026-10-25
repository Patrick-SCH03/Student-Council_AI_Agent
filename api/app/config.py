"""앱 전역 설정. .env를 로드하고, 모델 키가 없으면 목업 모드로 동작한다."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# 릴리스 태그와 같이 올린다. /api/health로 배포본이 어떤 버전인지 확인한다.
APP_VERSION = "2.17.1"

# 질문 분류·규정 검토·감사 분석·종합 조정·문서 OCR은 Claude, 검색 임베딩은 Gemini(기본) 또는 Voyage가 맡는다.
CLAUDE_API_KEY: str | None = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or None
CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")
# effort는 사고 깊이·출력량을 함께 정한다. 2026-10-13 A/B에서 low가 지연 목표에 맞았다.
CLAUDE_EFFORT: str = os.getenv("CLAUDE_EFFORT", "low")
# Claude 호출 타임아웃(초). Haiku·low는 단계당 5~10초라 30초면 충분하다. 더 큰 모델이나 높은 effort로
# 바꾸면 함께 올린다 — 낮으면 매번 타임아웃 → 재시도로 지연·비용만 겹친다.
CLAUDE_TIMEOUT: float = float(os.getenv("CLAUDE_TIMEOUT") or (30 if CLAUDE_EFFORT == "low" else 90))

# 검색 임베딩 공급자 (gemini | voyage). 바꾸면 벡터 공간이 달라 전체 재색인이 필요하다.
# Voyage는 Gemini 프로젝트가 막혔을 때(2026-10-24 정지)를 대비한 예비 경로로 남겨 둔다.
EMBEDDING_PROVIDER: str = (os.getenv("EMBEDDING_PROVIDER") or "gemini").strip().lower()
if EMBEDDING_PROVIDER not in ("gemini", "voyage"):
    print(f"EMBEDDING_PROVIDER={EMBEDDING_PROVIDER!r}는 알 수 없는 값이라 gemini로 동작한다")
    EMBEDDING_PROVIDER = "gemini"

GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY") or None
# 옛 설정값("models/gemini-embedding-2")도 받는다 — 접두어가 겹치면 요청 경로·컬렉션 이름이 깨진다
GEMINI_EMBEDDING_MODEL: str = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2").removeprefix("models/")
VOYAGE_API_KEY: str | None = os.getenv("VOYAGE_API_KEY") or None
VOYAGE_EMBEDDING_MODEL: str = os.getenv("VOYAGE_EMBEDDING_MODEL", "voyage-4")

EMBEDDING_API_KEY: str | None = GEMINI_API_KEY if EMBEDDING_PROVIDER == "gemini" else VOYAGE_API_KEY
EMBEDDING_MODEL: str = GEMINI_EMBEDDING_MODEL if EMBEDDING_PROVIDER == "gemini" else VOYAGE_EMBEDDING_MODEL

# Claude 키와 고른 공급자의 임베딩 키가 모두 있어야 실제로 동작한다.
# 하나라도 없으면 LLM·임베딩 호출 없이 전체 플로우를 검증하는 목업 모드.
MOCK_MODE: bool = not (CLAUDE_API_KEY and EMBEDDING_API_KEY)

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
CHROMA_DIR = DATA_DIR / "chroma"
SQLITE_PATH = DATA_DIR / "app.sqlite3"
# LLM OCR은 같은 PDF에도 매번 다른 텍스트를 내놓는다. 결과를 남겨 재색인 시 재사용한다.
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
# 위 값이 공개 상수로 떨어졌는지. 그 상태로 서명을 만들면 누구나 계산할 수 있어
# 서명이 필요한 기능(피드백)은 끈다 — 관리자 API의 fail-closed와 같은 원칙.
SIGNING_KEY_IS_PUBLIC: bool = not (os.getenv("IP_HASH_SALT") or ADMIN_TOKEN)

# 토큰 단가는 app/pricing.py (모델별·적용일별 공식 정가)

# 운영 지표·방문·분석 기록 보존 기간(일). 지나면 기동 시 삭제한다.
RETENTION_DAYS: int = int(os.getenv("RETENTION_DAYS", "365"))
# 동시에 LLM 파이프라인을 돌리는 요청 상한. 한도는 완료된 요청만 세므로,
# 응답이 끝나기 전에 몰려오는 요청을 여기서 막는다 (비용 폭주 방지).
MAX_INFLIGHT_TOTAL: int = int(os.getenv("MAX_INFLIGHT_TOTAL", "5"))

CORS_ORIGINS: list[str] = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
]

for _dir in (DATA_DIR, UPLOAD_DIR, CHROMA_DIR, OCR_CACHE_DIR):
    _dir.mkdir(parents=True, exist_ok=True)
