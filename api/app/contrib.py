"""서비스 개선용 자료 — 이용자가 '개선에 쓰도록 허락'을 고른 요청만 가명 처리해 보관한다 (기본 허락, 해제 가능).

보관: 원본 파일은 버리고, 추출한 본문과 결과를 가명 처리해 1년. 이용자가 확인 표에서 고친 값(정답)도 붙인다.
쓰임: 평가셋·규칙·프롬프트 개선. 외부 회사의 모델 학습에 넘기지 않는다.
철회: 본인이 언제든 모두 지울 수 있다(DELETE /api/contributions/mine). 계정이 지워지면 함께 지운다.
"""

import hashlib
import hmac
import json
import re

from fastapi import APIRouter, Depends

from app import db
from app.auth import current_user, origin_guard
from app.config import IP_HASH_SALT
from app.privacy import mask_text

CONSENT_VERSION = "2026-11-28"
KINDS = ("review", "plan", "minutes")
MAX_TEXT = 60_000

# 인하대 학번(12 + 입학 연도 두 자리 + 네 자리)과 주민등록번호. 금액은 쉼표가 있거나 구조화 값(숫자)이라 겹치지 않는다
_STUDENT_ID = re.compile(r"(?<![\d,.-])12[0-3]\d{5}(?![\d,.-])")
_RRN = re.compile(r"(?<!\d)\d{6}-[1-4]\d{6}(?!\d)")
# 직책·칸 이름 바로 뒤의 2~4글자 한글은 사람 이름으로 본다 ("학생회장 홍길동", "성명 | 홍길동", "예금주: 홍길동")
_ROLE = (
    "성명|이름|책임자|담당자|작성자|수령자|수령인|신청자|대표자|예금주|"
    "부학생회장|학생회장|부회장|회장|부위원장|위원장|사무국장|재무국장|국장|차장|부장|팀장|총무|급대표|과대표|과대|대표"
)
_ROLE_NAME = re.compile(rf"({_ROLE})(\s*[:：|]?\s*)([가-힣]{{2,4}})(?![가-힣])")
# 명단 줄('참석자: 가나다, 라마바', '성명 | 가나다')과 호칭('가나다 학우', '가나다님') — 여기서 찾은 이름은 문서 전체에서 가린다
_LIST_LINE = re.compile(r"(?:참석자|참석|불참|명단|성명|이름|담당|위원)\s*(?:\([^)]*\))?\s*[:：|]\s*([^\n]+)")
# 호칭: '가나다 학우(가)'·'가나다 씨'·'가나다님'(님은 세 글자만 — '선생님'·'교수님'을 이름으로 잡지 않게)
_HONORIFIC = re.compile(r"(?<![가-힣])(?:([가-힣]{2,4})\s?(?:학우|씨)|([가-힣]{3})님)")
_NAME_TOKEN = re.compile(r"^[가-힣]{2,4}$")
_NAME_COLUMN = re.compile(r"^(?:성명|이름|참석자|담당자|수령자|수령인|신청자|예금주)$")
# 직책 뒤에 오지만 이름이 아닌 말
_NOT_NAME = {
    "선거", "선출", "임명", "해임", "직무", "직무대행", "권한", "대행", "권한대행", "명의", "직인", "서명", "날인", "인준",
    "사업", "예산", "후보", "후보자", "당선", "당선인", "외", "및", "등", "이하", "이상", "단", "단위", "회의", "결의서",
    "임기", "공석", "선임", "포함", "제외", "확인", "승인", "보고", "참석", "불참", "지명", "명단", "직책", "소속",
}


def _role_name(m: re.Match) -> str:
    return m.group(0) if m.group(3) in _NOT_NAME else f"{m.group(1)}{m.group(2)}[이름]"


def listed_names(text: str) -> set[str]:
    """명단·성명 칸·호칭에서 사람 이름으로 보이는 2~4글자를 모은다. 직책·흔한 말은 뺀다."""
    names: set[str] = set()

    def add(token: str) -> None:
        token = re.sub(r"(?:학우|님|씨)$", "", token.strip())
        if _NAME_TOKEN.match(token) and token not in _NOT_NAME and not re.fullmatch(_ROLE, token):
            names.add(token)

    # 표: '성명 | 학번' 머리 줄 아래 행의 같은 칸
    column = None
    for line in (text or "").splitlines():
        cells = [c.strip() for c in line.split("|")] if "|" in line else []
        if not cells:
            column = None
            continue
        found = next((i for i, c in enumerate(cells) if _NAME_COLUMN.match(re.sub(r"\s+", "", c))), None)
        if found is not None:
            column = found
        elif column is not None and column < len(cells):
            add(cells[column])
    for m in _LIST_LINE.finditer(text or ""):
        for token in re.split(r"[\s,·/|()]+", m.group(1)):
            add(token)
    for m in _HONORIFIC.finditer(text or ""):
        name = m.group(1) or m.group(2)
        if name not in _NOT_NAME and not re.fullmatch(_ROLE, name):
            names.add(name)
    return names


def deidentify(text: str, names: set[str] = frozenset()) -> str:
    """등록 실명·전화·계좌·이메일(mask_text)에 더해 학번·주민번호·직책 뒤 이름, 명단에서 찾은 이름(names)을 가린다.
    지나치게 가리는 쪽을 택한다."""
    if not text:
        return text
    text = mask_text(text)
    text = _RRN.sub("[주민번호]", text)
    text = _STUDENT_ID.sub("[학번]", text)
    text = _ROLE_NAME.sub(_role_name, text)
    for name in sorted(names | listed_names(text), key=len, reverse=True):
        text = re.sub(rf"(?<![가-힣]){re.escape(name)}", "[이름]", text)
    return text


def _deidentify_obj(obj, names: set[str] = frozenset()):
    if isinstance(obj, str):
        return deidentify(obj, names)
    if isinstance(obj, dict):
        return {k: _deidentify_obj(v, names) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deidentify_obj(v, names) for v in obj]
    return obj


def _key(name: str) -> str:
    """이름 대신 남기는 열쇠 — 비밀값 없이는 이름을 되돌릴 수 없다."""
    return hmac.new(IP_HASH_SALT.encode(), name.encode(), hashlib.sha256).hexdigest()[:24]


def _known_names(obj, keys: set[str]) -> set[str]:
    """고친 값 안의 2~4글자 낱말 중 처음 저장 때 찾은 이름과 열쇠가 같은 것."""
    if not keys:
        return set()
    runs = re.findall(r"[가-힣]+", json.dumps(obj, ensure_ascii=False))
    words = {run[i:i + n] for run in runs for i in range(len(run)) for n in (2, 3, 4) if i + n <= len(run)}
    return {w for w in words if _key(w) in keys}


def save(user_id: int, kind: str, source: str, text: str, result: dict) -> int:
    assert kind in KINDS
    # 본문 명단에서 찾은 이름은 결과(예: 회의록 할 일 담당)에서도 가린다
    names = listed_names(text) | listed_names(json.dumps(result, ensure_ascii=False))
    return db.add_contribution(
        user_id=user_id,
        kind=kind,
        source=deidentify(source, names)[:200],
        text=deidentify(text, names)[:MAX_TEXT],
        result=json.dumps(_deidentify_obj(result, names), ensure_ascii=False),
        consent=CONSENT_VERSION,
        name_keys=json.dumps(sorted(_key(n) for n in names)),
    )


def attach_correction(user_id: int, contribution_id: int, corrected: dict) -> bool:
    """이용자가 확인 표에서 고친 값을 붙인다. 본인 자료만."""
    stored = db.contribution_name_keys(contribution_id, user_id)
    if stored is None:
        return False
    names = _known_names(corrected, set(json.loads(stored or "[]"))) | listed_names(json.dumps(corrected, ensure_ascii=False))
    return db.set_contribution_correction(contribution_id, user_id, json.dumps(_deidentify_obj(corrected, names), ensure_ascii=False))


def delete_mine(user_id: int) -> int:
    return db.delete_contributions(user_id)


# ---------------------------------------------------------------- 본인 자료 확인·철회 (로그인)

router = APIRouter(prefix="/api/contributions", dependencies=[Depends(origin_guard)])  # 읽기 외 요청은 Origin 검사 (CSRF)


@router.get("/mine")
def my_contributions(user: dict = Depends(current_user)) -> dict:
    return {"count": db.count_contributions(user["id"])}


@router.delete("/mine")
def withdraw(user: dict = Depends(current_user)) -> dict:
    return {"deleted": delete_mine(user["id"])}
