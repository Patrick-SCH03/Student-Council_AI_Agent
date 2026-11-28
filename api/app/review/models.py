"""문서 검토 데이터 모양. BudgetDoc은 LLM 추출의 출력 스키마이자, 사용자가 확인·수정해 다시 보내는 입력이다."""

from typing import Literal

from pydantic import BaseModel, Field

# 화면 배지와 같은 낱말. '통과'는 없다.
Level = Literal["위반 소지", "보완 필요", "확인 필요"]


class Line(BaseModel):
    item: str = Field(description="항목 이름 (원문 그대로)")
    amount: int | None = Field(description="금액(원). 원문 숫자를 그대로 옮기고 계산해서 고치지 않는다")
    note: str = Field(default="", description="비고 (원문 그대로, 없으면 빈 문자열)")


class Headcount(BaseModel):
    # 무리(신입생·재학생)를 중첩 객체 대신 같은 길이의 목록 두 개로 둔다 — 중첩하면 구조화 출력이
    # 'Schema is too complex'로 거부된다 (2026-11-28 평가에서 확인)
    label: str = Field(description="무엇을 인원 × 단가로 정했는지 (예: 참가비 갹출 기금)")
    counts: list[int] = Field(description="무리별 인원 (신입생·재학생처럼 나뉘면 무리마다 하나씩)")
    unit_prices: list[int] = Field(description="counts와 같은 순서의 무리별 단가")
    stated_amount: int | None = Field(description="문서가 이 계산의 결과로 적은 금액 (합계 하나). 없으면 null")


class EventDate(BaseModel):
    label: str = Field(description="사업 이름 또는 일정 이름")
    start: str | None = Field(description="시작일 YYYY-MM-DD. 원문에 적힌 연도 그대로 (예: '2025/03/07' → 2025-03-07). 연도가 없으면 null")
    end: str | None = Field(default=None, description="종료일 YYYY-MM-DD")
    text: str = Field(description="원문 표기")


class BudgetDoc(BaseModel):
    title: str = Field(description="문서 제목 또는 사업명")
    org: str = Field(default="", description="작성 기구 (예: 컴퓨터공학과 학생회)")
    meeting: str = Field(default="", description="인준 회의 이름 (예: 2025년도 2학기 상임위원회)")
    meeting_date: str | None = Field(default=None, description="인준 회의일 YYYY-MM-DD. 파일명·표지·본문에 있으면, 없으면 null")
    written_date: str | None = Field(default=None, description="표지 작성일 YYYY-MM-DD")
    event_dates: list[EventDate] = Field(default_factory=list)
    income: list[Line] = Field(default_factory=list, description="수입 표의 줄 (합계 줄 제외)")
    income_total: int | None = Field(default=None, description="수입 표의 합계 줄 금액")
    expense: list[Line] = Field(default_factory=list, description="지출 표의 줄 (합계 줄 제외)")
    expense_total: int | None = Field(default=None, description="지출 표의 합계 줄 금액")
    summary_income: int | None = Field(default=None, description="수입/지출 총계 표의 수입금")
    summary_expense: int | None = Field(default=None, description="수입/지출 총계 표의 지출금")
    balance: int | None = Field(default=None, description="수입/지출 총계 표의 차액")
    headcounts: list[Headcount] = Field(default_factory=list, description="인원 × 단가로 금액을 정한 곳")


class Finding(BaseModel):
    code: str
    level: Level
    title: str
    detail: str = ""
    basis: str = ""  # 근거 조항 (확인한 것만)
    where: str = ""  # 문서 안 위치·원문 일부
