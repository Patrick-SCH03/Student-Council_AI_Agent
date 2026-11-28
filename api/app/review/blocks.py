"""원문 표 → 예산 블록. LLM 없이 읽는 학생회 예산표 해석기 (2026-2 총회 자료 327개로 맞춘 규칙).

- 머리행: 금액 열(비용·금액·총액…)과 다른 열(구분·항목·세부내용…)이 함께 있는 줄. `예산운영 | 구분 | …`처럼 바깥 칸 이름이 붙어도 된다.
- 금액: 위치가 아니라 값 모양으로 읽는다 — 줄의 오른쪽에서 처음 나오는 금액 칸(병합 칸 때문에 47%의 줄이 머리행보다 칸이 적다).
- 줄 종류: 항목 · 예비비 · 총액(총액·합계·총계…) · 소계(사업별 총 비용·소계·총 사업 진행 비용).
- 표 종류(Block.kind): 지출표(관|금액|비고) · 판단 자료(사업명 칸) · 목록표(항목, 구분 없음) · 예산표(구분) — 한 곳에서 정한다.
- 표끼리 대조: 같은 사업이 세부 사업 계획서 예산표·지출표(관|금액|비고)·예산 세부 내역 판단 자료에 함께 나오면 금액이 같아야 한다.
읽지 못한 금액은 0으로 치지 않는다 — 그 판단은 건너뛴다.
문서 검토의 다른 검사(textcheck 소계·heuristic 대체 추출)도 이 모듈의 줄 해석(row_of)과 표 종류를 쓴다.
"""

import re
from dataclasses import dataclass, field

from app.privacy import mask_text
from app.review.models import Finding
from app.review.numbers import won

_NUM = r"\d{1,3}(?:,\d{3})+|\d+"
_MONEY = re.compile(rf"^[\\₩￦]?\s*(?P<n>{_NUM})\s*(?P<man>만)?\s*(?:원|\(원\))?\s*(?P<tail>\(.*\))?\s*$")
_MONEY_HEAD = re.compile(r"비용|금액|총액|소요예산|예산액|가격")
_OTHER_HEAD = re.compile(r"구분|항목|품목|품명|세부내용|단가|수량|예산출처|비고|산출|내역|내용|개수|관")
_TOTAL = re.compile(r"^(?:총\s*액|합\s*계|총\s*합\s*계?|총\s*계|계|총\s*예산|총\s*비용|소요\s*예산|예산\s*총액|총\s*금액)(?:\s*\(.*\))?$")
SUBTOTAL = re.compile(r"소\s*계|사업별\s*총\s*비용|총\s*사업\s*진행\s*비용")
# 판단 자료의 합계 단계: 사업별 총 비용 < N월(또는 상시사업) 총 사업 진행 비용 < 학기 총 사업 진행 비용
PROJECT_TOTAL = re.compile(r"사업별\s*총\s*비용")
GROUP_TOTAL = re.compile(r"(?P<name>\S+)\s*총\s*사업\s*진행\s*비용")
TERM_TOTAL = re.compile(r"학기\s*총\s*사업\s*진행\s*비용")
RESERVE = re.compile(r"예비비")
# 재원 이름 — 일부 재원 총액 판별과 대체 추출의 설명 칸 고르기가 같은 목록을 쓴다
FUND = r"(?:과\s*)?(?:자치비|학생회비|교비\s*지원금|교비|기금|각출비|회비|학과\s*지원금|행정실\s*지원금)"
_RESERVE_RATE = re.compile(r"예비비\s*(\d{1,2})\s*%\s*포함")


@dataclass
class Row:
    cells: list[str]
    kind: str  # line | reserve | total | sub
    amount: int | None
    tail: str = ""


@dataclass
class Block:
    header: list[str]
    rows: list[Row] = field(default_factory=list)
    project: str = ""  # 표 위 제목 줄(세부 사업 계획서의 사업명)
    line: str = ""  # 머리행 원문 (발견 위치)

    @property
    def kind(self) -> str:
        """expense: 지출표(관|금액|비고) · detail: 예산 세부 내역 판단 자료(사업명 칸) · list: 수입표 같은 목록표(항목, 구분 없음)
        · budget: 세부 사업 계획서 예산표(구분) · other."""
        head = squash(" ".join(self.header))
        if head.startswith("관"):
            return "expense"
        if "사업명" in head:
            return "detail"
        if "항목" in head and "구분" not in head:
            return "list"
        return "budget" if "구분" in head else "other"

    @property
    def lines(self) -> list[Row]:
        return [r for r in self.rows if r.kind == "line"]

    @property
    def total(self) -> Row | None:
        return next((r for r in self.rows if r.kind == "total"), None)


_RESULT = re.compile(rf"=\s*[\\₩￦]?\s*(?P<n>{_NUM})\s*원?\s*(?:\(.*\))?\s*$")
# 일부 재원만 더한 총액('총액(자치비)', '총액 (학과 지원금 제외)')은 줄 합과 비교하지 않는다
PARTIAL_TOTAL = re.compile(rf"제외|\({FUND}\)")


def money(cell: str) -> tuple[int, str] | None:
    s = (cell or "").strip()
    m = _MONEY.match(s)
    if not s or not m or re.search(r"[\d+]", m["tail"] or ""):  # '800,000원(자치비)+1,012,000원(각출비)'는 한 금액이 아니다
        return None
    value = int(m["n"].replace(",", "")) * (10_000 if m["man"] else 1)
    return value, (m["tail"] or "")


_CELL_SEP = re.compile(r"(?:(?<=\s)|^)\|(?=\s|$)")  # 빈 칸이 이어진 '| |'도 칸마다 나눈다
_FORMULA_CELL = re.compile(r"\d\s*[*×xX]\s*\d|[*×]\s*\d")


def cells_of(line: str) -> list[str]:
    """' | '로 이은 표 한 줄 → 칸. 줄 끝 공백이 잘려 마지막 빈 칸이 '200,000원 |'처럼 붙어도 나눈다."""
    return [c.strip() for c in _CELL_SEP.split(line)]


def looks_formula(cell: str) -> bool:
    """'15,000원 * 80명'처럼 산출 식이 든 칸 — 항목 이름으로 쓰지 않는다."""
    return bool(_FORMULA_CELL.search(cell))


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def is_header(cells: list[str]) -> bool:
    n = [squash(c) for c in cells if c.strip()]
    if not n or any(re.search(r"\d{3,}", c) for c in n) or any(len(c) > 24 for c in n):
        return False
    return any(_MONEY_HEAD.search(c) for c in n) and sum(bool(_OTHER_HEAD.search(c)) for c in n) >= 1


def row_of(cells: list[str]) -> Row:
    cells = [c.strip() for c in cells]
    filled = [c for c in cells if c]
    head = " ".join(filled[:2])
    kind = "line"
    if filled and (_TOTAL.match(squash(filled[0])) or (len(filled) > 1 and _TOTAL.match(squash(filled[1])) and not money(filled[0]))):
        kind = "total"
    if SUBTOTAL.search(head):
        kind = "sub"
    elif kind == "line" and RESERVE.search(head):
        kind = "reserve"
    amount, tail = None, ""
    many = sum(1 for c in cells if money(c)) > 1
    for c in reversed(cells):
        got = money(c)
        if not got:
            continue
        # 금액 칸이 여럿이면 쉼표·'원' 없는 작은 수는 수량으로 본다
        if many and "," not in c and "원" not in c and got[0] < 1000 and kind == "line":
            continue
        amount, tail = got
        break
    if kind == "line" and len(filled) == 1 and amount is not None:
        kind = "sub"  # 이름 없는 소계 줄 — 교비·자치비 표를 이어 쓰고 각각 소계를 단 경우
    if amount is None:  # '10 * 50,000원 = 500,000원'처럼 식으로 적은 금액 칸은 = 뒤 값을 읽는다
        for c in reversed(cells):
            if m := _RESULT.search(c):
                amount = int(m["n"].replace(",", ""))
                break
    return Row(cells=cells, kind=kind, amount=amount, tail=tail)


def _project_above(lines: list[str], i: int) -> str:
    """표 위의 사업명 제목 줄. '사업명 | X' 칸이 있으면 그것을, 아니면 표가 아닌 짧은 줄을 쓴다."""
    for j in range(i - 1, max(-1, i - 16), -1):
        line = lines[j].strip()
        cells = [c.strip() for c in line.split(" | ")]
        if len(cells) == 2 and squash(cells[0]) in ("사업명", "사업"):
            return cells[1]
        if " | " in line:
            continue
        if 2 <= len(line) <= 30 and ":" not in line and "：" not in line and not re.match(r"^(?:[ⅠⅡⅢⅣⅤ]|\d+[.)]|[가-하]\.|※|\[)", line):
            return line
        if line:
            return ""
    return ""


def parse_blocks(text: str) -> list[Block]:
    lines = text.splitlines()
    blocks: list[Block] = []
    current: Block | None = None
    for i, raw in enumerate(lines):
        if " | " not in raw:
            current = None
            continue
        for part in raw.split(" / "):  # 한 칸 안에 들어간 안쪽 표는 ' / '로 이어져 있다
            cells = [c.strip() for c in part.split(" | ")]
            if is_header(cells):
                current = Block(header=cells, project=_project_above(lines, i), line=raw.strip()[:80])
                blocks.append(current)
                continue
            if current is None:
                continue
            row = row_of(cells)
            current.rows.append(row)
            if row.kind == "total":
                current = None  # 총액 줄에서 표가 끝난다
    return [b for b in blocks if b.rows]


def _norm(name: str) -> str:
    return re.sub(r"[\s·ㆍ\-_()\[\]「」'\"]", "", name)


def _sum(rows: list[Row]) -> int | None:
    return None if any(r.amount is None for r in rows) else sum(r.amount for r in rows)  # type: ignore[misc]


def check_block_totals(text: str, blocks: list[Block] | None = None) -> list[Finding]:
    """예산표마다 (줄 합 + 예비비) = 소계, 소계 합 = 총액. '(예비비 10% 포함)'만 적고 예비비 줄이 없으면 그 비율로 본다.

    수입표(차감 줄을 양수로 적는 일이 있음)·판단 자료(check_subtotals가 봄)·일부 재원만 더한 총액은 비교하지 않는다.
    """
    found, seen = [], set()

    def report(b: Block, row: Row, expected: int, parts: str) -> None:
        key = (b.project, row.amount, expected)
        if key in seen:
            return
        seen.add(key)
        label = "소계" if row.kind == "sub" else "총액"
        found.append(Finding(
            code="block_total",
            level="보완 필요",
            title=f"{(b.project + ' ') if b.project else ''}예산표 {label}이 줄 합과 {won(abs(expected - row.amount))} 달라요",  # type: ignore[operator]
            detail=f"{parts} = {won(expected)} · 적힌 {label} {won(row.amount)}",  # type: ignore[arg-type]
            where=mask_text(" | ".join(c for c in row.cells if c)[:80]),
        ))

    for b in parse_blocks(text) if blocks is None else blocks:
        if b.kind in ("expense", "detail", "list"):
            continue  # 지출표 합계는 구조 검사(rules.check_totals)가, 판단 자료는 check_subtotals가 본다
        total = b.total
        segments: list[tuple[Row, list[Row]]] = []
        current: list[Row] = []
        for r in b.rows:
            if r.kind in ("line", "reserve"):
                current.append(r)
            elif r.kind == "sub":
                segments.append((r, current))
                current = []
            elif r.kind == "total":
                break
        for sub, rows in segments:
            got = _sum(rows)
            if sub.amount is not None and got is not None and rows and got != sub.amount:
                report(b, sub, got, f"줄 합 {won(got)}")
        if not total or total.amount is None or PARTIAL_TOTAL.search(" ".join(total.cells)):
            continue
        if segments:
            subs = [sub for sub, _ in segments]
            tail = _sum(current)
            if any(x.amount is None for x in subs) or tail is None:
                continue
            expected = sum(x.amount for x in subs) + tail  # type: ignore[misc]
            if expected != total.amount:
                report(b, total, expected, "소계 합 " + " + ".join(won(x.amount) for x in subs))  # type: ignore[arg-type]
            continue
        lines = [r for r in current if r.kind == "line"]
        reserves = [r for r in current if r.kind == "reserve"]
        items, reserve = _sum(lines), _sum(reserves)
        if not lines or items is None or reserve is None:
            continue
        expected = items + reserve
        note = total.tail + " " + " ".join(total.cells)
        if not reserves and (rate := _RESERVE_RATE.search(note)):
            expected = items + items * int(rate[1]) // 100
        if expected == total.amount or (not reserves and "예비비" in note and total.amount > items):
            continue  # 비율 없이 '예비비 포함'만 적은 총액은 숨은 예비비라 따로 판단하지 않는다
        report(b, total, expected, f"줄 합 {won(items)}" + (f" + 예비비 {won(reserve)}" if reserve else ""))
    return found


def _expense_rows(blocks: list[Block]) -> dict[str, int]:
    """지출표(관 | 금액 | 비고)의 사업별 금액 — 비고 칸에 사업명이 있는 줄."""
    out: dict[str, int] = {}
    twice: set[str] = set()
    for b in blocks:
        if b.kind != "expense":
            continue
        for r in b.rows:
            if r.kind != "line" or r.amount is None:
                continue
            name = next((c for c in reversed(r.cells) if c and not money(c)), "")
            if name and name != r.cells[0]:
                key = _norm(name)
                if key in out:
                    twice.add(key)
                out[key] = r.amount
    return {k: v for k, v in out.items() if k not in twice}


def _detail_totals(blocks: list[Block]) -> dict[str, int]:
    """예산 세부 내역 판단 자료의 사업별 총 비용 — 바로 위 줄들의 사업명 칸으로 사업을 정한다."""
    out: dict[str, int] = {}
    for b in blocks:
        head = [squash(h) for h in b.header]
        if b.kind != "detail" or "사업명" not in head:
            continue
        col = head.index("사업명")
        projects: list[str] = []
        for r in b.rows:
            if r.kind == "sub" and PROJECT_TOTAL.search(" ".join(r.cells)):
                if len(set(projects)) == 1 and r.amount is not None:  # 두 사업을 한 합계로 묶은 경우는 뺀다
                    out[_norm(projects[0])] = r.amount
                projects = []
            elif len(r.cells) > col and r.cells[col] and not money(r.cells[col]) and len(r.cells) >= len(head) - 1:
                projects.append(r.cells[col])
    return out


def _plan_totals(blocks: list[Block]) -> dict[str, int]:
    """세부 사업 계획서 예산운영 표의 총액 — 표 위 제목 줄이 사업명이다."""
    out: dict[str, int] = {}
    for b in blocks:
        if (
            b.project and b.total and b.total.amount is not None and "구분" in squash(" ".join(b.header))
            and not PARTIAL_TOTAL.search(" ".join(b.total.cells))
        ):
            out[_norm(b.project)] = b.total.amount
    return out


def check_cross_tables(text: str, blocks: list[Block] | None = None) -> list[Finding]:
    """같은 사업의 금액이 세부 사업 계획서·지출표·판단 자료에서 같은지 본다 (2026-2 총회 자료: 3개 파일에서 어긋남)."""
    blocks = parse_blocks(text) if blocks is None else blocks
    sources = {"세부 사업 계획서": _plan_totals(blocks), "지출표": _expense_rows(blocks), "판단 자료": _detail_totals(blocks)}
    names = sorted({n for src in sources.values() for n in src}, key=len)

    def same(a: str, b: str) -> bool:
        # '산공인의 밤'과 '제4회 산공인의 밤'처럼 한쪽이 다른 쪽을 품으면 같은 사업으로 본다 (세 글자 이상)
        return a == b or (min(len(a), len(b)) >= 3 and (a in b or b in a))

    found, done = [], set()
    for name in names:
        if any(same(name, d) for d in done):
            continue
        done.add(name)
        got = {}
        for label, src in sources.items():
            hits = [v for k, v in src.items() if same(name, k)]
            if len(hits) == 1:
                got[label] = hits[0]
        if len(got) >= 2 and len(set(got.values())) > 1:
            found.append(Finding(
                code="cross_table",
                level="보완 필요",
                title=f"'{name}' 금액이 표마다 달라요",
                detail=" · ".join(f"{label} {won(v)}" for label, v in got.items()),
                where=name,
            ))
    return found
