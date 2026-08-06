"""ChromaDB 벡터 스토어 래퍼.

- Gemini 임베딩(gemini-embedding-001) (목업 모드에서는 결정적 해시 임베딩)
- 문서 삭제/재색인을 위해 모든 청크에 doc_id 메타데이터를 부여
- v1의 메타데이터 키 불일치 버그(source_file vs source)를 없애기 위해
  메타데이터 키는 이 모듈에서만 정의한다: source_file, doc_id, chunk_index
"""

import hashlib
import math
import threading

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


def _embed(texts: list[str]) -> list[list[float]]:
    if MOCK_MODE:
        return _mock_embed(texts)
    global _embedder
    if _embedder is None:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        _embedder = GoogleGenerativeAIEmbeddings(
            model=GEMINI_EMBEDDING_MODEL, google_api_key=GEMINI_API_KEY
        )
    return _embedder.embed_documents(texts)


def add_chunks(doc_id: str, source_file: str, chunks: list[str]) -> int:
    """청크를 임베딩하여 컬렉션에 추가하고 추가된 개수를 반환한다."""
    if not chunks:
        return 0
    collection = _get_collection()
    embeddings = _embed(chunks)
    collection.add(
        ids=[f"{doc_id}:{i}" for i in range(len(chunks))],
        documents=chunks,
        embeddings=embeddings,
        metadatas=[
            {"doc_id": doc_id, "source_file": source_file, "chunk_index": i}
            for i in range(len(chunks))
        ],
    )
    return len(chunks)


def search(query: str, k: int = 5) -> list[dict]:
    """유사도 검색. [{text, source_file, doc_id, chunk_index}] 반환."""
    collection = _get_collection()
    if collection.count() == 0:
        return []
    result = collection.query(
        query_embeddings=_embed([query]),
        n_results=min(k, collection.count()),
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
            }
        )
    return hits


def delete_doc(doc_id: str) -> None:
    _get_collection().delete(where={"doc_id": doc_id})


def chunk_count() -> int:
    return _get_collection().count()
