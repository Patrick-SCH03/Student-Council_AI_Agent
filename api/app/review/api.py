"""문서 검토 API (학교 계정 로그인 필요).

POST /api/review/extract?filename=…  본문 = 파일 바이트 → 예산 구조(확인용) + 원문 검사 결과
POST /api/review/check               확인·수정한 예산 구조 → 점검 사항 (계산, 즉시)
POST /api/review/notes               → 규정 메모 (LLM, 수 초)

파일·결과는 저장하지 않는다. 지표에는 경로·시간·비용만 남긴다(파일 이름·내용은 남기지 않음).
예외: 이용자가 '개선에 쓰도록 허락'(contribute=true)을 고르면 가명 처리한 본문·결과를 보관한다 (app/contrib.py).
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app import contrib
from app.auth import current_user, origin_guard
from app.config import MOCK_MODE
from app.privacy import mask_text
from app.quota import llm_slots, metered
from app.review import service
from app.review.extract import MAX_BYTES, UnsupportedFile
from app.review.models import BudgetDoc, Finding

TOO_BIG = "파일이 너무 커요. 15MB 이하로 올려 주세요."

router = APIRouter(prefix="/api/review", dependencies=[Depends(origin_guard)])  # 읽기 외 요청은 Origin 검사 (CSRF)

DAILY_LIMIT = 30  # 사용자당 하루 추출 횟수 (메모는 추출마다 한 번 + 다시 보기 여유로 두 배)
LIMIT_MESSAGE = "오늘 문서 검토 한도를 다 썼어요. 내일 다시 이용해 주세요."


class ExtractOut(BaseModel):
    doc: BudgetDoc
    method: str
    kind: str
    pages: int
    text: str  # 마스킹한 원문 (메모 단계에 다시 보낸다 — 서버는 저장하지 않으므로)
    source: list[Finding]
    contribution_id: int | None = None  # 개선에 쓰도록 허락한 경우 — 확인 표에서 고친 값을 여기에 붙인다


@router.post("/extract", response_model=ExtractOut)
async def extract(
    request: Request,
    filename: str = Query(min_length=1, max_length=200),
    contribute: bool = Query(False),
    user: dict = Depends(current_user),
) -> ExtractOut:
    if int(request.headers.get("content-length") or 0) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=TOO_BIG)
    try:
        async with metered(user, "review-extract", DAILY_LIMIT, LIMIT_MESSAGE, free=(UnsupportedFile, HTTPException)) as usage:
            data = await request.body()
            if len(data) > MAX_BYTES:
                raise HTTPException(status_code=413, detail=TOO_BIG)
            async with llm_slots:
                result = await service.extract(filename, data, usage)
    except UnsupportedFile as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    source = await asyncio.to_thread(service.source_findings, result.file)  # 긴 글 검사가 다른 요청을 막지 않게
    cid = None
    if contribute:
        cid = contrib.save(
            user["id"], "review", filename, result.file.text,
            {"kind": result.file.kind, "method": result.method, "doc": result.doc.model_dump(), "source": [f.model_dump() for f in source]},
        )
    return ExtractOut(
        doc=result.doc,
        method=result.method,
        kind=result.file.kind,
        pages=result.file.pages,
        text=mask_text(result.file.text),
        source=source,
        contribution_id=cid,
    )


class CheckIn(BaseModel):
    doc: BudgetDoc
    source: list[Finding] = Field(default_factory=list, max_length=200)
    contribution_id: int | None = None


@router.post("/check")
def check(body: CheckIn, user: dict = Depends(current_user)) -> dict:
    findings = service.check(body.doc, body.source)
    if body.contribution_id:
        # 이용자가 확인·수정한 값이 추출의 정답이다 — 본인 자료에만 붙는다
        contrib.attach_correction(user["id"], body.contribution_id, {"doc": body.doc.model_dump(), "findings": [f.model_dump() for f in findings]})
    return {"findings": findings}


class NotesIn(BaseModel):
    doc: BudgetDoc
    text: str = Field(max_length=80_000)
    findings: list[Finding] = Field(default_factory=list, max_length=200)


@router.post("/notes")
async def notes(body: NotesIn, user: dict = Depends(current_user)) -> dict:
    try:
        async with metered(user, "review-notes", DAILY_LIMIT * 2, LIMIT_MESSAGE) as usage, llm_slots:
            found, _ = await service.notes(body.doc, body.text, body.findings, usage)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - 메모가 실패해도 계산 검사 결과는 화면에 남는다
        raise HTTPException(status_code=502, detail="규정 메모를 만들지 못했어요. 계산 검사 결과는 그대로 볼 수 있어요.") from e
    return {"notes": found, "mock": MOCK_MODE}
