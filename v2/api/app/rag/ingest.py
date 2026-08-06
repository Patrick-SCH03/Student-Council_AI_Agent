"""PDF 인제스천: 텍스트 추출 → 청킹 → 임베딩 → 벡터 스토어 저장.

질의 경로와 분리된 관리자 전용 파이프라인. v1과 달리 첫 질문 시점이 아니라
문서 업로드 시점에 색인한다.
"""

import io
import uuid

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.rag import store

# 스캔본 PDF 판별 기준: 추출 텍스트가 이보다 짧으면 OCR이 필요한 문서로 간주
MIN_TEXT_LENGTH = 50

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    separators=["\n\n", "\n", ".", " ", ""],
)


class IngestError(Exception):
    pass


def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception as e:
        raise IngestError(f"PDF 파일을 읽을 수 없습니다: {e}") from e

    text = "\n".join((page.extract_text() or "") for page in reader.pages)

    if len(text.strip()) < MIN_TEXT_LENGTH:
        raise IngestError(
            "텍스트를 추출할 수 없는 스캔본 PDF입니다. "
            "텍스트 레이어가 있는 PDF로 변환 후 다시 업로드해주세요."
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
