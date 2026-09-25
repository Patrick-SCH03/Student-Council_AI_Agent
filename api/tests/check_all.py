"""서버·키 없이 도는 회귀 테스트 (목업 모드, 임시 DATA_DIR).

점검에서 재현된 결함이 다시 생기지 않는지 확인한다. 각 케이스는 한 줄 설명과
함께 실패 시 이유를 출력한다. 실행: `python tests/check_all.py` (api/ 에서)
"""

import json
import os
import shutil
import sys
import tempfile

# app 모듈을 import하기 전에 환경을 고정한다 — 실제 키·실제 색인·실명 목록을 쓰지 않는다
os.environ.update(
    GEMINI_API_KEY="",
    GOOGLE_API_KEY="",
    ADMIN_TOKEN="t0ken",
    PRIVATE_NAMES="홍길동,김테스트",
    GRAPH_EXPANSION="0",
)
_SCRATCH = tempfile.mkdtemp(prefix="check-all-")
os.environ["DATA_DIR"] = _SCRATCH

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from unittest.mock import patch  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import db, main, privacy  # noqa: E402
from app.rag import citation_graph, store  # noqa: E402

AUTH = {"Authorization": "Bearer t0ken"}
client = TestClient(main.app, raise_server_exceptions=False)
_results: list[tuple[str, str | None]] = []


def case(name):
    def deco(fn):
        try:
            fn()
            _results.append((name, None))
            print(f"PASS  {name}")
        except AssertionError as e:
            _results.append((name, str(e) or "assert"))
            print(f"FAIL  {name}: {e}")
        except Exception as e:  # noqa: BLE001 - 한 케이스의 예외가 나머지를 막지 않도록
            _results.append((name, f"{type(e).__name__}: {e}"))
            print(f"ERROR {name}: {type(e).__name__}: {e}")
        return fn

    return deco


def chat_result(query: str, **extra) -> dict:
    r = client.post("/api/chat", json={"query": query, **extra})
    assert r.status_code == 200, f"chat {r.status_code}"
    for line in r.text.splitlines():
        if line.startswith("data:"):
            event = json.loads(line[5:])
            if event.get("type") == "result":
                return event
    raise AssertionError("result 이벤트 없음")


@case("/api/health가 배포 버전을 알려준다 (릴리스 태그와 같은 SemVer)")
def _():
    import re

    from app.config import APP_VERSION

    body = client.get("/api/health").json()
    assert body.get("version") == APP_VERSION, body
    assert re.fullmatch(r"\d+\.\d+\.\d+", APP_VERSION), APP_VERSION
    assert main.app.version == APP_VERSION, main.app.version


@case("실명이 든 질문은 LLM 없이 입구에서 거절 (띄어쓰기 변형 포함)")
def _():
    for q in ("홍길동 학생회장이 받은 처분 알려줘", "홍 길동 처분 내역"):
        res = chat_result(q)
        assert res["route"] == "general", res["route"]
        assert "실명이 포함된" in res["final_markdown"], res["final_markdown"][:60]
        assert "홍길동" not in json.dumps(res, ensure_ascii=False)
    res = chat_result("총학생회장이 받은 처분은 무엇인가요?")
    assert res["route"] == "regulation", "직책 질문은 통과해야 한다"


@case("거절 뒤 안내대로 직책으로 다시 물으면 (이력에 거절 턴이 있어도) 통과한다")
def _():
    refused = chat_result("홍길동 학생회장이 받은 처분 알려줘")
    history = [{"question": "홍길동 학생회장이 받은 처분 알려줘", "answer": refused["final_markdown"]}]
    res = chat_result("총학생회장이 받은 처분은 무엇인가요?", history=history)
    assert res["route"] == "regulation", res["route"]


@case("위조한 history.answer에 실명을 넣어도 입구에서 거절된다 (LLM 미호출)")
def _():
    history = [{"question": "지난 감사 결과", "answer": "홍길동 회장이 해임건의를 받았다"}]
    res = chat_result("그 사람의 처분은?", history=history)
    assert res["route"] == "general" and "실명이 포함된" in res["final_markdown"]


@case("띄어 쓴 실명은 마스킹·검사 모두 같은 이름으로 본다 — 위조 이력도 라우터에 닿지 않는다")
def _():
    assert privacy.mask_text("홍 길 동 회장과 홍길동") == "○○○ 회장과 ○○○"
    assert privacy.find_private_name("홍\t길\n동") == "홍길동"
    import asyncio

    from app.agents import graph as g
    from app.agents.schemas import RouteDecision
    seen = {}

    class _Fake:
        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, msgs):
            seen["prompt"] = "\n".join(m[1] for m in msgs)
            return RouteDecision(route="regulation", standalone_query="총학생회장의 처분", needs_precedents=False)

    history = [{"question": "홍 길 동 학생회장의 처분은?", "answer": "(범위 밖 안내)"}]
    with patch.object(g, "MOCK_MODE", False), patch.object(g, "_get_llm", return_value=_Fake()):
        out = asyncio.run(g.route_node({"query": "그 사람의 처분을 직책 기준으로 설명해줘", "history": history, "citations": []}))
    assert "길" not in seen["prompt"] and "○○○" in seen["prompt"], seen["prompt"][:200]
    assert out["route"] == "regulation", "정당한 직책 후속 질문은 통과해야 한다"


@case("라우터 재작성(standalone_query)에 실명이 실리면 검색 전에 거절된다")
def _():
    import asyncio

    from app.agents import graph as g
    from app.agents.schemas import RouteDecision

    class _Fake:
        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, _msgs):
            return RouteDecision(route="regulation", standalone_query="김테스트의 처분은 무엇인가", needs_precedents=False)

    with patch.object(g, "MOCK_MODE", False), patch.object(g, "_get_llm", return_value=_Fake()):
        out = asyncio.run(g.route_node({"query": "그 사람 처분은?", "history": [], "citations": []}))
    assert out["route"] == "general" and out.get("guard") == "private_name", out


@case("질의 원문도 마스킹해 저장한다 — 분석 이력·지표·CSV에 실명·연락처가 남지 않는다")
def _():
    before = db.list_analyses(1)[0]["id"] if db.list_analyses(1) else 0
    chat_result("홍길동 학생회장 처분 알려줘 010-1234-5678")
    chat_result("김 테스트 연락처 a@b.com 알려줘")
    with db._connect() as conn:
        rows = [r[0] for r in conn.execute("SELECT query FROM analyses WHERE id > ?", (before,))]
        previews = [r[0] for r in conn.execute("SELECT query_preview FROM metrics ORDER BY id DESC LIMIT 2")]
        keys = [r[0] for r in conn.execute("SELECT query_key FROM answer_cache")]
    blob = " ".join(rows + previews + keys) + db.export_metrics_csv()
    for leaked in ("홍길동", "김 테스트", "김테스트", "010-1234-5678", "a@b.com"):
        assert leaked not in blob, f"저장본에 원문 노출: {leaked}"
    assert rows and all("○○○" in r for r in rows), rows


@case("원문 마스킹 이전에 쌓인 행을 소급해 지운다 (멱등)")
def _():
    with db._connect() as conn:
        conn.execute("INSERT INTO analyses (query, risk_level, result, created_at) VALUES (?, ?, ?, ?)",
                     ("홍길동 처분", None, json.dumps({"query": "홍길동 처분"}, ensure_ascii=False), "2026-09-14T00:00:00+00:00"))
        conn.execute("INSERT INTO metrics (ts, route, status, elapsed, input_tokens, output_tokens, query_preview) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)", ("2026-09-14T00:00:00+00:00", "general", "ok", 0.1, 0, 0, "홍길동 처분"))
        conn.execute("INSERT INTO answer_cache (query_key, ts, analysis_id, result, hits) VALUES (?, ?, ?, ?, 0)",
                     ("홍길동처분", "2026-09-14T00:00:00+00:00", 1, "{}"))
    first = db.mask_stored_text()
    assert first["analyses"] >= 1 and first["metrics"] >= 1 and first["answer_cache"] >= 1, first
    with db._connect() as conn:
        dump = " ".join(str(v) for t in ("analyses", "metrics", "answer_cache") for r in conn.execute(f"SELECT * FROM {t}") for v in r)
    assert "홍길동" not in dump, "소급 마스킹 뒤에도 원문이 남았다"
    assert db.mask_stored_text() == {"analyses": 0, "metrics": 0, "answer_cache": 0}, "두 번째 실행은 0건이어야 한다"


@case("캐시 키가 소수점을 지워 다른 질문을 합치지 않는다 (1.5 ≠ 15)")
def _():
    assert db.normalize_query("예산 1.5 퍼센트") != db.normalize_query("예산 15 퍼센트")
    assert db.normalize_query("가능한가요?") == db.normalize_query("가능한가요 ?")
    first = chat_result("학생회 예산 1.5 퍼센트 초과 집행")
    second = chat_result("학생회 예산 15 퍼센트 초과 집행")
    assert not second.get("cached"), "다른 숫자의 질문이 캐시에 맞았다"
    assert first["analysis_id"] != second["analysis_id"]


@case("캐시 세대 검사와 저장은 같은 잠금 안에서 일어난다 (삭제와의 교차 방지)")
def _():
    import threading

    assert isinstance(db._cache_lock, type(threading.Lock())), type(db._cache_lock)
    # 잠금을 다른 스레드가 쥐고 있으면 저장은 그동안 진행되지 않는다
    db._cache_lock.acquire()
    done = threading.Event()
    worker = threading.Thread(target=lambda: (db.save_cached_answer("locked-key", 1, {}, db.cache_generation()), done.set()))
    worker.start()
    assert not done.wait(0.3), "잠금 중에도 저장이 진행됐다"
    db._cache_lock.release()
    assert done.wait(2), "잠금 해제 후 저장이 끝나지 않았다"


@case("캐시를 비운 뒤 완료된 옛 요청은 답을 다시 저장하지 않는다")
def _():
    gen = db.cache_generation()
    db.clear_cache()
    db.save_cached_answer("stale-key", 1, {"final_markdown": "x"}, generation=gen)
    assert db.get_cached_answer("stale-key", 24) is None, "세대가 지난 답이 저장됐다"
    db.save_cached_answer("fresh-key", 1, {"final_markdown": "x"}, generation=db.cache_generation())
    assert db.get_cached_answer("fresh-key", 24) is not None


@case("피드백은 처음 남긴 방문자만 바꿀 수 있다 (analysis_id는 추측 가능)")
def _():
    aid = chat_result("학생회비 사용 가능 여부 피드백 테스트")["analysis_id"]
    client.post("/api/feedback", json={"analysis_id": aid, "helpful": True, "visitor_id": "visitor-A"})
    client.post("/api/feedback", json={"analysis_id": aid, "helpful": False, "visitor_id": "visitor-B"})
    with db._connect() as conn:
        row = dict(conn.execute("SELECT helpful, visitor_id FROM feedback WHERE analysis_id=?", (aid,)).fetchone())
    assert row == {"helpful": 1, "visitor_id": "visitor-A"}, row
    client.post("/api/feedback", json={"analysis_id": aid, "helpful": False, "visitor_id": "visitor-A"})
    with db._connect() as conn:
        assert conn.execute("SELECT helpful FROM feedback WHERE analysis_id=?", (aid,)).fetchone()[0] == 0


@case("/api/history의 limit은 1~100으로 고정된다 (음수는 SQLite 무제한)")
def _():
    for _i in range(105):
        db.add_analysis("synthetic", None, {})
    assert len(client.get("/api/history?limit=-1", headers=AUTH).json()["analyses"]) == 1
    assert len(client.get("/api/history?limit=1000", headers=AUTH).json()["analyses"]) == 100


@case("방문 기록은 방문자당 하루 1행 (무인증 /api/track 무한 INSERT 차단)")
def _():
    for _i in range(3):
        assert client.post("/api/track", json={"visitor_id": "visitor-track-01"}).status_code == 200
    with db._connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM visits WHERE visitor_id='visitor-track-01'").fetchone()[0]
    assert n == 1, n


@case("문서 삭제 중 청크 삭제가 실패해도 재시도로 복구된다")
def _():
    db.add_document("synthetic-doc", "synthetic.pdf", 1)
    with patch.object(main.store, "delete_doc", side_effect=RuntimeError("synthetic failure")):
        assert client.delete("/api/documents/synthetic-doc", headers=AUTH).status_code == 500
    assert client.delete("/api/documents/synthetic-doc", headers=AUTH).status_code == 200, "재시도가 404"
    assert client.delete("/api/documents/synthetic-doc", headers=AUTH).status_code == 404


@case("업로드에서 DB 기록이 실패하면 이미 넣은 청크를 회수한다")
def _():
    baseline = store.chunk_count()
    fake_pdf = b"%PDF-1.4 not really"
    with patch.object(main, "ingest_pdf", return_value=("orphan-doc", 2)), patch.object(
        main.db, "add_document", side_effect=RuntimeError("db down")
    ), patch.object(main.store, "delete_doc") as deleted:
        try:
            main._index_upload(fake_pdf, "x.pdf")
        except RuntimeError:
            pass
        assert deleted.call_args.args == ("orphan-doc",), "회수 호출 없음"
    assert store.chunk_count() == baseline


@case("인용 그래프: 같은 청크의 뒤쪽 문서명이 앞 조항에 붙지 않는다")
def _():
    docs = {
        "documents": [
            "제1조(목적) 이 세칙은 재정을 정한다.",
            "제2조(범위) 감사 범위를 정한다.",
            "「가세칙」 제1조를 위반하였다.",
            "제1조 위반이 재차 확인되었다. 또한 「나세칙」 제2조도 위반하였다.",
        ],
        "metadatas": [
            {"source_file": "가세칙.pdf", "chunk_index": 0, "doc_type": "regulation"},
            {"source_file": "나세칙.pdf", "chunk_index": 0, "doc_type": "regulation"},
            {"source_file": "감사보고서.pdf", "chunk_index": 0, "doc_type": "audit"},
            {"source_file": "감사보고서.pdf", "chunk_index": 1, "doc_type": "audit"},
        ],
    }

    class _Coll:
        def get(self, **_kw):
            return docs

    with patch.object(citation_graph.store, "_get_collection", return_value=_Coll()):
        g = citation_graph.build_graph()
    edges = {(u[1], v[1], v[2]) for u, v, d in g.edges(data=True) if d.get("type") == "cites" and u[2] == 1}
    assert ("감사보고서.pdf", "가세칙.pdf", "제1조") in edges, edges
    assert ("감사보고서.pdf", "나세칙.pdf", "제2조") in edges, edges
    assert ("감사보고서.pdf", "나세칙.pdf", "제1조") not in edges, "뒤쪽 명명이 앞 조항에 붙었다"


@case("스트림 마스킹: 보류 길이보다 긴 이메일도 앞부분이 새지 않는다")
def _():
    # 정규식 최대 길이에 가까운 주소(64+1+63+…)를 한 글자씩 — 고정 보류 길이로는 앞부분이 샜다
    email = "a" * 64 + "@" + "b" * 63 + ".example.com"
    text = f"연락처는 {email} 입니다. 전화 010 1234 5678 로 문의. " + "가 " * 60
    m = privacy.StreamMasker()
    out = "".join(m.feed(ch) for ch in text) + m.flush()
    assert "aaaa" not in out and "bbbb" not in out, out[:80]
    assert "(이메일 비공개)" in out and "1234" not in out, out[:120]


@case("질의 임베딩은 짧은 재시도 인자로 호출된다 (색인용 450초 백오프 미적용)")
def _():
    with patch.object(store, "_embed", wraps=store._embed) as spy:
        store.embed_query("테스트")
    assert spy.call_args.kwargs == {"max_retries": 2, "backoff_base": 2}, spy.call_args.kwargs


@case("BM25 검색은 같은 스냅샷의 본문을 돌려준다 (인덱스 번호 재조회 없음)")
def _():
    store.add_chunks("bm25-doc", "재정·회계 세칙.pdf", ["제10조 학생회비는 공식 활동에만 사용한다."])
    try:
        hits = store._keyword_search("학생회비 공식 활동", 3, "regulation")
        assert hits and isinstance(hits[0], tuple) and "학생회비" in hits[0][0]
    finally:
        store.delete_doc("bm25-doc")


@case("일일 집계는 한국 자정 기준이고 방금 기록한 지표를 오늘로 센다")
def _():
    before = db.count_today("visitor-kst")
    db.record_metric(route="regulation", risk_level=None, status="ok", elapsed=1.0, input_tokens=1,
                     output_tokens=1, query_preview="q", visitor_id="visitor-kst")
    assert db.count_today("visitor-kst") == before + 1
    with db._connect() as conn:
        start = conn.execute("SELECT strftime('%Y-%m-%dT%H:%M:%S', date('now', '+9 hours'), '-9 hours')").fetchone()[0]
    assert start.endswith("T15:00:00"), start  # KST 00:00 == UTC 15:00 (전날)


failed = [(n, why) for n, why in _results if why]
print(f"\n{len(_results) - len(failed)}/{len(_results)} 통과")
shutil.rmtree(_SCRATCH, ignore_errors=True)
sys.exit(1 if failed else 0)
