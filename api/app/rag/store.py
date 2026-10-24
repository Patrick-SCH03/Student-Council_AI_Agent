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

from app.config import CHROMA_DIR, MOCK_MODE, VOYAGE_API_KEY, VOYAGE_EMBEDDING_MODEL

# 목업(256차원)과 실제 임베딩은 호환되지 않고, 임베딩 모델마다 벡터 공간이 달라 컬렉션 이름에 모델을 넣는다.
# 모델을 바꾸면 새 컬렉션이 비어 있으므로 문서를 다시 색인한다 (옛 컬렉션은 기동 시 정리).
COLLECTION_NAME = "regulations_mock" if MOCK_MODE else f"regulations_{VOYAGE_EMBEDDING_MODEL}".replace(".", "-")
_EMBED_DIM = 256  # 목업 임베딩 차원

# 재진입 가능해야 한다: BM25 색인을 만드는 도중 컬렉션 접근이 다시 락을 요구한다
_lock = threading.RLock()
_client: chromadb.ClientAPI | None = None
_voyage = None


def _get_client() -> chromadb.ClientAPI:
    global _client
    with _lock:
        if _client is None:
            _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        return _client


def _get_collection(name: str | None = None):
    return _get_client().get_or_create_collection(
        name or COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
    )


def drop_stale_collections() -> list[str]:
    """지금 쓰지 않는 실제 색인 컬렉션(옛 임베딩 모델의 벡터)을 지운다. 목업 컬렉션은 건드리지 않는다.

    임베딩 모델을 바꾸면 옛 벡터는 쓸모가 없고 디스크만 차지한다.
    """
    if MOCK_MODE:
        return []
    names = [c.name if hasattr(c, "name") else c for c in _get_client().list_collections()]
    stale = [n for n in names if n.startswith("regulations") and n != COLLECTION_NAME and "mock" not in n]
    for name in stale:
        _get_client().delete_collection(name)
    return stale


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


# 쿼터(429)·일시 장애 대응: 배치 + 지수 백오프 재시도
_EMBED_BATCH = 64
_EMBED_MAX_RETRIES = 5
_EMBED_BACKOFF_BASE = 20  # 초

# Voyage는 결제 수단이 없으면 분당 3요청·1만 토큰으로 묶인다. 첫 429를 보면 이 프로세스는
# 저속 모드로 바꿔, 문서 임베딩을 작은 배치(글자 수 기준)로 나눠 요청 간격을 벌린다.
# (결제 수단을 등록하면 429가 나지 않아 저속 모드로 들어가지 않는다)
_THROTTLE_BATCH_CHARS = 6000  # 한국어 기준 대략 1만 토큰 아래
_THROTTLE_INTERVAL = 21.0  # 초 (분당 3요청)
_throttled = False
_last_request = 0.0


def _batches(texts: list[str]) -> list[list[str]]:
    if not _throttled:
        return [texts[i : i + _EMBED_BATCH] for i in range(0, len(texts), _EMBED_BATCH)]
    out: list[list[str]] = []
    cur: list[str] = []
    size = 0
    for t in texts:
        if cur and size + len(t) > _THROTTLE_BATCH_CHARS:
            out.append(cur)
            cur, size = [], 0
        cur.append(t)
        size += len(t)
    if cur:
        out.append(cur)
    return out


def _voyage_embed(texts: list[str], input_type: str) -> list[list[float]]:
    """Voyage 임베딩 (공식 HTTP API). 문서와 질의를 input_type으로 구분해야 검색 품질이 나온다."""
    global _voyage
    if _voyage is None:
        import httpx

        _voyage = httpx.Client(
            base_url="https://api.voyageai.com/v1",
            headers={"Authorization": f"Bearer {VOYAGE_API_KEY}"},
            timeout=60,
        )
    res = _voyage.post("/embeddings", json={
        "input": texts, "model": VOYAGE_EMBEDDING_MODEL, "input_type": input_type,
    })
    if res.status_code >= 400:
        # 응답 본문만 남긴다 — 요청 헤더(키)는 예외 문구에 싣지 않는다
        raise RuntimeError(f"Voyage 임베딩 오류 {res.status_code}: {res.text[:200]}")
    data = sorted(res.json()["data"], key=lambda d: d["index"])
    return [d["embedding"] for d in data]


def _embed(
    texts: list[str],
    *,
    max_retries: int = _EMBED_MAX_RETRIES,
    backoff_base: int = _EMBED_BACKOFF_BASE,
    input_type: str = "document",
) -> list[list[float]]:
    if MOCK_MODE:
        return _mock_embed(texts)
    global _throttled, _last_request
    vectors: list[list[float]] = []
    pending = list(texts)
    while pending:
        batch = _batches(pending)[0]
        for attempt in range(max_retries):
            # 저속 모드에서 문서 색인은 요청 간격을 지킨다. 질의는 기다리지 않는다 — 막히면 키워드 검색으로 간다
            if _throttled and input_type == "document":
                wait = _THROTTLE_INTERVAL - (time.time() - _last_request)
                if wait > 0:
                    time.sleep(wait)
            try:
                _last_request = time.time()
                vectors.extend(_voyage_embed(batch, input_type))
                break
            except Exception as e:
                msg = str(e)
                if " 429" in msg and not _throttled:
                    print("Voyage 처리 한도(429) — 저속 모드로 전환 (작은 배치, 요청 간격 21초)")
                    _throttled = True
                    if input_type == "document":
                        batch = _batches(batch)[0]  # 이번 배치부터 작게 다시 나눈다
                # 쿼터 제한(429)·일시적 서버 장애(5xx)·네트워크 타임아웃은 재시도 대상
                # (httpx 타임아웃은 메시지가 "timed out"이나 빈 문자열이라 예외 종류로 본다)
                import httpx

                retryable = isinstance(e, httpx.TransportError) or any(
                    token in msg for token in (" 429", " 500", " 502", " 503", " 504")
                )
                if not retryable or attempt == max_retries - 1:
                    raise
                wait = backoff_base * (2**attempt)
                print(f"임베딩 일시 오류. {wait}초 대기 후 재시도 ({attempt + 1}/{max_retries})...")
                time.sleep(wait)
        pending = pending[len(batch):]
    return vectors


def classify_doc(source_file: str) -> str:
    """파일명으로 문서 유형 분류: 'audit'(감사보고서) 또는 'regulation'(회칙·세칙).

    감사보고서가 회칙·세칙보다 수가 많아, 유형 구분 없이 검색하면 규정 조항이
    상위 결과에서 밀려난다. 에이전트별로 적합한 유형을 검색하기 위해 구분한다.
    """
    if "보고서" in source_file or "감사결과" in source_file:
        return "audit"
    return "regulation"


def add_chunks(
    doc_id: str, source_file: str, chunks: list[str], embeddings: list[list[float]] | None = None
) -> int:
    """청크를 컬렉션에 추가하고 추가된 개수를 반환한다.

    embeddings를 주면 그대로 쓴다 — 로컬에서 만든 색인을 운영 서버로 옮길 때(/api/index/import).
    """
    if not chunks:
        return 0
    collection = _get_collection()
    if embeddings is None:
        embeddings = _embed(chunks)
    elif len(embeddings) != len(chunks):
        raise ValueError("청크와 임베딩 개수가 다르다")
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


def _keyword_search(query: str, k: int, doc_type: str | None) -> list[tuple[str, dict]]:
    """BM25 점수 상위 청크를 (본문, 메타) 목록으로 반환한다.

    인덱스 번호가 아니라 본문을 돌려준다. 번호를 돌려주면 호출 측이 다시 읽는
    인덱스가 그 사이 재구축돼 다른 청크를 가리킬 수 있다 (업로드·삭제와 동시 실행).
    """
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
    top = sorted(scores, key=scores.get, reverse=True)[:k]
    return [(docs[i], index["metas"][i]) for i in top]


def embed_query(text: str) -> list[float]:
    """질의 임베딩 1건. 같은 질의로 여러 검색을 돌릴 때 호출 측에서 재사용한다.

    색인용 백오프(최대 450초)를 그대로 쓰면 사용자 요청이 그만큼 붙잡힌다.
    질의는 짧게 두 번만 시도하고 실패를 빨리 돌려준다.
    """
    return _embed([text], max_retries=2, backoff_base=2, input_type="query")[0]


def _vector_search(
    query: str, k: int, doc_type: str | None, embedding: list[float] | None = None
) -> list[dict]:
    collection = _get_collection()
    result = collection.query(
        query_embeddings=[embedding] if embedding is not None else _embed([query], input_type="query"),
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
    query_embedding: list[float] | None = None,
    keyword_only: bool = False,
) -> list[dict]:
    """하이브리드 검색: 벡터 + 키워드 결과를 RRF로 융합하고 문서 편중을 완화한다.

    RRF는 두 검색의 점수 체계가 달라도 순위만으로 안전하게 합칠 수 있어,
    임베딩이 놓친 정확한 표현을 키워드 쪽이 보완한다.
    """
    collection = _get_collection()
    if collection.count() == 0:
        return []

    pool = max(k * 3, 15)  # 융합 전 후보를 넉넉히 확보
    # 임베딩 API가 막히면(쿼터·키 정지) 키워드 검색만으로 답한다 — 검색 실패가 응답 전체를 막지 않게
    vector_hits = [] if keyword_only else _vector_search(query, pool, doc_type, query_embedding)
    keyword_hits = _keyword_search(query, pool, doc_type)

    # 같은 청크를 (문서, 청크번호)로 식별해 두 결과를 합친다
    fused: dict[tuple, dict] = {}

    def _add(key: tuple, text: str, meta: dict, rank: int) -> None:
        entry = fused.setdefault(key, {"text": text, "meta": meta, "score": 0.0})
        entry["score"] += 1 / (_RRF_K + rank)

    for rank, hit in enumerate(vector_hits):
        m = hit["meta"]
        _add((m.get("doc_id"), m.get("chunk_index")), hit["text"], m, rank)

    for rank, (text, m) in enumerate(keyword_hits):
        _add((m.get("doc_id"), m.get("chunk_index")), text, m, rank)

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


def export_doc(doc_id: str) -> tuple[list[str], list[list[float]]]:
    """한 문서의 청크·임베딩을 청크 순서대로 돌려준다 (운영 서버로 옮기는 용도)."""
    got = _get_collection().get(where={"doc_id": doc_id}, include=["documents", "metadatas", "embeddings"])
    rows = sorted(zip(got["metadatas"], got["documents"], got["embeddings"]), key=lambda r: r[0]["chunk_index"])
    return [r[1] for r in rows], [list(map(float, r[2])) for r in rows]


def delete_doc(doc_id: str) -> None:
    _get_collection().delete(where={"doc_id": doc_id})
    _invalidate_bm25()


def reset_collection() -> int:
    """현재 색인 컬렉션을 비운다 (전체 재색인 전). 지운 청크 수를 돌려준다."""
    with _lock:
        removed = _get_collection().count()
        _get_client().delete_collection(COLLECTION_NAME)
        _get_collection()
    _invalidate_bm25()
    return removed


def chunk_count() -> int:
    return _get_collection().count()
