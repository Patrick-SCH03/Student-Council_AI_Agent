"""앱 전역 설정. .env를 로드하고, API 키가 없으면 목업 모드로 동작한다."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY: str | None = (
    os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or None
)
# 릴리스 태그(v2.7.0)와 같이 올린다. /api/health로 배포본이 어떤 버전인지 확인한다.
APP_VERSION = "2.11.0"

GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
# 라우터는 분류 + 한 문장 재작성만 하므로 경량 모델을 쓴다.
# flash-lite는 공식 문서가 classification·routing 용례로 명시하는 티어로,
# 단가가 본 모델의 1/3 수준이고 첫 토큰 지연도 가장 짧다.
GEMINI_ROUTER_MODEL: str = os.getenv("GEMINI_ROUTER_MODEL", "gemini-3.5-flash-lite")
GEMINI_EMBEDDING_MODEL: str = os.getenv(
    "GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-2"
)
# 규정 검토·감사 분석의 사고 수준 (low/medium/high). 비우면 모델 기본값.
# 사고 토큰은 첫 응답 전에 만들어져 지연의 주원인이라, 속도·품질 A/B를 코드 수정 없이 돌린다.
AGENT_THINKING: str | None = os.getenv("AGENT_THINKING") or None

# 규정 검토·감사 분석·종합 조정을 돌릴 모델 공급자 (gemini | claude). 라우터·임베딩은 항상 Gemini.
# claude로 켜도 Claude 호출이 실패하면 그 단계만 Gemini로 돌아간다 (가용성 우선).
AGENT_PROVIDER: str = (os.getenv("AGENT_PROVIDER") or "gemini").strip().lower()
CLAUDE_API_KEY: str | None = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or None
CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")
# effort는 사고 깊이·출력량을 함께 정한다. 2026-10-13 A/B에서 low가 지연 목표에 맞았다.
CLAUDE_EFFORT: str = os.getenv("CLAUDE_EFFORT", "low")
# Claude 호출 타임아웃(초). Haiku·low는 단계당 5~10초라 30초면 충분하다. 더 큰 모델이나 높은 effort로
# 바꾸면 함께 올린다 — 낮으면 매번 타임아웃 → 재시도 → Gemini 폴백으로 비용만 겹친다.
CLAUDE_TIMEOUT: float = float(os.getenv("CLAUDE_TIMEOUT") or (30 if CLAUDE_EFFORT == "low" else 90))
if AGENT_PROVIDER not in ("gemini", "claude"):
    print(f"AGENT_PROVIDER={AGENT_PROVIDER!r}는 알 수 없는 값이라 gemini로 동작한다")
    AGENT_PROVIDER = "gemini"
if AGENT_PROVIDER == "claude" and not CLAUDE_API_KEY:
    # 켠 줄 알았는데 매 요청이 조용히 Gemini로 폴백하면 결과·비용을 잘못 읽는다
    print("AGENT_PROVIDER=claude인데 CLAUDE_API_KEY가 없어 gemini로 동작한다")
    AGENT_PROVIDER = "gemini"
# 규정 검토·감사 분석·종합 조정이 실제로 쓰는 모델 (/api/health·대시보드 표시용)
AGENT_MODEL: str = CLAUDE_MODEL if AGENT_PROVIDER == "claude" else GEMINI_MODEL

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
# 위 값이 공개 상수로 떨어졌는지. 그 상태로 서명을 만들면 누구나 계산할 수 있어
# 서명이 필요한 기능(피드백)은 끈다 — 관리자 API의 fail-closed와 같은 원칙.
SIGNING_KEY_IS_PUBLIC: bool = not (os.getenv("IP_HASH_SALT") or ADMIN_TOKEN)

# 비용 추정 단가 (USD / 1M 토큰).
# gemini-3.7-flash 도입 할인가로, 2027-01-01부터 1.50 / 7.50으로 환원된다.
PRICE_INPUT_PER_1M: float = float(os.getenv("PRICE_INPUT_PER_1M", "0.75"))
PRICE_OUTPUT_PER_1M: float = float(os.getenv("PRICE_OUTPUT_PER_1M", "3.75"))
# Claude 단가 (USD / 1M 토큰, Anthropic 1st-party 정가). Haiku 5.5는 프롬프트 100K 토큰 이하 기준.
_CLAUDE_PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
CLAUDE_PRICE_INPUT_PER_1M: float = float(
    os.getenv("CLAUDE_PRICE_INPUT_PER_1M", _CLAUDE_PRICES.get(CLAUDE_MODEL, (4.00, 20.00))[0])
)
CLAUDE_PRICE_OUTPUT_PER_1M: float = float(
    os.getenv("CLAUDE_PRICE_OUTPUT_PER_1M", _CLAUDE_PRICES.get(CLAUDE_MODEL, (4.00, 20.00))[1])
)
USD_KRW: float = float(os.getenv("USD_KRW", "1400"))

# 운영 지표·방문·분석 기록 보존 기간(일). 지나면 기동 시 삭제한다.
RETENTION_DAYS: int = int(os.getenv("RETENTION_DAYS", "365"))
# 동시에 LLM 파이프라인을 돌리는 요청 상한. 한도는 완료된 요청만 세므로,
# 응답이 끝나기 전에 몰려오는 요청을 여기서 막는다 (비용 폭주 방지).
MAX_INFLIGHT_TOTAL: int = int(os.getenv("MAX_INFLIGHT_TOTAL", "5"))
# LLM 호출 타임아웃(초). 상류가 느려져도 요청이 무기한 붙잡히지 않도록.
LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "60"))

CORS_ORIGINS: list[str] = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
]

for _dir in (DATA_DIR, UPLOAD_DIR, CHROMA_DIR, OCR_CACHE_DIR):
    _dir.mkdir(parents=True, exist_ok=True)
