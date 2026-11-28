"""기획 도우미 데이터 모양.

PlanDraft는 LLM 구조화 출력 스키마다 — 금액 합계·예비비·날짜는 LLM이 정하지 않는다. 단가·수량과 '시작 며칠 전'만 받고
서버가 계산한다(계산 실수·날짜 지어내기 방지). 중첩 객체를 한 단계로만 둔다(깊으면 'Schema is too complex').
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

# 재정·회계 세칙의 재원 구분: 학생회비·교비지원금(제7조), 기금(제6조·제40조~). 참가비는 재원이 아니라 일회성 사업 수입으로
# 지출에서 상계한다(제27조 제1항). 과자치비는 전공 학생회의 학생회비다(제12조 제3항).
FUNDS = ("학생회비", "교비지원금", "기금")
MAX_LINES = 20  # 지출 줄 상한 — 화면(web/src/lib/plan-model.ts MAX_LINES)과 같게. 넘으면 자르지 않고 거부한다


class PlanIn(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    org: str = Field(default="", max_length=40)
    purpose: str = Field(min_length=1, max_length=400)
    target: str = Field(default="", max_length=80)
    headcount: int | None = Field(default=None, ge=1, le=5000)
    start: date
    end: date | None = None
    place: str = Field(default="", max_length=60)
    fund: Literal[FUNDS] = "학생회비"  # type: ignore[valid-type]
    budget_cap: int | None = Field(default=None, ge=0, le=100_000_000)
    fee: int | None = Field(default=None, ge=0, le=1_000_000)  # 참가비 1인 금액 — 예상 인원만큼 걷는다 (MT·총회처럼 갹출하는 사업)
    activities: str = Field(default="", max_length=1200)
    meeting: str = Field(default="", max_length=60)
    meeting_date: date | None = None
    term: str = Field(default="", max_length=20)  # '제43대' — Word 표지 명의에만 쓴다

    @property
    def fee_income(self) -> int:
        """참가비 수입 = 1인 참가비 × 예상 인원. 인원이 없으면 셀 수 없어 0."""
        return (self.fee or 0) * (self.headcount or 0)

    @property
    def spend_limit(self) -> int | None:
        """쓸 수 있는 돈 = 예산 상한(학생회 재원) + 참가비 수입. 상한이 없으면 None."""
        return self.budget_cap + self.fee_income if self.budget_cap else None

    @model_validator(mode="after")
    def _dates(self) -> "PlanIn":
        if self.end and self.end < self.start:
            raise ValueError("끝나는 날이 시작일보다 빨라요")
        if self.fee and not self.headcount:
            raise ValueError("참가비를 적으면 예상 인원도 적어 주세요")  # 인원이 없으면 참가비 수입을 셀 수 없어 조용히 빠졌다
        return self


class DraftLine(BaseModel):
    item: str = Field(description="지출 항목 이름 (예: 간식 기프티콘)")
    unit_price: int = Field(description="단가(원). 시중 가격을 보수적으로 어림한 정수")
    qty: int = Field(description="수량")
    unit: str = Field(default="개", description="수량 단위 (개·명·회·대·장·박)")
    basis: str = Field(default="", description="산출 근거 한 줄 (예: 1인 1개, 참가자 50명 기준)")


class DraftStep(BaseModel):
    phase: Literal["준비", "진행", "마무리"]
    text: str = Field(description="할 일 한 줄")
    days_before: int = Field(description="사업 시작일보다 며칠 전에 할 일인지. 진행 당일 0, 끝난 뒤는 음수(-3 = 끝난 지 3일 뒤)")


class PlanDraft(BaseModel):
    intent: str = Field(description="기획 의도 2~3문장")
    steps: list[DraftStep] = Field(description="사업 내용: 준비·진행·마무리 순서, 6~12줄")
    expected: list[str] = Field(description="기대 효과 2~3줄")
    lines: list[DraftLine] = Field(description="지출 항목 (예비비 제외)")
    reserve_rate: float = Field(description="예비비 비율 0~0.10(사업비 대비). 변동이 적으면 0")
    cautions: list[str] = Field(default_factory=list, description="비고에 적을 주의 사항 0~3줄 (인원 변동·선착순 등)")


class PlanLine(BaseModel):
    item: str
    unit_price: int
    qty: int
    unit: str
    amount: int
    basis: str
    evidence_kind: str
    evidence: list[str]
    checklist: str | None = None


Phase = Literal["준비", "진행", "마무리"]
Short = Annotated[str, Field(max_length=200)]


class PlanStep(BaseModel):
    phase: Phase
    text: Short
    date: date


MAX_UNIT_PRICE = 10_000_000
MAX_QTY = 10_000


class EditLine(BaseModel):
    """사용자가 고친 줄. 범위를 넘으면 깎지 않고 거부한다 — 화면과 저장본 금액이 달라지지 않게."""

    item: str = Field(max_length=80)
    unit_price: int = Field(ge=0, le=MAX_UNIT_PRICE)
    qty: int = Field(ge=0, le=MAX_QTY)
    unit: str = Field(default="개", max_length=10)
    basis: str = Field(default="", max_length=200)


class PlanEdit(BaseModel):
    """결과 화면에서 고친 기획안 — 금액·합계는 다시 서버가 계산한다 (LLM 없음)."""

    request: PlanIn
    intent: str = Field(max_length=1000)
    steps: list[PlanStep] = Field(max_length=20)
    expected: list[Short] = Field(default_factory=list, max_length=6)
    cautions: list[Short] = Field(default_factory=list, max_length=6)
    lines: list[EditLine] = Field(max_length=MAX_LINES)
    reserve: int = Field(ge=0, le=100_000_000)
    method: Literal["ai", "rule"] = "ai"


class PlanOut(BaseModel):
    request: PlanIn
    intent: str
    steps: list[PlanStep]
    expected: list[str]
    cautions: list[str]
    lines: list[PlanLine]
    reserve: int
    expense_total: int
    over_cap: int  # 예산 상한을 넘은 금액 (넘지 않으면 0)
    method: Literal["ai", "rule"]


SUGGEST_FIELDS = ("purpose", "activities")


class SuggestIn(BaseModel):
    """기획 개요 칸 하나(목적·주요 활동)의 AI 초안 요청. 지금까지 적은 개요를 함께 받는다(사업명만 있어도 된다)."""

    field: Literal[SUGGEST_FIELDS]  # type: ignore[valid-type]
    title: str = Field(min_length=1, max_length=60)
    org: str = Field(default="", max_length=40)
    purpose: str = Field(default="", max_length=400)
    target: str = Field(default="", max_length=80)
    headcount: int | None = Field(default=None, ge=1, le=5000)
    place: str = Field(default="", max_length=60)
    fund: Literal[FUNDS] = "학생회비"  # type: ignore[valid-type]
    budget_cap: int | None = Field(default=None, ge=0, le=100_000_000)
    fee: int | None = Field(default=None, ge=0, le=1_000_000)
    activities: str = Field(default="", max_length=1200)


class Suggestion(BaseModel):
    text: str = Field(description="칸에 그대로 넣을 글")
