"""관리자 API: 문서·색인 관리, 백업, 운영 지표, 설정. 모두 ADMIN_TOKEN이 있어야 한다.

색인은 로컬에서 만들어 옮긴다 (ingest_folder.py → sync_index_to_remote.py → /api/index/import).
서버가 PDF를 직접 받아 OCR·임베딩하는 업로드 경로는 두지 않는다 — 큰 문서는 프록시 제한에
걸리고, 관리자 API가 외부 유료 호출을 일으키는 면도 줄인다.
"""

import io
import json
import tempfile
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field, field_validator

from app import db, events, notice
from app.config import APP_VERSION, CLAUDE_MODEL, DEFAULT_LIMITS, EMBEDDING_MODEL, OCR_CACHE_DIR
from app.privacy import PRIVATE_NAMES
from app.rag import citation_graph, store
from app.security import admin_only

router = APIRouter(prefix="/api", dependencies=[admin_only])


def after_index_change() -> None:
    """색인이 바뀐 뒤 파생물(답변 캐시·인용 그래프)을 갱신한다. 넣기·지우기·비우기 공통.

    문서 변경은 이미 끝난 뒤라, 여기서 실패해도 요청을 실패로 돌려주지 않는다.
    실패로 알리면 운영자는 반영된 변경을 다시 시도한다.
    """
    # 색인이 바뀌면 이전 답변은 낡은 근거일 수 있으므로 캐시를 비운다
    db.clear_cache()
    # 인용 그래프도 색인의 파생물이므로 함께 재생성한다 (약 2초, 낡은 그래프 방지)
    try:
        citation_graph.get_graph(rebuild=True)
    except Exception as e:  # noqa: BLE001 - 파생물 실패가 끝난 문서 변경을 되돌리지 않도록
        print(f"인용 그래프 재생성 실패, 다음 조회 때 다시 만든다: {type(e).__name__}: {e}")
        citation_graph.invalidate()


# ---------------------------------------------------------------- 문서·색인

@router.get("/documents")
def get_documents():
    return {"documents": db.list_documents(), "indexed_chunks": store.chunk_count()}


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str):
    # 청크를 먼저 지운다. DB 행을 먼저 지우면 청크 삭제가 실패했을 때 재시도가 404가 된다.
    store.delete_doc(doc_id)
    if not db.delete_document(doc_id):
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없어요.")
    after_index_change()
    return {"deleted": doc_id}


class ImportRequest(BaseModel):
    filename: str = Field(min_length=5, max_length=200)
    chunks: list[str] = Field(min_length=1, max_length=2000)
    embeddings: list[list[float]] = Field(min_length=1, max_length=2000)

    @field_validator("filename")
    @classmethod
    def _pdf_name(cls, v: str) -> str:
        if not v.lower().endswith(".pdf") or "/" in v or "\\" in v:
            raise ValueError("PDF 파일 이름만 받는다")
        return v


@router.post("/index/import")
def import_document(request: ImportRequest):
    """로컬에서 추출·임베딩까지 끝낸 문서를 그대로 색인에 넣는다 (sync_index_to_remote.py가 부른다).

    외부 API를 부르지 않아 몇 초 안에 끝나고, 로컬과 운영 색인이 똑같아진다.
    """
    if len(request.chunks) != len(request.embeddings):
        raise HTTPException(status_code=422, detail="청크와 임베딩 개수가 달라요.")
    dims = {len(e) for e in request.embeddings}
    if len(dims) != 1 or not 64 <= dims.pop() <= 8192:
        raise HTTPException(status_code=422, detail="임베딩 차원이 올바르지 않아요.")
    if any(len(c) > 5000 for c in request.chunks):
        raise HTTPException(status_code=422, detail="청크가 너무 길어요.")
    if any(d["filename"] == request.filename for d in db.list_documents()):
        raise HTTPException(status_code=409, detail="이미 색인된 문서예요.")

    doc_id = uuid.uuid4().hex
    try:
        added = store.add_chunks(doc_id, request.filename, request.chunks, request.embeddings)
        db.add_document(doc_id, request.filename, added)
    except Exception:
        store.delete_doc(doc_id)  # 목록에 없는 청크가 검색에 섞이지 않도록 회수
        raise
    after_index_change()
    return {"doc_id": doc_id, "filename": request.filename, "chunks": added}


@router.post("/index/reset")
def reset_index(confirm: bool = False):
    """전체 재색인 준비: 문서 목록·색인·OCR 캐시·답변 캐시·인용 그래프를 모두 비운다.

    추출·임베딩 모델을 바꾼 뒤 sync_index_to_remote.py로 다시 옮기기 전에 부른다.
    되돌릴 수 없어 confirm=true를 요구한다 (먼저 backup_remote.py로 백업할 것).
    """
    if not confirm:
        raise HTTPException(status_code=400, detail="되돌릴 수 없는 작업이라 confirm=true가 필요해요.")
    chunks = store.reset_collection()
    documents = db.delete_all_documents()
    ocr_files = 0
    for f in OCR_CACHE_DIR.glob("*.txt"):
        f.unlink()
        ocr_files += 1
    after_index_change()
    return {"documents": documents, "chunks": chunks, "ocr_cache_files": ocr_files}


@router.get("/backup")
def download_backup():
    """되살릴 수 없는 운영 데이터를 zip 하나로 내려준다 (backup_remote.py가 받아 로컬에 보관).

    담는 것: SQLite(지표·분석·피드백·설정·방문)와 OCR 캐시. 색인(Chroma)·인용 그래프는 문서로
    다시 만들 수 있어 뺀다. Railway 볼륨 백업은 Pro 요금제 전용이라 쓰지 않는다.
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


# ---------------------------------------------------------------- 분석 기록·지표

@router.get("/history")
def get_history(limit: int = 20):
    return {"analyses": db.list_analyses(max(1, min(limit, 100)))}


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: int):
    item = db.get_analysis(analysis_id)
    if not item:
        raise HTTPException(status_code=404, detail="분석 기록을 찾을 수 없어요.")
    return item


@router.get("/stats/export")
def export_stats():
    return PlainTextResponse(
        db.export_metrics_csv(),
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
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1]) / 1024  # kB → MB
                break
    except OSError:
        pass

    # cgroup v2 우선, 없으면 v1
    used = _read("/sys/fs/cgroup/memory.current") or _read("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    limit = _read("/sys/fs/cgroup/memory.max") or _read("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    # 상한이 없으면 호스트 전체 메모리가 찍히므로(수십 GB) 의미 없는 값은 버린다
    limit_mb = limit / 1024 / 1024 if limit and limit < 1 << 43 else None
    return {
        "rss_mb": round(rss, 1) if rss else None,
        "container_mb": round(used / 1024 / 1024, 1) if used else None,
        "limit_mb": round(limit_mb, 1) if limit_mb else None,
    }


# 요청별 비용(cost_usd)을 남기기 전(~v2.8) 행은 모델·캐시 구분 없이 토큰 합만 있다.
# 그 시기 분석 모델의 단가(입력, 출력 USD / 1M 토큰)로 한 번에 추정한다. 새 행에는 쓰지 않는다.
_LEGACY_RATES = (0.75, 3.75)


def _legacy_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * _LEGACY_RATES[0] + output_tokens * _LEGACY_RATES[1]) / 1_000_000


@router.get("/stats")
def get_stats(days: int = 14):
    stats = db.get_stats(min(max(days, 1), 90))
    stats["limits"] = {**db.get_settings(DEFAULT_LIMITS), "used_today": db.count_today()}
    stats["memory"] = _memory_mb()
    # 요청별 비용이 있는 행은 그 값을, 도입 전 행은 토큰 합으로 추정해 더한다 (USD만 쓴다)
    legacy_usd = _legacy_cost_usd(stats["totals"]["legacy_input_tokens"], stats["totals"]["legacy_output_tokens"])
    today_legacy_usd = _legacy_cost_usd(stats["today"]["legacy_input_tokens"], stats["today"]["legacy_output_tokens"])
    stats["cost"] = {
        "total_usd": round(stats["totals"]["cost_usd"] + legacy_usd, 4),
        "today_usd": round(stats["today"]["cost_usd"] + today_legacy_usd, 4),
        # 위 합계 중 모델별 기록 없이 토큰 합으로 추정한 몫
        "estimated_usd": round(legacy_usd, 4),
    }
    stats["agent"] = {"model": CLAUDE_MODEL, "embedding_model": EMBEDDING_MODEL}
    return stats


# ---------------------------------------------------------------- 설정·캐시

class SettingsRequest(BaseModel):
    daily_limit_total: int = Field(ge=0, le=100_000)
    daily_limit_per_user: int = Field(ge=0, le=10_000)
    daily_limit_per_ip: int = Field(default=60, ge=0, le=10_000)
    cache_ttl_hours: int = Field(default=24, ge=0, le=720)


def _settings_view() -> dict:
    return {
        **db.get_settings(DEFAULT_LIMITS),
        "used_today": db.count_today(),
        # 마스킹 목록이 실제로 로드됐는지 운영자가 확인할 수 있게 개수만 노출한다
        "private_names": len(PRIVATE_NAMES),
    }


@router.get("/settings")
def get_settings():
    return _settings_view()


@router.put("/settings")
def update_settings(request: SettingsRequest):
    db.set_settings(request.model_dump())
    return _settings_view()



@router.get("/contributions")
def list_contributions(limit: int = 50):
    """서비스 개선용 자료 최근 목록 (가명 처리본, 본문은 앞부분만). 전체는 /api/backup의 SQLite에 있다."""
    return {"items": db.list_contributions(limit)}


@router.get("/settings/events")
def get_events_setting():
    """지난 일정까지 그대로 (정리할 수 있게)."""
    return {"events": events.stored()}


@router.put("/settings/events")
def save_events(request: events.EventsIn):
    return {"events": events.save(request)}


@router.get("/settings/notice")
def get_notice_setting():
    """끝난 공지도 그대로 보여 준다 (다시 올리거나 내릴 수 있게)."""
    return {"notice": notice.stored()}


@router.put("/settings/notice")
def publish_notice(request: notice.NoticeIn):
    return {"notice": notice.publish(request)}


@router.post("/settings/notice/draft")
async def draft_notice(request: Request):
    """공고문 사진·PDF(본문 = 파일 바이트) → 공지 초안. 올리기는 화면이 PUT /settings/notice로 한다.

    LLM 1회(공고 한 장 약 $0.0002). 지표 경로는 'review-' 접두어라 규정 질문 한도에서 빠진다. 원본은 저장하지 않는다.
    """
    from app.quota import llm_slots
    from app.review.service import Usage

    if int(request.headers.get("content-length") or 0) > notice.DRAFT_MAX_BYTES:
        raise HTTPException(413, "파일이 너무 커요. 5MB 이하로 올려 주세요.")
    data = await request.body()
    try:
        notice.sniff(data)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    usage, started, error = Usage(), time.monotonic(), None
    try:
        async with llm_slots:
            return {"draft": await notice.draft_from_file(data, on_usage=usage.add)}
    except notice.DraftError as e:
        error = str(e)
        raise HTTPException(422, str(e)) from e
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"
        raise HTTPException(503, "공고문을 읽지 못했어요. 잠시 뒤 다시 시도해 주세요.") from e
    except BaseException:  # 클라이언트가 끊으면(CancelledError) 성공으로 남기지 않는다
        error = "cancelled"
        raise
    finally:
        db.record_metric(
            route="review-notice-draft", risk_level=None,
            status="cancelled" if error == "cancelled" else "error" if error else "ok",
            elapsed=time.monotonic() - started, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
            query_preview="", visitor_id="admin", is_admin=True, error=error, cost_usd=round(usage.cost_usd, 6),
        )


@router.delete("/settings/notice")
def withdraw_notice():
    notice.withdraw()
    return {"notice": None}

# ---------------------------------------------------------------- 회원 관리


class BlockIn(BaseModel):
    blocked: bool


def _member(user_id: int) -> dict:
    from app.config import ADMIN_EMAILS

    detail = db.user_detail(user_id)
    if not detail:
        raise HTTPException(404, "없는 계정이에요.")
    detail["user"]["role"] = "admin" if detail["user"]["email"] in ADMIN_EMAILS else "member"
    return detail


def _not_admin(user_id: int) -> None:
    if _member(user_id)["user"]["role"] == "admin":
        raise HTTPException(400, "관리자 계정은 막거나 지울 수 없어요. 관리자에서 빼려면 ADMIN_EMAILS를 고쳐요.")


@router.get("/users")
def list_users(q: str = ""):
    from app.config import ADMIN_EMAILS

    rows = [{**u, "role": "admin" if u["email"] in ADMIN_EMAILS else "member"} for u in db.list_users(q[:60])]
    return {"users": rows, "counts": db.count_users()}


@router.get("/users/{user_id}")
def get_user(user_id: int):
    return _member(user_id)


@router.post("/users/{user_id}/logout")
def logout_user(user_id: int):
    _member(user_id)
    return {"revoked": db.revoke_user_sessions(user_id)}


@router.post("/users/{user_id}/block")
def block_user(user_id: int, body: BlockIn):
    if body.blocked:
        _not_admin(user_id)
    db.set_user_blocked(user_id, body.blocked)
    return _member(user_id)


@router.delete("/users/{user_id}")
def remove_user(user_id: int):
    _not_admin(user_id)
    db.delete_user(user_id)
    return {"deleted": True}


@router.post("/cache/clear")
def clear_cache():
    return {"cleared": db.clear_cache()}
