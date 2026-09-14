"""개인정보 결정론적 마스킹 — 프롬프트 지시의 안전망.

LLM에게 "실명을 쓰지 마라"고 지시하지만 지시는 확률적이다. 답변·근거·인용이
사용자에게 나가기 직전에 코드가 한 번 더 지운다.

- 전화번호·계좌번호·이메일: 형식이 정형적이라 정규식으로 잡는다.
- 실명: 운영자가 준 목록(PRIVATE_NAMES 환경변수 또는 private_names.txt)으로
  치환한다. 목록은 저장소에 두지 않는다 — 실명 비노출을 검증하는 코드가
  실명을 공개하는 일이 없도록.
"""

import os
import re
from pathlib import Path

from app.config import DATA_DIR

_PHONE = re.compile(r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}")
_ACCOUNT = re.compile(r"(?<!\d)\d{3,6}-\d{2,6}-\d{4,8}(?:-\d{1,4})?(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (_PHONE, "010-****-****"),
    (_ACCOUNT, "(계좌번호 비공개)"),
    (_EMAIL, "(이메일 비공개)"),
]

NAME_MASK = "○○○"


def _load_names() -> list[str]:
    raw = os.getenv("PRIVATE_NAMES", "")
    if not raw:
        for path in (
            Path(__file__).resolve().parents[1] / "private_names.txt",
            DATA_DIR / "private_names.txt",
        ):
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                break
    names = {n.strip() for n in re.split(r"[,\n]", raw) if n.strip()}
    # 긴 이름부터 치환해야 "홍길동"이 "홍길"에 먼저 잡히지 않는다
    return sorted(names, key=len, reverse=True)


PRIVATE_NAMES: list[str] = _load_names()

# 스트리밍 중 아직 내보내지 않고 붙들어 두는 꼬리 길이.
# 어떤 패턴도 이 길이보다 길지 않아야 토큰 경계를 걸친 일치를 놓치지 않는다.
_HOLD = 32


def _spans(text: str) -> list[tuple[int, int]]:
    spans = [m.span() for pat, _ in _PATTERNS for m in pat.finditer(text)]
    for name in PRIVATE_NAMES:
        start = text.find(name)
        while start != -1:
            spans.append((start, start + len(name)))
            start = text.find(name, start + 1)
    return spans


def find_private_name(text: str) -> str | None:
    """텍스트에 등록된 실명이 있으면 그 이름을 돌려준다.

    "성 보현"처럼 띄어 쓴 변형도 잡기 위해 공백을 지운 사본도 함께 본다.
    """
    if not text:
        return None
    compact = re.sub(r"\s+", "", text)
    for name in PRIVATE_NAMES:
        if name in text or name in compact:
            return name
    return None


def mask_text(text: str) -> str:
    if not text:
        return text
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    for name in PRIVATE_NAMES:
        text = text.replace(name, NAME_MASK)
    return text


def mask_obj(obj):
    """dict/list 안의 모든 문자열을 재귀적으로 마스킹한다 (새 객체 반환)."""
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, dict):
        return {k: mask_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_obj(v) for v in obj]
    return obj


class StreamMasker:
    """토큰 스트림용 마스킹. 패턴이 토큰 경계에 걸쳐 도착해도 놓치지 않도록
    꼬리를 붙들어 두고, 확정된 앞부분만 마스킹해 내보낸다."""

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, text: str) -> str:
        self._buf += text
        if len(self._buf) <= _HOLD:
            return ""
        cut = len(self._buf) - _HOLD
        # 경계를 걸친 일치가 있으면 그 시작점까지만 내보낸다
        for start, end in _spans(self._buf):
            if start < cut < end:
                cut = min(cut, start)
        if cut <= 0:
            return ""
        out, self._buf = self._buf[:cut], self._buf[cut:]
        return mask_text(out)

    def flush(self) -> str:
        out, self._buf = self._buf, ""
        return mask_text(out)
