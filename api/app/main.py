"""FastAPI 서버: SSE 스트리밍 채팅 + 문서 관리 API."""

import asyncio
import hashlib
import hmac
import io
import json
import re
import secrets
import tempfile
import time
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from langchain_core.callbacks import UsageMetadataCallbackHandler
from pydantic import BaseModel, Field, field_validator
from starlette.datastructures import MutableHeaders

from app import db, pricing
from app.agents.graph import content_to_text, graph
from app.agents.schemas import overall_risk
from app.config import (
    ADMIN_TOKEN,
    AGENT_MODEL,
    AGENT_PROVIDER,
    APP_VERSION,
    CORS_ORIGINS,
    DEFAULT_LIMITS,
    ROUTER_MODEL,
    IP_HASH_SALT,
    MAX_INFLIGHT_TOTAL,
    MOCK_MODE,
    OCR_CACHE_DIR,
    RETENTION_DAYS,
    SIGNING_KEY_IS_PUBLIC,
)
from app.privacy import PRIVATE_NAMES, StreamMasker, mask_obj, mask_text
from app.rag import citation_graph, store
from app.rag.ingest import IngestError, ingest_pdf

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_QUERY_LENGTH = 1000

app = FastAPI(
    title="학생회 규정 AI 어시스턴트 API",
    version=APP_VERSION,
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


# 서명 키가 공개 상수면 토큰을 누구나 계산할 수 있다 — 그때는 피드백을 받지 않는다
FEEDBACK_ENABLED = not SIGNING_KEY_IS_PUBLIC


def _feedback_token(analysis_id: int) -> str:
    """답변을 실제로 받은 쪽만 평가할 수 있게 하는 서명.

    analysis_id는 순번이라 누구나 추측할 수 있다. 서명 없이 받으면 아직 평가가
    없는 답변을 남이 먼저 차지할 수 있다 (선점). 결과 이벤트와 함께 내려준다.
    """
    msg = f"feedback:{analysis_id}".encode()
    return hmac.new(IP_HASH_SALT.encode(), msg, hashlib.sha256).hexdigest()[:32]


def _stage_timings(start: float, marks: dict[str, float], usage: dict) -> dict:
    """노드 완료 시각으로 단계별 소요 시간(초)을 계산한다.

    규정 검토·감사 분석은 동시에 돌므로 각자 검색 완료 시점부터 잰다. 종합 조정은 두 분석이
    모두 끝난 시점부터 첫 글자(ttft)와 끝까지를 잰다. 사고 토큰은 첫 글자 전에 생성돼
    지연의 주원인이 되므로 함께 남긴다 (모델 구분 없이 합계).
    """
    t: dict = {}

    def gap(end: str, begin: float | None) -> None:
        if end in marks and begin is not None:
            t[end] = round(marks[end] - begin, 2)

    gap("router", start)
    gap("retrieve", marks.get("router"))
    gap("reviewer", marks.get("retrieve"))
    gap("auditor", marks.get("retrieve"))
    agents_done = max((marks[k] for k in ("reviewer", "auditor") if k in marks), default=None)
    if "coordinator_first_token" in marks and agents_done is not None:
        t["coordinator_ttft"] = round(marks["coordinator_first_token"] - agents_done, 2)
    gap("coordinator", agents_done)
    reasoning = sum(
        (u.get("output_token_details") or {}).get("reasoning", 0) for u in usage.values()
    )
    if reasoning:
        t["reasoning_tokens"] = reasoning
    return t


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
            detail="ADMIN_TOKEN이 설정되지 않아 관리자 API를 열지 않았어요.",
        )
    expected = f"Bearer {ADMIN_TOKEN}"
    # 바이트로 비교한다. 문자열 비교는 비ASCII 헤더에서 TypeError → 500이 된다.
    if not authorization or not secrets.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="관리자 인증이 필요해요.")


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
        "version": APP_VERSION,
        "mock_mode": MOCK_MODE,
        "admin_protected": bool(ADMIN_TOKEN),
        # 분석·종합을 실제로 돌리는 모델. 질문 분류(router)는 공급자와 무관하게 Gemini다
        "agent_provider": AGENT_PROVIDER,
        "model": AGENT_MODEL,
        "router_model": ROUTER_MODEL,
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
            status_code=429, detail="지금 요청이 몰려 있어요. 잠시 후 다시 시도해 주세요."
        )

    limits = db.get_settings(DEFAULT_LIMITS)

    per_user = limits["daily_limit_per_user"]
    used_by_user = db.count_today(visitor_id) + _inflight.get(f"u:{visitor_id}", 0)
    if per_user > 0 and visitor_id and used_by_user >= per_user:
        raise HTTPException(
            status_code=429,
            detail=f"오늘 질문할 수 있는 횟수({per_user}회)를 모두 썼어요. 내일 다시 이용해 주세요.",
        )

    # visitor_id는 브라우저 저장소를 비우면 초기화되므로 IP 기준으로 한 번 더 막는다
    per_ip = limits["daily_limit_per_ip"]
    used_by_ip = (db.count_today_by_ip(ip_hash) if ip_hash else 0) + _inflight.get(f"ip:{ip_hash}", 0)
    if per_ip > 0 and ip_hash and used_by_ip >= per_ip:
        raise HTTPException(
            status_code=429,
            detail="같은 네트워크에서 오늘 이용할 수 있는 횟수를 모두 썼어요. 내일 다시 이용해 주세요.",
        )

    total = limits["daily_limit_total"]
    if total > 0 and db.count_today() + _inflight.get("total", 0) >= total:
        raise HTTPException(
            status_code=429,
            detail="오늘 전체 이용 한도에 도달했어요. 내일 다시 이용해 주세요.",
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
    # 마스킹 대상(실명·전화·계좌·이메일)이 든 질의는 캐시하지 않는다 — 캐시 키가 곧
    # 질의 원문이라 그대로 저장된다. 실명만 검사하면 연락처가 든 질의가 새어 나간다.
    cache_key = db.normalize_query(query) if not history and mask_text(query) == query else None
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
                    cost_usd=0.0,  # LLM 미호출 — 비용 기록이 없는 옛 행과 구분한다
                    query_preview=query,
                    analysis_id=cached.get("analysis_id"),
                    visitor_id=visitor_id,
                    ip_hash=ip_hash,
                    is_admin=is_admin,
                )
                payload = {"type": "result", **mask_obj(cached), "cached": True}
                if cached.get("analysis_id") and FEEDBACK_ENABLED:
                    payload["feedback_token"] = _feedback_token(cached["analysis_id"])
                yield _sse(payload)

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
    cache_generation = db.cache_generation()

    async def event_stream():
        start = time.time()
        merged: dict = {"citations": []}
        usage_handler = UsageMetadataCallbackHandler()
        # 프롬프트의 실명 금지 규칙은 확률적이다. 나가는 모든 텍스트를 코드가 한 번 더 지운다.
        masker = StreamMasker()
        recorded = False  # 정상·오류 경로에서 지표를 남겼는지
        marks: dict[str, float] = {}  # 노드별 완료 시각 (단계별 소요 시간 계산용)

        def _timings() -> dict:
            return _stage_timings(start, marks, usage_handler.usage_metadata or {})

        # Claude 단계는 LangChain 콜백에 잡히지 않아 custom 스트림으로 받은 사용량을 따로 모은다
        claude_usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        fallbacks: list[str] = []  # Claude가 실패해 Gemini로 넘어간 단계

        def _fallback() -> str | None:
            # 같은 단계가 두 번 남을 수 있다 (Claude 실패 → Gemini도 실패)
            return ",".join(dict.fromkeys(fallbacks)) or None

        def _gemini_totals() -> tuple[int, int]:
            usage = usage_handler.usage_metadata or {}
            return (
                sum(u.get("input_tokens", 0) for u in usage.values()),
                sum(u.get("output_tokens", 0) for u in usage.values()),
            )

        def _token_totals() -> tuple[int, int]:
            g_in, g_out = _gemini_totals()
            return g_in + claude_usage["input_tokens"], g_out + claude_usage["output_tokens"]

        def _request_cost() -> float:
            # 모델별 단가 + 캐시 적중 할인. 질문 분류(Flash-Lite)와 폴백(Flash)이 섞여도 각각 매긴다
            return pricing.langchain_usage_cost(usage_handler.usage_metadata) + claude_usage["cost_usd"]

        try:
            yield _sse({"type": "stage", "label": "질문 분석 중..."})

            async for mode, payload in graph.astream(
                {"query": query, "history": history, "citations": []},
                config={"callbacks": [usage_handler]},
                stream_mode=["updates", "messages", "custom"],
            ):
                if mode == "custom":
                    # Claude 단계가 직접 흘리는 토큰·사용량 (LangChain 모델이 아니라 messages에 안 잡힘)
                    if isinstance(payload, dict):
                        if text := payload.get("token"):
                            marks.setdefault("coordinator_first_token", time.time())
                            if visible := masker.feed(text):
                                yield _sse({"type": "token", "content": visible})
                        if usage := payload.get("usage"):
                            in_tok = int(usage.get("input_tokens", 0))
                            out_tok = int(usage.get("output_tokens", 0))
                            claude_usage["input_tokens"] += in_tok
                            claude_usage["output_tokens"] += out_tok
                            claude_usage["cost_usd"] += pricing.cost_usd(
                                usage.get("model") or AGENT_MODEL, in_tok, out_tok,
                                int(usage.get("cached_tokens", 0)),
                            )
                        if stage := payload.get("fallback"):
                            fallbacks.append(str(stage))
                    continue
                if mode == "messages":
                    chunk, meta = payload
                    node = meta.get("langgraph_node", "")
                    content = content_to_text(getattr(chunk, "content", ""))
                    if node in ("coordinator", "general") and content:
                        marks.setdefault("coordinator_first_token", time.time())
                        if visible := masker.feed(content):
                            yield _sse({"type": "token", "content": visible})
                    continue

                # mode == "updates": {node_name: state_delta}
                for node, delta in payload.items():
                    marks[node] = time.time()
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
            partial = bool(merged.get("partial"))
            db.record_metric(
                route=merged.get("route"),
                risk_level=risk,
                # 잘린 답은 정상과 구분해 남긴다 (대시보드 오류 집계에 잡혀 절단 빈도가 보인다)
                status="partial" if partial else "ok",
                elapsed=result["elapsed"],
                input_tokens=in_tok,
                output_tokens=out_tok,
                query_preview=query,
                analysis_id=analysis_id,
                visitor_id=visitor_id,
                ip_hash=ip_hash,
                is_admin=is_admin,
                stage_timings=_timings(),
                cost_usd=_request_cost(),
                fallback=_fallback(),
            )
            recorded = True
            # 잘린 답을 캐시하면 같은 질문을 한 모든 사용자에게 하루 동안 잘린 답이 나간다
            if cache_key and not partial:
                db.save_cached_answer(cache_key, analysis_id, result, cache_generation)
            # analysis_id는 저장 후에야 정해지므로 응답에만 덧붙인다 (피드백 전송용)
            yield _sse({
                "type": "result",
                **result,
                "analysis_id": analysis_id,
                "feedback_token": _feedback_token(analysis_id) if FEEDBACK_ENABLED else None,
            })

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
                stage_timings=_timings(),
                cost_usd=_request_cost(),
                fallback=_fallback(),
            )
            recorded = True
            # 예외 원문(LLM 출력 조각·내부 경로가 섞일 수 있음)은 지표에만 남기고 사용자에겐 일반 문구
            yield _sse({"type": "error", "message": "분석 중 오류가 생겼어요. 잠시 후 다시 시도해 주세요."})
        finally:
            _inflight_add(inflight_keys, -1)
            if not recorded:
                # 클라이언트가 끊어 스트림이 중간에 닫혔다. LLM 비용은 이미 발생했으므로
                # 기록해야 '완료 건수'로 세는 일일 한도를 끊기로 우회할 수 없다.
                in_tok, out_tok = _token_totals()
                db.record_metric(
                    route=merged.get("route"),
                    risk_level=None,
                    status="cancelled",
                    stage_timings=_timings(),
                    cost_usd=_request_cost(),
                    fallback=_fallback(),
                    elapsed=round(time.time() - start, 2),
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    query_preview=query,
                    visitor_id=visitor_id,
                    ip_hash=ip_hash,
                    is_admin=is_admin,
                    error="client disconnected",
                )

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
        raise HTTPException(status_code=400, detail="PDF 파일만 올릴 수 있어요.")

    content = await _read_limited(file, MAX_UPLOAD_BYTES)

    # OCR·임베딩·그래프 재구축은 수 분이 걸리는 동기 작업이다. 이벤트 루프에서
    # 돌리면 그동안 모든 채팅 스트림이 멈추므로 스레드로 보낸다.
    try:
        doc_id, chunks = await asyncio.to_thread(_index_upload, content, file.filename)
    except IngestError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"doc_id": doc_id, "filename": file.filename, "chunks": chunks}


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    """상한까지만 조금씩 읽는다. 통째로 읽고 나서 크기를 재면 큰 파일이 먼저 메모리에 다 올라간다."""
    buf = bytearray()
    while chunk := await file.read(1024 * 1024):
        buf += chunk
        if len(buf) > limit:
            raise HTTPException(status_code=413, detail="파일이 너무 커요 (최대 20MB).")
    return bytes(buf)


def _after_index_change() -> None:
    """색인이 바뀐 뒤 파생물(답변 캐시·인용 그래프)을 갱신한다. 업로드·삭제 공통.

    문서 변경은 이미 끝난 뒤라, 여기서 실패해도 요청을 실패로 돌려주지 않는다.
    실패로 알리면 운영자는 반영된 업로드를 다시 올리거나 삭제를 재시도한다.
    """
    # 색인이 바뀌면 이전 답변은 낡은 근거일 수 있으므로 캐시를 비운다
    db.clear_cache()
    # 인용 그래프도 색인의 파생물이므로 함께 재생성한다 (약 2초, 낡은 그래프 방지)
    try:
        citation_graph.get_graph(rebuild=True)
    except Exception as e:  # noqa: BLE001 - 파생물 실패가 끝난 문서 변경을 되돌리지 않도록
        print(f"인용 그래프 재생성 실패, 다음 조회 때 다시 만든다: {type(e).__name__}: {e}")
        citation_graph.invalidate()


def _index_upload(content: bytes, filename: str) -> tuple[str, int]:
    doc_id, chunks = ingest_pdf(content, filename)
    try:
        db.add_document(doc_id, filename, chunks)
    except Exception:
        store.delete_doc(doc_id)  # 목록에 없는 청크가 검색에 섞이지 않도록 회수
        raise
    _after_index_change()
    return doc_id, chunks


@app.get("/api/documents", dependencies=[admin_only])
def get_documents():
    return {"documents": db.list_documents(), "indexed_chunks": store.chunk_count()}


@app.delete("/api/documents/{doc_id}", dependencies=[admin_only])
def delete_document(doc_id: str):
    # 청크를 먼저 지운다. DB 행을 먼저 지우면 청크 삭제가 실패했을 때 재시도가 404가 된다.
    store.delete_doc(doc_id)
    if not db.delete_document(doc_id):
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없어요.")
    _after_index_change()
    return {"deleted": doc_id}


# ---------------------------------------------------------------- history / stats

@app.get("/api/history", dependencies=[admin_only])
def get_history(limit: int = 20):
    return {"analyses": db.list_analyses(max(1, min(limit, 100)))}


@app.get("/api/analyses/{analysis_id}", dependencies=[admin_only])
def get_analysis(analysis_id: int):
    item = db.get_analysis(analysis_id)
    if not item:
        raise HTTPException(status_code=404, detail="분석 기록을 찾을 수 없어요.")
    return item


class FeedbackRequest(BaseModel):
    analysis_id: int = Field(ge=1)
    helpful: bool
    visitor_id: str | None = Field(default=None, max_length=64)
    # 결과 이벤트로 받은 서명 — 답변을 받은 사람만 평가할 수 있다
    token: str = Field(min_length=16, max_length=64)


@app.post("/api/feedback")
def submit_feedback(request: FeedbackRequest):
    """답변 만족도 수집 (공개 — 사용자가 누르는 버튼)."""
    if not FEEDBACK_ENABLED:
        raise HTTPException(status_code=503, detail="서명 키가 설정되지 않아 피드백을 받지 않아요.")
    expected = _feedback_token(request.analysis_id)
    if not secrets.compare_digest(request.token.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="이 답변을 평가할 수 없어요.")
    if not db.get_analysis(request.analysis_id):
        raise HTTPException(status_code=404, detail="분석 기록을 찾을 수 없어요.")
    db.add_feedback(request.analysis_id, request.helpful, request.visitor_id)
    return {"ok": True}


class TrackRequest(BaseModel):
    visitor_id: str = Field(min_length=8, max_length=64)


@app.post("/api/track")
def track_visit(request: TrackRequest):
    db.add_visit(request.visitor_id)
    return {"ok": True}


@app.get("/api/backup", dependencies=[admin_only])
def download_backup():
    """되살릴 수 없는 운영 데이터를 zip 하나로 내려준다 (backup_remote.py가 받아 로컬에 보관).

    담는 것: SQLite(지표·분석·피드백·설정·방문)와 OCR 캐시. 색인(Chroma)·인용 그래프는 문서로
    다시 만들 수 있어 뺀다 — OCR 캐시가 있으면 재색인 때 OCR(약 750원)을 다시 부르지 않는다.
    Railway 볼륨 백업은 Pro 요금제 전용이라 쓰지 않는다.
    """
    buffer = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / "app.sqlite3"
        db.snapshot(str(db_copy))
        ocr_files = sorted(OCR_CACHE_DIR.glob("*.txt"))
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_copy, "app.sqlite3")
            for f in ocr_files:
                zf.write(f, f"ocr_cache/{f.name}")
            zf.writestr("manifest.json", json.dumps({
                "version": APP_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "ocr_cache_files": len(ocr_files),
            }))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=backup-{stamp}.zip"},
    )


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


# 요청별 비용(cost_usd)을 남기기 전(~v2.8) 행은 모델·캐시 구분 없이 토큰 합만 있다. 그때 분석 모델이던
# Flash의 당시 단가로 한 번에 매긴다 — 질문 분류(Flash-Lite)까지 Flash로 세므로 실제보다 약간 높다.
_LEGACY_MODEL = "gemini-3.7-flash"
_LEGACY_PRICED_ON = date(2026, 10, 13)


def _legacy_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return pricing.cost_usd(_LEGACY_MODEL, input_tokens, output_tokens, on=_LEGACY_PRICED_ON)


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
    # 요청별 비용(cost_usd)이 있는 행은 그 값을, 도입 전 행은 토큰 합으로 추정해 더한다 (USD만 쓴다)
    legacy_usd = _legacy_cost_usd(
        stats["totals"]["legacy_input_tokens"], stats["totals"]["legacy_output_tokens"])
    today_legacy_usd = _legacy_cost_usd(
        stats["today"]["legacy_input_tokens"], stats["today"]["legacy_output_tokens"])
    stats["cost"] = {
        "total_usd": round(stats["totals"]["cost_usd"] + legacy_usd, 4),
        "today_usd": round(stats["today"]["cost_usd"] + today_legacy_usd, 4),
        # 위 합계 중 모델별 기록 없이 토큰 합으로 추정한 몫
        "estimated_usd": round(legacy_usd, 4),
    }
    stats["agent"] = {"provider": AGENT_PROVIDER, "model": AGENT_MODEL}
    return stats


# 보존 기간이 지난 기록은 기동 시 정리한다 (지표·방문·분석·오래된 답변 캐시)
db.purge_old(RETENTION_DAYS)
# 원문 마스킹 이전에 쌓인 행을 소급해 지운다 (멱등 — 바뀔 행이 없으면 0건)
db.mask_stored_text()
