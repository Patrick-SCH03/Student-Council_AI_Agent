"""FastAPI 서버: SSE 스트리밍 채팅 + 문서 관리 API."""

import json
import time

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import db
from app.agents.graph import content_to_text, graph
from app.agents.schemas import overall_risk
from app.config import CORS_ORIGINS, GEMINI_MODEL, MOCK_MODE
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


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "mock_mode": MOCK_MODE,
        "model": GEMINI_MODEL,
        "indexed_chunks": store.chunk_count(),
    }


# ---------------------------------------------------------------- chat (SSE)

_STAGE_LABELS = {
    "regulation": "규정 검토·감사 에이전트 병렬 분석 중...",
    "general": "답변 생성 중...",
}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    query = request.query.strip()
    history = [h.model_dump() for h in request.history[-3:]]

    async def event_stream():
        start = time.time()
        merged: dict = {"citations": []}
        try:
            yield _sse({"type": "stage", "label": "질문 분석 중..."})

            async for mode, payload in graph.astream(
                {"query": query, "history": history, "citations": []},
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

            result = {
                "query": query,
                "route": merged.get("route", ""),
                "risk_level": risk,
                "final_markdown": merged.get("final_markdown", ""),
                "reviewer": reviewer.model_dump() if reviewer else None,
                "auditor": auditor.model_dump() if auditor else None,
                "citations": citations,
                "elapsed": round(time.time() - start, 2),
            }
            db.add_analysis(query, risk, result)
            yield _sse({"type": "result", **result})

        except Exception as e:  # noqa: BLE001 - 스트림 내 오류는 이벤트로 전달
            yield _sse({"type": "error", "message": f"분석 중 오류가 발생했습니다: {e}"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------- documents

@app.post("/api/documents")
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
    return {"doc_id": doc_id, "filename": file.filename, "chunks": chunks}


@app.get("/api/documents")
def get_documents():
    return {"documents": db.list_documents(), "indexed_chunks": store.chunk_count()}


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    if not db.delete_document(doc_id):
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    store.delete_doc(doc_id)
    return {"deleted": doc_id}


# ---------------------------------------------------------------- history

@app.get("/api/history")
def get_history(limit: int = 20):
    return {"analyses": db.list_analyses(min(limit, 100))}
