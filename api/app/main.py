"""FastAPI 서버: SSE 스트리밍 채팅 + 문서 관리 API."""

import asyncio
import hashlib
import json
import re
import secrets
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from langchain_core.callbacks import UsageMetadataCallbackHandler
from pydantic import BaseModel, Field, field_validator
from starlette.datastructures import MutableHeaders

from app import db
from app.agents.graph import content_to_text, graph
from app.agents.schemas import overall_risk
from app.config import (
    ADMIN_TOKEN,
    CORS_ORIGINS,
    DEFAULT_LIMITS,
    GEMINI_MODEL,
    IP_HASH_SALT,
    MAX_INFLIGHT_TOTAL,
    MOCK_MODE,
    PRICE_INPUT_PER_1M,
    PRICE_OUTPUT_PER_1M,
    RETENTION_DAYS,
    USD_KRW,
)
from app.privacy import PRIVATE_NAMES, StreamMasker, mask_obj
from app.rag import citation_graph, store
from app.rag.ingest import IngestError, ingest_pdf

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_QUERY_LENGTH = 1000

app = FastAPI(
    title="학생회 규정 AI 어시스턴트 API",
    version="2.0.0",
    # 자동 문서는 관리자 API 표면을 그대로 드러내므로 목업(로컬)에서만 연다
    docs_url="/docs" if MOCK_MODE else None,
    redoc_url="/redoc" if MOCK_MODE else None,
    openapi_url="/openapi.json" if MOCK_MODE else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class _SecurityHeaders:
    """모든 응답에 기본 보안 헤더를 붙인다.

    순수 ASGI로 구현해 SSE 스트리밍 응답을 버퍼링하지 않는다.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(_SecurityHeaders)


class HistoryItem(BaseModel):
    question: str = Field(max_length=MAX_QUERY_LENGTH)
    answer: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    # 후속 질문 맥락 유지용 이전 대화 (최근 것부터 최대 3개 사용)
    history: list[HistoryItem] = Field(default_factory=list, max_length=10)
    # 사용자별 일일 한도 계산용 익명 식별자 (브라우저 localStorage)
    visitor_id: str | None = Field(default=None, max_length=64)

    @field_validator("query")
    @classmethod
    def _strip_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("질문을 입력해 주세요.")
        return value


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def require_admin(authorization: str | None = Header(default=None)) -> None:
    """관리자 전용 엔드포인트 보호.

    문서 관리와 운영 지표(전체 질의 로그 포함)는 공개되면 안 되므로,
    ADMIN_TOKEN이 설정되지 않은 경우 열어두지 않고 차단한다.
    """
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_TOKEN이 설정되지 않아 관리자 API가 비활성화되었습니다.",
        )
    expected = f"Bearer {ADMIN_TOKEN}"
    # 바이트로 비교한다. 문자열 비교는 비ASCII 헤더에서 TypeError → 500이 된다.
    if not authorization or not secrets.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="관리자 인증이 필요합니다.")


admin_only = Depends(require_admin)


def is_admin_request(authorization: str | None) -> bool:
    """관리자 토큰이 실린 요청인지 판별한다 (차단하지 않고 참/거짓만 돌려준다).

    회귀 테스트처럼 운영자가 직접 돌리는 질의까지 일일 한도에 걸리면
    정작 점검이 막힌다. 한도 계산에서만 빼고 지표에는 그대로 기록한다.
    """
    if not ADMIN_TOKEN or not authorization:
        return False
    return secrets.compare_digest(authorization.encode(), f"Bearer {ADMIN_TOKEN}".encode())


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "mock_mode": MOCK_MODE,
        "admin_protected": bool(ADMIN_TOKEN),
        "model": GEMINI_MODEL,
        "indexed_chunks": store.chunk_count(),
    }


# ---------------------------------------------------------------- chat (SSE)

_FOLLOWUPS_RE = re.compile(r"<followups>(.*?)</followups>", re.DOTALL)


def _extract_followups(markdown: str) -> tuple[str, list[str]]:
    """조정 에이전트 출력에서 후속 질문 블록을 분리한다."""
    match = _FOLLOWUPS_RE.search(markdown)
    if not match:
        return markdown, []
    followups = [
        line.strip().lstrip("-").strip()
        for line in match.group(1).splitlines()
        if line.strip().startswith("-")
    ]
    cleaned = _FOLLOWUPS_RE.sub("", markdown).rstrip()
    return cleaned, followups[:3]


_STAGE_LABELS = {
    "regulation": "규정 검토·감사 에이전트 병렬 분석 중...",
    "general": "답변 생성 중...",
}


def _client_ip_hash(http_request: Request) -> str | None:
    """클라이언트 IP의 솔트 해시. 원문 IP는 저장하지 않는다.

    X-Forwarded-For는 "클라이언트, 프록시1, 프록시2" 순으로 쌓이고 각 프록시가
    뒤에 덧붙인다. 따라서 왼쪽 항목은 클라이언트가 위조해 보낼 수 있다.
    (X-Forwarded-For: 1.2.3.4 를 보내면 프록시가 뒤에 실제 IP를 붙여
    "1.2.3.4, 실제IP"가 되므로, 첫 항목을 믿으면 상한을 그냥 빠져나간다.)

    신뢰할 수 있는 값은 우리 앞단 프록시가 마지막에 붙인 오른쪽 끝 항목이다.
    """
    parts = [p.strip() for p in http_request.headers.get("x-forwarded-for", "").split(",")]
    ip = next((p for p in reversed(parts) if p), "")
    if not ip and http_request.client:
        ip = http_request.client.host
    if not ip:
        return None
    return hashlib.sha256(f"{IP_HASH_SALT}:{ip}".encode()).hexdigest()[:32]


# 진행 중인 요청 수 (키: "total" / "u:<visitor>" / "ip:<hash>").
# 한도는 완료된 요청(지표)만 세므로, 응답이 끝나기 전에 몰려오는 요청은 전부
# 통과했다 — 진행 중인 것까지 더해서 검사하고, 동시 실행 상한도 둔다.
_inflight: dict[str, int] = {}


def _inflight_add(keys: list[str], delta: int) -> None:
    for key in keys:
        value = _inflight.get(key, 0) + delta
        if value > 0:
            _inflight[key] = value
        else:
            _inflight.pop(key, None)


def _enforce_daily_limit(visitor_id: str | None, ip_hash: str | None = None) -> None:
    """일일 질의 상한 확인. 초과 시 429로 차단한다 (0 = 무제한)."""
    if _inflight.get("total", 0) >= MAX_INFLIGHT_TOTAL:
        raise HTTPException(
            status_code=429, detail="지금 요청이 몰려 있습니다. 잠시 후 다시 시도해주세요."
        )

    limits = db.get_settings(DEFAULT_LIMITS)

    per_user = limits["daily_limit_per_user"]
    used_by_user = db.count_today(visitor_id) + _inflight.get(f"u:{visitor_id}", 0)
    if per_user > 0 and visitor_id and used_by_user >= per_user:
        raise HTTPException(
            status_code=429,
            detail=f"오늘 사용 가능한 질문 횟수({per_user}회)를 모두 사용했습니다. 내일 다시 이용해주세요.",
        )

    # visitor_id는 브라우저 저장소를 비우면 초기화되므로 IP 기준으로 한 번 더 막는다
    per_ip = limits["daily_limit_per_ip"]
    used_by_ip = (db.count_today_by_ip(ip_hash) if ip_hash else 0) + _inflight.get(f"ip:{ip_hash}", 0)
    if per_ip > 0 and ip_hash and used_by_ip >= per_ip:
        raise HTTPException(
            status_code=429,
            detail="같은 네트워크에서 오늘 이용 가능한 횟수를 모두 사용했습니다. 내일 다시 이용해주세요.",
        )

    total = limits["daily_limit_total"]
    if total > 0 and db.count_today() + _inflight.get("total", 0) >= total:
        raise HTTPException(
            status_code=429,
            detail="오늘 전체 이용 한도에 도달했습니다. 내일 다시 이용해주세요.",
        )


@app.post("/api/chat")
async def chat(
    request: ChatRequest,
    http_request: Request,
    authorization: str | None = Header(default=None),
):
    query = request.query.strip()
    history = [h.model_dump() for h in request.history[-3:]]
    visitor_id = request.visitor_id
    ip_hash = _client_ip_hash(http_request)
    is_admin = is_admin_request(authorization)
    if not is_admin:
        _enforce_daily_limit(visitor_id, ip_hash)

    # 후속 질문이 아닌 단독 질문만 캐시 대상 (맥락에 따라 답이 달라지므로)
    cache_key = db.normalize_query(query) if not history else None
    if cache_key:
        limits = db.get_settings(DEFAULT_LIMITS)
        cached = db.get_cached_answer(cache_key, limits["cache_ttl_hours"])
        if cached:

            async def cached_stream():
                yield _sse({"type": "stage", "label": "이전 답변을 불러오는 중..."})
                db.record_metric(
                    route=cached.get("route"),
                    risk_level=cached.get("risk_level"),
                    status="cached",
                    elapsed=0.0,
                    input_tokens=0,
                    output_tokens=0,
                    query_preview=query,
                    analysis_id=cached.get("analysis_id"),
                    visitor_id=visitor_id,
                    ip_hash=ip_hash,
                    is_admin=is_admin,
                )
                yield _sse({"type": "result", **mask_obj(cached), "cached": True})

            return StreamingResponse(
                cached_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

    inflight_keys = ["total"] + [
        key
        for key in (f"u:{visitor_id}" if visitor_id else "", f"ip:{ip_hash}" if ip_hash else "")
        if key
    ]
    _inflight_add(inflight_keys, +1)

    async def event_stream():
        start = time.time()
        merged: dict = {"citations": []}
        usage_handler = UsageMetadataCallbackHandler()
        # 프롬프트의 실명 금지 규칙은 확률적이다. 나가는 모든 텍스트를 코드가 한 번 더 지운다.
        masker = StreamMasker()

        def _token_totals() -> tuple[int, int]:
            usage = usage_handler.usage_metadata or {}
            return (
                sum(u.get("input_tokens", 0) for u in usage.values()),
                sum(u.get("output_tokens", 0) for u in usage.values()),
            )

        try:
            yield _sse({"type": "stage", "label": "질문 분석 중..."})

            async for mode, payload in graph.astream(
                {"query": query, "history": history, "citations": []},
                config={"callbacks": [usage_handler]},
                stream_mode=["updates", "messages"],
            ):
                if mode == "messages":
                    chunk, meta = payload
                    node = meta.get("langgraph_node", "")
                    content = content_to_text(getattr(chunk, "content", ""))
                    if node in ("coordinator", "general") and content:
                        if visible := masker.feed(content):
                            yield _sse({"type": "token", "content": visible})
                    continue

                # mode == "updates": {node_name: state_delta}
                for node, delta in payload.items():
                    if not isinstance(delta, dict):
                        continue
                    for key, value in delta.items():
                        if key == "citations":
                            merged["citations"].extend(value or [])
                        else:
                            merged[key] = value

                    if node == "router":
                        route = delta.get("route", "regulation")
                        yield _sse({
                            "type": "stage",
                            "label": _STAGE_LABELS.get(route, _STAGE_LABELS["regulation"]),
                            "route": route,
                        })
                    elif node in ("reviewer", "auditor"):
                        # 완료된 에이전트의 분석 내용을 즉시 전달해 부분 렌더링 지원
                        agent_result = delta.get(node)
                        yield _sse({
                            "type": "agent_done",
                            "agent": node,
                            "data": mask_obj(agent_result.model_dump()) if agent_result else None,
                        })
                        if merged.get("reviewer") is not None and merged.get("auditor") is not None:
                            yield _sse({"type": "stage", "label": "조정 에이전트가 결과를 종합 중..."})

            reviewer = merged.get("reviewer")
            auditor = merged.get("auditor")
            risk = overall_risk(reviewer, auditor).value if (reviewer or auditor) else None

            # 인용 중복 제거 (문서명+내용 기준)
            seen, citations = set(), []
            for c in merged["citations"]:
                key = (c.source_file, c.snippet)
                if key not in seen:
                    seen.add(key)
                    citations.append({"source_file": c.source_file, "snippet": c.snippet})

            final_markdown, followups = _extract_followups(merged.get("final_markdown", ""))
            if tail := masker.flush():
                yield _sse({"type": "token", "content": tail})

            result = {
                "query": query,
                "route": merged.get("route", ""),
                "risk_level": risk,
                "final_markdown": final_markdown,
                "followups": followups,
                "reviewer": reviewer.model_dump() if reviewer else None,
                "auditor": auditor.model_dump() if auditor else None,
                "citations": citations,
                "elapsed": round(time.time() - start, 2),
            }
            result = mask_obj(result)
            analysis_id = db.add_analysis(query, risk, result)
            in_tok, out_tok = _token_totals()
            db.record_metric(
                route=merged.get("route"),
                risk_level=risk,
                status="ok",
                elapsed=result["elapsed"],
                input_tokens=in_tok,
                output_tokens=out_tok,
                query_preview=query,
                analysis_id=analysis_id,
                visitor_id=visitor_id,
                ip_hash=ip_hash,
                is_admin=is_admin,
            )
            if cache_key:
                db.save_cached_answer(cache_key, analysis_id, result)
            # analysis_id는 저장 후에야 정해지므로 응답에만 덧붙인다 (피드백 전송용)
            yield _sse({"type": "result", **result, "analysis_id": analysis_id})

        except Exception as e:  # noqa: BLE001 - 스트림 내 오류는 이벤트로 전달
            in_tok, out_tok = _token_totals()
            db.record_metric(
                route=merged.get("route"),
                risk_level=None,
                status="error",
                elapsed=round(time.time() - start, 2),
                input_tokens=in_tok,
                output_tokens=out_tok,
                query_preview=query,
                visitor_id=visitor_id,
                ip_hash=ip_hash,
                is_admin=is_admin,
                error=f"{type(e).__name__}: {e}",
            )
            # 예외 원문(LLM 출력 조각·내부 경로가 섞일 수 있음)은 지표에만 남기고 사용자에겐 일반 문구
            yield _sse({"type": "error", "message": "분석 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."})
        finally:
            _inflight_add(inflight_keys, -1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------- documents
# 아래 엔드포인트는 모두 관리자 전용 (문서 색인 변조·질의 로그 유출 방지)

@app.post("/api/documents", dependencies=[admin_only])
async def upload_document(file: UploadFile):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드할 수 있습니다.")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="파일이 너무 큽니다 (최대 20MB).")

    # OCR·임베딩·그래프 재구축은 수 분이 걸리는 동기 작업이다. 이벤트 루프에서
    # 돌리면 그동안 모든 채팅 스트림이 멈추므로 스레드로 보낸다.
    try:
        doc_id, chunks = await asyncio.to_thread(_index_upload, content, file.filename)
    except IngestError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"doc_id": doc_id, "filename": file.filename, "chunks": chunks}


def _index_upload(content: bytes, filename: str) -> tuple[str, int]:
    doc_id, chunks = ingest_pdf(content, filename)
    db.add_document(doc_id, filename, chunks)
    # 색인이 바뀌면 이전 답변은 낡은 근거일 수 있으므로 캐시를 비운다
    db.clear_cache()
    # 인용 그래프도 색인의 파생물이므로 함께 재생성한다 (약 2초, 낡은 그래프 방지)
    citation_graph.get_graph(rebuild=True)
    return doc_id, chunks


@app.get("/api/documents", dependencies=[admin_only])
def get_documents():
    return {"documents": db.list_documents(), "indexed_chunks": store.chunk_count()}


@app.delete("/api/documents/{doc_id}", dependencies=[admin_only])
def delete_document(doc_id: str):
    if not db.delete_document(doc_id):
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    store.delete_doc(doc_id)
    db.clear_cache()
    citation_graph.get_graph(rebuild=True)
    return {"deleted": doc_id}


# ---------------------------------------------------------------- history / stats

@app.get("/api/history", dependencies=[admin_only])
def get_history(limit: int = 20):
    return {"analyses": db.list_analyses(min(limit, 100))}


@app.get("/api/analyses/{analysis_id}", dependencies=[admin_only])
def get_analysis(analysis_id: int):
    item = db.get_analysis(analysis_id)
    if not item:
        raise HTTPException(status_code=404, detail="분석 기록을 찾을 수 없습니다.")
    return item


class FeedbackRequest(BaseModel):
    analysis_id: int = Field(ge=1)
    helpful: bool
    visitor_id: str | None = Field(default=None, max_length=64)


@app.post("/api/feedback")
def submit_feedback(request: FeedbackRequest):
    """답변 만족도 수집 (공개 — 사용자가 누르는 버튼)."""
    if not db.get_analysis(request.analysis_id):
        raise HTTPException(status_code=404, detail="분석 기록을 찾을 수 없습니다.")
    db.add_feedback(request.analysis_id, request.helpful, request.visitor_id)
    return {"ok": True}


class TrackRequest(BaseModel):
    visitor_id: str = Field(min_length=8, max_length=64)


@app.post("/api/track")
def track_visit(request: TrackRequest):
    db.add_visit(request.visitor_id)
    return {"ok": True}


@app.get("/api/stats/export", dependencies=[admin_only])
def export_stats():
    csv = db.export_metrics_csv()
    return PlainTextResponse(
        csv,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=metrics.csv"},
    )


def _memory_mb() -> dict:
    """컨테이너 메모리 사용량. Railway 요금이 메모리 기준이라 지표로 남긴다.

    Linux 컨테이너에서만 값이 나온다 (로컬 개발 환경에서는 None).
    """

    def _read(path: str) -> int | None:
        try:
            return int(Path(path).read_text().strip())
        except (OSError, ValueError):
            return None

    rss = None
    try:
        for line in Path('/proc/self/status').read_text().splitlines():
            if line.startswith('VmRSS:'):
                rss = int(line.split()[1]) / 1024  # kB → MB
                break
    except OSError:
        pass

    # cgroup v2 우선, 없으면 v1
    used = _read('/sys/fs/cgroup/memory.current') or _read(
        '/sys/fs/cgroup/memory/memory.usage_in_bytes'
    )
    limit = _read('/sys/fs/cgroup/memory.max') or _read(
        '/sys/fs/cgroup/memory/memory.limit_in_bytes'
    )
    # 상한이 없으면 호스트 전체 메모리가 찍히므로(수십 GB) 의미 없는 값은 버린다
    limit_mb = limit / 1024 / 1024 if limit and limit < 1 << 43 else None
    return {
        "rss_mb": round(rss, 1) if rss else None,
        "container_mb": round(used / 1024 / 1024, 1) if used else None,
        "limit_mb": round(limit_mb, 1) if limit_mb else None,
    }


def _cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens / 1_000_000 * PRICE_INPUT_PER_1M
        + output_tokens / 1_000_000 * PRICE_OUTPUT_PER_1M
    )


class SettingsRequest(BaseModel):
    daily_limit_total: int = Field(ge=0, le=100_000)
    daily_limit_per_user: int = Field(ge=0, le=10_000)
    daily_limit_per_ip: int = Field(default=60, ge=0, le=10_000)
    cache_ttl_hours: int = Field(default=24, ge=0, le=720)


@app.post("/api/cache/clear", dependencies=[admin_only])
def clear_cache():
    return {"cleared": db.clear_cache()}


@app.get("/api/settings", dependencies=[admin_only])
def get_settings():
    return {
        **db.get_settings(DEFAULT_LIMITS),
        "used_today": db.count_today(),
        # 마스킹 목록이 실제로 로드됐는지 운영자가 확인할 수 있게 개수만 노출한다
        "private_names": len(PRIVATE_NAMES),
    }


@app.put("/api/settings", dependencies=[admin_only])
def update_settings(request: SettingsRequest):
    db.set_settings(request.model_dump())
    return {
        **db.get_settings(DEFAULT_LIMITS),
        "used_today": db.count_today(),
        # 마스킹 목록이 실제로 로드됐는지 운영자가 확인할 수 있게 개수만 노출한다
        "private_names": len(PRIVATE_NAMES),
    }


@app.get("/api/stats", dependencies=[admin_only])
def get_stats(days: int = 14):
    stats = db.get_stats(min(max(days, 1), 90))
    stats["limits"] = {**db.get_settings(DEFAULT_LIMITS), "used_today": db.count_today()}
    stats["memory"] = _memory_mb()
    total_usd = _cost_usd(stats["totals"]["input_tokens"], stats["totals"]["output_tokens"])
    today_usd = _cost_usd(stats["today"]["input_tokens"], stats["today"]["output_tokens"])
    stats["cost"] = {
        "total_usd": round(total_usd, 4),
        "today_usd": round(today_usd, 4),
        "total_krw": round(total_usd * USD_KRW),
        "today_krw": round(today_usd * USD_KRW),
        "usd_krw": USD_KRW,
    }
    return stats


# 보존 기간이 지난 기록은 기동 시 정리한다 (지표·방문·분석·오래된 답변 캐시)
db.purge_old(RETENTION_DAYS)
