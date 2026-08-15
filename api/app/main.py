"""FastAPI 서버: SSE 스트리밍 채팅 + 문서 관리 API."""

import hashlib
import json
import re
import secrets
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from langchain_core.callbacks import UsageMetadataCallbackHandler
from pydantic import BaseModel, Field

from app import db
from app.agents.graph import content_to_text, graph
from app.agents.schemas import overall_risk
from app.config import (
    ADMIN_TOKEN,
    CORS_ORIGINS,
    DEFAULT_LIMITS,
    GEMINI_MODEL,
    IP_HASH_SALT,
    MOCK_MODE,
    PRICE_INPUT_PER_1M,
    PRICE_OUTPUT_PER_1M,
    USD_KRW,
)
from app.rag import store
from app.rag.ingest import IngestError, ingest_pdf

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_QUERY_LENGTH = 1000

app = FastAPI(title="학생회 규정 AI 어시스턴트 API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HistoryItem(BaseModel):
    question: str = Field(max_length=MAX_QUERY_LENGTH)
    answer: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    # 후속 질문 맥락 유지용 이전 대화 (최근 것부터 최대 3개 사용)
    history: list[HistoryItem] = Field(default_factory=list, max_length=10)
    # 사용자별 일일 한도 계산용 익명 식별자 (브라우저 localStorage)
    visitor_id: str | None = Field(default=None, max_length=64)


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
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="관리자 인증이 필요합니다.")


admin_only = Depends(require_admin)


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

    Railway 같은 프록시 뒤에서는 X-Forwarded-For의 첫 항목이 실제 클라이언트다.
    """
    forwarded = http_request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip()
    if not ip and http_request.client:
        ip = http_request.client.host
    if not ip:
        return None
    return hashlib.sha256(f"{IP_HASH_SALT}:{ip}".encode()).hexdigest()[:32]


def _enforce_daily_limit(visitor_id: str | None, ip_hash: str | None = None) -> None:
    """일일 질의 상한 확인. 초과 시 429로 차단한다 (0 = 무제한)."""
    limits = db.get_settings(DEFAULT_LIMITS)

    per_user = limits["daily_limit_per_user"]
    if per_user > 0 and visitor_id and db.count_today(visitor_id) >= per_user:
        raise HTTPException(
            status_code=429,
            detail=f"오늘 사용 가능한 질문 횟수({per_user}회)를 모두 사용했습니다. 내일 다시 이용해주세요.",
        )

    # visitor_id는 브라우저 저장소를 비우면 초기화되므로 IP 기준으로 한 번 더 막는다
    per_ip = limits["daily_limit_per_ip"]
    if per_ip > 0 and ip_hash and db.count_today_by_ip(ip_hash) >= per_ip:
        raise HTTPException(
            status_code=429,
            detail="같은 네트워크에서 오늘 이용 가능한 횟수를 모두 사용했습니다. 내일 다시 이용해주세요.",
        )

    total = limits["daily_limit_total"]
    if total > 0 and db.count_today() >= total:
        raise HTTPException(
            status_code=429,
            detail="오늘 전체 이용 한도에 도달했습니다. 내일 다시 이용해주세요.",
        )


@app.post("/api/chat")
async def chat(request: ChatRequest, http_request: Request):
    query = request.query.strip()
    history = [h.model_dump() for h in request.history[-3:]]
    visitor_id = request.visitor_id
    ip_hash = _client_ip_hash(http_request)
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
                )
                yield _sse({"type": "result", **cached, "cached": True})

            return StreamingResponse(
                cached_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

    async def event_stream():
        start = time.time()
        merged: dict = {"citations": []}
        usage_handler = UsageMetadataCallbackHandler()

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
                        yield _sse({"type": "token", "content": content})
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
                            "data": agent_result.model_dump() if agent_result else None,
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
            )
            yield _sse({"type": "error", "message": f"분석 중 오류가 발생했습니다: {e}"})

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

    try:
        doc_id, chunks = ingest_pdf(content, file.filename)
    except IngestError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    db.add_document(doc_id, file.filename, chunks)
    # 색인이 바뀌면 이전 답변은 낡은 근거일 수 있으므로 캐시를 비운다
    db.clear_cache()
    return {"doc_id": doc_id, "filename": file.filename, "chunks": chunks}


@app.get("/api/documents", dependencies=[admin_only])
def get_documents():
    return {"documents": db.list_documents(), "indexed_chunks": store.chunk_count()}


@app.delete("/api/documents/{doc_id}", dependencies=[admin_only])
def delete_document(doc_id: str):
    if not db.delete_document(doc_id):
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    store.delete_doc(doc_id)
    db.clear_cache()
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
    return {**db.get_settings(DEFAULT_LIMITS), "used_today": db.count_today()}


@app.put("/api/settings", dependencies=[admin_only])
def update_settings(request: SettingsRequest):
    db.set_settings(request.model_dump())
    return {**db.get_settings(DEFAULT_LIMITS), "used_today": db.count_today()}


@app.get("/api/stats", dependencies=[admin_only])
def get_stats(days: int = 14):
    stats = db.get_stats(min(max(days, 1), 90))
    stats["limits"] = {**db.get_settings(DEFAULT_LIMITS), "used_today": db.count_today()}
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
