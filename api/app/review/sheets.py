"""정산서·산출표(XLSX) 검사: 저장된 계산값과 수식을 다시 계산한 값을 대조한다.

실제 정산서에서 본 오류: 합계 범위에 영수증번호 열이 섞임, 결과가 #REF!, 같은 표를 두 번 계산해 값이 다름.
SUM·사칙연산만 다시 계산한다 — IF·VLOOKUP 같은 함수가 든 수식은 건너뛴다(추측하지 않음).
"""

import ast
import io
import operator
import re

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter, range_boundaries

from app.review.models import Finding
from app.review.numbers import won

MAX_CELLS = 200_000  # 시트 범위(행×열) 합 상한 — 빈 칸도 순회 비용이 든다
MAX_UNZIPPED = 60 * 1024 * 1024  # 압축을 푼 크기 상한 (압축 폭탄 방지)


class SheetTooLarge(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 문구."""


def _guard(data: bytes) -> None:
    """열기 전에 압축 해제 크기를, 연 뒤에는 시트 범위를 확인한다.

    값이 두 칸뿐인 1KB 파일도 A1과 XFD1048576을 쓰면 170억 칸 범위가 되어 순회가 끝나지 않는다(2026-11-28 교차 리뷰).
    """
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
                raise SheetTooLarge("엑셀 파일이 너무 커요. 예산·정산 시트만 남겨 다시 올려 주세요.")
    except zipfile.BadZipFile as e:
        raise SheetTooLarge("엑셀 파일을 열지 못했어요.") from e


# 칸·행의 서식 번호(s="N"). 없는 번호를 가리키면 openpyxl이 IndexError를 낸다
# 속성 앞 공백은 한 칸만 맞춘다: '\s+'로 두면 공백을 잔뜩 채운 태그에서 게으른 [^>]*?와 맞물려 제곱 시간(ReDoS)이 된다(보안 점검)
_STYLE_ATTR = re.compile(rb'(<(?:\w+:)?(?:c|row)\b[^>]*?)\ss="\d+"')  # <x:c …>처럼 접두어가 붙기도 한다
_COL_STYLE = re.compile(rb'(<(?:\w+:)?col\b[^>]*?)\sstyle="\d+"')  # 열 너비 정의의 서식 번호
# 서식 표가 비었거나 깨졌을 때 갈아 끼울 최소 서식 (값 읽기에는 서식이 필요 없다)
_MIN_STYLES = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    b'<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    b'<fonts count="1"><font/></fonts><fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
    b'<borders count="1"><border/></borders>'
    b'<cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="1"><xf/></cellXfs></styleSheet>'
)


def _rezip(data: bytes, drop: set[str], fix_styles: bool) -> bytes:
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            if info.filename in drop:
                continue
            body = src.read(info)
            if fix_styles and info.filename == "xl/styles.xml":
                body = _MIN_STYLES
            elif fix_styles and info.filename.startswith("xl/worksheets/") and info.filename.endswith(".xml"):
                body = _COL_STYLE.sub(rb"\1", _STYLE_ATTR.sub(rb"\1", body))
            dst.writestr(info, body)
    return out.getvalue()


def _open(data: bytes, data_only: bool):
    """한셀·구글 시트 등에서 만든 파일도 연다 (2026-2 총회 자료 실측 2건).

    값만 읽으므로 계산과 무관한 부분을 덜어 낸다: 깨진 사용자 정의 속성(docProps/custom.xml, 이름 없는 속성 → TypeError),
    없는 서식 번호를 가리키는 칸(IndexError)은 서식 번호를 지우고 다시 연다.
    """
    cleaned = _rezip(data, {"docProps/custom.xml"}, fix_styles=False)
    try:
        return load_workbook(io.BytesIO(cleaned), data_only=data_only)
    except IndexError:
        return load_workbook(io.BytesIO(_rezip(cleaned, set(), fix_styles=True)), data_only=data_only)


def _check_extent(wb) -> None:
    cells = sum(ws.max_row * ws.max_column for ws in wb.worksheets)
    if cells > MAX_CELLS:
        raise SheetTooLarge("표 범위가 너무 넓어요. 쓰지 않는 행·열을 지우거나 필요한 시트만 남겨 올려 주세요.")
_SHEET = r"(?:'(?P<sheet>[^']+)'|(?P<bare>[^\s!'(),+\-*/=]+))!"
_REF = re.compile(rf"(?:{_SHEET})?\$?(?P<col>[A-Z]{{1,3}})\$?(?P<row>\d+)")
_SUM = re.compile(r"SUM\(([^()]*)\)", re.I)
_FUNC = re.compile(r"[A-Z]{2,}\(", re.I)
_RECEIPT_HEADER = re.compile(r"영수증|번호|No\.?$", re.I)
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def _number(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def _safe_eval(expr: str) -> float | None:
    """숫자와 + - * / 괄호만 계산한다."""

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -walk(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.left), walk(node.right))
        raise ValueError(node)

    try:
        return walk(ast.parse(expr, mode="eval"))
    except (SyntaxError, ValueError, ZeroDivisionError, TypeError):
        return None


class _Book:
    def __init__(self, data: bytes):
        _guard(data)
        self.formulas = _open(data, data_only=False)
        _check_extent(self.formulas)
        self.values = _open(data, data_only=True)

    def value(self, sheet: str, coord: str):
        ws = self.values[sheet] if sheet in self.values.sheetnames else None
        return ws[coord].value if ws is not None else None

    def header_text(self, sheet: str, col: int, first_row: int) -> str:
        """범위 위쪽 10행 안에서 그 열의 머리글(글자 칸)을 찾는다."""
        ws = self.values[sheet]
        for row in range(first_row - 1, max(0, first_row - 11), -1):
            v = ws.cell(row=row, column=col).value
            if isinstance(v, str) and v.strip() and _number(v) is None:
                return v.strip()
        return ""


def _range_sum(book: _Book, sheet: str, ref: str) -> tuple[float, list[int]]:
    """'A1:B3' 합과 범위가 걸친 열 번호."""
    target = sheet
    if "!" in ref:
        target, ref = ref.rsplit("!", 1)
        target = target.strip("'")
    min_col, min_row, max_col, max_row = range_boundaries(ref.replace("$", ""))
    ws = book.values[target]
    # '=SUM(A1:XFD1048576)'처럼 시트보다 넓은 범위는 실제로 값이 있는 범위까지만 본다 (빈 칸 순회 방지)
    max_row, max_col = min(max_row, ws.max_row), min(max_col, ws.max_column)
    total = 0.0
    for row in ws.iter_rows(min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col, values_only=True):
        # 엑셀 SUM처럼 숫자 칸만 더한다 — '2,28' 같은 글자 칸(영수증번호 목록)은 건너뛴다
        total += sum(float(v) for v in row if isinstance(v, (int, float)) and not isinstance(v, bool))
    return total, list(range(min_col, max_col + 1))


def _recalculate(book: _Book, sheet: str, formula: str) -> tuple[float | None, list[tuple[list[int], int]]]:
    """수식을 다시 계산한다. 반환: (값 또는 None, [(SUM 범위의 열들, 시작 행)])."""
    body = formula.lstrip("=")
    ranges: list[tuple[list[int], int]] = []

    def sum_repl(m: re.Match) -> str:
        total = 0.0
        for part in m.group(1).split(","):
            part = part.strip()
            if ":" in part:
                value, cols = _range_sum(book, sheet, part)
                ranges.append((cols, range_boundaries(part.split("!")[-1].replace("$", ""))[1]))
            else:
                value = _expression(book, sheet, part) or 0
            total += value
        return repr(total)

    body = _SUM.sub(sum_repl, body)
    if _FUNC.search(body):
        return None, ranges  # 다시 계산하지 않는 함수가 남았다
    return _expression(book, sheet, body), ranges


def _expression(book: _Book, sheet: str, body: str) -> float | None:
    """칸 참조를 값으로 바꿔 사칙연산을 계산한다 (`D27+D30`, `O4*P4`)."""
    body = _REF.sub(lambda m: repr(_ref_value(book, sheet, m.group()) or 0.0), body)
    return _safe_eval(body)


def _ref_value(book: _Book, sheet: str, ref: str) -> float | None:
    m = _REF.fullmatch(ref.strip())
    if not m:
        return _number(ref)
    target = m["sheet"] or m["bare"] or sheet
    if target not in book.values.sheetnames:
        return None
    return _number(book.value(target, f"{m['col']}{m['row']}"))


def check_workbook(data: bytes) -> list[Finding]:
    book = _Book(data)
    found: list[Finding] = [*_check_unit_rows(book), *_check_fund_columns(book)]
    cells = 0
    for ws in book.formulas.worksheets:
        values = book.values[ws.title] if ws.title in book.values.sheetnames else None
        # 값이 있는 칸만 행 순서대로 본다 — iter_rows는 범위 안 빈 칸까지 모두 만들어 느리다 (16만 칸 시트 0.66초 → 0.01초)
        for (r, c), cell in sorted(ws._cells.items()):
            cells += 1
            if cells > MAX_CELLS:
                return found
            formula = cell.value
            where = f"{ws.title} {cell.coordinate}"
            stored = values._cells.get((r, c)) if values is not None else None
            cached = stored.value if stored is not None else None
            if isinstance(cached, str) and cached.startswith("#"):
                found.append(Finding(code="sheet_error", level="보완 필요", title=f"계산 오류 {cached}가 있어요",
                                     detail="참조한 칸이 지워졌거나 옮겨졌어요.", where=where))
                continue
            if not (isinstance(formula, str) and formula.startswith("=")):
                continue
            value, ranges = _recalculate(book, ws.title, formula)
            for cols, first_row in ranges:
                if len(cols) < 2:
                    continue
                headers = [book.header_text(ws.title, c, first_row) for c in cols]
                mixed = [h for h in headers if _RECEIPT_HEADER.search(h)]
                if mixed:
                    found.append(Finding(
                        code="sum_range", level="보완 필요",
                        title="합계 범위에 금액이 아닌 열이 섞여 있어요",
                        detail=f"{formula} 가 '{mixed[0]}' 열까지 더해요.", where=where,
                    ))
            cached_num = _number(cached)
            if value is not None and cached_num is not None and abs(value - cached_num) >= 1:
                found.append(Finding(
                    code="recalc", level="보완 필요",
                    title=f"저장된 계산값이 다시 계산한 값과 {won(round(abs(value - cached_num)))} 달라요",
                    detail=f"{formula} → 다시 계산 {won(round(value))} · 저장값 {won(round(cached_num))}",
                    where=where,
                ))
    return found


_FUND_HEADER = re.compile(r"학생회비|자치비|지원금|교비|기금|각출|참가비|회비|후원")
_TOTAL_HEADER = re.compile(r"^(?:총\s*계|합\s*계|계|총\s*액|소\s*계|총\s*금액)$")


def _check_fund_columns(book: _Book) -> list[Finding]:
    """재원별 열(과 지원금 | 학생회비 | 기금 | 총계)이 있는 표에서 줄마다 재원 합 = 총계인지 본다.

    2026-2 총회 자료: 현수막 줄의 학생회비 열에 14,900원이 있는데 총계 열은 0이라 표 전체가 14,900원 어긋난 예산안이
    세 판 모두 그대로 냈다. 빈 재원 칸은 0으로 보지만 총계 칸이 비면 그 줄은 판단하지 않는다.
    """
    found = []
    for ws in book.values.worksheets:
        reported: set[int] = set()  # 한 줄의 오류가 소계·총계로 번진 것은 처음 한 번만 알린다
        for header in ws.iter_rows(max_row=min(ws.max_row, 200)):
            funds, total = [], None
            for cell in header:
                if not isinstance(cell.value, str):
                    continue
                name = cell.value.replace(" ", "").strip()
                if _TOTAL_HEADER.match(name):
                    total = total or cell.column
                elif _FUND_HEADER.search(name) and len(name) <= 12:
                    funds.append((cell.column, cell.value.strip()))
            if len(funds) < 2 or total is None:
                continue
            for row in range(header[0].row + 1, min(ws.max_row, header[0].row + 300) + 1):
                stated = _number(ws.cell(row=row, column=total).value)
                parts = [_number(ws.cell(row=row, column=c).value) for c, _ in funds]
                if stated is None and all(v is None for v in parts):
                    break
                if stated is None or all(v is None for v in parts):
                    continue
                got = sum(v or 0 for v in parts)
                if abs(got - stated) >= 1 and round(got - stated) not in reported:
                    reported.add(round(got - stated))
                    label = next((str(c.value).strip() for c in ws[row] if isinstance(c.value, str) and c.value.strip()), f"{row}행")
                    detail = " + ".join(f"{n} {won(round(v or 0))}" for (_, n), v in zip(funds, parts))
                    found.append(Finding(
                        code="fund_columns", level="보완 필요",
                        title=f"{label}: 재원별 금액 합이 총계와 {won(round(abs(got - stated)))} 달라요",
                        detail=f"{detail} = {won(round(got))} · 총계 {won(round(stated))}",
                        where=f"{ws.title} {row}행",
                    ))
    return found


def _check_unit_rows(book: _Book) -> list[Finding]:
    """'단가 | 수량 | 금액' 머리글이 있는 표에서 단가 × 수량 ≠ 금액인 줄을 찾는다 (값이 숫자로 적힌 표)."""
    found = []
    for ws in book.values.worksheets:
        for header in ws.iter_rows(max_row=min(ws.max_row, 400)):
            cols = {}
            for cell in header:
                if isinstance(cell.value, str):
                    name = cell.value.replace(" ", "")
                    for key in ("단가", "수량", "금액"):
                        if name == key or name.startswith(key):
                            cols.setdefault(key, cell.column)
            if len(cols) < 3:
                continue
            for row in range(header[0].row + 1, min(ws.max_row, header[0].row + 300) + 1):
                unit, qty, amount = (_number(ws.cell(row=row, column=cols[k]).value) for k in ("단가", "수량", "금액"))
                if unit is None and qty is None and amount is None:
                    break
                if None not in (unit, qty, amount) and abs(unit * qty - amount) >= 1:
                    found.append(Finding(
                        code="unit_qty", level="보완 필요",
                        title="단가 × 수량이 금액과 달라요",
                        detail=f"{won(round(unit))} × {qty:g} = {won(round(unit * qty))} · 적힌 금액 {won(round(amount))}",
                        where=f"{ws.title} {row}행",
                    ))
    return found


_CELL = re.compile(r"\b[A-Z]{1,3}\d+=")


def _sheet_line(line: str) -> str:
    """엑셀 텍스트 줄('A6=항목 | B6=금액')을 표 줄('항목 금액')로. 숫자만 든 칸은 금액으로 본다."""
    cells = [c.strip(" |") for c in _CELL.split(line) if c.strip(" |")]
    return " ".join(f"{int(float(c)):,}원" if re.fullmatch(r"\d{3,}(?:\.0)?", c) else c for c in cells)


def table_text(text: str) -> str:
    """workbook_text 결과를 PDF 표처럼 읽히는 줄로 바꾼다 (규칙 기반 추출·원문 검사용)."""
    return "\n".join(_sheet_line(line) if _CELL.match(line) else line for line in text.splitlines())


def workbook_text(data: bytes, limit: int = 40_000) -> str:
    """LLM 추출용 텍스트: 시트별로 값이 있는 칸을 '좌표=값'으로 나열한다."""
    _guard(data)
    wb = _open(data, data_only=True)
    _check_extent(wb)
    out: list[str] = []
    size = 0
    for ws in wb.worksheets:
        out.append(f"## 시트: {ws.title}")
        for row in ws.iter_rows():
            parts = []
            for cell in row:
                v = cell.value
                if v is None or (isinstance(v, str) and not v.strip()):
                    continue
                if isinstance(v, float) and v.is_integer():
                    v = int(v)
                parts.append(f"{get_column_letter(cell.column)}{cell.row}={v}")
            if parts:
                line = " | ".join(parts)
                out.append(line)
                size += len(line)
                if size > limit:
                    out.append("…(이하 생략)")
                    return "\n".join(out)
    return "\n".join(out)
