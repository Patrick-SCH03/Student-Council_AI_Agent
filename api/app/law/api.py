"""법령 점검표 '더 물어보기' API (학교 계정 로그인 필요 — 유료 호출이라 하루 한도를 둔다).

POST /api/law/ask  질문(+점검표 주제, 직전 대화 3턴까지) → 답·근거 조문(법제처 원문 대조). 질문·답은 저장하지 않는다.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.auth import current_user, origin_guard
from app.law import service
from app.quota import metered

router = APIRouter(prefix="/api/law", dependencies=[Depends(origin_guard)])  # 읽기 외 요청은 Origin 검사 (CSRF)

DAILY_LIMIT = 20
ROUTE = "review-law-ask"  # 'review-' 접두어: 규정 질문 한도 집계에서 빠진다 (app/quota.py)
LIMIT_MESSAGE = "오늘 법령 질문 한도를 다 썼어요. 내일 다시 이용해 주세요."
# 법령 질문은 도구를 여러 번 불러 길다(20~60초) — 공용 자리(llm_slots)를 잡지 않고 따로 둬서 문서 검토·기획을 막지 않는다
law_slots = asyncio.Semaphore(2)


@router.post("/ask", response_model=service.AskOut)
async def ask(body: service.AskIn, user: dict = Depends(current_user)) -> service.AskOut:
    try:
        async with metered(user, ROUTE, DAILY_LIMIT, LIMIT_MESSAGE) as usage, law_slots:
            return await service.ask(body, usage)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - 모델·법령 도구 오류는 지표에 남기고(metered) 다시 시도 안내
        print(f"법령 질문 실패: {type(e).__name__}: {e}")
        raise HTTPException(status_code=503, detail="법령을 찾지 못했어요. 잠시 뒤 다시 시도해 주세요.") from e
