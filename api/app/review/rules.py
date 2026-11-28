"""예산 구조(BudgetDoc)에 대한 계산 검사. 확인한 사실만 말하고, 조항은 원문을 확인한 것만 인용한다.

등급: 위반 소지 = 규정에 어긋날 수 있음 · 보완 필요 = 문서 숫자·표기를 고쳐야 함 · 확인 필요 = 사람이 확인할 것.
"""

from datetime import date

from app.review.models import BudgetDoc, Finding, Line
from app.review.numbers import won

RESERVE_BASIS = "「재정·회계 세칙」 제16조(예비비는 예산총액의 10분의 1 이내)"
RESERVE_PROJECT_BASIS = "총대의원회 사업자료 작성 안내(예비비는 사업 예산의 10% 이내)"
SUPPLEMENTARY_BASIS = "「재정·회계 세칙」 제22조 제2항(추가경정예산은 확정 전에 집행할 수 없음)"


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _sum(lines: list[Line]) -> int | None:
    """모든 줄에 금액이 있을 때만 합계를 낸다 (빈 금액을 0으로 치면 거짓 불일치가 난다)."""
    if not lines or any(line.amount is None for line in lines):
        return None
    return sum(line.amount for line in lines)  # type: ignore[misc]


def _is_reserve(line: Line) -> bool:
    return "예비" in line.item and "물품" not in line.item


def _total_mismatch(name: str, lines: list[Line], stated: int | None) -> Finding | None:
    total = _sum(lines)
    if total is None or stated is None or total == stated:
        return None
    reserve = sum(line.amount or 0 for line in lines if _is_reserve(line))
    if name == "지출" and reserve and total - reserve == stated:
        # 예비비 줄은 따로 적고 총액에는 넣지 않은 경우 (2026-2 총회 자료 2건) — 합이 틀린 게 아니라 예비비가 빠졌다
        return Finding(
            code="reserve_outside_total",
            level="확인 필요",
            title=f"예비비 {won(reserve)}이 지출 총액에 들어 있지 않아요",
            detail=f"항목 합 {won(stated)} = 문서 총액 · 예비비까지 더하면 {won(total)}. 예비비를 쓸 수 있게 하려면 총액에 넣어요.",
            where=f"{name} 표",
        )
    return Finding(
        code=f"{name}_total",
        level="보완 필요",
        title=f"{name} 합계가 항목 합과 {won(abs(total - stated))} 달라요",
        detail=f"문서 합계 {won(stated)} · 항목을 더하면 {won(total)}",
        where=f"{name} 표",
    )


def check_totals(doc: BudgetDoc) -> list[Finding]:
    found = [
        _total_mismatch("수입", doc.income, doc.income_total),
        _total_mismatch("지출", doc.expense, doc.expense_total),
    ]
    pairs = (("수입", doc.income_total, doc.summary_income), ("지출", doc.expense_total, doc.summary_expense))
    for name, section, summary in pairs:
        if section is not None and summary is not None and section != summary:
            found.append(Finding(
                code=f"{name}_summary",
                level="보완 필요",
                title=f"{name} 표 합계와 총계 표의 {name}금이 달라요",
                detail=f"{name} 표 {won(section)} · 총계 표 {won(summary)}",
                where="수입/지출 총계 표",
            ))
    income = doc.summary_income if doc.summary_income is not None else doc.income_total
    expense = doc.summary_expense if doc.summary_expense is not None else doc.expense_total
    if None not in (income, expense, doc.balance) and income - expense != doc.balance:  # type: ignore[operator]
        found.append(Finding(
            code="balance",
            level="보완 필요",
            title="수입에서 지출을 뺀 값이 차액과 달라요",
            detail=f"{won(income)} − {won(expense)} = {won(income - expense)} · 문서 차액 {won(doc.balance)}",  # type: ignore[operator]
            where="수입/지출 총계 표",
        ))
    return [f for f in found if f]


def check_headcounts(doc: BudgetDoc) -> list[Finding]:
    found = []
    for h in doc.headcounts:
        if h.stated_amount is None or not h.counts or len(h.counts) != len(h.unit_prices):
            continue
        pairs = list(zip(h.counts, h.unit_prices))
        expected = sum(c * p for c, p in pairs)
        if h.stated_amount != expected:
            formula = " + ".join(f"{c:,}명 × {won(p)}" for c, p in pairs)
            found.append(Finding(
                code="headcount",
                level="보완 필요",
                title=f"{h.label}: 인원 × 단가가 금액과 {won(abs(expected - h.stated_amount))} 달라요",
                detail=f"{formula} = {won(expected)} · 문서 금액 {won(h.stated_amount)}",
                where=h.label,
            ))
    return found


def check_reserve(doc: BudgetDoc) -> list[Finding]:
    """예비비 한도. 세칙은 '예산총액의 10분의 1'(예비비 포함 총액), 총대 작성 안내와 문서 관행은 '사업비의 10%'(예비비 제외).

    총액 기준을 넘으면 위반 소지, 총액 기준은 지키지만 사업비 기준을 넘으면 확인 필요로 둘 다 보여 준다
    (2026-2 총회 자료: 사업비 대비 10.5~20.7% 8건 중 3건이 총액 대비로는 10% 안).
    """
    total = doc.summary_expense or doc.expense_total or _sum(doc.expense)
    reserve = sum(line.amount or 0 for line in doc.expense if _is_reserve(line))
    if not total or not reserve:
        return []
    project = total - reserve
    lines = _sum(doc.expense)
    if lines is not None and lines - reserve == total:
        # 총액에 예비비가 빠진 문서 — 적힌 총액이 곧 사업비다 (reserve_outside_total이 따로 알린다)
        project, total = total, total + reserve
    ratio = f"총액 대비 {reserve / total:.1%}" + (f" · 사업비 대비 {reserve / project:.1%}" if project > 0 else "")
    if reserve * 10 > total:
        return [Finding(
            code="reserve",
            level="위반 소지",
            title=f"예비비가 지출 총액의 10%를 넘어요 ({reserve / total:.1%})",
            detail=f"예비비 {won(reserve)} · 한도 {won(total // 10)} (지출 총액 {won(total)}) · {ratio}",
            basis=RESERVE_BASIS,
            where="지출 표",
        )]
    if project > 0 and reserve * 10 > project:
        return [Finding(
            code="reserve_project",
            level="확인 필요",
            title=f"예비비가 사업비의 10%를 넘어요 ({reserve / project:.1%})",
            detail=f"예비비 {won(reserve)} · 사업비의 10%는 {won(project // 10)} · {ratio}. 총대 작성 안내는 사업 예산의 10% 이내예요.",
            basis=RESERVE_PROJECT_BASIS,
            where="지출 표",
        )]
    return []


def check_dates(doc: BudgetDoc) -> list[Finding]:
    found = []
    meeting = _parse_date(doc.meeting_date)
    doc_year = (meeting or _parse_date(doc.written_date) or date.min).year
    is_supplementary = "추가경정" in doc.title or "추경" in doc.title
    for ev in doc.event_dates:
        start = _parse_date(ev.start)
        if not start:
            continue
        wrong_year = doc_year != date.min.year and start.year < doc_year
        if meeting and start < meeting and not wrong_year:
            found.append(Finding(
                code="event_before_meeting",
                level="위반 소지",
                title=f"인준 회의({meeting:%m.%d})보다 사업({start:%m.%d})이 먼저예요",
                detail="인준을 받기 전에 집행하게 돼요. 일정이나 인준 회의를 조정해 주세요.",
                basis=SUPPLEMENTARY_BASIS if is_supplementary else "",
                where=ev.text,
            ))
        if wrong_year:
            found.append(Finding(
                code="event_year",
                level="확인 필요",
                title=year_title(start.year, doc_year),
                detail="지난 문서를 복사하면서 연도가 남은 것일 수 있어요.",
                where=ev.text,
            ))
    return found


def year_title(year: int, doc_year: int) -> str:
    """원문 검사(textcheck)와 같은 제목 — 둘이 같이 잡으면 하나로 묶인다."""
    return f"사업 연도({year})가 문서 연도({doc_year})와 달라요"


def check_budget(doc: BudgetDoc) -> list[Finding]:
    return [*check_totals(doc), *check_headcounts(doc), *check_reserve(doc), *check_dates(doc)]
