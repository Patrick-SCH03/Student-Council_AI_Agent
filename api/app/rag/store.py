"""ChromaDB 벡터 스토어 래퍼. 하이브리드 검색(BM25 + 벡터)을 담당한다.

메타데이터 키(source_file, doc_id, chunk_index, doc_type)는 이 모듈에서만
정의한다. 저장하는 쪽과 읽는 쪽이 키를 따로 쓰면 인용이 조용히 깨진다.
"""

import hashlib
import math
import re
import threading
import time

import chromadb

from app.config import CHROMA_DIR, GEMINI_API_KEY, GEMINI_EMBEDDING_MODEL, MOCK_MODE

# 목업(256차원)과 실제 Gemini 임베딩(3072차원)은 호환되지 않으므로 컬렉션을 분리한다.
COLLECTION_NAME = "regulations_mock" if MOCK_MODE else "regulations"
_EMBED_DIM = 256  # 목업 임베딩 차원

# 재진입 가능해야 한다: BM25 색인을 만드는 도중 컬렉션 접근이 다시 락을 요구한다
_lock = threading.RLock()
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
    _invalidate_bm25()  # 색인이 바뀌었으므로 키워드 역색인 재생성 필요
    return len(chunks)


# ---------------------------------------------------------------- 키워드 검색 (BM25)
# 임베딩 검색만으로는 "제32조", "비룡제" 같은 정확한 표현을 놓칠 수 있어
# 키워드 검색을 함께 돌리고 두 결과를 융합한다.

_ARTICLE_RE = re.compile(r"제\s*\d+\s*조(?:의\s*\d+)?")
_WORD_RE = re.compile(r"[가-힣]+|[a-zA-Z]+|\d+")
_BM25_K1, _BM25_B = 1.5, 0.75
_RRF_K = 60  # Reciprocal Rank Fusion 상수 (관례값)

_bm25_cache: dict | None = None


def _tokenize(text: str) -> list[str]:
    """한국어 형태소 분석기 없이 쓰는 경량 토크나이저.

    조항 표기를 하나의 토큰으로 보존하고, 한글은 2-gram을 함께 넣어
    조사·어미 변화("예산을", "예산이")를 흡수한다.
    """
    tokens = [re.sub(r"\s+", "", m) for m in _ARTICLE_RE.findall(text)]
    for word in _WORD_RE.findall(text.lower()):
        tokens.append(word)
        if len(word) > 2 and "가" <= word[0] <= "힣":
            tokens.extend(word[i : i + 2] for i in range(len(word) - 1))
    return tokens


def _build_bm25() -> dict:
    """전체 청크로 역색인을 만든다 (수백~수천 청크 규모에서 메모리 부담 없음)."""
    data = _get_collection().get(include=["documents", "metadatas"])
    docs, metas = data["documents"], data["metadatas"]
    postings: dict[str, dict[int, int]] = {}
    lengths: list[int] = []
    for idx, text in enumerate(docs):
        tokens = _tokenize(text)
        lengths.append(len(tokens) or 1)
        counts: dict[str, int] = {}
        for t in tokens:
            counts[t] = counts.get(t, 0) + 1
        for t, c in counts.items():
            postings.setdefault(t, {})[idx] = c
    return {
        "docs": docs,
        "metas": metas,
        "postings": postings,
        "lengths": lengths,
        "avgdl": (sum(lengths) / len(lengths)) if lengths else 1.0,
    }


def _get_bm25() -> dict:
    global _bm25_cache
    with _lock:
        if _bm25_cache is None:
            _bm25_cache = _build_bm25()
        return _bm25_cache


def _invalidate_bm25() -> None:
    global _bm25_cache
    with _lock:
        _bm25_cache = None


def _keyword_search(query: str, k: int, doc_type: str | None) -> list[int]:
    """BM25 점수 상위 청크의 인덱스를 반환한다."""
    index = _get_bm25()
    docs, postings, lengths, avgdl = (
        index["docs"], index["postings"], index["lengths"], index["avgdl"]
    )
    if not docs:
        return []

    n = len(docs)
    scores: dict[int, float] = {}
    for term in set(_tokenize(query)):
        posting = postings.get(term)
        if not posting:
            continue
        idf = math.log((n - len(posting) + 0.5) / (len(posting) + 0.5) + 1)
        for idx, tf in posting.items():
            norm = 1 - _BM25_B + _BM25_B * lengths[idx] / avgdl
            scores[idx] = scores.get(idx, 0.0) + idf * tf * (_BM25_K1 + 1) / (
                tf + _BM25_K1 * norm
            )

    if doc_type:
        metas = index["metas"]
        scores = {i: s for i, s in scores.items() if metas[i].get("doc_type") == doc_type}
    return sorted(scores, key=scores.get, reverse=True)[:k]


def _vector_search(query: str, k: int, doc_type: str | None) -> list[dict]:
    collection = _get_collection()
    result = collection.query(
        query_embeddings=_embed([query]),
        n_results=min(k, collection.count()),
        where={"doc_type": doc_type} if doc_type else None,
        include=["documents", "metadatas"],
    )
    return [
        {"text": t, "meta": m}
        for t, m in zip(result["documents"][0], result["metadatas"][0])
    ]


def _diversify(entries: list[dict], k: int, max_per_source: int) -> list[dict]:
    """문서별 상한을 두고 상위 k개를 고른다.

    한 문서의 인접 청크가 결과를 채우면 근거가 좁아진다. 상한을 먼저 적용해
    여러 문서를 확보하고, 남는 자리는 순위대로 채운다.
    """
    picked: list[dict] = []
    per_source: dict[str, int] = {}
    overflow: list[dict] = []

    for entry in entries:
        source = entry["meta"].get("source_file", "")
        if per_source.get(source, 0) < max_per_source:
            per_source[source] = per_source.get(source, 0) + 1
            picked.append(entry)
            if len(picked) == k:
                return picked
        else:
            overflow.append(entry)

    picked.extend(overflow[: k - len(picked)])
    return picked


def search(
    query: str,
    k: int = 5,
    doc_type: str | None = None,
    max_per_source: int = 3,
) -> list[dict]:
    """하이브리드 검색: 벡터 + 키워드 결과를 RRF로 융합하고 문서 편중을 완화한다.

    RRF는 두 검색의 점수 체계가 달라도 순위만으로 안전하게 합칠 수 있어,
    임베딩이 놓친 정확한 표현을 키워드 쪽이 보완한다.
    """
    collection = _get_collection()
    if collection.count() == 0:
        return []

    pool = max(k * 3, 15)  # 융합 전 후보를 넉넉히 확보
    vector_hits = _vector_search(query, pool, doc_type)
    keyword_idx = _keyword_search(query, pool, doc_type)
    index = _get_bm25()

    # 같은 청크를 (문서, 청크번호)로 식별해 두 결과를 합친다
    fused: dict[tuple, dict] = {}

    def _add(key: tuple, text: str, meta: dict, rank: int) -> None:
        entry = fused.setdefault(key, {"text": text, "meta": meta, "score": 0.0})
        entry["score"] += 1 / (_RRF_K + rank)

    for rank, hit in enumerate(vector_hits):
        m = hit["meta"]
        _add((m.get("doc_id"), m.get("chunk_index")), hit["text"], m, rank)

    for rank, idx in enumerate(keyword_idx):
        m = index["metas"][idx]
        _add((m.get("doc_id"), m.get("chunk_index")), index["docs"][idx], m, rank)

    ranked = sorted(fused.values(), key=lambda e: e["score"], reverse=True)
    ordered = _diversify(ranked, k, max_per_source)

    hits = []
    for entry in ordered:
        text, meta = entry["text"], entry["meta"]
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


def expand_neighbors(hits: list[dict], radius: int = 1, top_n: int | None = None) -> list[dict]:
    """검색된 청크의 인접 청크를 함께 붙여 반환한다.

    감사보고서의 처분 목록처럼 하나의 열거가 청크 경계로 나뉘면, 질의어와 겹치는
    항목만 검색되고 같은 사안의 나머지가 빠진다. 순위를 다시 계산하지 않고
    근접 문맥만 보강하므로 리랭킹보다 싸다.

    top_n은 확장할 상위 건수. 하위 순위까지 늘리면 토큰만 불어난다.
    """
    if not hits or radius <= 0:
        return hits

    anchor_count = top_n if top_n else len(hits)
    present = {(h["doc_id"], h["chunk_index"]) for h in hits}
    wanted: list[tuple[str, int]] = []
    for hit in hits[:anchor_count]:
        for offset in range(-radius, radius + 1):
            key = (hit["doc_id"], hit["chunk_index"] + offset)
            if offset and key[1] >= 0 and key not in present and key not in wanted:
                wanted.append(key)
    if not wanted:
        return hits

    fetched = _get_collection().get(
        ids=[f"{doc_id}:{idx}" for doc_id, idx in wanted],
        include=["documents", "metadatas"],
    )
    neighbors = {
        (m.get("doc_id"), m.get("chunk_index")): {
            "text": t,
            "source_file": m.get("source_file", "알 수 없음"),
            "doc_id": m.get("doc_id", ""),
            "chunk_index": m.get("chunk_index", -1),
            "doc_type": m.get("doc_type", ""),
        }
        for t, m in zip(fetched["documents"], fetched["metadatas"])
    }

    # 각 청크 뒤에 그 이웃을 붙여 원문 순서에 가까운 형태로 전달한다
    expanded: list[dict] = []
    seen: set[tuple] = set()
    for position, hit in enumerate(hits):
        offsets = range(-radius, radius + 1) if position < anchor_count else (0,)
        for offset in offsets:
            key = (hit["doc_id"], hit["chunk_index"] + offset)
            entry = hit if offset == 0 else neighbors.get(key)
            if entry and key not in seen:
                seen.add(key)
                expanded.append(entry)
    return expanded


def delete_doc(doc_id: str) -> None:
    _get_collection().delete(where={"doc_id": doc_id})
    _invalidate_bm25()


def chunk_count() -> int:
    return _get_collection().count()
