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
# 길이를 제한한다 — 무한정이면 스트림 보류 길이보다 긴 이메일의 앞부분이 먼저 나간다
_EMAIL = re.compile(r"[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,4}")

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
# 이름 매칭은 한 곳에서: 글자 사이 공백을 허용해 "홍 길 동" 같은 변형도 같은 이름으로 본다.
# 검사(find)와 치환(mask)이 다른 기준을 쓰면 검사는 잡고 치환은 놓치는 틈이 생긴다.
_NAME_PATTERNS: list[re.Pattern] = [
    re.compile(r"\s*".join(re.escape(ch) for ch in name)) for name in PRIVATE_NAMES
]

# 스트리밍 보류 규칙: 전화·계좌·이메일·실명은 모두 공백을 포함하지 않는다(전화의
# 구분 공백만 예외이고, 그건 아래 경계 검사가 잡는다). 그러므로 마지막 공백 뒤의
# 토막은 아직 끝나지 않은 패턴일 수 있어 붙들고, 그 앞은 확정으로 내보낸다.
# 고정 길이 보류(32·96자)는 정규식이 허용하는 최대 길이보다 짧아 앞부분이 샜다.
_WS = (" ", "\n", "\t")
_HOLD_MAX = 512  # 공백 없는 토막이 이보다 길면(URL·표) 앞부분은 내보낸다
# 전화번호만 공백으로 나뉠 수 있다("010 1234 5678"). 버퍼 끝이 전화번호의 앞부분이면
# 아직 끝나지 않은 것으로 보고 그 시작점 앞에서 끊는다 (최대 14자 보류).
_PHONE_PREFIX = re.compile(r"01[016789][-.\s]?\d{0,4}[-.\s]?\d{0,4}$")


def _spans(text: str) -> list[tuple[int, int]]:
    spans = [m.span() for pat, _ in _PATTERNS for m in pat.finditer(text)]
    for pat in _NAME_PATTERNS:
        spans.extend(m.span() for m in pat.finditer(text))
    return spans


def find_private_name(text: str) -> str | None:
    """텍스트에 등록된 실명이 있으면 그 이름을 돌려준다.

    글자 사이 공백 변형("성 보현")도 같은 이름으로 본다 (_NAME_PATTERNS).
    """
    if not text:
        return None
    for name, pat in zip(PRIVATE_NAMES, _NAME_PATTERNS):
        if pat.search(text):
            return name
    return None


def mask_text(text: str) -> str:
    if not text:
        return text
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    for pat in _NAME_PATTERNS:
        text = pat.sub(NAME_MASK, text)
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
        # 마지막 공백까지가 확정 구간. 공백 없이 너무 길면 상한만큼만 붙든다.
        cut = max(self._buf.rfind(ch) for ch in _WS) + 1
        cut = max(cut, len(self._buf) - _HOLD_MAX)
        if partial := _PHONE_PREFIX.search(self._buf):
            cut = min(cut, partial.start())
        # 경계를 걸친 일치(공백 구분 전화번호 등)가 있으면 그 시작점까지만 내보낸다
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
