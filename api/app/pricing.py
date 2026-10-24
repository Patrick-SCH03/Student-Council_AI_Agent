"""모델별 토큰 단가와 요청 비용 계산 (USD).

단가는 Claude 공식 가격표의 표준 정가다 (2026-10-14 확인):
https://platform.claude.com/docs/en/about-claude/pricing

호출마다 모델과 캐시 적중 토큰을 따로 받아 계산한다. 가격이 바뀌면 이 표에 시작일과 함께
한 줄을 더한다. 검색 임베딩(Voyage)은 계정 무료 토큰 안에서 쓰여 요청 비용에 넣지 않는다.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

# 모델 → [(적용 시작일, 입력, 출력, 캐시 적중 입력)] (USD / 1M 토큰, 시작일 오름차순).
# 출력 단가는 사고(thinking) 토큰을 포함한다.
PRICES: dict[str, list[tuple[date, float, float, float]]] = {
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


def _lookup(key: str) -> str | None:
    """정확히 같은 이름, 없으면 가장 긴 접두사가 맞는 이름 (날짜·버전 접미사가 붙은 모델 ID 대응)."""
    if key in PRICES:
        return key
    matches = [k for k in PRICES if key.startswith(k)]
    return max(matches, key=len) if matches else None


def rates(model: str, on: date | None = None) -> tuple[float, float, float]:
    """(입력, 출력, 캐시 적중 입력) 단가."""
    raw = _normalize(model)
    key = _lookup(raw)
    if key is None:
        if raw not in _warned:
            _warned.add(raw)
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
