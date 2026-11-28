"""회의록 정리 API (학교 계정 로그인 필요). POST /api/minutes — 회의 메모 → 회의록 서식·결정사항·할 일 (LLM 1회).

입력·결과는 저장하지 않는다. 지표에는 경로·시간·비용만 남긴다.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app import contrib
from app.auth import current_user, origin_guard
from app.minutes import service
from app.minutes.service import MAX_CHARS, Minutes
from app.quota import llm_slots, metered

router = APIRouter(prefix="/api/minutes", dependencies=[Depends(origin_guard)])  # 읽기 외 요청은 Origin 검사 (CSRF)

DAILY_LIMIT = 20
ROUTE = "review-minutes"  # 'review-' 접두어: 규정 질문 한도 집계에서 빠진다 (app/quota.py)
LIMIT_MESSAGE = "오늘 회의록 정리 한도를 다 썼어요. 내일 다시 이용해 주세요."


class MinutesIn(BaseModel):
    text: str = Field(min_length=20, max_length=MAX_CHARS)
    held_on: date | None = None


class MinutesOut(BaseModel):
    minutes: Minutes
    text: str
    method: str


@router.post("", response_model=MinutesOut)
async def organize(body: MinutesIn, contribute: bool = Query(False), user: dict = Depends(current_user)) -> MinutesOut:
    async with metered(user, ROUTE, DAILY_LIMIT, LIMIT_MESSAGE) as usage, llm_slots:
        minutes, method, _ = await service.organize(body.text, body.held_on, usage)
    if contribute:
        contrib.save(user["id"], "minutes", "회의록", body.text, {"method": method, "minutes": minutes.model_dump(mode="json")})
    return MinutesOut(minutes=minutes, text=service.to_text(minutes), method=method)
