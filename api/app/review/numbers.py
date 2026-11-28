"""금액 표기 해석: `5,698,191원`, `₩ 17,200,000`, `120만원`, `(육백만원)`, `백삼십만원`."""

import re

_DIGITS = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
_SMALL = {"십": 10, "백": 100, "천": 1000}
_BIG = {"만": 10_000, "억": 100_000_000}

_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+|\d+")


def to_int(text: str) -> int | None:
    """`5,698,191` → 5698191. 숫자가 없으면 None."""
    m = _NUMBER.search(text or "")
    return int(m.group().replace(",", "")) if m else None


def korean_amount(text: str) -> int | None:
    """한글·혼용 금액을 정수로: `육백만원` 6,000,000 · `백삼십만원` 1,300,000 · `120만원` 1,200,000.

    해석할 수 없는 글자가 섞이면 None (추측하지 않는다).
    """
    s = re.sub(r"[\s,원정]", "", text or "")
    if not s:
        return None
    total, section, number = 0, 0, 0
    i = 0
    while i < len(s):
        ch = s[i]
        if ch.isdigit():
            j = i
            while j < len(s) and s[j].isdigit():
                j += 1
            number = int(s[i:j])
            i = j
            continue
        if ch in _DIGITS:
            number = _DIGITS[ch]
        elif ch in _SMALL:
            section += (number or 1) * _SMALL[ch]
            number = 0
        elif ch in _BIG:
            total += (section + number or 1) * _BIG[ch]
            section, number = 0, 0
        else:
            return None
        i += 1
    return total + section + number


def won(value: int | None) -> str:
    """5698191 → '5,698,191원'"""
    return "—" if value is None else f"{value:,}원"
