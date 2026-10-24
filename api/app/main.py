"""FastAPI 서버: 공개 API(헬스·SSE 채팅·피드백·방문 기록). 관리자 API는 app/admin.py."""

import hashlib
import hmac
import json
import re
import secrets
import time

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from starlette.datastructures import MutableHeaders

from app import admin, db, pricing
from app.agents.graph import graph
from app.agents.schemas import overall_risk
from app.config import (
    ADMIN_TOKEN,
    APP_VERSION,
    CLAUDE_MODEL,
    CORS_ORIGINS,
    DEFAULT_LIMITS,
    IP_HASH_SALT,
    MAX_INFLIGHT_TOTAL,
    MOCK_MODE,
    RETENTION_DAYS,
    SIGNING_KEY_IS_PUBLIC,
    VOYAGE_EMBEDDING_MODEL,
)
from app.privacy import StreamMasker, mask_obj, mask_text
from app.rag import store
from app.security import is_admin_request

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
app.include_router(admin.router)


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


def _stage_timings(start: float, marks: dict[str, float]) -> dict:
    """노드 완료 시각으로 단계별 소요 시간(초)을 계산한다.

    규정 검토·감사 분석은 동시에 돌므로 각자 검색 완료 시점부터 잰다. 종합 조정은 두 분석이
    모두 끝난 시점부터 첫 글자(ttft)와 끝까지를 잰다.
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
    return t


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "mock_mode": MOCK_MODE,
        "admin_protected": bool(ADMIN_TOKEN),
        # 질문 분류·분석·종합·OCR을 돌리는 모델과 검색 임베딩 모델
        "model": CLAUDE_MODEL,
        "embedding_model": VOYAGE_EMBEDDING_MODEL,
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
        # 프롬프트의 실명 금지 규칙은 확률적이다. 나가는 모든 텍스트를 코드가 한 번 더 지운다.
        masker = StreamMasker()
        recorded = False  # 정상·오류 경로에서 지표를 남겼는지
        marks: dict[str, float] = {}  # 노드별 완료 시각 (단계별 소요 시간 계산용)

        def _timings() -> dict:
            return _stage_timings(start, marks)

        # 각 Claude 호출이 custom 스트림으로 흘린 사용량을 모은다 (요청 비용·토큰 집계)
        claude_usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        fallbacks: list[str] = []  # 낮춘 경로로 이어간 단계 (검색 키워드만·분류 실패)

        def _fallback() -> str | None:
            return ",".join(dict.fromkeys(fallbacks)) or None

        def _token_totals() -> tuple[int, int]:
            return claude_usage["input_tokens"], claude_usage["output_tokens"]

        def _request_cost() -> float:
            return claude_usage["cost_usd"]

        try:
            yield _sse({"type": "stage", "label": "질문 분석 중..."})

            async for mode, payload in graph.astream(
                {"query": query, "history": history, "citations": []},
                stream_mode=["updates", "custom"],
            ):
                if mode == "custom":
                    # Claude 단계가 직접 흘리는 토큰·사용량
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
                                usage.get("model") or CLAUDE_MODEL, in_tok, out_tok,
                                int(usage.get("cached_tokens", 0)),
                            )
                        if stage := payload.get("fallback"):
                            fallbacks.append(str(stage))
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


# 보존 기간이 지난 기록은 기동 시 정리한다 (지표·방문·분석·오래된 답변 캐시)
db.purge_old(RETENTION_DAYS)
# 원문 마스킹 이전에 쌓인 행을 소급해 지운다 (멱등 — 바뀔 행이 없으면 0건)
db.mask_stored_text()
# 지금 쓰지 않는 임베딩 모델의 옛 색인을 지운다 (멱등)
try:
    if dropped := store.drop_stale_collections():
        print(f"옛 색인 컬렉션 삭제: {dropped}")
except Exception as e:  # noqa: BLE001 - 정리 실패가 기동(헬스체크)을 막으면 크래시 루프가 된다
    print(f"옛 색인 컬렉션 정리 실패, 건너뜀: {type(e).__name__}: {e}")
