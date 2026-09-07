"""PDF 인제스천: 텍스트 추출 → 청킹 → 임베딩 → 벡터 스토어 저장.

질의 경로와 분리된 관리자 전용 파이프라인으로, 문서 업로드 시점에 색인한다.
텍스트 레이어가 없는 스캔본 PDF는 Gemini 멀티모달로 추출하는 폴백을 거친다.
"""

import hashlib
import io
import re
import time
import unicodedata
import uuid
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.config import GEMINI_API_KEY, GEMINI_MODEL, MOCK_MODE, OCR_CACHE_DIR
from app.rag import store

# 스캔본 PDF 판별 기준
# 절대 길이만 보면, 목차·표지만 텍스트로 들어있고 본문이 이미지인 문서를 놓친다.
# (예: 18페이지 감사보고서에서 851자만 추출 → 본문 누락) 따라서 페이지당 평균도 함께 본다.
MIN_TEXT_LENGTH = 50
MIN_CHARS_PER_PAGE = 200
WARN_CHARS_PER_PAGE = 350  # 폴백 임계값은 넘겼지만 확인이 필요한 수준

_OCR_MAX_RETRIES = 3
_OCR_RETRY_WAIT = 5  # 초 (시도마다 배수로 늘린다)

_OCR_PROMPT = """\
이 PDF 문서에 있는 모든 텍스트를 원문 그대로 순서대로 추출하라.
- 요약하거나 생략하지 마라. 조항 번호, 항, 호를 정확히 보존하라.
- 표는 행 단위로 풀어 쓰되, 각 칸 앞에 그 칸이 속한 열 제목을 붙여라.
  한 행이 끝나면 빈 줄로 구분하라. 예:
    [피감사기구] 교육학과 학생회
    [감사 처분 내용] 시정조치 요구안 송부
- 추출한 텍스트 외에 다른 설명이나 머리말을 출력하지 마라."""

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    separators=["\n\n", "\n", ".", " ", ""],
)

# 회칙·세칙의 조항 제목은 '제10조(목적)'처럼 괄호가 따라온다.
# 반면 본문 중 참조는 '제29조에 따라', '제42조제3항'처럼 괄호가 없어,
# 괄호를 조건에 넣으면 참조에서 잘못 끊기는 일을 피할 수 있다.
_ARTICLE_HEAD = re.compile(r"(?=제\s*\d+\s*조(?:의\s*\d+)?\s*\()")
ARTICLE_CHUNK_MAX = 1500  # 조항을 합쳐 담을 때의 상한
MIN_ARTICLES = 3  # 이보다 적으면 조항 구조가 없는 문서로 보고 기본 분할


def split_by_article(text: str) -> list[str] | None:
    """조항 경계로 분할한다. 조항 구조가 없으면 None을 반환한다.

    조항이 중간에서 잘리면 인용 근거가 불완전해지므로, 한 조항은 나누지 않고
    짧은 조항들만 상한까지 묶는다. 상한을 넘는 긴 조항만 기본 분할기로 쪼갠다.
    """
    parts = [p.strip() for p in _ARTICLE_HEAD.split(text) if p.strip()]
    if len(parts) < MIN_ARTICLES:
        return None

    chunks: list[str] = []
    buffer = ""
    for part in parts:
        if len(part) > ARTICLE_CHUNK_MAX:
            if buffer:
                chunks.append(buffer)
                buffer = ""
            chunks.extend(_splitter.split_text(part))
        elif len(buffer) + len(part) + 1 <= ARTICLE_CHUNK_MAX:
            buffer = f"{buffer}\n{part}".strip()
        else:
            chunks.append(buffer)
            buffer = part
    if buffer:
        chunks.append(buffer)
    return chunks


class IngestError(Exception):
    pass


def _ocr_cache_path(file_bytes: bytes) -> Path:
    # 프롬프트도 키에 넣는다. 파일 해시만 쓰면 추출 지시를 바꿔도 옛 결과가 그대로 나온다.
    key = hashlib.sha256(file_bytes + _OCR_PROMPT.encode()).hexdigest()[:32]
    return OCR_CACHE_DIR / f"{key}.txt"


def _extract_with_gemini(file_bytes: bytes) -> str:
    """스캔본 PDF 폴백: Gemini 멀티모달에 PDF를 직접 넣어 텍스트를 추출한다.

    결과는 파일 내용 해시로 캐싱한다. 같은 PDF에도 매번 다른 텍스트가 나와
    재색인마다 청크 경계가 달라지므로, 캐시로 재현성과 비용을 함께 잡는다.
    """
    cached = _ocr_cache_path(file_bytes)
    if cached.exists():
        text = cached.read_text(encoding="utf-8")
        if text.strip():
            print(f"  OCR 캐시 사용 ({len(text)}자)")
            return text

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    part = types.Part.from_bytes(data=file_bytes, mime_type="application/pdf")

    # 빈 응답이 한 번 오면 문서가 통째로 색인에서 빠진다. 실제로 겪어서 재시도를 둔다.
    text = ""
    for attempt in range(1, _OCR_MAX_RETRIES + 1):
        try:
            text = client.models.generate_content(
                model=GEMINI_MODEL, contents=[part, _OCR_PROMPT]
            ).text or ""
        except Exception as e:  # noqa: BLE001 - 마지막 시도까지 실패하면 그대로 올린다
            if attempt == _OCR_MAX_RETRIES:
                raise
            print(f"  추출 오류({type(e).__name__}), 재시도 {attempt}/{_OCR_MAX_RETRIES - 1}...")
            time.sleep(_OCR_RETRY_WAIT * attempt)
            continue
        if len(text.strip()) >= MIN_TEXT_LENGTH:
            break
        if attempt < _OCR_MAX_RETRIES:
            print(f"  추출 결과가 비어 재시도 {attempt}/{_OCR_MAX_RETRIES - 1}...")
            time.sleep(_OCR_RETRY_WAIT * attempt)

    if text.strip():
        cached.write_text(text, encoding="utf-8")
    return text


# 표지·서식 제목은 자간을 벌려 조판하는 경우가 많아 "인 하 대 학 교"처럼 추출된다.
# 낱글자 수만 보면 "위원 한 명 한 명" 같은 정상 문장까지 붙여버리므로,
# 그 줄의 한글 대부분이 낱글자일 때만 자간 조판으로 판정한다.
# 줄 전체가 낱글자면("가 나 다 라 마") 자간 조판과 구분할 수 없어 붙는다.
_ISOLATED_HANGUL = re.compile(r"(?<![가-힣])[가-힣](?![가-힣])")
_HANGUL = re.compile(r"[가-힣]")
_HANGUL_GAP = re.compile(r"(?<=[가-힣])[ ](?=[가-힣])")
_MIDDLE_DOT = re.compile(r"(?<=[가-힣])\s*[·ㆍ]\s*(?=[가-힣])")
_SPACED_MIN_CHARS = 5
_SPACED_MIN_RATIO = 0.75  # 0.6에서는 "지 할 때 는 각 자 부담한다" 같은 문장이 걸렸다


def _collapse_spaced_line(line: str) -> str:
    total = len(_HANGUL.findall(line))
    isolated = len(_ISOLATED_HANGUL.findall(line))
    if isolated >= _SPACED_MIN_CHARS and total and isolated / total >= _SPACED_MIN_RATIO:
        return _HANGUL_GAP.sub("", line)
    return line


def clean_text(text: str) -> str:
    """PDF 추출 텍스트 정규화.

    일부 한글 PDF는 공백을 널바이트(\\x00)나 특수 공백으로 추출해 단어 경계가
    사라지고 임베딩 품질이 크게 저하된다. 이를 일반 공백으로 복원한다.

    조판상의 공백도 정리한다. 그대로 두면 "재 정 · 회 계 세 칙"처럼 답변에까지 옮겨진다.
    """
    if not text:
        return ""
    # 널바이트 및 특수 공백(비분할 공백, 전각 공백 등) → 일반 공백
    text = text.replace("\x00", " ").replace("﻿", " ")
    text = re.sub(r"[  -​ 　]", " ", text)
    # 유니코드 정규화 (호환 문자 통일)
    text = unicodedata.normalize("NFKC", text)
    # 남은 제어문자 제거 (줄바꿈·탭은 보존)
    text = "".join(c for c in text if c in "\n\t" or unicodedata.category(c) != "Cc")
    # 과도한 공백/빈 줄 정리
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 가운뎃점 앞뒤 공백 제거 ("재정 · 회계" → "재정·회계")
    text = _MIDDLE_DOT.sub("·", text)
    # 자간을 벌려 조판한 줄 복원 (줄 단위 판정)
    text = "\n".join(_collapse_spaced_line(line) for line in text.split("\n"))
    return text.strip()


# 표 구조 추출본을 채택하는 최소 분량 (pypdf 대비).
# LLM 추출은 중간에 끊기거나 요약해버릴 수 있어, 원문보다 크게 짧으면 신뢰하지 않는다.
MULTIMODAL_MIN_RATIO = 0.8


def extract_text_from_pdf(file_bytes: bytes, *, prefer_multimodal: bool = False) -> str:
    """PDF에서 텍스트를 추출한다.

    prefer_multimodal이면 텍스트 레이어가 있어도 Gemini 멀티모달을 먼저 시도한다.
    감사보고서는 표가 핵심인데 pypdf는 셀 경계를 잃어 "교육학과 학생회시정조치
    요구안 송부감사 처분 없음"처럼 붙어 나온다. 기구와 처분의 연결이 모호해진다.
    """
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception as e:
        raise IngestError(f"PDF 파일을 읽을 수 없습니다: {e}") from e
    if reader.is_encrypted:
        raise IngestError("암호화된 PDF는 지원하지 않습니다. 암호를 해제한 뒤 업로드하세요.")

    text = clean_text("\n".join((page.extract_text() or "") for page in reader.pages))

    page_count = max(len(reader.pages), 1)
    chars_per_page = len(text.strip()) / page_count
    needs_ocr = len(text.strip()) < MIN_TEXT_LENGTH or chars_per_page < MIN_CHARS_PER_PAGE

    if needs_ocr:
        if MOCK_MODE:
            raise IngestError(
                "텍스트를 추출할 수 없는 스캔본 PDF입니다. "
                "목업 모드에서는 스캔본 파싱이 불가하니 GEMINI_API_KEY를 설정하세요."
            )
        print(
            f"본문 추출 부족 ({page_count}페이지, 페이지당 {chars_per_page:.0f}자) "
            "— Gemini 멀티모달로 재추출합니다..."
        )
        try:
            text = clean_text(_extract_with_gemini(file_bytes))
        except Exception as e:
            raise IngestError(f"스캔본 텍스트 추출 실패 (Gemini): {e}") from e

        if len(text.strip()) < MIN_TEXT_LENGTH:
            raise IngestError(
                "스캔본에서 유의미한 텍스트를 추출하지 못했습니다. "
                "원본 문서에서 텍스트 PDF로 재출력을 권장합니다."
            )
    else:
        if prefer_multimodal and not MOCK_MODE:
            text = _with_table_structure(file_bytes, text)
        if chars_per_page < WARN_CHARS_PER_PAGE:
            # 임계값은 넘겼지만 본문 일부가 이미지일 수 있어 눈에 띄게 알린다.
            print(
                f"  ⚠ 추출량이 적습니다 ({page_count}페이지, 페이지당 {chars_per_page:.0f}자) "
                "— 본문 일부가 이미지일 수 있으니 답변 품질을 확인하세요."
            )
    return text


def _with_table_structure(file_bytes: bytes, fallback: str) -> str:
    """Gemini로 표 구조를 살려 재추출한다. 결과가 미덥지 않으면 fallback을 쓴다."""
    try:
        text = clean_text(_extract_with_gemini(file_bytes))
    except Exception as e:  # noqa: BLE001 - 추출 실패가 색인 전체를 막지 않도록
        print(f"  표 구조 추출 실패, pypdf 결과 사용: {type(e).__name__}: {e}")
        return fallback

    if len(text) < len(fallback) * MULTIMODAL_MIN_RATIO:
        print(f"  표 구조 추출이 짧아 pypdf 결과 사용 ({len(text):,} < {len(fallback):,}자)")
        return fallback
    print(f"  표 구조 추출 적용 ({len(fallback):,} -> {len(text):,}자)")
    return text


def ingest_pdf(file_bytes: bytes, filename: str) -> tuple[str, int]:
    """PDF를 색인하고 (doc_id, 청크 수)를 반환한다."""
    doc_type = store.classify_doc(filename)
    # 감사보고서만 표 구조 추출을 거친다. 회칙·세칙은 조문이 그대로 보존돼야 하고
    # 표도 거의 없어, 원문을 그대로 읽는 pypdf가 더 안전하다.
    text = extract_text_from_pdf(file_bytes, prefer_multimodal=doc_type == "audit")

    # 회칙·세칙은 조항 단위로, 감사보고서는 길이 기준으로 나눈다
    chunks = None
    if doc_type == "regulation":
        chunks = split_by_article(text)
        if chunks:
            print(f"  조항 단위 분할: {len(chunks)}개 청크")
    if not chunks:
        chunks = _splitter.split_text(text)
    if not chunks:
        raise IngestError("문서에서 색인할 내용을 찾지 못했습니다.")

    doc_id = uuid.uuid4().hex
    added = store.add_chunks(doc_id, filename, chunks)
    return doc_id, added
