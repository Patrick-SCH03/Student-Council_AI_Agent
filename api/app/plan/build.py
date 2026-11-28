"""LLM 초안 → 계산을 마친 기획안. 금액·예비비·날짜는 여기서만 정한다.

예비비는 총회 자료 관행대로 '사업비(항목 합)의 10% 이내'로 정하고 10원 단위로 내림한다. 사업비의 10%는
총액의 9.09%라 「재정·회계 세칙」 제16조(예산총액의 10분의 1 이내)도 함께 지킨다 (2026-2 총회 자료 158블록 중 112블록이 정확히 10%).

문서는 총대의원회 양식(2026-2 총회 자료 46개 단위, 사업계획서 파일의 74%)을 따른다:
Ⅱ-1 전체 사업 계획서(+책임자·참여자) → Ⅱ-2 세부 사업 계획서(시기·책임자·참여자·기획 의도·사업내용·예산운영·비고, 예산운영 안에 구분|세부내용(개수)|비용|예산 출처 표)
→ Ⅲ 예산운영 계획서(1. 전체 예산 계획서: 수입·지출·총계 → 2. 세부 예산 계획서: 예산 세부 내역 판단 자료).
표지·목차·Ⅰ 기구표 자리는 화면(web/src/lib/office/forms.ts planDocBlocks)이 Word에만 붙인다. 모든 금액은 같은 계산 결과로 채워 표끼리 어긋나지 않는다.
블록(to_blocks)은 복사용 글(render_text)과 화면의 Word 파일이 함께 쓴다.
"""

from datetime import date, timedelta

from app.notice import today_kst
from app.plan.evidence import papers_for
from app.plan.models import MAX_LINES, MAX_QTY, MAX_UNIT_PRICE, DraftLine, DraftStep, EditLine, PlanDraft, PlanEdit, PlanIn, PlanLine, PlanOut, PlanStep
from app.review.models import BudgetDoc, EventDate, Line
from app.review.numbers import won

MAX_RESERVE_RATE = 0.10
STEP_RANGE = (-30, 120)  # 시작 120일 전 ~ 끝난 뒤 30일


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _line(d: DraftLine | EditLine) -> PlanLine | None:
    item = d.item.strip()[:40]
    if not item or item.replace(" ", "").startswith("예비비"):  # 예비비는 서버가 따로 붙인다
        return None
    unit_price, qty = _clamp(d.unit_price, 0, MAX_UNIT_PRICE), _clamp(d.qty, 0, MAX_QTY)
    kind, papers, checklist = papers_for(item)
    return PlanLine(
        item=item, unit_price=unit_price, qty=qty, unit=(d.unit.strip() or "개")[:4], amount=unit_price * qty,
        basis=d.basis.strip()[:80], evidence_kind=kind, evidence=papers, checklist=checklist,
    )


def _step(s: DraftStep, req: PlanIn, today: date, approval: bool = False, after_approval: bool = False) -> PlanStep:
    """'시작 며칠 전'을 날짜로. 진행은 사업 기간 안, 준비는 시작 전, 마무리는 끝난 뒤로 맞춘다.

    모델이 부호를 반대로 주는 일이 있다(준비에 -14 → 행사 뒤 날짜, 2026-11-28 실측). 단계가 날짜 방향을 정하고 숫자는 거리로만 쓴다.
    """
    n = _clamp(s.days_before, *STEP_RANGE)
    end = req.end or req.start
    if s.phase == "진행":
        day = min(max(req.start - timedelta(days=n), req.start), end)
    elif s.phase == "준비":
        day = req.start - timedelta(days=max(abs(n), 1))
        if approval and req.meeting_date:
            return PlanStep(phase=s.phase, text=s.text.strip()[:120], date=req.meeting_date)  # 사용자가 적은 회의일 그대로
        if today < req.start:
            day = max(day, today)  # 준비 일정이 오늘보다 과거로 잡히지 않게
        if after_approval and req.meeting_date and req.meeting_date < req.start:
            day = min(max(day, req.meeting_date), req.start - timedelta(days=1))  # 인준 뒤에 할 준비는 인준 날 이후
    else:
        day = end + timedelta(days=abs(n))
    return PlanStep(phase=s.phase, text=s.text.strip()[:120], date=day)


def reserve_for(items: int, rate: float) -> int:
    return int(items * min(max(rate, 0.0), MAX_RESERVE_RATE)) // 10 * 10


# 재원에 따라 꼭 적어 둘 비고 (재정·회계 세칙)
FUND_NOTES = {
    "교비지원금": "교비지원금은 지원받은 목적 외에 사용할 수 없음 (재정·회계 세칙 제7조 제5항)",
    "기금": "기금은 대의원회에 제출한 기금운용계획에 맞게 집행 (재정·회계 세칙 제40조·제43조)",
}


def _cautions(req: PlanIn, cautions: list[str]) -> list[str]:
    out = [c.strip() for c in cautions if c.strip()]
    note = FUND_NOTES.get(req.fund)
    return [note, *out] if note and note not in out else out


def assemble(req: PlanIn, draft: PlanDraft | PlanEdit, method: str) -> PlanOut:
    """초안(LLM) 또는 사용자가 고친 기획안을 계산해 PlanOut으로. 초안의 예비비는 비율로, 고친 안은 적은 금액 그대로."""
    lines = [line for line in map(_line, draft.lines[:MAX_LINES]) if line]
    items = sum(line.amount for line in lines)
    if isinstance(draft, PlanDraft):
        reserve = reserve_for(items, draft.reserve_rate)
        if req.spend_limit and items <= req.spend_limit:  # 예비비 때문에 상한(+참가비)을 넘지 않게 남은 만큼만
            reserve = min(reserve, (req.spend_limit - items) // 10 * 10)
    else:
        reserve = draft.reserve
    total = items + max(reserve, 0)
    if isinstance(draft, PlanDraft):
        today = today_kst()
        drafts = [s for s in draft.steps[:14] if s.text.strip()]
        # 인준 단계: 이름이 '인준'으로 끝나는 첫 준비 단계 (2026-11-28 파일럿: 시작 14일 전으로 고정돼 적은 회의일과 달랐다)
        at = next((i for i, s in enumerate(drafts) if s.phase == "준비" and s.text.strip().endswith("인준")), None)
        steps = [_step(s, req, today, approval=i == at, after_approval=at is not None and i > at) for i, s in enumerate(drafts)]
    else:
        steps = [s for s in draft.steps[:14] if s.text.strip()]
    order = {"준비": 0, "진행": 1, "마무리": 2}
    steps.sort(key=lambda s: (s.date, order.get(s.phase, 9)))
    return PlanOut(
        request=req,
        intent=draft.intent.strip(),
        steps=steps,
        expected=[e.strip() for e in draft.expected[:4] if e.strip()],
        cautions=_cautions(req, draft.cautions[:3] if isinstance(draft, PlanDraft) else draft.cautions),
        lines=lines,
        reserve=max(reserve, 0),
        expense_total=total,
        over_cap=max(0, total - req.spend_limit) if req.spend_limit else 0,
        method=method,  # type: ignore[arg-type]
    )


def to_budget_doc(plan: PlanOut) -> BudgetDoc:
    """문서 검토의 계산 검사·규정 메모에 그대로 넣을 수 있는 모양."""
    req = plan.request
    expense = [Line(item=line.item, amount=line.amount, note=f"{line.unit_price:,}원 × {line.qty}{line.unit}") for line in plan.lines]
    if plan.reserve:
        expense.append(Line(item="예비비", amount=plan.reserve, note="변동 대비"))
    fee = req.fee_income
    own = req.budget_cap if req.budget_cap else max(plan.expense_total - fee, 0)
    note = "예산 상한" if req.budget_cap else ("지출에서 참가비를 뺀 금액" if fee else "지출 합계")
    # 상한 없이 참가비로 지출을 다 덮으면 학생회 재원은 0원 — 0원 줄은 두지 않는다
    income = [Line(item=req.fund, amount=own, note=note)] if own or not fee else []
    if fee:
        income.append(Line(item="참가비", amount=fee, note=f"1인 {req.fee:,}원 × {req.headcount}명"))
    income_amount = own + fee
    return BudgetDoc(
        title=req.title,
        org=req.org,
        meeting=req.meeting,
        meeting_date=req.meeting_date.isoformat() if req.meeting_date else None,
        event_dates=[EventDate(
            label=req.title, start=req.start.isoformat(), end=req.end.isoformat() if req.end else None,
            text=_period(plan),
        )],
        income=income,
        income_total=income_amount,
        expense=expense,
        expense_total=plan.expense_total,
        summary_income=income_amount,
        summary_expense=plan.expense_total,
        balance=income_amount - plan.expense_total,
    )


_WEEK = "월화수목금토일"


def _dot(d) -> str:
    return f"{d.year}. {d.month:02d}. {d.day:02d}."


def _day(d) -> str:
    """2026. 12. 10.(목) — 총회 자료처럼 요일을 붙인다 (요일은 계산하므로 틀리지 않는다)."""
    return f"{d.year}. {d.month}. {d.day}.({_WEEK[d.weekday()]})"


def _period(plan: PlanOut) -> str:
    req = plan.request
    return _dot(req.start) + (f" ~ {_dot(req.end)}" if req.end and req.end != req.start else "")


def _when(plan: PlanOut) -> str:
    req = plan.request
    return _day(req.start) + (f" ~ {_day(req.end)}" if req.end and req.end != req.start else "")


def _semester(d) -> str:
    """3~8월 1학기, 9~2월 2학기 (1·2월은 전년도 2학기)."""
    if 3 <= d.month <= 8:
        return f"{d.year}년도 1학기"
    return f"{d.year if d.month >= 9 else d.year - 1}년도 2학기"


def _cell(text="", *, bold=False, align="left", span=1, table=None) -> dict:
    return {"text": text, "bold": bold, "align": align, "span": span, "table": table}


def _table(header: list[str] | None, rows: list[list], widths: list[int]) -> dict:
    as_cell = lambda c: c if isinstance(c, dict) else _cell(str(c))  # noqa: E731
    return {
        "t": "table",
        "widths": widths,
        "header": header or [],
        "rows": [[as_cell(c) for c in row] for row in rows],
    }


def _budget_table(plan: PlanOut) -> dict:
    """세부 사업 계획서 안의 예산운영 표: 구분 | 세부내용(개수) | 비용 | 예산 출처 (총회 자료 287블록의 형식)."""
    fund = plan.request.fund + ("·참가비" if plan.request.fee_income else "")
    rows = [
        [line.evidence_kind or "진행비", f"{line.item} ({line.unit_price:,}원*{line.qty}{line.unit})", _cell(won(line.amount), align="right"), fund]
        for line in plan.lines
    ]
    if plan.reserve:
        rows.append(["예비비", "사업비의 10% 이내", _cell(won(plan.reserve), align="right"), fund])
    rows.append([_cell("총액", bold=True), "", _cell(won(plan.expense_total), bold=True, align="right"), ""])
    return _table(["구분", "세부내용(개수)", "비용", "예산 출처"], rows, [18, 46, 18, 18])


def to_blocks(plan: PlanOut) -> list[dict]:
    req = plan.request
    doc = to_budget_doc(plan)
    groups = [(phase, [s for s in plan.steps if s.phase == phase]) for phase in ("준비", "진행", "마무리")]
    # 책임자·참여자는 따로 줄을 둔다(학생회 총회 자료 꼴). 책임자 이름은 쓰지 않는다 — 개인정보, 화면에서 채운다
    org = req.org.strip()
    head = f"{org}장 [이름]" if org.endswith("학생회") else "[직책] [이름]"
    who = (req.target or "[대상]") + (f" ({req.headcount}명 예정)" if req.headcount else "")
    content = [f"일시 및 장소: {_when(plan)}" + (f" / {req.place}" if req.place else ""), ""]
    for n, (phase, rows) in enumerate((g for g in groups if g[1]), 1):
        content.append(f"{n}. {phase}")
        content += [f" {i}) {s.text} ({s.date.month}.{s.date.day}.)" for i, s in enumerate(rows, 1)]
    intent = plan.intent + ("\n\n기대 효과: " + " / ".join(plan.expected) if plan.expected else "")
    note = "\n".join(f"※ {c}" for c in plan.cautions) or "-"
    month = req.start.month
    detail_rows = [
        [f"{month}월", req.title, line.evidence_kind or "진행비", line.item, _cell(won(line.amount), align="right"),
         f"{line.unit_price:,}원*{line.qty}{line.unit}" + (f" ({line.basis})" if line.basis else "")]
        for line in plan.lines
    ]
    if plan.reserve:
        detail_rows.append(["", "", "예비비", "사업비의 10% 이내", _cell(won(plan.reserve), align="right"), ""])
    for label in (f"{req.title} 사업별 총 비용", f"{month}월 총 사업 진행 비용", f"{_semester(req.start)} 총 사업 진행 비용"):
        detail_rows.append([_cell(label, bold=True, span=4), _cell(won(plan.expense_total), bold=True, align="right"), ""])
    return [
        {"t": "heading", "text": "Ⅱ. 사업 계획서"},
        {"t": "subheading", "text": "1. 전체 사업 계획서"},
        _table(["시기", "사업명", "비고"], [[_period(plan), req.title, f"{req.target} 대상 사업" if req.target else ""]], [30, 45, 25]),
        _table(None, [
            [_cell("책임자", bold=True, align="center"), head],
            [_cell("참여자", bold=True, align="center"), who],
        ], [16, 84]),
        {"t": "subheading", "text": "2. 세부 사업 계획서"},
        {"t": "para", "text": req.title, "bold": True},
        _table(None, [
            [_cell("시기", bold=True, align="center"), _when(plan)],
            [_cell("책임자", bold=True, align="center"), head],
            [_cell("참여자", bold=True, align="center"), who],
            [_cell("기획 의도", bold=True, align="center"), intent],
            [_cell("사업내용", bold=True, align="center"), "\n".join(content)],
            [_cell("예산운영", bold=True, align="center"), _cell(table=_budget_table(plan))],
            [_cell("비고", bold=True, align="center"), note],
        ], [16, 84]),
        {"t": "heading", "text": "Ⅲ. 예산운영 계획서"},
        {"t": "subheading", "text": "1. 전체 예산 계획서"},
        {"t": "subheading", "text": "1) 수입"},
        _table(["항목", "금액", "비고"], [
            *[[line.item, _cell(won(line.amount or 0), align="right"), line.note] for line in doc.income],
            [_cell("합계", bold=True), _cell(won(doc.income_total or 0), bold=True, align="right"), ""],
        ], [30, 30, 40]),
        {"t": "subheading", "text": "2) 지출"},
        _table(["관", "금액", "비고"], [
            ["사업비", _cell(won(plan.expense_total), align="right"), req.title],
            [_cell("합계", bold=True), _cell(won(plan.expense_total), bold=True, align="right"), ""],
        ], [30, 30, 40]),
        {"t": "subheading", "text": "3) 수입/지출 총계"},
        _table(None, [
            [_cell("수 입 금", bold=True, align="center"), _cell(won(doc.summary_income or 0), align="right")],
            [_cell("지 출 금", bold=True, align="center"), _cell(won(doc.summary_expense or 0), align="right")],
            [_cell("차 액", bold=True, align="center"), _cell(won(doc.balance or 0), align="right")],
        ], [30, 70]),
        {"t": "subheading", "text": "2. 세부 예산 계획서 (예산 세부 내역 판단 자료)"},
        _table(["시기", "사업명", "구분", "세부 내용", "금액", "비고"], detail_rows, [9, 22, 14, 21, 15, 19]),
        {"t": "subheading", "text": "※ 감사 자료 확보 (사업 끝나고 모을 증빙)"},
        _table(["항목", "증빙"], [[line.item, ", ".join(line.evidence)] for line in plan.lines], [35, 65]),
    ]


def render_text(blocks: list[dict]) -> str:
    """블록 → 복사해 한글 양식에 붙일 글. 표는 칸을 ' | '로 잇고, 안쪽 표는 들여 쓴다."""

    def cell_text(c: dict) -> str:
        return c["text"].replace("\n", " / ")

    def table_lines(t: dict, indent: str = "") -> list[str]:
        out = [indent + " | ".join(t["header"])] if t["header"] else []
        for row in t["rows"]:
            inner = [c for c in row if c.get("table")]
            out.append(indent + " | ".join(cell_text(c) for c in row if not c.get("table")))
            for c in inner:
                out += table_lines(c["table"], indent + "    ")
        return out

    out: list[str] = []
    for b in blocks:
        if b["t"] == "table":
            out += table_lines(b)
        else:
            if b["t"] == "heading" and out:
                out.append("")
            out.append(b["text"])
    return "\n".join(out)


def to_text(plan: PlanOut) -> str:
    return render_text(to_blocks(plan))
