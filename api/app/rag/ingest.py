"""PDF 인제스천: 텍스트 추출 → 청킹 → 임베딩 → 벡터 스토어 저장.

질의 경로와 분리된 관리자 전용 파이프라인. v1과 달리 첫 질문 시점이 아니라
문서 업로드 시점에 색인한다.

텍스트 레이어가 없는 스캔본 PDF는 Gemini 멀티모달(PDF 네이티브 입력)로
텍스트를 추출하는 폴백을 거친다.
"""

import io
import re
import unicodedata
import uuid

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.config import GEMINI_API_KEY, GEMINI_MODEL, MOCK_MODE
from app.rag import store

# 스캔본 PDF 판별 기준
# 절대 길이만 보면, 목차·표지만 텍스트로 들어있고 본문이 이미지인 문서를 놓친다.
# (예: 18페이지 감사보고서에서 851자만 추출 → 본문 누락) 따라서 페이지당 평균도 함께 본다.
MIN_TEXT_LENGTH = 50
MIN_CHARS_PER_PAGE = 200
WARN_CHARS_PER_PAGE = 350  # 폴백 임계값은 넘겼지만 확인이 필요한 수준

_OCR_PROMPT = """\
이 PDF 문서에 있는 모든 텍스트를 원문 그대로 순서대로 추출하라.
- 요약하거나 생략하지 마라. 조항 번호, 항, 호를 정확히 보존하라.
- 표는 행 단위 텍스트로 풀어서 표현하라.
- 추출한 텍스트 외에 다른 설명이나 머리말을 출력하지 마라."""

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    separators=["\n\n", "\n", ".", " ", ""],
)


class IngestError(Exception):
    pass


def _extract_with_gemini(file_bytes: bytes) -> str:
    """스캔본 PDF 폴백: Gemini 멀티모달에 PDF를 직접 넣어 텍스트를 추출한다."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=file_bytes, mime_type="application/pdf"),
            _OCR_PROMPT,
        ],
    )
    return response.text or ""


def clean_text(text: str) -> str:
    """PDF 추출 텍스트 정규화.

    일부 한글 PDF는 공백을 널바이트(\\x00)나 특수 공백으로 추출해 단어 경계가
    사라지고 임베딩 품질이 크게 저하된다. 이를 일반 공백으로 복원한다.
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
    return text.strip()


def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception as e:
        raise IngestError(f"PDF 파일을 읽을 수 없습니다: {e}") from e

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
    elif chars_per_page < WARN_CHARS_PER_PAGE:
        # 임계값은 넘겼지만 본문 일부가 이미지일 수 있어 눈에 띄게 알린다.
        print(
            f"  ⚠ 추출량이 적습니다 ({page_count}페이지, 페이지당 {chars_per_page:.0f}자) "
            "— 본문 일부가 이미지일 수 있으니 답변 품질을 확인하세요."
        )
    return text


def ingest_pdf(file_bytes: bytes, filename: str) -> tuple[str, int]:
    """PDF를 색인하고 (doc_id, 청크 수)를 반환한다."""
    text = extract_text_from_pdf(file_bytes)
    chunks = _splitter.split_text(text)
    if not chunks:
        raise IngestError("문서에서 색인할 내용을 찾지 못했습니다.")

    doc_id = uuid.uuid4().hex
    added = store.add_chunks(doc_id, filename, chunks)
    return doc_id, added
