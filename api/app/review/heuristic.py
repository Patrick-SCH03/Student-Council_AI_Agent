"""규칙 기반 예산 추출 — 목업 모드와 LLM 추출 실패 때 쓰는 예비 경로.

학생회 양식의 `1) 수입 / 2) 지출 / 3) 수입/지출 총계` 표를 읽는다. 칸 안 줄바꿈으로 항목 이름이 여러 줄에
걸치면 금액이 나올 때까지 이어 붙인다. 지출 표가 없으면(단건 사업안) 세부 사업 계획서의 예산표(blocks)로 채운다.
'사업별 총 비용'·'소계' 같은 합계 줄은 항목으로 더하지 않는다(2026-2 총회 자료에서 이 때문에 지출 합계를 잘못 읽었다).
양식이 다르면 빈 표로 돌려주고, 사용자가 확인 화면에서 채운다.
"""

import re

from app.review.blocks import (
    FUND,
    PARTIAL_TOTAL,
    RESERVE,
    SUBTOTAL,
    cells_of,
    is_header,
    looks_formula,
    money,
    parse_blocks,
    row_of,
    squash,
)
from app.review.models import BudgetDoc, EventDate, Line
from app.review.numbers import to_int
from app.review.sheets import table_text

_AMOUNT = re.compile(r"(?:₩\s*)?(\d{1,3}(?:,\d{3})+|\d+)\s*원")
_SECTION = re.compile(r"^\s*(?:\d\)|[가-하]\.)?\s*(수입/지출\s*총계|수입\s*지출\s*총계|수입|지출)\s*$")
_TOTAL_WORDS = ("합계", "총액", "총합", "계")
_SUMMARY = {"수입금": "summary_income", "총수입": "summary_income", "지출금": "summary_expense",
            "총지출": "summary_expense", "차액": "balance", "잔액": "balance"}
_DATE = re.compile(r"(20\d{2})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})")


def _clean_item(s: str) -> str:
    """'수 입 금'(자간 공백)은 붙이고 '강사 사례금' 같은 띄어쓰기는 살린다."""
    words = s.split()
    return "".join(words) if all(len(w) == 1 for w in words) else " ".join(words)


def meeting_date_from_filename(filename: str) -> str | None:
    """'260210 [1학기 3차 …]' → 2026-02-10. 형식이 아니면 None."""
    m = re.match(r"\s*(\d{2})(\d{2})(\d{2})\b", filename)
    if m and 1 <= int(m[2]) <= 12 and 1 <= int(m[3]) <= 31:
        return f"20{m[1]}-{m[2]}-{m[3]}"
    return None


def heuristic_extract(filename: str, text: str) -> BudgetDoc:
    text = table_text(text)
    doc = BudgetDoc(title=filename.rsplit(".", 1)[0], meeting_date=meeting_date_from_filename(filename))
    section: str | None = None
    pending: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("["):
            continue
        if m := _SECTION.match(line):
            section = "summary" if "총계" in m[1] else ("income" if m[1].startswith("수입") else "expense")
            pending = []
            if section != "summary" and getattr(doc, f"{section}_total") is not None:
                section = None  # 같은 표가 또 나오면(회의 자료를 이어 붙인 파일) 첫 표만 읽는다
            continue
        if section is None:
            continue
        if squash(line).startswith("항목"):
            continue
        # 표가 끝나고 다음 장('Ⅳ.', '3.', '4) 예산 세부 내역 판단 자료')이 시작되면 멈춘다
        if re.match(r"^(?:[ⅠⅡⅢⅣⅤ]\.|\d+[.)]\s*[가-힣])", line):
            section = None
            continue
        if section in ("income", "expense") and " | " in line:
            _table_row(doc, section, line)
            pending = []
            if getattr(doc, f"{section}_total") is not None:
                section = None  # 합계 줄에서 표가 끝난다
            continue
        amount = _AMOUNT.search(line)
        if not amount:
            pending.append(line)
            continue
        item = _clean_item(" ".join([*pending, line[: amount.start()]]))
        note = line[amount.end():].strip(" ⋅·")
        if not item and note and section in ("income", "expense"):
            item, note = note, ""  # 병합 칸이라 금액이 줄 맨 앞에 온 경우('396,000원 간식드리미')
        pending = []
        value = to_int(amount[1])
        if section == "summary":
            # '(7,515,044원 - 393,300원)+ α - β' 처럼 식으로 적은 값은 하나의 금액으로 읽지 않는다
            if re.search(r"[αβ]|원\s*[-+]", line):
                continue
            for word, attr in _SUMMARY.items():
                if word in squash(item):
                    if getattr(doc, attr) is None:  # 회의 자료를 이어 붙인 파일은 첫 총계 표만 쓴다
                        setattr(doc, attr, value)
                    break
            continue
        if squash(item) in _TOTAL_WORDS or any(squash(item).startswith(w) for w in _TOTAL_WORDS[:3]):
            setattr(doc, f"{section}_total", value)
        elif SUBTOTAL.search(item):
            continue
        elif item:
            getattr(doc, section).append(Line(item=item, amount=value, note=note))
    _deductions(doc)
    if not doc.expense:
        _expense_from_blocks(doc, text)
    if m := re.search(r"시\s*기\s*[:：]?\s*(" + _DATE.pattern + r"[^\n]*)", text):
        y, mo, d = m[2], int(m[3]), int(m[4])
        doc.event_dates.append(EventDate(label="사업 시기", start=f"{y}-{mo:02d}-{d:02d}", text=m[1].strip()[:40]))
    return doc


def _expense_from_blocks(doc: BudgetDoc, text: str) -> None:
    """세부 사업 계획서의 예산운영 표(구분 | 세부내용 | 비용 | 예산 출처)로 지출을 채운다.

    표가 하나면 그 줄·예비비·총액을, 여럿이면 사업마다 총액 한 줄씩 넣는다(사업 총액을 다 읽었을 때만 합계도).
    일부 재원만 더한 총액('총액(자치비)')은 합계로 쓰지 않는다.
    """
    budgets = [b for b in parse_blocks(text) if b.kind == "budget"]
    if len(budgets) == 1:
        b = budgets[0]
        unread = False
        for r in b.rows:
            if r.kind in ("line", "reserve") and r.amount is None and any(c for c in r.cells if c not in ("", "-")):
                # 금액을 못 읽은 줄은 금액을 비워 넣는다 — 확인 화면에서 채우고, 그전엔 합계·예비비 비율을 판단하지 않는다
                unread = True
                doc.expense.append(Line(item=" ".join(c for c in r.cells if c)[:60], amount=None, note="금액을 읽지 못했어요"))
                continue
            if r.kind == "reserve" and r.amount is not None:
                doc.expense.append(Line(item="예비비", amount=r.amount, note=" · ".join(c for c in r.cells if c and not money(c))[:60]))
                continue
            if r.kind in ("line", "reserve") and r.amount is not None:
                name = next((c for c in r.cells if c and c.strip() not in ("-",)), "")
                detail = next((c for c in r.cells[1:] if c and c != name and not re.search(r"\d{1,3}(?:,\d{3})+|\d+원", c)), "")
                doc.expense.append(Line(item=(detail or name)[:60], amount=r.amount, note=name if detail else ""))
        total = b.total
        if not unread and total and total.amount is not None and not PARTIAL_TOTAL.search(" ".join(total.cells)):
            doc.expense_total = total.amount
    elif len(budgets) > 1:
        totals = [(b.project or f"사업 {i}", b.total.amount if b.total else None) for i, b in enumerate(budgets, 1)]
        doc.expense = [Line(item=name[:60], amount=amount, note="세부 사업 계획서 예산표 총액") for name, amount in totals]
        if all(amount is not None for _, amount in totals):
            doc.expense_total = sum(amount for _, amount in totals)  # type: ignore[misc]


def _table_row(doc: BudgetDoc, section: str, line: str) -> None:
    """표 한 줄(칸이 ' | '로 나뉜 줄)을 값 모양으로 읽는다 — '300,000 | 자치비'처럼 '원'이 없는 금액, 병합 칸
    ('500,000원 | 제4회 산공인의 밤'), 이름 없는 소계 줄('237,710원')을 처리한다. 금액을 못 읽은 줄은 넣지 않는다."""
    cells = cells_of(line)
    if is_header(cells):
        return
    row = row_of(cells)
    if row.amount is None or row.kind == "sub" or SUBTOTAL.search(" ".join(cells)):
        return
    first = squash(next((c for c in cells if c), ""))
    if row.kind != "total" and first.endswith("합계") and first != "합계":
        return  # '수납금 합계'처럼 표 가운데의 부분 합계 줄은 항목이 아니다
    if row.kind == "total":
        setattr(doc, f"{section}_total", row.amount)
        return
    words = [c for c in cells if c and not money(c) and c != "-"]
    item = words[0] if words else ""
    if section == "expense" and not RESERVE.search(item):
        # 지출은 금액 칸 바로 왼쪽의 설명 칸이 항목이다 ('구분 | 사업 | 항목 | 금액 | 비고') — 오른쪽 비고·산출식·재원 이름은 쓰지 않는다
        at = next((i for i in range(len(cells) - 1, -1, -1) if (m := money(cells[i])) and m[0] == row.amount), len(cells))
        left = [c for c in reversed(cells[:at]) if c and c != "-" and not money(c) and not looks_formula(c)
                and not _FUND_WORD.fullmatch(c.replace(" ", ""))]
        named = [w for w in words if not _FUND_WORD.fullmatch(w.replace(" ", "")) and not looks_formula(w)]
        right = [c for c in cells[at + 1:] if c and c != "-" and not money(c) and not looks_formula(c)
                 and not _FUND_WORD.fullmatch(c.replace(" ", ""))]
        left_named = [c for c in left if not _CATEGORY.fullmatch(squash(c))]
        near = next((c for c in reversed(cells[:at]) if c and c != "-" and not money(c)), "")
        if left_named:
            item = left_named[0]
        elif left and right:
            item = right[0]  # 지출표(관 | 금액 | 비고)는 '사업비' 같은 관 이름이 왼쪽, 사업명이 비고에 있다
        elif left:
            item = left[0]
        elif near:
            item = near  # 이름에 숫자 식이 든 경우('생수 500ml*40')도 금액 바로 왼쪽 칸이 항목이다
        else:
            item = named[-1] if named else item
    note = " · ".join(w for w in words if w != item)[:80]
    if item:
        getattr(doc, section).append(Line(item=item[:60], amount=row.amount, note=note))


_FUND_WORD = re.compile(FUND)
_CATEGORY = re.compile(r"(?:사업|운영|사무|행정|사업운영)비|관")  # 지출표의 관 이름
_DEDUCTION = re.compile(r"사용|차감|지원비|지출|반환")


def _deductions(doc: BudgetDoc) -> None:
    """수입표에 '…에 사용 | 500,000원'처럼 빼는 줄을 양수로 적은 경우: 그 줄들을 빼야 합계가 정확히 맞을 때만 뺀다."""
    if doc.income_total is None or not doc.income or any(line.amount is None for line in doc.income):
        return
    plain = sum(line.amount for line in doc.income)  # type: ignore[misc]
    minus = [line for line in doc.income[1:] if _DEDUCTION.search(line.item)]
    if plain == doc.income_total or not minus:
        return
    if plain - 2 * sum(line.amount for line in minus) == doc.income_total:  # type: ignore[misc]
        for line in minus:
            line.amount = -line.amount  # type: ignore[operator]
            line.note = (line.note + " 차감으로 읽음").strip()
