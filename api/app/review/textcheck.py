"""원문 텍스트에 대한 검사. 구조 추출(LLM)이 놓치거나 고쳐 버려도 원문의 식·표기를 직접 확인한다.

- 인라인 식 `7,300 * 50 = 365,000원` 재계산
- 숫자 금액과 한글 병기 `6,000,000원 (육백만원)` 대조
- 날짜와 요일 `2025.05.11(월)` 대조 (연도 없는 `11월 30일 (화)`는 앞에 나온 연도로)
- 표 한 줄의 식과 금액 칸 `콜라 | 2,000*90 | 171,000원` 대조
- 금액 표기 오기 `250.000원`·`480,00`·`4,0000원`
- 'VAT 별도'와 'VAT 포함'이 함께 나오는지
- 현금 지출 한도, 개인 명의 통장, 공개 문서의 계좌번호, 민감정보 수집
"""

import re
from datetime import date

from app.privacy import mask_text
from app.review.blocks import GROUP_TOTAL, PROJECT_TOTAL, TERM_TOTAL, check_block_totals, check_cross_tables, parse_blocks, row_of
from app.review.models import Finding
from app.review.numbers import korean_amount, to_int, won

CASH_BASIS = "「재정·회계 세칙」 제31조 제3항(현금 지출은 15만 원 이하, 총학생회·총대의원회는 25만 원 이하)"
ACCOUNT_BASIS = "「재정·회계 세칙」 제31조 제2항(수입은 공금전용계좌로)"
SENSITIVE_BASIS = "「개인정보 보호법」 제23조(건강 등 민감정보는 별도 동의)"
CASH_LIMIT = 150_000

# 숫자는 숫자·쉼표 바로 뒤에서 시작하지 않고(중간 자리에서 다시 맞추기 금지) 자릿수를 묶는다 — 긴 숫자열이 제곱 시간이 되지 않게(보안 점검)
_NUM = r"(?<![\d,])(?:\d{1,3}(?:,\d{3}){1,5}|\d{1,15})(?![\d])"
_UNIT = r"(?:\s*(?:원|명|인분|인|개|EA|ea|병|부|장|세트|회|팀|박스|매))?"
_FORMULA = re.compile(
    rf"(?P<expr>(?:{_NUM}){_UNIT}(?:\s*[*×+]\s*(?:{_NUM}){_UNIT})+)\s*=\s*(?P<result>{_NUM})"
)
_KOREAN = re.compile(rf"(?P<num>{_NUM})\s*원\s*\(\s*(?P<kor>[일이삼사오육칠팔구십백천만억\d\s]+원)\s*\)")
_DATE_DAY = re.compile(
    r"(?P<y>20\d{2})\s*[.\-/년]\s*(?P<m>\d{1,2})\s*[.\-/월]\s*(?P<d>\d{1,2})\s*[.일]?\s*\(\s*(?P<w>[월화수목금토일])\s*\)"
)
_WEEKDAYS = "월화수목금토일"
# 연도 없이 쓴 날짜 '11월 30일 (화)' — 연도는 앞에 나온 마지막 연도로 정한다
_MONTH_DAY = re.compile(r"(?<![\d.])(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일\s*\(\s*(?P<w>[월화수목금토일])\s*\)")
_YEAR = re.compile(r"(20\d{2})\s*(?:년|[.\-/]\s*\d{1,2}\s*[.\-/])")
# 표 한 칸의 곱셈식 (= 없이 옆 칸에 금액을 두는 학생회 예산표 방식). x·X도 곱하기로 쓴다
_CELL_FORMULA = re.compile(
    rf"(?P<expr>(?:{_NUM})(?:\s*원)?(?:\s*[*×xX]\s*(?:{_NUM}){_UNIT})+)"
)
_CELL_AMOUNT = re.compile(rf"^\s*(?P<num>{_NUM})\s*원?\s*(?:\(.*\))?\s*$")
# 금액 표기 오기: 천 단위를 마침표로(250.000원), 쉼표 뒤 두 자리(480,00), 쉼표 뒤 네 자리 이상(4,0000원)
_BAD_NUMBER = re.compile(
    r"(?<![\d.,])(?:\d{1,3}(?:\.\d{3})+\s*원|\d{3}(?:,\d{3})*,\d{1,2}(?![\d,.])|\d{1,3}(?:,\d{3})*,\d{1,2}\s*원|\d{1,3},\d{4,}(?![\d,]))"
)
_PERSONAL_ACCOUNT = re.compile(r"[가-힣]{2,8}\s*명의\s*(?:의\s*)?(?:기금\s*)?(?:통장|계좌)")
_ACCOUNT_NUMBER = re.compile(r"(?<![\d-])(?!01[016789]-)\d{2,6}-\d{2,6}-\d{2,8}(?![\d-])")
_SENSITIVE = re.compile(r"질환|복용\s*약물|병력|주민\s*등록\s*번호|주민번호")
_CASH_WORD = re.compile(r"현금(?!\s*(?:영수증|IC|ic|캐시백))")
# '현금 대신 계좌이체'·'현금 지급 금지'처럼 현금을 쓰지 말라는 말
_CASH_NEGATED = re.compile(
    r"현금\s*(?:대신|말고|이\s*아닌)|현금(?:은|으로는)\s*안\s*(?:되|돼|받|써)"
    r"|현금\s*(?:으로\s*)?(?:지급|결제|사용|수납|거래)?\s*(?:은|는|을|를)?\s*(?:금지|불가(?!피)|지양|하지\s*않(?!으면))"
)
_CLAUSE = re.compile(r"\s/\s|※|(?<=[다요.])\s+(?=\S)")


def _flat(text: str) -> str:
    """줄바꿈·연속 공백을 한 칸으로 (칸 안 줄바꿈으로 쪼개진 식·금액을 다시 잇는다)."""
    return re.sub(r"\s+", " ", text)


def _snippet(text: str, start: int, end: int, pad: int = 24) -> str:
    """찾은 곳 앞뒤 조각. 금액·단어 가운데서 자르지 않게 가까운 띄어쓰기까지 넓힌다 ('000원은 현금으로'처럼 잘리지 않게)."""
    a, b = max(0, start - pad), min(len(text), end + pad)
    while a > 0 and not text[a - 1].isspace() and start - a < pad + 12:
        a -= 1
    while b < len(text) and not text[b].isspace() and b - end < pad + 12:
        b += 1
    # 숫자·하이픈 덩어리(전화·계좌번호) 가운데서 자르면 마스킹이 번호로 알아보지 못해 꼬리가 남는다 — 덩어리 끝까지 넓힌다
    # (번호 길이만큼만 — 목차 점선·'-----' 같은 긴 줄로 조각이 부풀지 않게)
    stop_a, stop_b = max(0, a - 20), min(len(text), b + 20)
    while a > stop_a and (text[a - 1].isdigit() or text[a - 1] in "-."):
        a -= 1
    while b < stop_b and (text[b].isdigit() or text[b] in "-."):
        b += 1
    return mask_text(text[a:b].strip())


def _evaluate(expr: str) -> int:
    """`7,300원 * 50 + 1,000` → 366,000 (곱셈 먼저)."""
    total = 0
    for term in expr.split("+"):
        value = 1
        for factor in re.split(r"[*×]", term):
            value *= to_int(factor) or 0
        total += value
    return total


def _whole_formula(flat: str, m: re.Match) -> bool:
    """식 전체를 읽었는지. '100 - 20 + 10 = 90'에서 '20 + 10'만 잡거나 '1.5 * 10'에서 '5 * 10'만 잡으면
    정상 식을 오류로 판정한다 — 지원하지 않는 연산(빼기·나누기)·소수가 붙어 있으면 검사하지 않는다."""
    before = flat[: m.start()].rstrip()
    if before and before[-1] in "0123456789.,-−/÷":
        return False
    after = flat[m.end():]
    return not re.match(r"\.\d", after)


def check_formulas(text: str) -> list[Finding]:
    flat, found, seen = _flat(text), [], set()
    for m in _FORMULA.finditer(flat):
        if not _whole_formula(flat, m):
            continue
        expected, stated = _evaluate(m["expr"]), to_int(m["result"])
        key = (m["expr"].strip(), stated)
        if stated is None or expected == stated or key in seen:
            continue
        seen.add(key)
        found.append(Finding(
            code="formula",
            level="보완 필요",
            title=f"계산식 결과가 {won(abs(expected - stated))} 달라요",
            detail=f"{m['expr'].strip()} = {won(expected)} · 문서에는 {won(stated)}",
            where=_snippet(flat, m.start(), m.end()),
        ))
    return found


def check_korean_amounts(text: str) -> list[Finding]:
    flat, found = _flat(text), []
    for m in _KOREAN.finditer(flat):
        digits, korean = to_int(m["num"]), korean_amount(m["kor"])
        if digits is None or korean is None or digits == korean:
            continue
        found.append(Finding(
            code="korean_amount",
            level="보완 필요",
            title="숫자 금액과 한글 금액이 달라요",
            detail=f"숫자 {won(digits)} · 한글 {m['kor'].strip()}({won(korean)})",
            where=_snippet(flat, m.start(), m.end()),
        ))
    return found


def _dated_weekdays(flat: str):
    """(날짜, 적힌 요일, 위치) — 연도가 있는 날짜와, 연도 없는 날짜(앞에 나온 연도를 붙임)."""
    taken = []
    for m in _DATE_DAY.finditer(flat):
        taken.append((m.start(), m.end()))
        try:
            yield date(int(m["y"]), int(m["m"]), int(m["d"])), m["w"], m
        except ValueError:
            continue
    for m in _MONTH_DAY.finditer(flat):
        if any(a <= m.start() < b for a, b in taken):
            continue
        years = _YEAR.findall(flat[: m.start()])
        if not years:
            continue  # 연도를 모르면 판단하지 않는다
        try:
            yield date(int(years[-1]), int(m["m"]), int(m["d"])), m["w"], m
        except ValueError:
            continue


def check_weekdays(text: str) -> list[Finding]:
    flat, found, seen = _flat(text), [], set()
    for day, written, m in _dated_weekdays(flat):
        actual = _WEEKDAYS[day.weekday()]
        if actual == written or day in seen:
            continue
        seen.add(day)
        found.append(Finding(
            code="weekday",
            level="보완 필요",
            title=f"{day:%Y.%m.%d}은 {written}요일이 아니라 {actual}요일이에요",
            detail="연도나 날짜가 잘못 적혔을 수 있어요.",
            where=_snippet(flat, m.start(), m.end()),
        ))
    return found


def _partial(cell: str, m: re.Match) -> bool:
    """식의 일부만 읽었는지: 앞에 숫자·연산('17원/명*450')이 붙었거나 뒤에 소수('*0.1')가 이어진다."""
    return bool(re.search(r"[\d.,/*×xX+\-]\s*$", cell[: m.start()]) or re.match(r"\.\d", cell[m.end():]))


def check_row_formulas(text: str) -> list[Finding]:
    """표 한 줄에서 식 칸과 바로 뒤 금액 칸을 대조한다 (2026-2 총회 자료: 두 줄의 금액이 맞바뀐 표가 파일 5개에 그대로 있었다).

    식 앞에 다른 숫자·연산이 붙어 있으면('17원/명*450*15회') 식 전체를 읽지 못한 것이라 건너뛴다.
    절반 지원처럼 일부러 다른 금액일 수 있어 '확인 필요'로 둔다.
    """
    found, seen = [], set()
    for line in text.splitlines():
        if " | " not in line or "=" in line:
            continue  # '='가 있는 식은 check_formulas가 본다
        cells = line.split(" | ")
        for i, cell in enumerate(cells[:-1]):
            matches = list(_CELL_FORMULA.finditer(cell))
            if not matches or any(_partial(cell, x) for x in matches):
                continue
            amount = _CELL_AMOUNT.match(cells[i + 1])
            if not amount:
                continue
            expr = " + ".join(x["expr"].strip() for x in matches)
            expected, stated = sum(_evaluate(re.sub(r"[xX]", "*", x["expr"])) for x in matches), to_int(amount["num"])
            key = (expr, stated)
            if stated is None or expected == stated or key in seen:
                continue
            seen.add(key)
            found.append(Finding(
                code="row_formula",
                level="확인 필요",
                title=f"식과 금액 칸이 {won(abs(expected - stated))} 달라요",
                detail=f"{expr} = {won(expected)} · 금액 칸 {won(stated)}. 일부만 지원하는 금액이면 비고에 적어 두세요.",
                where=mask_text(line.strip()[:80]),
            ))
    return found


_LOOKS_MONEY = re.compile(r"\d\s*(?:만|천)?\s*원")


def check_subtotals(text: str) -> list[Finding]:
    """'예산 세부 내역 판단 자료'의 세 단계 합계를 단계마다 다시 더한다 (총대 양식 A, 2026-2 총회 자료 38개 파일).

    사업별 총 비용 = 그 사업의 줄 합, N월(또는 상시사업) 총 사업 진행 비용 = 그 묶음의 사업별 합계(없으면 줄)의 합,
    학기 총 사업 진행 비용 = 묶음 합계의 합.
    합계 줄을 다시 항목으로 더하지 않는다. 어느 단계든 금액을 못 읽은 줄이 있으면 그 단계는 판단하지 않는다.
    """
    found: list[Finding] = []
    items: list[int | None] = []
    projects: list[int] = []
    months: list[int] = []
    active = False
    for line in text.splitlines():
        if "세부 내용" in line.replace("세부내용", "세부 내용") and "금액" in line and " | " in line:
            active, items, projects, months = True, [], [], []
            continue
        if not active or " | " not in line:
            continue
        cells = [c.strip() for c in line.split(" | ")]
        amount = row_of(cells).amount  # 예산표와 같은 줄 해석 (만원·괄호 꼬리·식의 = 값·수량 칸)
        label = " ".join(cells)

        def mismatch(kind: str, parts: list[int | None], stated: int | None):
            if stated is None or not parts or any(x is None for x in parts):
                return
            total = sum(parts)  # type: ignore[arg-type]
            if total != stated:
                found.append(Finding(
                    code="subtotal",
                    level="보완 필요",
                    title=f"{kind}이 아래 단계 합과 {won(abs(total - stated))} 달라요",
                    detail=f"적힌 금액 {won(stated)} · 더하면 {won(total)}",
                    where=mask_text(line.strip()[:80]),
                ))

        unread = amount is None and any(_LOOKS_MONEY.search(c) for c in cells)  # '10만원'처럼 금액인데 못 읽음
        if TERM_TOTAL.search(label):
            mismatch("학기 총 사업 진행 비용", months + projects, amount)  # type: ignore[arg-type]  # 달 합계가 없는 사업도 더한다
            active = False
        elif group := GROUP_TOTAL.search(label):
            # 묶음은 사업별 합계를 모은 것(월)일 수도, 줄을 바로 더한 것(상시 사업)일 수도 있다.
            # 앞 사업의 달 합계 줄이 빠진 문서도 있어, 셋 중 하나와 맞으면 맞는 것으로 보고 남은 쪽은 학기 합계로 넘긴다.
            pending = projects
            if amount is not None and items and None not in items and sum(items) == amount:  # type: ignore[arg-type]
                pass  # 줄만 더한 묶음 — 앞 사업 합계는 학기 합계로
            elif amount is not None and projects and None not in projects and sum(projects) == amount:  # type: ignore[arg-type]
                pending = []
            else:
                mismatch(f"{group['name']} 총 사업 진행 비용", projects + items, amount)  # type: ignore[arg-type]
                pending = []
            if amount is not None or unread:
                months.append(amount)
            projects, items = pending, []
        elif PROJECT_TOTAL.search(label):
            mismatch("사업별 총 비용", items, amount)
            if amount is not None or unread:
                projects.append(amount)  # 못 읽었으면 None — 학기 합계 비교를 멈춘다
            items = []
        elif amount is not None:
            items.append(amount)
        elif unread:
            items.append(None)  # 일부만 더해 틀렸다고 하지 않는다
    return found


def check_number_format(text: str) -> list[Finding]:
    """천 단위 마침표·자리 어긋난 쉼표처럼 읽는 사람마다 다르게 읽을 금액 표기."""
    flat, found, seen = _flat(text), [], set()
    for m in _BAD_NUMBER.finditer(flat):
        token = m[0].strip()
        if token in seen:
            continue
        seen.add(token)
        found.append(Finding(
            code="number_format",
            level="보완 필요",
            title=f"금액 표기 '{token}'를 확인해 주세요",
            detail="천 단위는 쉼표로 세 자리씩 끊어요(예: 250,000원). 자릿수가 틀리면 금액이 다르게 읽혀요.",
            where=_snippet(flat, m.start(), m.end()),
        ))
    return found


def check_vat(text: str) -> list[Finding]:
    flat = _flat(text)
    excluded = re.search(r"(?:VAT|부가세|부가가치세)\s*별도", flat)
    included = re.search(r"(?:VAT|부가세|부가가치세)\s*포함", flat)
    if not (excluded and included):
        return []
    return [Finding(
        code="vat",
        level="확인 필요",
        title="'VAT 별도'와 'VAT 포함'이 함께 적혀 있어요",
        detail="VAT 별도 금액이면 결제할 때 10%가 더 나가요. 예산 안에 들어가는지 확인해 주세요.",
        where=_snippet(flat, excluded.start(), excluded.end()),
    )]


def check_cash(text: str) -> list[Finding]:
    """'현금' 이 들어간 줄에서 15만 원을 넘는 금액을 찾는다 (현금영수증·현금IC는 제외)."""
    found = []
    for line in text.splitlines():
        if not _CASH_WORD.search(line):
            continue
        # 표 줄(' | ')은 한 지출이라 나누지 않는다. 글 줄은 문장으로 나눠, '현금 대신 계좌이체'처럼 현금을 쓰지 말라는
        # 문장의 금액만 뺀다 ('상한 30만 원 초과 / ※ 현금 대신 계좌이체'). 현금을 쓰는 문장이 하나도 없으면 넘어간다.
        clauses = [line] if " | " in line else _CLAUSE.split(line)
        if not any(_CASH_WORD.search(c) and not _CASH_NEGATED.search(c) for c in clauses):
            continue
        kept = [c for c in clauses if not _CASH_NEGATED.search(c)]
        amounts = [to_int(n) or 0 for c in kept for n in re.findall(rf"(?:{_NUM})\s*원", c)]
        amounts += [korean_amount(k) or 0 for c in kept for k in re.findall(r"\d+\s*만\s*원", c)]
        over = [a for a in amounts if a > CASH_LIMIT]
        if over:
            found.append(Finding(
                code="cash",
                level="위반 소지",
                title=f"{won(max(over))}을 현금으로 지급하는 계획이 있어요",
                detail="단과대·학과는 15만 원을 넘는 지출을 현금으로 할 수 없어요. 계좌이체·카드로 바꿔 주세요.",
                basis=CASH_BASIS,
                where=mask_text(line.strip()[:120]),
            ))
    return found


def check_accounts(text: str) -> list[Finding]:
    flat, found = _flat(text), []
    if m := _PERSONAL_ACCOUNT.search(flat):
        found.append(Finding(
            code="personal_account",
            level="확인 필요",
            title="개인 명의 통장으로 돈을 받는 계획이 있어요",
            detail="자치기구 수입은 공금전용계좌로 받아야 해요. 개인 명의 계좌라면 바꿔 주세요.",
            basis=ACCOUNT_BASIS,
            where=_snippet(flat, m.start(), m.end()),
        ))
    if _ACCOUNT_NUMBER.search(flat):
        found.append(Finding(
            code="account_number",
            level="확인 필요",
            title="문서에 계좌번호가 그대로 있어요",
            detail="총회 자료는 공개될 수 있어요. 계좌번호는 공지·신청 안내에서 따로 알리는 편이 안전해요.",
        ))
    return found


def check_sensitive(text: str) -> list[Finding]:
    m = _SENSITIVE.search(_flat(text))
    if not m:
        return []
    return [Finding(
        code="sensitive",
        level="확인 필요",
        title=f"'{m.group()}' 정보를 모으는 계획이 있어요",
        detail="건강 정보·주민등록번호는 꼭 필요한 경우에만, 따로 동의를 받고 행사 뒤 파기해요.",
        basis=SENSITIVE_BASIS,
        where=_snippet(_flat(text), m.start(), m.end()),
    )]


def _document_year(text: str) -> int | None:
    """표지(첫 쪽)의 작성일 연도."""
    first = text.split("[2쪽]", 1)[0]
    m = re.search(r"(20\d{2})\s*[.\-/년]\s*\d{1,2}\s*[.\-/월]\s*\d{1,2}", first)
    return int(m[1]) if m else None


# 두 자리 연도 '25. 10. 5.' (시기 줄에서만 본다 — 다른 곳의 '1. 2. 3.' 같은 번호와 헷갈리지 않게)
_SHORT_YEAR = re.compile(r"(?<![\d.])(\d{2})\.\s*\d{1,2}\.\s*\d{1,2}\.")


def check_schedule_years(text: str) -> list[Finding]:
    """'시기' 줄의 연도가 표지 연도보다 앞서면 지난 문서를 복사한 흔적일 수 있다."""
    from app.review.rules import year_title

    doc_year = _document_year(text)
    if not doc_year:
        return []
    found, seen = [], set()
    for m in re.finditer(r"시\s*기\s*[:：]?\s*([^\n]{0,40})", text):
        years = [int(y) for y in re.findall(r"(20\d{2})\s*[.\-/년]\s*\d{1,2}", m[1])]
        years += [2000 + int(y) for y in _SHORT_YEAR.findall(m[1]) if 15 <= int(y) <= 40]
        for year in years:
            if year < doc_year and year not in seen:
                seen.add(year)
                found.append(Finding(
                    code="event_year", level="확인 필요", title=year_title(year, doc_year),
                    detail="지난 문서를 복사하면서 연도가 남은 것일 수 있어요.", where=mask_text(m[0].strip()),
                ))
    return found


def check_text(text: str) -> list[Finding]:
    blocks = parse_blocks(text)  # 예산표는 한 번만 읽어 두 검사가 함께 쓴다
    return [
        *check_schedule_years(text),
        *check_formulas(text),
        *check_row_formulas(text),
        *check_subtotals(text),
        *check_block_totals(text, blocks),
        *check_cross_tables(text, blocks),
        *check_number_format(text),
        *check_korean_amounts(text),
        *check_weekdays(text),
        *check_vat(text),
        *check_cash(text),
        *check_accounts(text),
        *check_sensitive(text),
    ]
