"""기획 도우미 흐름: 사업 개요 → 초안(LLM 1회) → 서버 계산 → 문서 검토 계산 검사.

LLM이 막히거나 목업이면 규칙 기반 뼈대를 준다 — 사용자가 결과 화면에서 항목을 채우면 된다.
규정 메모는 화면이 문서 검토의 /api/review/notes를 따로 부른다(같은 한도·같은 근거 검증).
"""

from dataclasses import dataclass

from app.config import MOCK_MODE
from app.plan import prompts
from app.plan.build import assemble, render_text, to_blocks, to_budget_doc, to_text
from app.plan.models import DraftLine, DraftStep, PlanDraft, PlanEdit, PlanIn, PlanOut, SuggestIn, Suggestion
from app.privacy import mask_obj, mask_text
from app.review.models import BudgetDoc, Finding
from app.review.rules import check_budget
from app.review.service import Usage, merge
from app.review.textcheck import check_text

DRAFT_TIMEOUT = 60


@dataclass
class Result:
    plan: PlanOut
    doc: BudgetDoc
    text: str
    findings: list[Finding]
    blocks: list[dict]  # 문서 구조 (화면이 Word 파일을 만든다)


def _period(req: PlanIn) -> str:
    return req.start.isoformat() + (f" ~ {req.end.isoformat()}" if req.end else "")


def _per_head(req: PlanIn) -> str:
    """모델이 합계를 잘 맞추지 못해(상한 초과 → 재작성 20초) 1인당 쓸 수 있는 돈을 미리 셈해 준다."""
    if not (req.spend_limit and req.headcount):
        return ""
    return f" (1인당 약 {req.spend_limit * 9 // 10 // req.headcount:,}원)"


def rule_draft(req: PlanIn) -> PlanDraft:
    """LLM 없이 만드는 뼈대. 지출은 인원이 있으면 1인당 항목 한 줄만 두고 단가는 비워 둔다."""
    steps = [
        DraftStep(phase="준비", text="사업 계획·예산 인준", days_before=14),
        DraftStep(phase="준비", text="홍보 게시물 올리기·신청 받기", days_before=10),
        DraftStep(phase="준비", text="신청자 대상 여부 확인·물품 구매", days_before=3),
        DraftStep(phase="진행", text=f"{req.title} 진행", days_before=0),
        DraftStep(phase="마무리", text="영수증·지급 확인서·수령 명단 정리", days_before=-3),
        DraftStep(phase="마무리", text="결과 공유·정산", days_before=-7),
    ]
    lines = [DraftLine(item="1인당 물품", unit_price=0, qty=req.headcount, unit="명", basis="")] if req.headcount else []
    return PlanDraft(
        intent=req.purpose,
        steps=steps,
        expected=["참여 학우의 만족도 향상"],
        lines=lines,
        reserve_rate=0,
        cautions=[],
    )


CAP_BASIS = "사업안 예산은 인준받은 총예산을 넘을 수 없음 (총대의원회 사업자료 작성 안내)"


def masked(req: PlanIn) -> PlanIn:
    """모델에 보내기 전에 사용자가 적은 칸의 전화·계좌·이메일·등록 실명을 지운다."""
    fields = ("title", "org", "purpose", "target", "place", "activities", "meeting")
    return req.model_copy(update={f: mask_text(getattr(req, f)) for f in fields})


def _cap_finding(plan: PlanOut) -> list[Finding]:
    if not plan.over_cap:
        return []
    return [Finding(
        code="plan_cap", level="보완 필요", title="지출이 예산 상한을 넘어요",
        detail=f"상한 {plan.request.spend_limit:,}원"
        + (f"(참가비 {plan.request.fee_income:,}원 포함)" if plan.request.fee_income else "")
        + f"보다 {plan.over_cap:,}원 많아요. 수량·단가를 줄이거나 상한을 다시 확인해 주세요.",
        basis=CAP_BASIS, where="예산운영 계획서",
    )]


def _result(plan: PlanOut) -> Result:
    """초안·고친 안 모두 같은 길: 본문 검사(현금·계좌·민감정보 등, 마스킹 전) + 예산 계산 검사 + 상한.

    돌려주는 기획안·본문은 마스킹한 것이다 — 고친 안에 사용자가 연락처를 적어도 인쇄본에 남지 않는다.
    """
    source = check_text(to_text(plan))  # 발견 위치(where)는 검사기가 마스킹해 둔다
    plan = PlanOut.model_validate(mask_obj(plan.model_dump()))
    doc = to_budget_doc(plan)
    blocks = to_blocks(plan)
    return Result(plan, doc, render_text(blocks), merge([*source, *check_budget(doc), *_cap_finding(plan)]), blocks)


async def draft(req: PlanIn, usage: Usage | None = None) -> tuple[Result, Usage]:
    usage = usage if usage is not None else Usage()
    req = masked(req)
    if MOCK_MODE:
        return _result(assemble(req, rule_draft(req), "rule")), usage
    from app.agents import claude_agents

    user = prompts.USER.format(
        title=req.title, org=req.org, purpose=req.purpose, target=req.target,
        headcount=req.headcount or "미정", period=_period(req), place=req.place, fund=req.fund,
        cap=f"{req.budget_cap:,}원" if req.budget_cap else "없음", per_head=_per_head(req), activities=req.activities or "(적지 않음)",
        fee=f"1인 {req.fee:,}원 × {req.headcount}명 = {req.fee_income:,}원 ("
        + ("예산 상한에 더해 쓸 수 있는 수입)" if req.budget_cap else "사업 수입)") if req.fee_income else "없음",
    )
    try:
        out = await claude_agents.structured(prompts.SYSTEM, user, PlanDraft, max_tokens=4000, on_usage=usage.add, timeout=DRAFT_TIMEOUT)
        plan = assemble(req, out, "ai")
        if plan.over_cap:
            # 모델은 합계를 셈하지 못해 상한을 넘기곤 한다(2026-11-28 체육대회 예시 70만 원 초과) — 넘은 만큼 알려 주고 한 번만 다시
            cap_note = f"(예산 상한 {req.budget_cap:,}원 + 참가비 {req.fee_income:,}원)" if req.fee_income else ""
            retry = user + prompts.OVER_CAP.format(total=plan.expense_total, cap=req.spend_limit, cap_note=cap_note, over=plan.over_cap)
            try:
                out2 = await claude_agents.structured(prompts.SYSTEM, retry, PlanDraft, max_tokens=4000, on_usage=usage.add, timeout=DRAFT_TIMEOUT)
                plan2 = assemble(req, out2, "ai")
                if plan2.over_cap < plan.over_cap:
                    plan = plan2
            except Exception as e:  # noqa: BLE001 - 재작성이 막혀도 첫 초안(상한 초과 표시)을 그대로 준다
                print(f"기획 초안 재작성 실패, 첫 초안 유지: {type(e).__name__}: {e}")
        return _result(plan), usage
    except Exception as e:  # noqa: BLE001 - 초안 실패는 규칙 기반 뼈대로 이어 간다
        print(f"기획 초안 실패, 규칙 기반으로 진행: {type(e).__name__}: {e}")
        return _result(assemble(req, rule_draft(req), "rule")), usage


def rebuild(edit: PlanEdit) -> Result:
    """화면에서 고친 기획안을 다시 계산·점검 (LLM 없음)."""
    return _result(assemble(edit.request, edit, edit.method))


SUGGEST_TIMEOUT = 30
SUGGEST_LABEL = {"purpose": "목적", "activities": "주요 활동"}


def rule_suggest(req: SuggestIn) -> str:
    """목업 모드의 뼈대 — 사용자가 고쳐 쓰기 쉬운 자리 표시 문장."""
    if req.field == "purpose":
        who = req.target or "학우"
        return f"{who}가 함께하는 {req.title}을(를) 열어 학생회 활동에 대한 관심과 참여를 높이고자 합니다."
    return "\n".join(["홍보 게시물 올리기", "신청 받기·대상 확인", "물품 준비", "행사 진행", "수령 확인·결과 공유"])


async def suggest(req: SuggestIn, usage: Usage | None = None) -> str:
    """기획 개요 칸 하나(목적·주요 활동)를 채운다. 입력·출력 모두 마스킹한다."""
    usage = usage if usage is not None else Usage()
    fields = ("title", "org", "purpose", "target", "place", "activities")
    req = req.model_copy(update={f: mask_text(getattr(req, f)) for f in fields})
    if MOCK_MODE:
        return rule_suggest(req)
    from app.agents import claude_agents

    user = prompts.SUGGEST_USER.format(
        title=req.title, org=req.org or "(적지 않음)", target=req.target or "(적지 않음)", headcount=req.headcount or "미정",
        place=req.place or "(적지 않음)", fund=req.fund, cap=f"{req.budget_cap:,}원" if req.budget_cap else "없음",
        fee=f"1인 {req.fee:,}원" if req.fee else "없음", purpose=req.purpose or "(비어 있음)",
        activities=req.activities or "(비어 있음)", label=SUGGEST_LABEL[req.field],
    )
    out = await claude_agents.structured(prompts.SUGGEST_SYSTEM, user, Suggestion, max_tokens=800, on_usage=usage.add, timeout=SUGGEST_TIMEOUT)
    limit = 400 if req.field == "purpose" else 1200  # 칸 길이 제한(PlanIn)과 같게
    return mask_text(out.text.strip())[:limit]
