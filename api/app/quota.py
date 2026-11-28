"""로그인 업무 도구(문서 검토·기획 도우미)의 유료 호출 한도와 지표.

지표 route는 'review-'로 시작한다 — db의 규정 질문 한도 집계(_NOT_REVIEW)가 이 접두어로 업무 도구 호출을 뺀다.
"""

import asyncio
import time
from collections import Counter
from contextlib import asynccontextmanager, contextmanager

from fastapi import HTTPException

from app import db
from app.review.service import Usage

llm_slots = asyncio.Semaphore(3)  # 업무 도구 LLM 동시 실행 상한 (규정 질문 한도와 별도)
# 끝나지 않은 요청 수 — 지표는 끝난 요청만 세므로, 동시에 여러 번 보내 한도를 넘는 것을 막는다
_inflight: Counter = Counter()


def user_key(user: dict) -> str:
    return f"user:{user['id']}"


@contextmanager
def reserve(user: dict, route: str, limit: int, message: str = "오늘 사용 한도를 다 썼어요. 내일 다시 이용해 주세요."):
    """유료 호출마다 사용자별 하루 한도를 건다. 진행 중 요청도 함께 센다. 관리자는 점검용으로 뺀다.

    확인과 예약 사이에 await가 없어(이벤트 루프 한 번에 실행) 동시 요청이 같은 자리를 차지하지 못한다.
    """
    key = (user_key(user), route)
    if user["role"] != "admin" and db.count_review_today(key[0], route) + _inflight[key] >= limit:
        raise HTTPException(status_code=429, detail=message)
    _inflight[key] += 1
    try:
        yield
    finally:
        _inflight[key] -= 1
        if _inflight[key] <= 0:
            del _inflight[key]


@asynccontextmanager
async def metered(user: dict, route: str, limit: int, message: str, free: tuple[type[BaseException], ...] = ()):
    """유료 업무 도구 호출 한 번: 하루 한도 예약 → 끝나면 성공·실패 모두 지표에 남긴다. LLM 자리(llm_slots)는 호출 쪽이 잡는다.

    넘겨준 Usage에 서비스가 사용량을 채운다 — 실패해도 그때까지 쓴 비용이 기록되어 한도에서 빠지지 않는다.
    free에 든 오류(예: 지원하지 않는 파일·너무 큰 파일)는 유료 호출 전에 난 것이라 기록하지 않는다.
    """
    with reserve(user, route, limit, message):
        started = time.monotonic()
        usage = Usage()
        error = None
        try:
            yield usage
        except free:
            started = None
            raise
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            raise
        finally:
            if started is not None:
                record(route, user, started, usage, error)


def record(route: str, user: dict, started: float, usage: Usage, error: str | None = None) -> None:
    """지표에는 경로·시간·비용만 남긴다 (입력 내용은 남기지 않음)."""
    db.record_metric(
        route=route, risk_level=None, status="error" if error else "ok", elapsed=time.monotonic() - started,
        input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, query_preview="",
        visitor_id=user_key(user), is_admin=user["role"] == "admin", error=error,
        cost_usd=round(usage.cost_usd, 6),
    )
