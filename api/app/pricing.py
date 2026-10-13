"""모델별 토큰 단가와 요청 비용 계산 (USD).

단가는 공식 가격표의 표준(유료) 등급 정가다. 2026-10-14 확인:
- Gemini: https://ai.google.dev/gemini-api/docs/pricing
- Claude: https://platform.claude.com/docs/en/about-claude/pricing

한 단가로 모든 호출을 매기면 틀린다. 질문 분류(Flash-Lite)는 분석 모델(Flash)보다 싸고,
Gemini가 암묵적 캐시로 읽은 입력 토큰은 정가의 10%만 청구된다. 그래서 호출마다 모델과
캐시 적중 토큰을 따로 받아 계산한다. 가격이 바뀌면 이 표에 시작일과 함께 한 줄을 더한다.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

# 모델 → [(적용 시작일, 입력, 출력, 캐시 적중 입력)] (USD / 1M 토큰, 시작일 오름차순).
# 출력 단가는 사고(thinking) 토큰을 포함한다 — 두 공급자 모두 사고 토큰을 출력으로 청구한다.
_FLASH = [
    # 3.x Flash 도입 할인가. 2027-01-01부터 두 배로 환원된다.
    (date(2000, 1, 1), 0.75, 3.75, 0.075),
    (date(2027, 1, 1), 1.50, 7.50, 0.15),
]
PRICES: dict[str, list[tuple[date, float, float, float]]] = {
    # gemini-3.7-flash는 가격표에서 빠졌지만 계속 호출된다. 같은 세대(3.6·3.8 Flash)와 같은 값으로 둔다.
    "gemini-3.7-flash": _FLASH,
    "gemini-3.6-flash": _FLASH,
    "gemini-3.8-flash": _FLASH,
    "gemini-3.5-flash-lite": [(date(2000, 1, 1), 0.30, 2.50, 0.03)],
    # Haiku 5.5는 프롬프트 100K 토큰 이하 단가 (이 서비스 프롬프트는 ~25K 이하)
    "claude-haiku-5-5": [(date(2000, 1, 1), 0.10, 0.50, 0.01)],
    "claude-sonnet-5-5": [(date(2000, 1, 1), 2.00, 10.00, 0.10)],
    "claude-opus-5-5": [(date(2000, 1, 1), 4.00, 20.00, 0.20)],
}
# 표에 없는 모델은 아는 모델 중 가장 비싼 단가로 매긴다 — 비용 한도 판단에서 과소 추정이 더 위험하다
_UNKNOWN = "claude-opus-5-5"
_warned: set[str] = set()


def _normalize(model: str) -> str:
    return model.removeprefix("models/").strip().lower()


def rates(model: str, on: date | None = None) -> tuple[float, float, float]:
    """(입력, 출력, 캐시 적중 입력) 단가."""
    key = _normalize(model)
    if key not in PRICES:
        if key not in _warned:
            _warned.add(key)
            print(f"단가표에 없는 모델 {model!r} — {_UNKNOWN} 단가로 비용을 매긴다 (app/pricing.py에 추가)")
        key = _UNKNOWN
    day = on or datetime.now(timezone.utc).date()
    current = PRICES[key][0]
    for row in PRICES[key]:
        if row[0] <= day:
            current = row
    return current[1], current[2], current[3]


def cost_usd(model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0,
             on: date | None = None) -> float:
    """한 호출의 비용. input_tokens는 캐시 적중분을 포함한 전체 입력 토큰이다."""
    price_in, price_out, price_cached = rates(model, on)
    cached = min(max(cached_tokens, 0), input_tokens)
    return (
        (input_tokens - cached) * price_in + cached * price_cached + output_tokens * price_out
    ) / 1_000_000


def langchain_usage_cost(usage_by_model: dict, on: date | None = None) -> float:
    """UsageMetadataCallbackHandler.usage_metadata ({모델: 사용량}) 전체 비용."""
    total = 0.0
    for model, u in (usage_by_model or {}).items():
        cached = (u.get("input_token_details") or {}).get("cache_read", 0) or 0
        total += cost_usd(model, u.get("input_tokens", 0), u.get("output_tokens", 0), cached, on)
    return total
