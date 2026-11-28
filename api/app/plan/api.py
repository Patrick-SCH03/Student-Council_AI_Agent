"""기획 도우미 API (학교 계정 로그인 필요).

POST /api/plan/draft    사업 개요 → 초안 + 계산 점검 (LLM 1회, 하루 한도)
POST /api/plan/rebuild  고친 기획안 → 다시 계산·점검 (LLM 없음)
POST /api/plan/suggest  개요 칸 하나(목적·주요 활동) AI 초안 (LLM 1회, 하루 한도)
규정 메모는 화면이 /api/review/notes 를 부른다 — 메모가 실패해도 초안은 남는다.

입력·초안은 저장하지 않는다. 지표에는 경로·시간·비용만 남긴다.
"""


from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import contrib
from app.auth import current_user, origin_guard
from app.plan import service
from app.plan.models import PlanEdit, PlanIn, PlanOut, SuggestIn
from app.quota import llm_slots, metered
from app.review.models import BudgetDoc, Finding

router = APIRouter(prefix="/api/plan", dependencies=[Depends(origin_guard)])  # 읽기 외 요청은 Origin 검사 (CSRF)

DAILY_LIMIT = 20
ROUTE = "review-plan"  # 'review-' 접두어: 규정 질문 한도 집계에서 빠진다 (app/quota.py)
LIMIT_MESSAGE = "오늘 기획 초안 한도를 다 썼어요. 내일 다시 이용해 주세요."
SUGGEST_LIMIT = 40
SUGGEST_ROUTE = "review-plan-suggest"
SUGGEST_MESSAGE = "오늘 AI 초안 한도를 다 썼어요. 내일 다시 이용해 주세요."


class PlanResult(BaseModel):
    plan: PlanOut
    doc: BudgetDoc
    text: str
    findings: list[Finding]
    blocks: list[dict]


def _out(result: service.Result) -> PlanResult:
    return PlanResult(plan=result.plan, doc=result.doc, text=result.text, findings=result.findings, blocks=result.blocks)


@router.post("/draft", response_model=PlanResult)
async def draft(body: PlanIn, contribute: bool = Query(False), user: dict = Depends(current_user)) -> PlanResult:
    async with metered(user, ROUTE, DAILY_LIMIT, LIMIT_MESSAGE) as usage, llm_slots:
        result, _ = await service.draft(body, usage)
    if contribute:
        contrib.save(user["id"], "plan", body.title, body.model_dump_json(), {"plan": result.plan.model_dump(mode="json"), "findings": [f.model_dump() for f in result.findings]})
    return _out(result)


@router.post("/rebuild", response_model=PlanResult)
def rebuild(body: PlanEdit, user: dict = Depends(current_user)) -> PlanResult:
    return _out(service.rebuild(body))


class SuggestOut(BaseModel):
    text: str


@router.post("/suggest", response_model=SuggestOut)
async def suggest(body: SuggestIn, user: dict = Depends(current_user)) -> SuggestOut:
    try:
        async with metered(user, SUGGEST_ROUTE, SUGGEST_LIMIT, SUGGEST_MESSAGE) as usage, llm_slots:
            return SuggestOut(text=await service.suggest(body, usage))
    except HTTPException:
        raise  # 한도 초과 등은 그대로
    except Exception as e:  # noqa: BLE001 - 모델 오류·시간 초과는 지표에 남기고(metered) 다시 시도 안내
        print(f"기획 AI 초안 실패: {type(e).__name__}: {e}")
        raise HTTPException(status_code=503, detail="AI 초안을 만들지 못했어요. 잠시 뒤 다시 시도해 주세요.") from e
