"""에이전트 구조화 출력 스키마.

v1은 LLM의 자유 텍스트에서 키워드를 세어 위험도를 판정했는데(부분 문자열 중복
카운팅 버그 존재), v2는 각 에이전트가 enum 필드로 판정을 직접 반환하고
최종 위험도는 코드에서 결정론적으로 계산한다.
"""

from enum import Enum

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    LOW = "낮음"
    MEDIUM = "보통"
    HIGH = "높음"


_RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}


class RouteDecision(BaseModel):
    """질문이 학생회 규정/재정/감사 업무와 관련 있는지 판별."""

    route: str = Field(description="'regulation'(학생회 규정·재정·감사 관련) 또는 'general'(그 외)")


class Citation(BaseModel):
    source_file: str = Field(description="근거 문서 파일명")
    snippet: str = Field(description="근거가 된 규정 조항 요약 또는 인용 (한두 문장)")


class ReviewerResult(BaseModel):
    """규정 검토 에이전트의 구조화 분석 결과."""

    violation: str = Field(description="규정 위반 판단: '위반 가능성 높음' | '위반 가능성 낮음' | '위반 없음'")
    risk_level: RiskLevel = Field(description="위험도")
    reasoning: str = Field(description="판단 근거. 반드시 참고한 문서명과 조항을 명시")
    recommendation: str = Field(description="위반을 막기 위한 대안 또는 권고사항")
    citations: list[Citation] = Field(default_factory=list, description="근거로 사용한 규정 인용 목록")


class AuditorResult(BaseModel):
    """감사 에이전트의 구조화 분석 결과."""

    compliance: str = Field(description="감사 기준 준수 여부: '준수' | '위반 가능성 낮음' | '위반 가능성 높음'")
    sanction_likelihood: RiskLevel = Field(description="감사 처분 가능성 (낮음/보통/높음)")
    reasoning: str = Field(description="판단 근거. 관련 규정 조항과 과거 감사 사례를 명시")
    recommendation: str = Field(description="감사 리스크를 줄이기 위한 조치 제안")
    citations: list[Citation] = Field(default_factory=list, description="근거로 사용한 규정/감사기록 인용 목록")


def overall_risk(reviewer: ReviewerResult | None, auditor: AuditorResult | None) -> RiskLevel:
    """두 에이전트의 enum 판정 중 더 높은 쪽을 최종 위험도로 채택한다."""
    levels = []
    if reviewer:
        levels.append(reviewer.risk_level)
    if auditor:
        levels.append(auditor.sanction_likelihood)
    if not levels:
        return RiskLevel.LOW
    return max(levels, key=lambda lv: _RISK_ORDER[lv])
