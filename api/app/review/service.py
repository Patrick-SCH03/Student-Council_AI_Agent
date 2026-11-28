"""문서 검토 흐름: 파일 → 예산 구조 추출 → 계산 검사 → 규정 메모.

LLM이 막히면 규칙 기반 추출(heuristic)로 이어 간다 — 사용자가 확인 화면에서 고칠 수 있으니 멈추지 않는다.
메모(LLM)가 실패해도 계산 검사 결과는 그대로 돌려준다.
"""

import asyncio
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app import pricing
from app.config import CLAUDE_MODEL, MOCK_MODE
from app.privacy import mask_text
from app.rag import store
from app.review import prompts
from app.review.extract import Extracted, extract_file
from app.review.heuristic import heuristic_extract
from app.review.models import BudgetDoc, Finding
from app.review.rules import check_budget
from app.review.sheets import table_text
from app.review.textcheck import check_text

# 문서 내용에서 찾을 주제 → 규정 검색어. 문서에 낱말이 있을 때만 그 조항을 찾아 메모 근거로 쓴다.
TOPICS: dict[str, tuple[tuple[str, ...], str]] = {
    "주류": (("주류", "소주", "맥주", "양주", "술집", "주점"), "주류 구매 예산 집행 목적 외 사용"),
    "상품권": (("상품권", "기프티콘", "포인트", "경품", "상금"), "상품권 경품 상금 지급 증빙"),
    "사례금": (("사례금", "강사비", "멘토비", "섭외비", "수당", "인건비", "인력비"), "사례금 수당 개인 현금 교부 수령증"),
    "개인정보": (("학번", "연락처", "전화번호", "질환", "명단", "재학증명"), "개인정보 수집 동의 파기"),
    "후원": (("후원", "협찬", "제휴", "기부"), "후원 협찬 기부금 수입 처리"),
    "추경": (("추가경정", "추경", "추후 인준", "사후"), "추가경정예산 확정 전 집행 금지"),
    "계좌": (("명의", "통장", "계좌"), "공금전용계좌 수입 현금 보관"),
}
BASE_QUERY = "예산 집행 지출 증빙 예비비"
EXTRACT_TIMEOUT = 90  # 15쪽 안팎 문서 추출이 30초를 넘는 일이 있었다 (2026-11-28 평가)
NOTES_TIMEOUT = 60
MAX_NOTES = 3

# 계산 검사가 이미 잡은 주제 — 메모가 같은 말을 되풀이하지 않게 거른다
_COVERED = {
    "vat": ("VAT", "부가세"),
    "personal_account": ("명의", "통장", "계좌"),
    "account_number": ("계좌번호",),
    "sensitive": ("질환", "약물", "민감"),
    "cash": ("현금",),
    "reserve": ("예비비",),
    "korean_amount": ("한글",),
    "weekday": ("요일",),
    "event_year": ("연도",),
}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, payload: dict) -> None:
        u = payload.get("usage") or {}
        i, o = int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))
        self.input_tokens += i
        self.output_tokens += o
        self.cost_usd += pricing.cost_usd(u.get("model") or CLAUDE_MODEL, i, o, int(u.get("cached_tokens", 0)))


@dataclass
class ExtractResult:
    file: Extracted
    doc: BudgetDoc
    method: str  # ai | rule
    usage: Usage = field(default_factory=Usage)


_UNIT_LINE = re.compile(r"(?<![\d,])1\s*(?:EA|ea|개|인분|세트|인)(?![가-힣A-Za-z])|개당|단가")


def drop_unit_price_lines(doc: BudgetDoc) -> BudgetDoc:
    """'세트 1EA 7,700원' 같은 단가 줄이 지출 줄로 들어왔으면 뺀다 — 빼야 합계가 맞을 때만.

    실제 표에 단가가 한 줄로 적혀 있어 추출이 줄로 옮기는 일이 있었다(2026-11-28 평가). 합계가 맞지 않게 되면
    그대로 둔다(진짜 불일치일 수 있다).
    """
    for name in ("income", "expense"):
        lines, total = getattr(doc, name), getattr(doc, f"{name}_total")
        if total is None or any(line.amount is None for line in lines):
            continue
        current = sum(line.amount for line in lines)  # type: ignore[misc]
        unit = [line for line in lines if _UNIT_LINE.search(line.item)]
        if current != total and unit and current - sum(line.amount for line in unit) == total:  # type: ignore[misc]
            doc = doc.model_copy(update={name: [line for line in lines if line not in unit]})
    return doc


async def extract(filename: str, data: bytes, usage: Usage | None = None) -> ExtractResult:
    file = await asyncio.to_thread(extract_file, filename, data)
    usage = usage if usage is not None else Usage()
    masked = mask_text(file.text)
    if MOCK_MODE:
        return ExtractResult(file, heuristic_extract(filename, file.text), "rule", usage)
    from app.agents import claude_agents

    try:
        doc = await claude_agents.structured(
            prompts.EXTRACT_SYSTEM,
            prompts.EXTRACT_USER.format(filename=mask_text(filename), text=masked),
            BudgetDoc,
            on_usage=usage.add,
            timeout=EXTRACT_TIMEOUT,
        )
        return ExtractResult(file, drop_unit_price_lines(doc), "ai", usage)
    except Exception as e:  # noqa: BLE001 - 추출 실패는 규칙 기반으로 이어 간다
        print(f"문서 검토 추출 실패, 규칙 기반으로 진행: {type(e).__name__}: {e}")
        return ExtractResult(file, heuristic_extract(filename, file.text), "rule", usage)


async def warm_up() -> None:
    """서버 기동 때 추출·메모 스키마를 한 번 써 둔다.

    구조화 출력은 새 스키마를 처음 쓸 때 문법을 컴파일하느라 100초 가까이 걸렸다(2026-11-28 실측, 이후 13초).
    첫 사용자가 그 시간을 기다리지 않게 아주 짧은 문서로 미리 부른다 (호출당 $0.001 미만).
    """
    if MOCK_MODE:
        return
    from app.agents import claude_agents

    sample = "1) 수입\n항목 금액\n자치비 1,000원\n합계 1,000원"
    # 두 스키마를 함께 예열한다 (차례로 하면 메모 스키마가 기동 뒤 200초쯤에야 준비됐다)
    results = await asyncio.gather(
        claude_agents.structured(
            prompts.EXTRACT_SYSTEM, prompts.EXTRACT_USER.format(filename="warmup.pdf", text=sample),
            BudgetDoc, on_usage=lambda _u: None, timeout=180,
        ),
        claude_agents.structured(
            prompts.NOTES_SYSTEM, prompts.NOTES_USER.format(regulations="", already="(없음)", text=sample),
            _Notes, on_usage=lambda _u: None, timeout=180,
        ),
        return_exceptions=True,
    )
    for e in results:
        if isinstance(e, Exception):  # 예열 실패는 서비스에 영향이 없다
            print(f"문서 검토 예열 실패, 건너뜀: {type(e).__name__}: {e}")


def merge(findings: list[Finding]) -> list[Finding]:
    """같은 검사가 같은 제목으로 여러 번 나오면 하나로 묶고 위치를 모은다. 등급 순으로 정렬."""
    merged: dict[tuple[str, str], Finding] = {}
    for f in findings:
        key = (f.code, f.title)
        if key in merged:
            where = mask_text(f.where)
            if where and where not in merged[key].where:
                merged[key].where = f"{merged[key].where} · {where}" if merged[key].where else where
        else:
            # 원문에서 뽑은 사업명·셀 이름이 제목·위치에 들어간다 — 화면·개선 자료로 나가기 전에 한 곳에서 가린다
            merged[key] = f.model_copy(update={"title": mask_text(f.title), "detail": mask_text(f.detail), "where": mask_text(f.where)})
    order = {"위반 소지": 0, "보완 필요": 1, "확인 필요": 2}
    return sorted(merged.values(), key=lambda f: order[f.level])


def source_findings(file: Extracted) -> list[Finding]:
    """원문·파일 자체 검사. 마스킹 전 원문으로 해야 계좌번호 노출 같은 것을 찾는다 — 추출할 때 한 번 한다."""
    text = table_text(file.text) if file.kind == "xlsx" else file.text
    return merge([*file.findings, *check_text(text)])


def check(doc: BudgetDoc, source: list[Finding]) -> list[Finding]:
    """사용자가 확인한 예산 구조의 계산 검사 + 원문 검사 결과 (LLM 없음, 즉시)."""
    return merge([*source, *check_budget(doc)])


def _topics(text: str) -> list[str]:
    return [name for name, (words, _q) in TOPICS.items() if any(w in text for w in words)]


def _regulations(text: str) -> list[tuple[str, str]]:
    """문서 주제로 찾은 규정 조각 (규정 이름, 본문). 메모 근거는 이 안에서만 확인한다."""
    queries = [BASE_QUERY, *(TOPICS[t][1] for t in _topics(text))]
    seen, parts = set(), []
    for q in queries:
        for hit in store.search(q, k=3, doc_type="regulation", max_per_source=2):
            key = (hit["doc_id"], hit["chunk_index"])
            if key in seen:
                continue
            seen.add(key)
            parts.append((store.doc_title(hit["source_file"]), hit["text"]))
    return parts[:12]


def _regulation_text(parts: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"[{title}]\n{body}" for title, body in parts)


class _Note(BaseModel):
    level: Literal["보완 필요", "확인 필요"]
    title: str
    detail: str = ""
    basis: str = Field(default="", description="「문서명」 제N조 제M항. <regulations>에 없으면 빈 문자열")
    quote: str = Field(default="", description="이 점이 걸리는 문서 원문 구절 그대로 (30자 이내)")


class _Notes(BaseModel):
    notes: list[_Note] = Field(default_factory=list, description="최대 3개. 없으면 빈 목록")


_CITE = re.compile(r"「([^」]+)」\s*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?(?:\s*제\s*(\d+)\s*항)?")


def _squash_text(t: str) -> str:
    """구절 대조용: 공백·줄바꿈·표 칸 구분·따옴표·쌍점을 없앤다 (모델이 옮기며 띄어쓰기·따옴표를 바꿔도 같은 구절로 본다)."""
    return re.sub(r"[\s|·ㆍ:'\"‘’“”「」]", "", t)


def _quoted(quote: str, source: str) -> bool:
    """메모가 옮긴 구절이 문서에 있는가. 말줄임('…', '...')으로 나뉘면 6자 이상 조각 하나만 있어도 된다. 4자 미만 인용은 근거가 못 된다."""
    whole = _squash_text(re.sub(r"…|\.{3}", "", quote))
    if len(whole) < 4:
        return False
    if whole in source:
        return True
    parts = [p for p in (_squash_text(x) for x in re.split(r"…|\.{3}", quote)) if p]
    if len(parts) > 1 and sum(map(len, parts)) >= 6 and all(p in source for p in parts):
        return True  # '주류 구매 … 학생회비'처럼 조각마다 원문에 있다
    return any(len(p) >= 6 and p in source for p in parts)


def _norm_title(t: str) -> str:
    return re.sub(r"[\s·ㆍ「」\[\]]", "", t)


_HEADING = re.compile(r"제\s*\d+\s*조(?:\s*의\s*\d+)?\s*\(")


def _article_text(body: str, num: str, sub: str | None) -> str | None:
    """조각에서 '제N조(제목)'로 시작하는 그 조의 본문만 (다음 조 제목 앞까지). 본문 속 '제N조' 참조는 조 본문이 아니다."""
    head = re.search(rf"제\s*{num}\s*조" + (rf"\s*의\s*{sub}" if sub else "") + r"\s*\(", body)
    if not head:
        return None
    rest = body[head.end():]
    nxt = _HEADING.search(rest)
    return body[head.start(): head.end() + (nxt.start() if nxt else len(rest))]


def _has_paragraph(article: str, para: int) -> bool:
    """항 표시는 줄머리(또는 조 제목 바로 뒤)의 숫자·①. 색인 원문은 PDF 추출로 ①이 '1 '이 된다."""
    mark = rf"(?:{para}|{chr(0x2460 + para - 1)})" if 1 <= para <= 20 else str(para)
    return bool(re.search(rf"(?:^|\n|\))\s*{mark}\s", article))


def _verified_basis(basis: str, parts: list[tuple[str, str]]) -> str:
    """메모가 든 「규정」 제N조가 검색한 같은 규정 조각에 조 제목으로 있을 때만 근거로 남긴다.

    조 번호만 아무 데서나 찾던 때는 다른 규정의 같은 번호, 본문 속 참조, 다른 조의 항을 근거로 보여 줄 수 있었다
    (2026-11-28 교차 리뷰). 항은 그 조 본문에서 확인될 때만 붙이고, 아니면 조까지만 남긴다. 하나도 없으면 빈 문자열.
    """
    verified = []
    for m in _CITE.finditer(basis):
        title, num, sub, para = m.groups()
        want = _norm_title(title)
        for doc_title, body in parts:
            have = _norm_title(doc_title)
            article = _article_text(body, num, sub) if want and (want in have or have in want) else None
            if article is None:
                continue
            cite = f"「{title}」 제{num}조" + (f"의{sub}" if sub else "")
            if para and _has_paragraph(article, int(para)):
                cite += f" 제{para}항"
            verified.append(cite)
            break
    return " · ".join(dict.fromkeys(verified))


def _already_covered(note: _Note, findings: list[Finding]) -> bool:
    codes = {f.code for f in findings}
    return any(code in codes and any(w in note.title for w in words) for code, words in _COVERED.items())


async def notes(doc: BudgetDoc, text: str, already: list[Finding], usage: Usage | None = None) -> tuple[list[Finding], Usage]:
    """규정 해석이 필요한 메모. 목업이면 빈 목록. usage를 넘기면 실패해도 그때까지의 사용량이 거기 남는다."""
    usage = usage if usage is not None else Usage()
    if MOCK_MODE:
        return [], usage
    from app.agents import claude_agents

    parts = await asyncio.to_thread(_regulations, text)
    regulations = _regulation_text(parts)
    # 메모는 확인 표보다 먼저 시작해 계산 검사(합계·예비비 등) 결과를 받지 못한다 — 여기서 함께 돌려 같은 지적을 되풀이하지 않게.
    # 다만 그 결과는 모델에 알리기만 한다. 메모를 기계적으로 거르는 건 화면이 보낸 지적뿐 — 확정 전 추출값으로 낸 지적(잘못 읽은
    # 예비비 등)은 사용자가 표를 고치면 사라지는데, 그걸로 관련 메모까지 지우면 둘 다 안 보인다 (Fable 리뷰)
    told = dict.fromkeys(f.title for f in [*already, *check_budget(doc)])
    already_text = "\n".join(f"- {t}" for t in told) or "(없음)"
    result = await claude_agents.structured(
        prompts.NOTES_SYSTEM,
        prompts.NOTES_USER.format(regulations=regulations, already=already_text, text=mask_text(text)[:30_000]),
        _Notes,
        on_usage=usage.add,
        timeout=NOTES_TIMEOUT,
    )
    found = []
    source = _squash_text(mask_text(text))
    for i, n in enumerate(result.notes[:MAX_NOTES]):
        if _already_covered(n, already):
            continue
        # 문서에서 옮긴 구절이 실제로 없으면 문서에 근거하지 않은 일반론이다 — 내보내지 않는다 (2026-11-28 파일럿)
        if not _quoted(n.quote, source):
            continue
        basis = _verified_basis(n.basis, parts)
        found.append(Finding(
            code=f"note:{i}",
            level=n.level if basis else "확인 필요",
            title=n.title,
            detail=n.detail,
            basis=basis,
        ))
    return found, usage
