"""ChromaDB 벡터 스토어 래퍼.

- Gemini 임베딩(gemini-embedding-001) (목업 모드에서는 결정적 해시 임베딩)
- 문서 삭제/재색인을 위해 모든 청크에 doc_id 메타데이터를 부여
- v1의 메타데이터 키 불일치 버그(source_file vs source)를 없애기 위해
  메타데이터 키는 이 모듈에서만 정의한다: source_file, doc_id, chunk_index
"""

import hashlib
import math
import threading
import time

import chromadb

from app.config import CHROMA_DIR, GEMINI_API_KEY, GEMINI_EMBEDDING_MODEL, MOCK_MODE

# 목업(256차원)과 실제 Gemini 임베딩(3072차원)은 호환되지 않으므로 컬렉션을 분리한다.
COLLECTION_NAME = "regulations_mock" if MOCK_MODE else "regulations"
_EMBED_DIM = 256  # 목업 임베딩 차원

_lock = threading.Lock()
_client: chromadb.ClientAPI | None = None
_embedder = None


def _get_client() -> chromadb.ClientAPI:
    global _client
    with _lock:
        if _client is None:
            _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        return _client


def _get_collection():
    return _get_client().get_or_create_collection(
        COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
    )


def _mock_embed(texts: list[str]) -> list[list[float]]:
    """API 키 없이 파이프라인을 검증하기 위한 결정적 해시 임베딩."""
    vectors = []
    for text in texts:
        vec = []
        for i in range(_EMBED_DIM):
            digest = hashlib.sha256(f"{i}:{text}".encode()).digest()
            vec.append(int.from_bytes(digest[:4], "big") / 2**32 - 0.5)
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        vectors.append([v / norm for v in vec])
    return vectors


# 무료 티어 쿼터(429) 대응: 작은 배치 + 지수 백오프 재시도
_EMBED_BATCH = 20
_EMBED_MAX_RETRIES = 5
_EMBED_BACKOFF_BASE = 30  # 초


def _embed(texts: list[str]) -> list[list[float]]:
    if MOCK_MODE:
        return _mock_embed(texts)
    global _embedder
    if _embedder is None:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        _embedder = GoogleGenerativeAIEmbeddings(
            model=GEMINI_EMBEDDING_MODEL, google_api_key=GEMINI_API_KEY
        )

    vectors: list[list[float]] = []
    for start in range(0, len(texts), _EMBED_BATCH):
        batch = texts[start : start + _EMBED_BATCH]
        for attempt in range(_EMBED_MAX_RETRIES):
            try:
                vectors.extend(_embedder.embed_documents(batch))
                break
            except Exception as e:
                msg = str(e)
                # 쿼터 제한(429)과 일시적 서버 장애(500/503)는 재시도 대상
                retryable = any(
                    token in msg
                    for token in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500", "INTERNAL")
                )
                if not retryable or attempt == _EMBED_MAX_RETRIES - 1:
                    raise
                wait = _EMBED_BACKOFF_BASE * (2**attempt)
                print(f"임베딩 일시 오류. {wait}초 대기 후 재시도 ({attempt + 1}/{_EMBED_MAX_RETRIES})...")
                time.sleep(wait)
    return vectors


def classify_doc(source_file: str) -> str:
    """파일명으로 문서 유형 분류: 'audit'(감사보고서) 또는 'regulation'(회칙·세칙).

    감사보고서가 회칙·세칙보다 수가 많아, 유형 구분 없이 검색하면 규정 조항이
    상위 결과에서 밀려난다. 에이전트별로 적합한 유형을 검색하기 위해 구분한다.
    """
    if "보고서" in source_file or "감사결과" in source_file:
        return "audit"
    return "regulation"


def add_chunks(doc_id: str, source_file: str, chunks: list[str]) -> int:
    """청크를 임베딩하여 컬렉션에 추가하고 추가된 개수를 반환한다."""
    if not chunks:
        return 0
    collection = _get_collection()
    embeddings = _embed(chunks)
    doc_type = classify_doc(source_file)
    collection.add(
        ids=[f"{doc_id}:{i}" for i in range(len(chunks))],
        documents=chunks,
        embeddings=embeddings,
        metadatas=[
            {
                "doc_id": doc_id,
                "source_file": source_file,
                "chunk_index": i,
                "doc_type": doc_type,
            }
            for i in range(len(chunks))
        ],
    )
    return len(chunks)


def search(query: str, k: int = 5, doc_type: str | None = None) -> list[dict]:
    """유사도 검색. doc_type을 주면 해당 유형(regulation/audit)만 검색한다."""
    collection = _get_collection()
    if collection.count() == 0:
        return []
    result = collection.query(
        query_embeddings=_embed([query]),
        n_results=min(k, collection.count()),
        where={"doc_type": doc_type} if doc_type else None,
        include=["documents", "metadatas"],
    )
    hits = []
    for text, meta in zip(result["documents"][0], result["metadatas"][0]):
        hits.append(
            {
                "text": text,
                "source_file": meta.get("source_file", "알 수 없음"),
                "doc_id": meta.get("doc_id", ""),
                "chunk_index": meta.get("chunk_index", -1),
                "doc_type": meta.get("doc_type", ""),
            }
        )
    return hits


def delete_doc(doc_id: str) -> None:
    _get_collection().delete(where={"doc_id": doc_id})


def chunk_count() -> int:
    return _get_collection().count()
