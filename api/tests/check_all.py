"""서버·키 없이 도는 회귀 테스트 (목업 모드, 임시 DATA_DIR).

점검에서 재현된 결함이 다시 생기지 않는지 확인한다. 각 케이스는 한 줄 설명과
함께 실패 시 이유를 출력한다. 실행: `python tests/check_all.py` (api/ 에서)
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

# app 모듈을 import하기 전에 환경을 고정한다 — 실제 키·실제 색인·실명 목록을 쓰지 않는다
os.environ.update(
    # 두 모델 키를 모두 비워 목업을 강제한다 (api/.env에 실키가 있어도)
    CLAUDE_API_KEY="",
    ANTHROPIC_API_KEY="",
    GEMINI_API_KEY="",
    VOYAGE_API_KEY="",
    ADMIN_TOKEN="t0ken",
    PRIVATE_NAMES="홍길동,김테스트",
    GRAPH_EXPANSION="0",
    GOOGLE_CLIENT_ID="test-client.apps.googleusercontent.com",
    ADMIN_EMAILS="boss@inha.edu",
    CORS_ORIGINS="http://localhost:3000",
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


@case("/api/health가 실제로 쓰는 Claude 모델과 임베딩 모델을 알려준다")
def _():
    from app.config import CLAUDE_MODEL, EMBEDDING_MODEL

    body = client.get("/api/health").json()
    assert body["model"] == CLAUDE_MODEL and body["embedding_model"] == EMBEDDING_MODEL, body
    assert body["mock_mode"] is True, "테스트는 키를 비워 목업으로 돌아야 한다"


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

    from app.agents import claude_agents as ca
    from app.agents import graph as g
    from app.agents.schemas import RouteDecision
    seen = {}

    async def classify(system, user, schema, max_tokens=16000):
        seen["prompt"] = user
        return RouteDecision(route="regulation", standalone_query='총학생회장의 처분', needs_precedents=False)

    history = [{"question": "홍 길 동 학생회장의 처분은?", "answer": "(범위 밖 안내)"}]
    with patch.object(g, "MOCK_MODE", False), patch.object(ca, "structured", classify):
        out = asyncio.run(g.route_node({"query": "그 사람의 처분을 직책 기준으로 설명해줘", "history": history, "citations": []}))
    assert "길" not in seen["prompt"] and "○○○" in seen["prompt"], seen["prompt"][:200]
    assert out["route"] == "regulation", "정당한 직책 후속 질문은 통과해야 한다"


@case("라우터 재작성(standalone_query)에 실명이 실리면 검색 전에 거절된다")
def _():
    import asyncio

    from app.agents import claude_agents as ca
    from app.agents import graph as g
    from app.agents.schemas import RouteDecision
    seen = {}

    async def classify(system, user, schema, max_tokens=16000):
        seen["prompt"] = user
        return RouteDecision(route="regulation", standalone_query='김테스트의 처분은 무엇인가', needs_precedents=False)

    with patch.object(g, "MOCK_MODE", False), patch.object(ca, "structured", classify):
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


@case("실명 없이 연락처만 든 질의도 캐시 키·저장본에 원문이 남지 않는다")
def _():
    res = chat_result("학생회비 환불 문의는 010-9876-5432 또는 x.y@inha.edu 로 해도 되나요?")
    assert res["route"] == "regulation", res["route"]
    assert "010-9876-5432" not in res["query"] and "x.y@inha.edu" not in res["query"], res["query"]
    with db._connect() as conn:
        keys = " ".join(r[0] for r in conn.execute("SELECT query_key FROM answer_cache"))
        previews = " ".join(r[0] for r in conn.execute("SELECT query_preview FROM metrics ORDER BY id DESC LIMIT 1"))
    for leaked in ("9876", "x.y@inha.edu", "inha.edu"):
        assert leaked not in keys and leaked not in previews, f"원문 노출: {leaked}"


@case("서명 키가 공개 상수면 피드백을 끈다 — 토큰을 누구나 계산할 수 있으므로")
def _():
    with patch.object(main, "FEEDBACK_ENABLED", False):
        res = chat_result("학생회비 서명 키 폴백 테스트")
        assert res.get("feedback_token") is None, "공개 키로 서명을 발급했다"
        forged = main._feedback_token(res["analysis_id"])
        r = client.post("/api/feedback", json={"analysis_id": res["analysis_id"], "helpful": True, "token": forged})
        assert r.status_code == 503, r.status_code


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
    res = chat_result("학생회비 사용 가능 여부 피드백 테스트")
    aid, tok = res["analysis_id"], res["feedback_token"]
    client.post("/api/feedback", json={"analysis_id": aid, "helpful": True, "visitor_id": "visitor-A", "token": tok})
    client.post("/api/feedback", json={"analysis_id": aid, "helpful": False, "visitor_id": "visitor-B", "token": tok})
    with db._connect() as conn:
        row = dict(conn.execute("SELECT helpful, visitor_id FROM feedback WHERE analysis_id=?", (aid,)).fetchone())
    assert row == {"helpful": 1, "visitor_id": "visitor-A"}, row
    client.post("/api/feedback", json={"analysis_id": aid, "helpful": False, "visitor_id": "visitor-A", "token": tok})
    with db._connect() as conn:
        assert conn.execute("SELECT helpful FROM feedback WHERE analysis_id=?", (aid,)).fetchone()[0] == 0


@case("서명 없는 피드백은 거절된다 — 아직 평가 없는 답변을 남이 선점할 수 없다")
def _():
    aid = chat_result("학생회비 서명 토큰 테스트")["analysis_id"]
    bad = {"analysis_id": aid, "helpful": False, "visitor_id": "attacker"}
    assert client.post("/api/feedback", json=bad).status_code == 422, "토큰 없이 통과했다"
    assert client.post("/api/feedback", json={**bad, "token": "0" * 32}).status_code == 403
    other = main._feedback_token(aid + 1)
    assert client.post("/api/feedback", json={**bad, "token": other}).status_code == 403, "다른 답변의 토큰이 통했다"
    with db._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM feedback WHERE analysis_id=?", (aid,)).fetchone()[0] == 0


@case("사용자가 창을 닫아 중단된 요청은 대시보드 오류로 세지 않는다")
def _():
    before = client.get("/api/stats", headers=AUTH).json()["totals"]["errors"]
    db.record_metric(route="regulation", risk_level=None, status="cancelled", elapsed=1.0,
                     input_tokens=1, output_tokens=1, query_preview="q", error="client disconnected")
    after = client.get("/api/stats", headers=AUTH).json()["totals"]["errors"]
    assert after == before, (before, after)


@case("라우터 재작성이 실패해도 후속 질문은 직전 질문(마스킹)을 맥락으로 들고 간다")
def _():
    from app.agents.graph import _fallback_query
    assert _fallback_query("증빙은 뭐가 필요해?", []) == "증빙은 뭐가 필요해?"
    hist = [{"question": "영수증 없이 회식비를 집행했어. 010-1234-5678로 연락 왔는데", "answer": "..."}]
    q = _fallback_query("증빙은 뭐가 필요해?", hist)
    assert "영수증 없이 회식비를 집행" in q and q.endswith("증빙은 뭐가 필요해?"), q
    assert "1234-5678" not in q, "직전 질문의 연락처가 마스킹되지 않았다"


@case("단계별 소요 시간: 병렬 분석은 검색 완료부터, 종합 조정은 두 분석이 끝난 뒤부터 잰다")
def _():
    marks = {"router": 1.0, "retrieve": 2.0, "reviewer": 5.0, "auditor": 7.0,
             "coordinator_first_token": 9.5, "coordinator": 12.0}
    got = main._stage_timings(0.0, marks)
    want = {"router": 1.0, "retrieve": 1.0, "reviewer": 3.0, "auditor": 5.0,
            "coordinator_ttft": 2.5, "coordinator": 5.0}
    assert got == want, got
    # 중간에 끊긴 요청: 있는 단계만 남는다
    assert main._stage_timings(0.0, {"router": 0.5}) == {"router": 0.5}


@case("규정 질의는 단계별 시간을 지표에 남기고 대시보드가 중앙값을 보여준다")
def _():
    chat_result("학생회비 단계 시간 기록 테스트")
    with db._connect() as conn:
        raw = conn.execute("SELECT stage_timings FROM metrics ORDER BY id DESC LIMIT 1").fetchone()[0]
    stages = json.loads(raw)
    for key in ("router", "retrieve", "reviewer", "auditor", "coordinator"):
        assert key in stages, f"{key} 없음: {stages}"
    summary = client.get("/api/stats", headers=AUTH).json()["stages"]
    assert summary["samples"] >= 1 and "coordinator" in summary, summary


class _FakeUsage:
    def __init__(self, i, o):
        self.input_tokens, self.output_tokens = i, o


class _FakeStream:
    """anthropic messages.stream 흉내: text_stream을 내보내고 fail_after개 뒤 예외."""

    def __init__(self, texts, fail_after=None, stop_reason="end_turn"):
        self.texts, self.fail_after, self.stop_reason = texts, fail_after, stop_reason

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    async def text_stream(self):
        for i, x in enumerate(self.texts):
            if self.fail_after is not None and i >= self.fail_after:
                raise RuntimeError("stream cut")
            yield x

    async def get_final_message(self):
        class M:
            usage = _FakeUsage(100, 20)
            stop_reason = self.stop_reason
            stop_details = None
        return M()


def _fake_client(parse_result=None, stream=None):
    class Messages:
        async def parse(self, **kw):
            class R:
                usage = _FakeUsage(1000, 50)
                stop_reason = "end_turn"
                stop_details = None
                parsed_output = parse_result
            return R()

        def stream(self, **kw):
            return stream

    class C:
        messages = Messages()
    return C()


def _run(coro):
    import asyncio
    return asyncio.run(coro)


@case("Claude 경로: 구조화 출력·스트림 토큰·사용량을 custom 스트림으로 흘리고, 중간에 끊기면 폴백하지 않는다")
def _():
    from app.agents import claude_agents as ca
    from app.agents.schemas import ReviewerResult, RiskLevel

    sent = []
    rv = ReviewerResult(question_type="행위", violation="위반 없음", risk_level=RiskLevel.LOW, reasoning="r", recommendation="c")
    with patch.object(ca, "_writer", return_value=sent.append), patch.object(
        ca, "_get_client", return_value=_fake_client(parse_result=rv, stream=_FakeStream(["가", "나"]))
    ):
        assert _run(ca.structured("s", "u", ReviewerResult)) is rv
        assert _run(ca.coordinate("s", "u")) == "가나"
    tokens = [p["token"] for p in sent if "token" in p]
    usages = [p["usage"] for p in sent if "usage" in p]
    assert tokens == ["가", "나"], sent
    assert [(u["input_tokens"], u["output_tokens"]) for u in usages] == [(1000, 50), (100, 20)], usages
    with patch.object(ca, "_writer", return_value=sent.append), patch.object(
        ca, "_get_client", return_value=_fake_client(stream=_FakeStream(["가", "나"], fail_after=1))
    ):
        try:
            _run(ca.coordinate("s", "u"))
            raise AssertionError("부분 출력 뒤 실패가 StreamStarted로 올라오지 않았다")
        except ca.StreamStarted:
            pass


@case("질문 분류는 Claude 구조화 출력(짧은 max_tokens)으로 하고, 실패하면 규정 경로로 이어가며 기록한다")
def _():
    from app.agents import claude_agents as ca
    from app.agents import graph as gr
    from app.agents.schemas import RouteDecision

    seen = {}

    async def classify(system, user, schema, max_tokens=16000):
        seen.update(schema=schema, max_tokens=max_tokens)
        return RouteDecision(route="general", standalone_query="오늘 날씨", needs_precedents=False)

    with patch.object(gr, "MOCK_MODE", False), patch.object(ca, "structured", classify):
        out = _run(gr.route_node({"query": "오늘 날씨 어때?"}))
    assert out["route"] == "general", out
    assert seen["schema"] is RouteDecision and seen["max_tokens"] <= 2048, seen

    async def boom(*a, **kw):
        raise RuntimeError("down")

    sent = []
    with patch.object(gr, "MOCK_MODE", False), patch.object(ca, "structured", boom), \
            patch.object(ca, "_writer", return_value=sent.append):
        out = _run(gr.route_node({"query": "예산 변경 절차는?"}))
    assert out["route"] == "regulation", out
    assert sent == [{"fallback": "router_failed"}], sent


@case("Claude 종합 조정이 중간에 끊기면 받은 데까지에 안내를 붙여 완결한다 (요청 전체를 버리지 않음)")
def _():
    from app.agents import claude_agents as ca
    from app.agents import graph as gr
    from app.agents.schemas import AuditorResult, ReviewerResult, RiskLevel

    async def cut(system, user):
        raise ca.StreamStarted("cut", partial="### 결론 부분")

    state = {
        "query": "q",
        "reviewer": ReviewerResult(question_type="행위", violation="위반 없음", risk_level=RiskLevel.LOW, reasoning="r", recommendation="c"),
        "auditor": AuditorResult(compliance="준수", sanction_likelihood=RiskLevel.LOW, reasoning="r", recommendation="c"),
    }
    with patch.object(gr, "MOCK_MODE", False), patch.object(ca, "coordinate", cut):
        out = _run(gr.coordinator_node(state))
    assert out["final_markdown"].startswith("### 결론 부분"), out
    assert gr.PARTIAL_ANSWER_NOTICE.strip() in out["final_markdown"]


@case("잘린 답(partial)은 캐시하지 않고 지표에 status=partial로 남긴다")
def _():
    class FakeGraph:
        async def astream(self, *a, **kw):
            yield ("updates", {"router": {"route": "regulation", "standalone_query": "q"}})
            yield ("updates", {"coordinator": {"final_markdown": "부분 답변", "partial": True}})

    query = "부분 답변 캐시 금지 테스트 질문"
    with patch.object(main, "graph", FakeGraph()):
        r = client.post("/api/chat", json={"query": query})
    assert r.status_code == 200
    with db._connect() as conn:
        status = conn.execute("SELECT status FROM metrics ORDER BY id DESC LIMIT 1").fetchone()[0]
        cached = conn.execute("SELECT COUNT(*) FROM answer_cache WHERE query_key = ?",
                              (db.normalize_query(query),)).fetchone()[0]
    assert status == "partial", status
    assert cached == 0, "잘린 답이 캐시됐다"


@case("custom 스트림 토큰은 마스킹돼 SSE로 나가고, Claude 사용량은 Claude 단가로 요청 비용에 들어간다")
def _():
    class FakeGraph:
        async def astream(self, *a, **kw):
            yield ("updates", {"router": {"route": "regulation", "standalone_query": "q"}})
            yield ("custom", {"token": "연락처는 010-1234-5678 "})
            yield ("custom", {"token": "입니다."})
            yield ("custom", {"usage": {"model": "claude-haiku-5-5", "input_tokens": 1_000_000, "output_tokens": 0}})
            yield ("updates", {"coordinator": {"final_markdown": "연락처는 010-1234-5678 입니다."}})

    with patch.object(main, "graph", FakeGraph()):
        r = client.post("/api/chat", json={"query": "custom 스트림 비용 테스트"})
    body = r.text
    assert "1234-5678" not in body, "custom 토큰이 마스킹되지 않았다"
    assert '"type": "token"' in body
    with db._connect() as conn:
        cost = conn.execute("SELECT cost_usd FROM metrics ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert abs(cost - 0.10) < 1e-9, f"Haiku 입력 100만 토큰은 $0.10이어야 한다: {cost}"
    stats = client.get("/api/stats", headers=AUTH).json()["cost"]
    assert stats["total_usd"] >= 0.10 - 1e-4, stats


@case("낮춘 경로(검색 키워드만·분류 실패)는 요청 지표에 남고 대시보드 집계·최근 질의에 보인다")
def _():
    class FakeGraph:
        async def astream(self, *a, **kw):
            yield ("updates", {"router": {"route": "regulation", "standalone_query": "q"}})
            yield ("custom", {"fallback": "router_failed"})
            yield ("custom", {"fallback": "retrieve"})
            yield ("custom", {"fallback": "retrieve"})
            yield ("updates", {"coordinator": {"final_markdown": "답변"}})

    before = client.get("/api/stats", headers=AUTH).json()["totals"]["fallbacks"]
    with patch.object(main, "graph", FakeGraph()):
        client.post("/api/chat", json={"query": "폴백 기록 테스트 질문"})
    with db._connect() as conn:
        fallback = conn.execute("SELECT fallback FROM metrics ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert fallback == "router_failed,retrieve", fallback
    stats = client.get("/api/stats", headers=AUTH).json()
    assert stats["totals"]["fallbacks"] == before + 1, stats["totals"]
    assert stats["today"]["fallbacks"] >= 1, stats["today"]
    assert stats["recent"][0]["fallback"] == "router_failed,retrieve", stats["recent"][0]
    assert stats["agent"]["model"] and stats["agent"]["embedding_model"], stats.get("agent")


@case("/api/backup은 관리자만 받고, 열리는 SQLite 스냅샷과 OCR 캐시를 zip으로 내려준다")
def _():
    import io
    import sqlite3
    import zipfile

    from app.config import OCR_CACHE_DIR

    assert client.get("/api/backup").status_code == 401
    (OCR_CACHE_DIR / "backup-test.txt").write_text("ocr", encoding="utf-8")
    db.record_metric(route="general", risk_level=None, status="ok", elapsed=0.1,
                     input_tokens=0, output_tokens=0, query_preview="백업 확인용")
    r = client.get("/api/backup", headers=AUTH)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip", r.status_code
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.testzip() is None
        names = zf.namelist()
        assert "ocr_cache/backup-test.txt" in names and "manifest.json" in names, names
        path = os.path.join(_SCRATCH, "restored.sqlite3")
        with open(path, "wb") as f:
            f.write(zf.read("app.sqlite3"))
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        n = conn.execute("SELECT COUNT(*) FROM metrics WHERE query_preview = '백업 확인용'").fetchone()[0]
    finally:
        conn.close()
    assert n == 1, "스냅샷에 최근 기록이 없다"


@case("비용은 모델별 단가·캐시 적중 할인을 반영하고, 모르는 모델은 최고 단가로 매긴다")
def _():
    from app import pricing

    assert abs(pricing.cost_usd("claude-haiku-5-5", 1_000_000, 0) - 0.10) < 1e-9
    assert abs(pricing.cost_usd("claude-haiku-5-5", 0, 1_000_000) - 0.50) < 1e-9
    # 입력 100만 중 80만이 캐시 적중이면 20만 × 정가 + 80만 × 캐시 단가
    cached = pricing.cost_usd("claude-haiku-5-5", 1_000_000, 0, cached_tokens=800_000)
    assert abs(cached - (0.2 * 0.10 + 0.8 * 0.01)) < 1e-9, cached
    # 날짜·버전 접미사가 붙은 모델 ID도 같은 단가 (최고 단가로 새지 않음)
    assert abs(pricing.cost_usd("claude-haiku-5-5-20261001", 1_000_000, 0) - 0.10) < 1e-9
    unknown = pricing.cost_usd("some-new-model", 1_000_000, 0)
    assert unknown >= max(r[0][1] for r in pricing.PRICES.values()), "모르는 모델을 싸게 매겼다"


@case("대시보드 비용은 달러로만 내려주고, 캐시 응답은 비용 0으로 기록된다")
def _():
    query = "캐시 비용 기록 테스트 질문"
    with patch.object(main.db, "get_cached_answer", return_value={"route": "regulation", "final_markdown": "x"}):
        client.post("/api/chat", json={"query": query})
    with db._connect() as conn:
        status, cost = conn.execute("SELECT status, cost_usd FROM metrics ORDER BY id DESC LIMIT 1").fetchone()
    assert status == "cached" and cost == 0.0, (status, cost)
    c = client.get("/api/stats", headers=AUTH).json()["cost"]
    assert set(c) == {"total_usd", "today_usd", "estimated_usd"}, c


@case("임베딩이 막혀도 키워드 검색만으로 근거를 찾아 답을 이어가고, 검색 폴백으로 기록한다")
def _():
    from app.agents import claude_agents as ca
    from app.agents import graph as gr

    store.add_chunks("kw-only-doc", "재정세칙.pdf", ["제10조 행사 물품 구매 시 증빙서류로 영수증과 품의서를 제출한다"])
    sent = []
    try:
        with patch.object(gr.store, "embed_query", side_effect=RuntimeError("403 PERMISSION_DENIED suspended")),                 patch.object(gr.store, "_vector_search", side_effect=AssertionError("벡터 검색을 부르면 안 된다")),                 patch.object(ca, "_writer", return_value=sent.append):
            out = _run(gr.retrieve_node({"query": "행사 물품 구매 증빙서류", "standalone_query": "행사 물품 구매 증빙서류"}))
    finally:
        store.delete_doc("kw-only-doc")
    assert any("증빙서류" in h["text"] for h in out["reg_hits"]), out["reg_hits"]
    assert {"fallback": "retrieve"} in sent, sent


@case("상류 오류 문구에 실린 API 키는 지표·로그에 남기 전에 지운다 (잘린 앞부분 포함)")
def _():
    # 가짜 키도 소스에 통째로 두지 않는다 — 비밀값 스캐너(GitHub·Google)가 실제 키로 오인해 신고할 수 있다
    g_key = "AI" + "za" + "Sy" + "X" * 33
    google = f"Permission denied: Consumer 'api_key:{g_key}' has been suspended"
    cut = f"Consumer 'api_key:{g_key[:14]}"
    claude = "invalid x-api-key " + "sk-" + "ant-" + "api03-" + "X" * 16
    for text in (google, cut, claude):
        masked = privacy.mask_text(text)
        assert "AIza" not in masked and "sk-ant-" not in masked, masked
    db.record_metric(route="regulation", risk_level=None, status="error", elapsed=0.1, input_tokens=0,
                     output_tokens=0, query_preview="키 마스킹 확인", error=f"UpstreamError: {google}")
    with db._connect() as conn:
        err = conn.execute("SELECT error FROM metrics ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert "AIza" not in err and "(API 키 비공개)" in err, err


@case("지금 쓰지 않는 임베딩 모델의 옛 색인 컬렉션은 기동 시 지우고, 현재·목업 컬렉션은 남긴다")
def _():
    client_ = store._get_client()
    for name in ("regulations", "regulations_old-model", "regulations_voyage-test"):
        client_.get_or_create_collection(name)
    try:
        with patch.object(store, "MOCK_MODE", False), patch.object(store, "COLLECTION_NAME", "regulations_voyage-test"):
            dropped = store.drop_stale_collections()
        names = {c.name if hasattr(c, "name") else c for c in client_.list_collections()}
        assert set(dropped) == {"regulations", "regulations_old-model"}, dropped
        assert "regulations_voyage-test" in names and "regulations_mock" in names, names
        assert store.drop_stale_collections() == [], "목업 모드에서는 지우지 않는다"
    finally:
        for name in ("regulations", "regulations_old-model", "regulations_voyage-test"):
            try:
                client_.delete_collection(name)
            except Exception:  # noqa: BLE001
                pass


@case("임베딩은 문서·질의를 input_type으로 구분해 요청한다")
def _():
    calls = []

    def fake(texts, input_type, title=None):
        calls.append(input_type)
        return [[0.1, 0.2] for _ in texts]

    with patch.object(store, "MOCK_MODE", False), patch.object(store, "_remote_embed", fake):
        store.embed_query("증빙서류")
        store._embed(["본문"])
    assert calls == ["query", "document"], calls


@case("Gemini 임베딩: 문서·질의 접두어, 출력 차원, 키는 헤더로만 (URL·오류 문구에 없음)")
def _():
    import httpx

    seen = []
    vec = [0.5] * store.GEMINI_EMBED_DIM

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        text = body["requests"][0]["content"]["parts"][0]["text"]
        if text.startswith("task: search result | query: 실패"):
            return httpx.Response(403, json={"error": {"message": "denied"}})
        if text.endswith("차원무시"):  # 차원 지정이 무시돼 기본 3072차원이 온 경우
            return httpx.Response(200, json={"embeddings": [{"values": [0.5] * 3072}]})
        return httpx.Response(200, json={"embeddings": [{"values": vec} for _ in body["requests"]]})

    fake_key = "AI" + "za" + "x" * 30
    mock_client = httpx.Client(base_url="https://generativelanguage.googleapis.com/v1beta",
                               headers={"x-goog-api-key": fake_key}, transport=httpx.MockTransport(handler))
    with patch.object(store, "_client_for", lambda *_a: mock_client), \
            patch.object(store, "EMBEDDING_MODEL", "gemini-embedding-2"):
        assert store._gemini_embed(["제1조", "제2조"], "document", "재정 회계 세칙") == [vec, vec]
        store._gemini_embed(["회식비"], "query")
        for bad, why in ((["실패"], " 403"), (["차원무시"], "차원")):
            try:
                store._gemini_embed(bad, "query")
                raise AssertionError(f"{why} 오류를 삼켰다")
            except RuntimeError as e:
                assert fake_key not in str(e) and why in str(e), str(e)
    doc_req, query_req = seen[0], seen[1]
    assert doc_req.url.path.endswith("/models/gemini-embedding-2:batchEmbedContents"), doc_req.url
    assert fake_key not in str(doc_req.url), "키가 URL에 실렸다"
    doc_body, query_body = json.loads(doc_req.content), json.loads(query_req.content)
    assert doc_body["requests"][1]["content"]["parts"][0]["text"] == "title: 재정 회계 세칙 | text: 제2조", doc_body
    assert doc_body["requests"][0]["output_dimensionality"] == store.GEMINI_EMBED_DIM
    assert query_body["requests"][0]["content"]["parts"][0]["text"] == "task: search result | query: 회식비"


@case("문서 임베딩에는 파일명에서 만든 제목을 넣는다 (벡터 검색이 문서 종류·기구를 알게)")
def _():
    assert store.doc_title("25-2 총학생회_특별감사_보고서.pdf") == "25-2 총학생회 특별감사 보고서"
    assert store.doc_title("재정·회계 세칙.pdf") == "재정·회계 세칙"
    titles = []

    def fake(texts, input_type, title=None):
        titles.append((input_type, title))
        return [[0.0] * 256 for _ in texts]

    with patch.object(store, "MOCK_MODE", False), patch.object(store, "_remote_embed", fake):
        store.add_chunks("title-doc", "26-1_중앙_정기감사_보고서.pdf", ["처분 목록"])
        store.embed_query("처분")
    store.delete_doc("title-doc")
    assert titles == [("document", "26-1 중앙 정기감사 보고서"), ("query", None)], titles


@case("임베딩 공급자 설정에 따라 Gemini·Voyage 중 하나만 부르고, 공급자마다 HTTP 클라이언트(키 헤더)를 따로 둔다")
def _():
    hit = []
    with patch.object(store, "_gemini_embed", lambda t, i, title=None: hit.append("gemini") or [[0.0]]), \
            patch.object(store, "_voyage_embed", lambda t, i: hit.append("voyage") or [[0.0]]):
        for provider in ("gemini", "voyage"):
            with patch.object(store, "EMBEDDING_PROVIDER", provider):
                store._remote_embed(["본문"], "document")
    assert hit == ["gemini", "voyage"], hit
    with patch.object(store, "_http", {}):
        a = store._client_for("https://a.example", {"x-goog-api-key": "k1"})
        b = store._client_for("https://b.example", {"Authorization": "Bearer k2"})
        assert a is not b and "x-goog-api-key" not in b.headers, "다른 공급자에 키 헤더가 섞였다"
        assert store._client_for("https://a.example", {}) is a


@case("전체 재색인 준비(/api/index/reset)는 관리자·confirm이 있어야 하고 문서·색인·OCR 캐시를 비운다")
def _():
    from app.config import OCR_CACHE_DIR

    store.add_chunks("reset-doc", "재정세칙.pdf", ["제1조 목적"])
    db.add_document("reset-doc", "재정세칙.pdf", 1)
    (OCR_CACHE_DIR / "reset-test.txt").write_text("ocr", encoding="utf-8")
    assert client.post("/api/index/reset?confirm=true").status_code == 401
    assert client.post("/api/index/reset", headers=AUTH).status_code == 400, "confirm 없이 지웠다"
    r = client.post("/api/index/reset?confirm=true", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["documents"] >= 1 and body["chunks"] >= 1 and body["ocr_cache_files"] >= 1, body
    assert store.chunk_count() == 0 and db.list_documents() == [], "비워지지 않았다"
    assert not list(OCR_CACHE_DIR.glob("*.txt")), "OCR 캐시가 남았다"


@case("Claude OCR은 잘린 추출본(max_tokens)을 받아들이지 않는다 — 문서 뒷부분이 색인에서 빠지므로")
def _():
    from app.agents import claude_agents as ca

    class Final:
        def __init__(self, stop):
            self.stop_reason, self.stop_details = stop, None
            self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 5})()
            self.content = [type("B", (), {"type": "text", "text": "추출본"})()]

    class Stream:
        def __init__(self, stop):
            self.stop = stop

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return Final(self.stop)

    class Client:
        def __init__(self, stop):
            self.messages = type("M", (), {"stream": lambda _self, **kw: Stream(stop)})()

    with patch.object(ca, "_sync_client", Client("end_turn")):
        assert ca.ocr_pdf(b"%PDF", "추출") == "추출본"
    with patch.object(ca, "_sync_client", Client("max_tokens")):
        try:
            ca.ocr_pdf(b"%PDF", "추출")
            raise AssertionError("잘린 추출본을 그대로 돌려줬다")
        except RuntimeError as e:
            assert "잘렸다" in str(e)


@case("임베딩 429(무료 한도)를 받으면 저속 모드로 바꿔 작은 배치·요청 간격으로 문서 색인을 끝낸다")
def _():
    calls, sleeps = [], []

    def fake(texts, input_type, title=None):
        calls.append(len(texts))
        if len(calls) == 1:
            raise RuntimeError("Voyage 임베딩 오류 429: reduced rate limits of 3 RPM and 10K TPM")
        return [[0.0] for _ in texts]

    texts = ["가" * 1000] * 20  # 2만 자 — 저속 모드 배치(6천 자)로 4번 이상 나뉘어야 한다
    with patch.object(store, "MOCK_MODE", False), patch.object(store, "_remote_embed", fake),             patch.object(store, "_throttled", False), patch.object(store.time, "sleep", sleeps.append):
        vecs = store._embed(texts)
    assert len(vecs) == 20, len(vecs)
    assert calls[0] == 20 and max(calls[1:]) <= 6, calls
    assert sum(calls[1:]) == 20, calls
    assert any(w >= 15 for w in sleeps), f"요청 간격을 두지 않았다: {sleeps}"


@case("로컬에서 만든 청크·임베딩을 그대로 옮겨 넣는다 (/api/index/import) — 검증·중복 거절·왕복 동일")
def _():
    vec = [0.1] * 256
    body = {"filename": "옮김세칙.pdf", "chunks": ["제1조 목적", "제2조 정의"], "embeddings": [vec, vec]}
    assert client.post("/api/index/import", json=body).status_code == 401
    bad = {**body, "embeddings": [vec]}
    assert client.post("/api/index/import", json=bad, headers=AUTH).status_code == 422, "개수 불일치 통과"
    assert client.post("/api/index/import", json={**body, "filename": "../x.pdf"}, headers=AUTH).status_code == 422
    r = client.post("/api/index/import", json=body, headers=AUTH)
    assert r.status_code == 200, r.text
    doc_id = r.json()["doc_id"]
    assert client.post("/api/index/import", json=body, headers=AUTH).status_code == 409, "중복 문서 통과"
    chunks, embs = store.export_doc(doc_id)
    assert chunks == body["chunks"] and len(embs) == 2 and abs(embs[0][0] - 0.1) < 1e-6, (chunks, embs[0][:2])
    client.delete(f"/api/documents/{doc_id}", headers=AUTH)


@case("잘린 OCR은 재시도하지 않고(과금 반복 방지), 임베딩 네트워크 타임아웃은 재시도한다")
def _():
    import httpx

    from app.agents import claude_agents as ca
    from app.rag import ingest

    calls = []

    def truncated(_b, _p):
        calls.append(1)
        raise ca.OcrTruncated("cut")

    with patch.object(ca, "ocr_pdf", truncated), patch.object(ingest.time, "sleep", lambda _s: None):
        try:
            ingest._extract_with_llm(b"%PDF-unique-for-test")
            raise AssertionError("잘린 OCR을 받아들였다")
        except ca.OcrTruncated:
            pass
    assert len(calls) == 1, f"잘린 OCR을 {len(calls)}번 불렀다"

    attempts = []

    def flaky(texts, input_type, title=None):
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ReadTimeout("")
        return [[0.0] for _ in texts]

    with patch.object(store, "MOCK_MODE", False), patch.object(store, "_remote_embed", flaky), \
            patch.object(store.time, "sleep", lambda _s: None):
        assert len(store._embed(["본문"])) == 1
    assert len(attempts) == 2, attempts


@case("공개 API(health·chat·feedback·track·notice·events·로그인·로그아웃)를 뺀 모든 /api 라우트는 토큰 없이 401이다 (새 관리자 라우트 인증 누락 방지)")
def _():
    from app import admin

    # 로그인 시작·로그아웃은 세션 없이 부르는 공개 API다 (각각 Origin 검사로 보호, 아래 로그인 케이스에서 검사)
    public = {"/api/health", "/api/chat", "/api/feedback", "/api/track", "/api/notice", "/api/events", "/api/auth/google", "/api/auth/logout"}
    # 앱에 직접 붙은 라우트 + 관리자 라우터 (FastAPI가 포함한 라우터를 한 항목으로 묶어 보여줄 수 있다)
    from app import auth

    from app import ledger
    from app.minutes import api as minutes_api
    from app.plan import api as plan_api
    from app.review import api as review_api

    routers = (admin, auth, review_api, ledger, plan_api, minutes_api)
    routes = [r for r in main.app.routes if getattr(r, "path", None)] + [r for m in routers for r in m.router.routes]
    checked = 0
    for route in routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/") or path in public:
            continue
        url = path.replace("{doc_id}", "x").replace("{analysis_id}", "1").replace("{entry_id}", "1")
        for method in getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}:
            # Origin은 맞춰 보낸다 — 쿠키 라우터는 Origin 검사가 먼저라, 없으면 403으로 막혀 인증 누락을 가린다
            r = client.request(method, url, json={}, headers={"Origin": "http://localhost:3000"})
            assert r.status_code == 401, f"{method} {path} → {r.status_code} (인증 없이 열림)"
            checked += 1
    assert checked >= 12, f"검사한 관리자 라우트가 너무 적다: {checked}"


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
    with patch.object(store, "delete_doc", side_effect=RuntimeError("synthetic failure")):
        assert client.delete("/api/documents/synthetic-doc", headers=AUTH).status_code == 500
    assert client.delete("/api/documents/synthetic-doc", headers=AUTH).status_code == 200, "재시도가 404"
    assert client.delete("/api/documents/synthetic-doc", headers=AUTH).status_code == 404


@case("문서 삭제 뒤 그래프 재생성이 실패해도 삭제는 성공으로 끝나고 그래프는 다시 만들 대상이 된다")
def _():
    db.add_document("graph-fail-doc", "graph-fail.pdf", 1)
    with patch.object(citation_graph, "get_graph", side_effect=RuntimeError("graph down")):
        r = client.delete("/api/documents/graph-fail-doc", headers=AUTH)
    assert r.status_code == 200, f"이미 지운 문서를 실패로 알렸다 ({r.status_code})"
    assert citation_graph._graph is None and not citation_graph.GRAPH_PATH.exists(), "낡은 그래프가 남았다"
    assert client.delete("/api/documents/graph-fail-doc", headers=AUTH).status_code == 404


@case("그래프 무효화 도중 옛 파일을 읽던 조회가 낡은 그래프를 다시 게시하지 않는다")
def _():
    import threading

    citation_graph.invalidate()
    citation_graph.GRAPH_PATH.write_text("{}", encoding="utf-8")  # 아직 지워지지 않은 옛 파일
    started, release = threading.Event(), threading.Event()

    def slow_load():
        started.set()
        release.wait(5)
        return "OLD"

    with patch.object(citation_graph, "load_graph", side_effect=slow_load):
        reader = threading.Thread(target=citation_graph.get_graph)
        reader.start()
        assert started.wait(5), "조회가 시작되지 않았다"
        invalidator = threading.Thread(target=citation_graph.invalidate)
        invalidator.start()
        invalidator.join(0.2)  # 잠금이 있으면 조회가 끝날 때까지 기다린다
        release.set()
        reader.join(5)
        invalidator.join(5)
    assert citation_graph._graph is None, f"무효화 뒤 낡은 그래프가 남았다: {citation_graph._graph!r}"
    assert not citation_graph.GRAPH_PATH.exists()


@case("옮겨 넣기에서 DB 기록이 실패하면 이미 넣은 청크를 회수한다")
def _():
    baseline = store.chunk_count()
    body = {"filename": "회수세칙.pdf", "chunks": ["제1조 목적"], "embeddings": [[0.1] * 256]}
    with patch.object(main.db, "add_document", side_effect=RuntimeError("db down")):
        r = client.post("/api/index/import", json=body, headers=AUTH)
    assert r.status_code == 500, r.status_code
    assert store.chunk_count() == baseline, "목록에 없는 청크가 색인에 남았다"


@case("서버가 PDF를 직접 받아 색인하는 업로드 경로는 없다 (로컬 색인을 옮기는 방식만)")
def _():
    r = client.post("/api/documents", headers=AUTH)
    assert r.status_code == 405, r.status_code


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
    kw = spy.call_args.kwargs
    assert (kw["max_retries"], kw["backoff_base"]) == (2, 2), kw
    assert kw.get("input_type") == "query", kw  # 질의·문서 임베딩을 구분한다


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


@case("smoke는 두 모델 키와 DATA_DIR이 주입돼도 목업과 임시 폴더만 사용한다")
def _():
    with tempfile.TemporaryDirectory(prefix="smoke-watch-", dir=_SCRATCH) as watch_dir:
        env = os.environ.copy()
        env.update(
            CLAUDE_API_KEY="dummy-not-a-real-key",
            GEMINI_API_KEY="dummy-not-a-real-key",
            VOYAGE_API_KEY="dummy-not-a-real-key",
            DATA_DIR=watch_dir,
            PYTHONIOENCODING="utf-8",
        )
        api_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result = subprocess.run(
            [sys.executable, os.path.join(api_dir, "smoke_test.py")],
            cwd=api_dir,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0, f"smoke exit {result.returncode}:\n{result.stdout}\n{result.stderr}"
        assert os.listdir(watch_dir) == [], f"injected DATA_DIR was modified: {os.listdir(watch_dir)}"
        scratch_lines = [line for line in result.stdout.splitlines() if line.startswith("MOCK_MODE=True; isolated DATA_DIR: ")]
        assert len(scratch_lines) == 1, result.stdout
        scratch_dir = scratch_lines[0].split("DATA_DIR: ", 1)[1]
        assert not os.path.exists(scratch_dir), f"smoke DATA_DIR was left behind: {scratch_dir}"
        assert "ALL SMOKE TESTS PASSED" in result.stdout, result.stdout


@case("종합 답변 단계는 직전 대화를 받는다 — '그래도 같은 답인가요?' 같은 후속 질문에 답할 수 있게 (실명은 마스킹)")
def _():
    import asyncio

    from app.agents import claude_agents
    from app.agents import graph as g
    from app.agents.schemas import AuditorResult, ReviewerResult, RiskLevel

    seen = {}

    async def fake_coordinate(system, user):
        seen["system"], seen["user"] = system, user
        return "### 결론\n가능합니다."

    reviewer = ReviewerResult(question_type="기준·절차", violation="위반 없음", risk_level=RiskLevel.LOW,
                              reasoning="r", recommendation="c")
    auditor = AuditorResult(compliance="준수", sanction_likelihood=RiskLevel.LOW, reasoning="r", recommendation="c")
    # 실명은 질문·답변 양쪽에, 답변 쪽은 500자 경계에 걸치게 둔다 (자른 뒤 마스킹하면 조각이 남는다)
    long_answer = "### 결론\n사퇴하면 출마할 수 있습니다." + "가" * (497 - len("### 결론\n사퇴하면 출마할 수 있습니다.")) + "홍길동 위원장"
    history = [{"question": "홍길동 위원이 사퇴 후 출마할 수 있나요?", "answer": long_answer}]
    state = {"query": "그래도 같은 답인가요?", "standalone_query": "사퇴한 위원도 같은 해 선거에 출마할 수 있나요?",
             "history": history, "reviewer": reviewer, "auditor": auditor}
    with patch.object(g, "MOCK_MODE", False), patch.object(claude_agents, "coordinate", fake_coordinate):
        out = asyncio.run(g.coordinator_node(state))
    assert out["final_markdown"].startswith("### 결론"), out
    user = seen["user"]
    assert "<history>" in user and "사퇴하면 출마할 수 있습니다" in user, user[:300]
    assert "홍길동" not in user and "홍길" not in user, "이력의 실명(경계 조각 포함)이 마스킹되지 않았다"
    # 재작성 질의와 함께, 가리킴 표현("그래도 같은")이 남은 원문을 받는다
    assert "<original_question>\n그래도 같은 답인가요?" in user and "<question>\n사퇴한 위원도" in user, user[-300:]
    assert "<question_type>기준·절차</question_type>" in user
    assert "### 결론" in seen["system"] and "의견 조정" not in seen["system"]

    with patch.object(g, "MOCK_MODE", False), patch.object(claude_agents, "coordinate", fake_coordinate):
        asyncio.run(g.coordinator_node({**state, "history": [], "standalone_query": "그래도 같은 답인가요?"}))
    assert "<history>" not in seen["user"], "이력이 없는데 history 블록이 들어갔다"
    assert "<original_question>" not in seen["user"], "재작성이 원문과 같으면 원문 블록을 넣지 않는다"


@case("규정 검토 결과의 질문 유형은 필수이고 세 갈래만 받으며, 채팅 결과 이벤트에 문자열로 실린다")
def _():
    from pydantic import ValidationError

    from app.agents.schemas import ReviewerResult, RiskLevel

    base = {"violation": "위반 없음", "risk_level": RiskLevel.LOW, "reasoning": "r", "recommendation": "c"}
    assert ReviewerResult(**base, question_type="기준·절차").model_dump(mode="json")["question_type"] == "기준·절차"
    for bad in ({}, {"question_type": "잡담"}):
        try:
            ReviewerResult(**base, **bad)
            raise AssertionError(f"질문 유형 검증 실패: {bad}")
        except ValidationError:
            pass

    # 목업 파이프라인: 절차를 묻는 말투는 '기준·절차'로, 결과 이벤트의 reviewer에 그대로 실린다
    result = chat_result("학생회 예산 변경 절차는 무엇인가요?")
    assert result["reviewer"]["question_type"] == "기준·절차", result["reviewer"]
    assert result["final_markdown"].startswith("### 결론"), result["final_markdown"][:80]


@case("평가 문체 검사: 내부 용어·명령형·해요체·결론 누락·결론의 한다체를 잡고, 근거 조항의 규정 원문 인용은 허용한다")
def _():
    from evaluate import _style_issues

    good = ("### 결론\n할 수 없습니다. 다만 인준을 받으면 위반이 아닙니다.\n\n"
            "### 근거 조항\n- 「재정·회계 세칙」 제10조: 학생회비는 공식 활동 목적으로만 집행한다.\n\n"
            "### 해야 할 일\n1. 공식 활동비 항목으로 집행하시기 바랍니다.")
    assert _style_issues(good) == [], _style_issues(good)
    bad = "### 핵심 요약\n두 분석 모두 위반으로 본다. 제공된 규정에서 확인되지 않는다.\n1. 대의원회에 문의하라."
    issues = " ".join(_style_issues(bad))
    for expected in ("결론 섹션", "내부 용어", "명령형"):
        assert expected in issues, issues
    probes = {
        "### 결론\n집행할 수 없다.": "한다체",
        "### 결론\n**집행할 수 없다.**": "한다체",
        "### 결론\n쓸 수 없어요. 인준을 받으세요.": "해요체",
        "### 결론\n안 됩니다.\n1. 집행하지 마십시오.": "명령형",
        "### 결론\n감사 분석에 따르면 안 됩니다.": "내부 용어",
    }
    for text, expected in probes.items():
        assert expected in " ".join(_style_issues(text)), f"{expected} 놓침: {text!r}"


# ---------------------------------------------------------------- v3 로그인 (Google ID 토큰 + 세션 쿠키)
# 가짜 RSA 키로 서명한 토큰을 쓴다 — Google 공개키 조회는 테스트에서 이 키로 바꿔 끼운다.

def _google_token_kit():
    import time

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def make(**over):
        now = int(time.time())
        claims = {
            "iss": "https://accounts.google.com",
            "aud": "test-client.apps.googleusercontent.com",
            "sub": "1234567890",
            "iat": now,
            "exp": now + 600,
            "email": "member@inha.edu",
            "email_verified": True,
            "hd": "inha.edu",
            "name": "테스트",
        }
        claims.update(over)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, key, algorithm="RS256")

    return key, make


_KEY, _make_token = _google_token_kit()
_ORIGIN = {"Origin": "http://localhost:3000"}


def _https_client():
    # 세션 쿠키는 Secure라 http 주소로는 다시 보내지 않는다 — https 기준 클라이언트로 검사한다
    return TestClient(main.app, base_url="https://testserver", raise_server_exceptions=False)


@case("Google 토큰 검증: 다른 도메인·hd 불일치·aud 불일치·만료·미확인 이메일·발급자·서명 위조를 모두 거부한다")
def _():
    import time

    from cryptography.hazmat.primitives.asymmetric import rsa

    from app.auth import AuthError, verify_google_token

    pub = lambda _t: _KEY.public_key()  # noqa: E731
    ok = verify_google_token(_make_token(), key_resolver=pub)
    assert ok == {"sub": "1234567890", "email": "member@inha.edu", "name": "테스트"}, ok
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    import jwt as _jwt

    forged = _jwt.encode({"iss": "https://accounts.google.com", "aud": "test-client.apps.googleusercontent.com",
                          "sub": "1", "iat": int(time.time()), "exp": int(time.time()) + 600,
                          "email": "member@inha.edu", "email_verified": True, "hd": "inha.edu"},
                         other, algorithm="RS256")
    bad = {
        "개인 Gmail": _make_token(email="someone@gmail.com", hd=None),
        "hd 불일치": _make_token(hd="gmail.com"),
        "이메일 도메인 불일치": _make_token(email="x@inha.ac.kr"),
        "aud 불일치": _make_token(aud="other-client"),
        "만료": _make_token(iat=int(time.time()) - 7200, exp=int(time.time()) - 3600),
        "미확인 이메일": _make_token(email_verified=False),
        "발급자": _make_token(iss="https://evil.example"),
        "서명 위조": forged,
    }
    for why, token in bad.items():
        try:
            verify_google_token(token, key_resolver=pub)
        except AuthError:
            continue
        raise AssertionError(f"{why} 토큰을 받아들임")


@case("로그인 행렬: Origin 없는 로그인·로그아웃 403, 로그인하면 세션 쿠키로 /me, 관리자 이메일은 admin, 로그아웃·재로그인 뒤 옛 세션 무효")
def _():
    from app import auth

    c = _https_client()
    with patch.object(auth, "_google_signing_key", lambda _t: _KEY.public_key()):
        assert c.post("/api/auth/google", json={"credential": _make_token()}).status_code == 403
        assert c.post("/api/auth/google", json={"credential": _make_token()},
                      headers={"Origin": "https://evil.example"}).status_code == 403
        assert c.get("/api/auth/me").status_code == 401
        bad = c.post("/api/auth/google", json={"credential": _make_token(hd=None, email="a@gmail.com")}, headers=_ORIGIN)
        assert bad.status_code == 401 and "inha.edu" in bad.json()["detail"], bad.text
        r = c.post("/api/auth/google", json={"credential": _make_token()}, headers=_ORIGIN)
        assert r.status_code == 200, r.text
        set_cookie = r.headers.get("set-cookie", "").lower()
        for attr in ("httponly", "secure", "samesite=lax"):
            assert attr in set_cookie, set_cookie
        first = c.cookies.get("sid")
        me = c.get("/api/auth/me")
        assert me.status_code == 200 and me.json()["user"] == {"email": "member@inha.edu", "name": "테스트", "role": "member"}, me.text
        # DB에는 토큰 원문이 아니라 해시만 있다
        with db._connect() as conn:
            hashes = [row[0] for row in conn.execute("SELECT token_hash FROM sessions")]
        assert first not in hashes and auth._hash(first) in hashes
        # 다시 로그인하면 옛 세션은 폐기된다 (세션 고정 방지)
        c.post("/api/auth/google", json={"credential": _make_token()}, headers=_ORIGIN)
        assert c.cookies.get("sid") != first
        stale = _https_client()
        stale.cookies.set("sid", first)
        assert stale.get("/api/auth/me").status_code == 401
        # 로그아웃: Origin 없으면 거부, 있으면 세션 폐기
        assert c.post("/api/auth/logout").status_code == 403
        current = c.cookies.get("sid")
        assert c.post("/api/auth/logout", headers=_ORIGIN).status_code == 200
        replay = _https_client()
        replay.cookies.set("sid", current)
        assert replay.get("/api/auth/me").status_code == 401
        # ADMIN_EMAILS의 계정은 admin 역할
        a = _https_client()
        a.post("/api/auth/google", json={"credential": _make_token(email="boss@inha.edu", sub="boss-sub")}, headers=_ORIGIN)
        assert a.get("/api/auth/me").json()["user"]["role"] == "admin"
        # 역할은 매 요청 ADMIN_EMAILS로 정한다 — 이미 로그인한 세션도 다시 로그인 없이 추가·해제가 반영된다
        from app import auth as _auth

        with patch.object(_auth, "ADMIN_EMAILS", frozenset()):
            assert a.get("/api/auth/me").json()["user"]["role"] == "member"
        m = _https_client()
        m.post("/api/auth/google", json={"credential": _make_token()}, headers=_ORIGIN)
        assert m.get("/api/auth/me").json()["user"]["role"] == "member"
        with patch.object(_auth, "ADMIN_EMAILS", frozenset({"member@inha.edu"})):
            assert m.get("/api/auth/me").json()["user"]["role"] == "admin"
        # 관리자 계정 세션은 토큰 없이 관리자 API(관리자 패널)를 쓴다. 상태 변경은 Origin이 있어야 한다. 일반 계정은 401
        assert a.get("/api/stats").status_code == 200
        assert a.post("/api/cache/clear").status_code == 403
        assert a.post("/api/cache/clear", headers=_ORIGIN).status_code == 200
        assert m.get("/api/stats").status_code == 401
        assert _https_client().get("/api/stats").status_code == 401
        # 같은 이메일이 다른 Google 계정(sub)으로 오면 다른 사람이다 — 기존 계정을 덮어쓰지 않는다
        other = _https_client()
        other.post("/api/auth/google", json={"credential": _make_token(sub="someone-else")}, headers=_ORIGIN)
        with db._connect() as conn:
            subs = {r[0] for r in conn.execute("SELECT google_sub FROM users WHERE email = 'member@inha.edu'")}
        assert subs == {"1234567890", "someone-else"}, subs


@case("Google 공개키를 받지 못하면 401(계정 문제)이 아니라 503(잠시 후 재시도)이다")
def _():
    from app import auth

    def down(_t):
        raise auth.AuthUnavailable

    with patch.object(auth, "_google_signing_key", down):
        r = _https_client().post("/api/auth/google", json={"credential": _make_token()}, headers=_ORIGIN)
    assert r.status_code == 503, r.text


@case("오래 로그인하지 않은 계정과 그 세션은 보존 기간이 지나면 지운다")
def _():
    db.upsert_user("old-sub", "old@inha.edu", "옛 사용자", "member")
    with db._connect() as conn:
        conn.execute("UPDATE users SET last_login_at = '2020-01-01T00:00:00+00:00' WHERE google_sub = 'old-sub'")
    removed = db.purge_sessions(365)
    assert removed["users"] >= 1, removed
    with db._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE google_sub = 'old-sub'").fetchone()[0] == 0


@case("관리자 계정 세션도 문서·색인·백업 경로는 열지 않는다 (ADMIN_TOKEN만)")
def _():
    from app import auth

    a = _https_client()
    with patch.object(auth, "_google_signing_key", lambda _t: _KEY.public_key()):
        a.post("/api/auth/google", json={"credential": _make_token(email="boss@inha.edu")}, headers=_ORIGIN)
    assert a.get("/api/stats").status_code == 200
    assert a.post("/api/index/reset?confirm=true", headers=_ORIGIN).status_code == 401
    assert a.get("/api/backup").status_code == 401
    assert a.get("/api/documents").status_code == 401
    # 열 목록 방식: 패널이 쓰지 않는 관리자 경로(이력·기여 데이터)는 세션으로 열리지 않는다
    assert a.get("/api/history").status_code == 401
    assert a.get("/api/contributions").status_code == 401
    # 브라우저에 낡은 토큰이 남아 있어도 관리자 세션이면 패널이 열린다
    assert a.get("/api/stats", headers={"Authorization": "Bearer old"}).status_code == 200


# ---------------------------------------------------------------- v3 문서 검토 (합성 문서 — 실제 문서·개인정보 없음)

_SAMPLE_BUDGET = """[1쪽]
인 하 대 학 교
가나다학과 학생회
2025년도 2학기 상임위원회
2025. 10. 28
[4쪽]
2. 세부 사업 계획서
시기 2025.11.13.(목)
Ⅲ. 예산운영 계획서
1) 수입
항목 금액 비   고
과자치비 5,000,000원 ⋅
합계 5,000,000원 ⋅
2) 지출
항목 금액 비   고
대관비 1,200,000원 변동사항 없음
홍보비 100,000원
예비비 150,000원
합계 1,450,000원
3) 수입/지출 총계
항목 금액 비   고
수 입 금 5,000,000원 과자치비
지 출 금 1,450,000원
차    액 3,550,000원
2. 세부 예산 계획서
간식 7,300 * 50 = 365,000원
"""


@case("문서 검토 숫자: 콤마·만원·한글 금액을 해석하고 모르는 글자는 추측하지 않는다")
def _():
    from app.review.numbers import korean_amount, to_int

    assert to_int("5,698,191원") == 5698191
    assert korean_amount("육백만원") == 6_000_000
    assert korean_amount("백삼십만원") == 1_300_000
    assert korean_amount("120만원") == 1_200_000
    assert korean_amount("이천일백일십일만원") == 21_110_000
    assert korean_amount("삼천오백팔십일만원") == 35_810_000
    assert korean_amount("약 육백만원") is None


@case("원문 검사: 틀린 계산식·한글 금액·요일·VAT 혼용·15만 원 초과 현금·개인 명의 통장·민감정보를 찾고, 맞는 식은 지나간다")
def _():
    from app.review.textcheck import check_text

    ok = check_text("간식 7,300 * 50 = 365,000원\n2025.11.13.(목) 진행\n100 - 20 + 10 = 90\n1.5 * 10 = 15\n100 * 2 = 200.5")
    assert ok == [], [f.code for f in ok]
    bad = check_text(
        "멘토비 4 * 200,000 = 1,000,000원\n"
        "21,110,000원\n(이천일백일십만원)\n"
        "대회 기간 2025.05.11(월)\n"
        "단가 7,500원 VAT 별도 / 결제는 VAT 포함\n"
        "심판 수당 300,000원 현금 지급\n"
        "매출은 재무부장 명의 기금통장으로 받음\n"
        "신청 시 질환·복용 약물 조사\n"
    )
    codes = {f.code for f in bad}
    for expected in ("formula", "korean_amount", "weekday", "vat", "cash", "personal_account", "sensitive"):
        assert expected in codes, (expected, codes)
    assert not any(f.code == "cash" for f in check_text("현금영수증 발급 500,000원")), "현금영수증을 현금 지급으로 봄"
    copied = check_text("[1쪽]\n가나다학과 학생회\n2026. 02. 21\n[2쪽]\n시기 2025/03/07 ~ 2025/03/08\n")
    assert [f.code for f in copied] == ["event_year"], [f.code for f in copied]


@case("예산 구조 검사: 합계·차액·인원×단가·예비비 10%·인준 전 사업·연도 오기를 잡고 맞는 문서는 조용하다")
def _():
    from app.review.models import BudgetDoc, EventDate, Headcount, Line
    from app.review.rules import check_budget

    good = BudgetDoc(
        title="일일호프", meeting_date="2025-10-28",
        income=[Line(item="과자치비", amount=5_000_000)], income_total=5_000_000,
        expense=[Line(item="대관비", amount=1_200_000), Line(item="예비비", amount=100_000)], expense_total=1_300_000,
        summary_income=5_000_000, summary_expense=1_300_000, balance=3_700_000,
        headcounts=[Headcount(label="참가비", counts=[40, 10], unit_prices=[10_000, 10_000], stated_amount=500_000)],
        event_dates=[EventDate(label="행사", start="2025-11-13", text="2025.11.13.(목)")],
    )
    assert check_budget(good) == [], [f.code for f in check_budget(good)]
    bad = good.model_copy(update={
        "expense": [Line(item="대관비", amount=1_200_000), Line(item="예비비", amount=300_000)],
        "expense_total": 1_400_000, "summary_expense": 1_400_000, "balance": 3_500_000,
        "headcounts": [Headcount(label="갹출 기금", counts=[298, 99], unit_prices=[65_000, 55_000], stated_amount=24_915_000)],
        "event_dates": [EventDate(label="행사", start="2025-10-20", text="2025.10.20"), EventDate(label="둘째 날", start="2024-11-13", text="2024.11.13")],
    })
    codes = {f.code for f in check_budget(bad)}
    for expected in ("지출_total", "balance", "headcount", "reserve", "event_before_meeting", "event_year"):
        assert expected in codes, (expected, codes)
    # 연도를 잘못 쓴 일정은 연도 문제로만 말한다 (인준 전 사업으로 두 번 말하지 않음)
    before = [f for f in check_budget(bad) if f.code == "event_before_meeting"]
    assert len(before) == 1 and "10.20" in before[0].title, [f.title for f in before]
    reserve = next(f for f in check_budget(bad) if f.code == "reserve")
    assert "제16조" in reserve.basis and reserve.level == "위반 소지"


@case("추출 정리: 표 안의 '1EA 7,700원' 단가 줄은 빼야 합계가 맞을 때만 뺀다")
def _():
    from app.review.models import BudgetDoc, Line
    from app.review.service import drop_unit_price_lines

    doc = BudgetDoc(title="간식", expense=[Line(item="세트 50EA", amount=385_000), Line(item="세트 1EA", amount=7_700)], expense_total=385_000)
    assert [l.item for l in drop_unit_price_lines(doc).expense] == ["세트 50EA"]
    real = doc.model_copy(update={"expense_total": 400_000})  # 빼도 안 맞으면 진짜 불일치 — 그대로
    assert len(drop_unit_price_lines(real).expense) == 2


@case("엑셀 검사: 합계 범위에 영수증번호 열이 섞이면, 단가×수량이 금액과 다르면 잡는다")
def _():
    import io

    from openpyxl import Workbook

    from app.review.sheets import check_workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["사업명", "금액", "영수증번호"])
    ws.append(["간식", 10000, 1])
    ws.append(["물", 5000, 2])
    ws["D4"] = "=SUM(B2:C3)"
    ws2 = wb.create_sheet("사업별")
    ws2.append(["품목", "단가", "수량", "금액"])
    ws2.append(["샌드위치", 9600, 3, 28000])
    ws2.append(["음료", 1000, 5, 5000])
    buf = io.BytesIO()
    wb.save(buf)
    found = check_workbook(buf.getvalue())
    codes = [f.code for f in found]
    assert "sum_range" in codes, codes
    unit = [f for f in found if f.code == "unit_qty"]
    assert len(unit) == 1 and "28,800" in unit[0].detail, [f.detail for f in unit]


@case("규칙 기반 추출: 학생회 양식의 수입·지출·총계 표와 시기를 읽는다 (목업·LLM 실패 때 예비 경로)")
def _():
    from app.review.heuristic import heuristic_extract, meeting_date_from_filename

    doc = heuristic_extract("251028 상임위 일일호프.pdf", _SAMPLE_BUDGET)
    assert [(l.item, l.amount) for l in doc.income] == [("과자치비", 5_000_000)], doc.income
    assert [l.item for l in doc.expense] == ["대관비", "홍보비", "예비비"], doc.expense
    assert (doc.income_total, doc.expense_total) == (5_000_000, 1_450_000)
    assert (doc.summary_income, doc.summary_expense, doc.balance) == (5_000_000, 1_450_000, 3_550_000)
    assert doc.meeting_date == "2025-10-28" and doc.event_dates[0].start == "2025-11-13"
    assert meeting_date_from_filename("2025_가나다학과.pdf") is None


@case("문서 검토 API: 로그인·Origin 필요, 추출 → 확인 → 점검 → 메모 흐름, 열리지 않는 한글 파일은 다시 저장 안내, 하루 한도")
def _():
    import io

    from pypdf import PdfWriter

    from app import auth
    from app.review import api as review_api
    from app.review import service

    chat_count_before = db.count_today()
    c = _https_client()
    assert c.post("/api/review/extract?filename=a.pdf", content=b"%PDF", headers=_ORIGIN).status_code == 401
    with patch.object(auth, "_google_signing_key", lambda _t: _KEY.public_key()):
        c.post("/api/auth/google", json={"credential": _make_token(sub="reviewer", email="reviewer@inha.edu")}, headers=_ORIGIN)
    assert c.post("/api/review/extract?filename=a.pdf", content=b"%PDF").status_code == 403  # Origin 없음
    hwp = c.post("/api/review/extract?filename=a.hwp", content=b"HWP Document File", headers=_ORIGIN)
    assert hwp.status_code == 422 and "PDF" in hwp.json()["detail"], hwp.text
    blank = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(blank)
    scanned = c.post("/api/review/extract?filename=scan.pdf", content=blank.getvalue(), headers=_ORIGIN)
    assert scanned.status_code == 422 and "글자" in scanned.json()["detail"], scanned.text

    # 실제 PDF 대신 추출 단계만 합성 텍스트로 바꿔 흐름을 본다
    from app.review.extract import Extracted

    fake = Extracted(kind="pdf", text=_SAMPLE_BUDGET + "\n멘토비 4 * 200,000 = 1,000,000원", pages=4)
    with patch.object(service, "extract_file", lambda _n, _d: fake):
        r = c.post("/api/review/extract?filename=251028 일일호프.pdf", content=b"%PDF-1.4", headers=_ORIGIN)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["method"] == "rule" and out["doc"]["income_total"] == 5_000_000
    assert any(f["code"] == "formula" for f in out["source"]), out["source"]
    doc = out["doc"]
    doc["expense"][2]["amount"] = 900_000  # 사용자가 예비비를 고쳐 10%를 넘김
    doc["expense_total"] = doc["summary_expense"] = 2_200_000
    doc["balance"] = 2_800_000
    checked = c.post("/api/review/check", json={"doc": doc, "source": out["source"]}, headers=_ORIGIN).json()["findings"]
    codes = [f["code"] for f in checked]
    assert "reserve" in codes and "formula" in codes, codes
    assert codes.index("reserve") < codes.index("formula"), "위반 소지가 먼저 와야 한다"
    notes = c.post("/api/review/notes", json={"doc": doc, "text": out["text"], "findings": checked}, headers=_ORIGIN)
    assert notes.status_code == 200 and notes.json()["notes"] == [], notes.text
    # 하루 한도
    with patch.object(review_api, "DAILY_LIMIT", 1), patch.object(service, "extract_file", lambda _n, _d: fake):
        limited = c.post("/api/review/extract?filename=a.pdf", content=b"%PDF-1.4", headers=_ORIGIN)
    assert limited.status_code == 429, limited.text
    # 문서 검토 기록은 규정 질문 한도에 세지 않는다
    with db._connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM metrics WHERE route LIKE 'review%'").fetchone()[0]
    assert n >= 2, n
    assert db.count_today() == chat_count_before, (db.count_today(), chat_count_before)


@case("공문 번호 대장: 다음 번호 자동, 빈 번호·중복·날짜 역순 표시, 남의 기록은 지울 수 없음, Origin 필요")
def _():
    from app import auth

    a, b = _https_client(), _https_client()
    with patch.object(auth, "_google_signing_key", lambda _t: _KEY.public_key()):
        a.post("/api/auth/google", json={"credential": _make_token(sub="ledger-a", email="la@inha.edu")}, headers=_ORIGIN)
        b.post("/api/auth/google", json={"credential": _make_token(sub="ledger-b", email="lb@inha.edu")}, headers=_ORIGIN)
    entry = {"prefix": "가나다", "issued_on": "2026-03-02", "title": "자료 제출", "recipient": "총대의원회"}
    assert a.post("/api/ledger", json=entry).status_code == 403
    out = a.post("/api/ledger", json=entry, headers=_ORIGIN).json()
    assert out["entries"][0]["seq"] == 1 and out["problems"] == [], out
    assert a.get("/api/ledger/next?prefix=가나다&year=2026").json()["number"] == "가나다-2026-0002"
    out = a.post("/api/ledger", json={**entry, "seq": 4, "issued_on": "2026-03-01"}, headers=_ORIGIN).json()
    joined = " ".join(out["problems"])
    assert "빠진 번호 0002, 0003" in joined and "앞 번호보다 빨라요" in joined, out["problems"]
    out = a.post("/api/ledger", json={**entry, "seq": 4}, headers=_ORIGIN).json()
    assert any("겹치는 번호 0004" in p for p in out["problems"]), out["problems"]
    victim = out["entries"][0]["id"]
    assert b.delete(f"/api/ledger/{victim}", headers=_ORIGIN).status_code == 404  # 남의 기록
    assert b.get("/api/ledger").json()["entries"] == []
    assert a.post("/api/ledger", json={**entry, "prefix": "<script>"}, headers=_ORIGIN).status_code == 422


@case("업로드 자원 상한: 두 칸짜리 엑셀이라도 범위가 170억 칸이면 열기 전에 거절한다")
def _():
    import io

    from openpyxl import Workbook

    from app.review.extract import UnsupportedFile, extract_file

    wb = Workbook()
    wb.active["A1"] = 1
    wb.active["XFD1048576"] = 2
    buf = io.BytesIO()
    wb.save(buf)
    try:
        extract_file("wide.xlsx", buf.getvalue())
    except UnsupportedFile as e:
        assert "범위" in str(e), str(e)
    else:
        raise AssertionError("거대한 범위를 받아들임")


@case("수식의 합계 범위가 시트보다 넓어도(=SUM(A1:XFD1048576)) 실제 범위까지만 계산한다")
def _():
    import io
    import time

    from openpyxl import Workbook

    from app.review.sheets import check_workbook

    wb = Workbook()
    wb.active["A1"] = 10
    wb.active["A2"] = 20
    wb.active["B1"] = "=SUM(A1:XFD1048576)"
    buf = io.BytesIO()
    wb.save(buf)
    t = time.monotonic()
    check_workbook(buf.getvalue())
    assert time.monotonic() - t < 5, "넓은 범위를 다 돌았다"


@case("번호 대장: 번호를 비우고 동시에 등록해도 번호가 겹치지 않는다")
def _():
    from concurrent.futures import ThreadPoolExecutor

    db.upsert_user("race-sub", "race@inha.edu", None, "member")
    with db._connect() as conn:
        uid = conn.execute("SELECT id FROM users WHERE google_sub = 'race-sub'").fetchone()[0]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda i: db.add_ledger(uid, "경합", 2026, None, "2026-03-02", f"t{i}", ""), range(8)))
    seqs = sorted(e["seq"] for e in db.list_ledger(uid))
    assert seqs == list(range(1, 9)), seqs


@case("문서 검토 메모(유료)도 사용자별 하루 한도가 있다")
def _():
    from app import auth
    from app.review import api as review_api

    c = _https_client()
    with patch.object(auth, "_google_signing_key", lambda _t: _KEY.public_key()):
        c.post("/api/auth/google", json={"credential": _make_token(sub="notes-limit", email="nl@inha.edu")}, headers=_ORIGIN)
    body = {"doc": {"title": "x"}, "text": "본문", "findings": []}
    assert c.post("/api/review/notes", json=body, headers=_ORIGIN).status_code == 200
    with patch.object(review_api, "DAILY_LIMIT", 0):
        assert c.post("/api/review/notes", json=body, headers=_ORIGIN).status_code == 429



def _plan_draft(**kw):
    from app.plan.models import DraftLine, DraftStep, PlanDraft

    base = dict(
        intent="시험 기간 학우를 응원하고자 함.",
        steps=[
            DraftStep(phase="준비", text="홍보·신청 받기", days_before=7),
            DraftStep(phase="진행", text="간식 나눠 주기", days_before=-5),  # 진행인데 기간 밖 → 기간 안으로
            DraftStep(phase="마무리", text="수령 명단 정리", days_before=-2),
        ],
        expected=["학우 만족도 향상"],
        lines=[
            DraftLine(item="간식 기프티콘", unit_price=7_700, qty=50, unit="개", basis="1인 1개"),
            DraftLine(item="예비비", unit_price=99_999, qty=1),  # 모델이 넣은 예비비 줄은 버린다
            DraftLine(item="홍보 포스터 인쇄", unit_price=1_500, qty=20, unit="장"),
        ],
        reserve_rate=0.5,  # 9%로 깎인다
        cautions=["신청 인원에 따라 수량이 바뀔 수 있음"],
    )
    base.update(kw)
    return PlanDraft(**base)


_PLAN_IN = {
    "title": "중간고사 간식드리미", "org": "가나다학과 학생회", "purpose": "시험 기간 응원. 문의 010-1234-5678",
    "target": "학생회비 납부 학우", "headcount": 50, "start": "2026-04-20", "end": "2026-04-21",
    "fund": "학생회비", "budget_cap": 400_000, "activities": "기프티콘 지급",
}


@case("기획 도우미 계산: 금액은 단가×수량, 모델이 넣은 예비비 줄은 버리고 예비비는 사업비의 10% 이내 10원 내림, 진행 일정은 사업 기간 안")
def _():
    from app.plan.build import assemble, to_budget_doc, to_text
    from app.plan.models import PlanIn
    from app.review.rules import check_reserve

    req = PlanIn(**_PLAN_IN)
    plan = assemble(req, _plan_draft(), "ai")
    assert [l.item for l in plan.lines] == ["간식 기프티콘", "홍보 포스터 인쇄"], plan.lines
    items = 385_000 + 30_000
    assert plan.reserve == int(items * 0.10) // 10 * 10 == 41_500, plan.reserve
    assert plan.expense_total == items + plan.reserve
    assert plan.over_cap == plan.expense_total - 400_000 > 0  # 항목만으로 넘으면 예비비를 깎아도 넘는다
    fits = assemble(req.model_copy(update={"budget_cap": 430_000}), _plan_draft(), "ai")
    assert fits.reserve == 15_000 and fits.over_cap == 0, (fits.reserve, fits.over_cap)  # 예비비는 남은 만큼만
    run = [s for s in plan.steps if s.phase == "진행"][0]
    assert str(run.date) == "2026-04-21", run.date  # 끝난 뒤 5일 → 끝나는 날로 맞춤
    assert [s.phase for s in plan.steps] == ["준비", "진행", "마무리"]
    doc = to_budget_doc(plan)
    assert check_reserve(doc) == [], "서버가 정한 예비비는 10% 규정에 걸리지 않아야 한다"
    assert doc.expense_total == sum(l.amount for l in doc.expense)
    text = to_text(plan)
    for want in ("Ⅱ. 사업 계획서", "1. 전체 사업 계획서", "2. 세부 사업 계획서", "구분 | 세부내용(개수) | 비용 | 예산 출처",
                 "간식 기프티콘 (7,700원*50개) | 385,000원 | 학생회비", "예비비 | 사업비의 10% 이내 | 41,500원",
                 "총액 |  | 456,500원", "관 | 금액 | 비고", "사업비 | 456,500원", "1. 전체 예산 계획서", "2. 세부 예산 계획서 (예산 세부 내역 판단 자료)",
                 "2026년도 1학기 총 사업 진행 비용 | 456,500원", "구매 확인서"):
        assert want in text, (want, text)
    assert "(월)" in text or "(화)" in text  # 시기에 요일을 붙인다 (2026-04-20은 월요일)
    assert "2026. 4. 20.(월)" in text, text
    from app.review.textcheck import check_text

    assert check_text(text) == [], [f.title for f in check_text(text)]  # 만든 문서는 원문 검사(식·요일·표기)에 걸리지 않는다


@case("기획 AI 초안(목적·주요 활동): 로그인·Origin 필요, 입력·출력 연락처 지움, 칸 길이로 자름, 모델 실패는 503 + 지표 기록, 질문 한도와 별도")
def _():
    from app import auth
    from app.agents import claude_agents
    from app.plan import service as plan_service
    from app.plan.models import Suggestion

    body = {"field": "purpose", "title": "중간고사 간식드리미", "target": "학생회비 납부 학우", "activities": "문의 010-1234-5678"}
    c = _https_client()
    assert c.post("/api/plan/suggest", json=body, headers=_ORIGIN).status_code == 401
    with patch.object(auth, "_google_signing_key", lambda _t: _KEY.public_key()):
        c.post("/api/auth/google", json={"credential": _make_token(sub="suggester", email="suggester@inha.edu")}, headers=_ORIGIN)
    assert c.post("/api/plan/suggest", json=body).status_code == 403  # Origin 없음
    assert c.post("/api/plan/suggest", json={**body, "field": "budget"}, headers=_ORIGIN).status_code == 422

    mock = c.post("/api/plan/suggest", json={**body, "field": "activities"}, headers=_ORIGIN)  # 목업: 자리 표시 뼈대
    assert mock.status_code == 200 and "\n" in mock.json()["text"], mock.text

    seen = {}

    async def fake(system, user, schema, **kw):
        seen["user"] = user
        return Suggestion(text="학우를 응원하고자 해요. 담당 010-9999-8888 " + "가" * 500)

    chat_before = db.count_today()
    with patch.object(plan_service, "MOCK_MODE", False), patch.object(claude_agents, "structured", fake):
        r = c.post("/api/plan/suggest", json=body, headers=_ORIGIN)
    assert r.status_code == 200, r.text
    text = r.json()["text"]
    assert "010-1234-5678" not in seen["user"] and "010-9999-8888" not in text, "연락처가 모델·결과에 남았다"
    assert len(text) <= 400 and text.startswith("학우를 응원"), text[:40]
    assert "'목적' 칸" in seen["user"]

    async def down(*a, **kw):
        raise RuntimeError("overloaded")

    with patch.object(plan_service, "MOCK_MODE", False), patch.object(claude_agents, "structured", down):
        fail = c.post("/api/plan/suggest", json=body, headers=_ORIGIN)
    assert fail.status_code == 503 and "다시 시도" in fail.json()["detail"], fail.text
    with db._connect() as conn:
        rows = conn.execute("SELECT status FROM metrics WHERE route = 'review-plan-suggest' ORDER BY id").fetchall()
    assert [r[0] for r in rows][-2:] == ["ok", "error"], rows
    assert db.count_today() == chat_before, "AI 초안이 규정 질문 한도에 섞였다"


@case("보안 점검(DoS): 긴 숫자열·공백 채운 엑셀 태그도 정규식이 선형으로 끝나고, 본문 상한은 선언 길이·청크 전송 모두 413")
def _():
    import time

    from app.review import sheets, textcheck

    started = time.monotonic()
    textcheck.check_text("1" * 60_000)
    textcheck.check_text("1,000원 " * 2000 + "9" * 30_000 + " = 1")
    assert time.monotonic() - started < 2, "긴 숫자열 검사가 느리다"
    tag = b'<c r="B1"' + b" " * 200_000 + b'x s="5"'
    started = time.monotonic()
    sheets._STYLE_ATTR.sub(rb"\1", tag + b"/>")
    sheets._COL_STYLE.sub(rb"\1", b"<col" + b" " * 200_000 + b'style="1"/>')
    assert time.monotonic() - started < 1, "엑셀 서식 정규식이 느리다"
    # 맞는 식·한글 금액은 그대로 찾는다
    assert any("계산" in f.title or "식" in f.title for f in textcheck.check_text("간식 7,700원 * 50개 = 385,001원"))

    assert client.post("/api/feedback", content=b"x" * (1024 * 1024 + 10), headers={"Content-Type": "application/json"}).status_code == 413

    def chunks():
        for _ in range(40):
            yield b"x" * 32_768  # Content-Length 없이 1.3MB
    r = client.post("/api/track", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413, r.status_code
    assert client.post("/api/track", json={"visitor_id": "v-1", "path": "/"}).status_code != 413


@case("보안 헤더: 모든 API 응답에 nosniff·DENY·no-referrer·no-store·CSP(default-src 'none')·HSTS·CORP")
def _():
    r = client.get("/api/health")
    h = {k.lower(): v for k, v in r.headers.items()}
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and h["cache-control"] == "no-store"
    assert h["content-security-policy"].startswith("default-src 'none'") and "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["strict-transport-security"].startswith("max-age=63072000") and h["cross-origin-resource-policy"] == "same-site"
    assert "permissions-policy" in h


@case("회원 관리: 관리자만, 목록·상세(내용 없이 사용 기록), 로그아웃시키기, 이용 제한은 세션·로그인을 막고 풀 수 있다, 관리자는 막거나 못 지움, 삭제는 대장까지 지우고 지표 연결만 끊는다")
def _():
    from app import auth

    member, boss = _https_client(), _https_client()
    with patch.object(auth, "_google_signing_key", lambda _t: _KEY.public_key()):
        r = member.post("/api/auth/google", json={"credential": _make_token(sub="m-1", email="target@inha.edu")}, headers=_ORIGIN)
        boss.post("/api/auth/google", json={"credential": _make_token(sub="b-1", email="boss@inha.edu")}, headers=_ORIGIN)
    assert r.status_code == 200, r.text
    uid = next(u["id"] for u in client.get("/api/users?q=target", headers=AUTH).json()["users"])
    db.record_metric(route="review-plan", risk_level=None, status="ok", elapsed=1.0, input_tokens=10, output_tokens=5,
                     query_preview="", visitor_id=f"user:{uid}", cost_usd=0.01)
    assert member.get("/api/users").status_code == 401  # 일반 계정은 못 본다
    rows = client.get("/api/users?q=target", headers=AUTH).json()
    assert [u["email"] for u in rows["users"]] == ["target@inha.edu"] and rows["users"][0]["uses_30d"] == 1, rows
    d = client.get(f"/api/users/{uid}", headers=AUTH).json()
    assert d["by_route"][0]["route"] == "review-plan" and "query_preview" not in d["recent"][0] and d["sessions"][0]["active"]
    assert boss.get("/api/users", headers=_ORIGIN).status_code == 200  # 관리자 세션도 연다

    assert client.post(f"/api/users/{uid}/logout", headers=AUTH).json()["revoked"] == 1
    assert member.get("/api/auth/me").json().get("user") is None
    with patch.object(auth, "_google_signing_key", lambda _t: _KEY.public_key()):
        member.post("/api/auth/google", json={"credential": _make_token(sub="m-1", email="target@inha.edu")}, headers=_ORIGIN)
    assert client.post(f"/api/users/{uid}/block", json={"blocked": True}, headers=AUTH).json()["user"]["blocked_at"]
    assert member.get("/api/auth/me").json().get("user") is None, "막힌 계정의 세션이 살아 있다"
    with patch.object(auth, "_google_signing_key", lambda _t: _KEY.public_key()):
        again = member.post("/api/auth/google", json={"credential": _make_token(sub="m-1", email="target@inha.edu")}, headers=_ORIGIN)
    assert again.status_code == 403 and "제한" in again.json()["detail"]
    client.post(f"/api/users/{uid}/block", json={"blocked": False}, headers=AUTH)
    with patch.object(auth, "_google_signing_key", lambda _t: _KEY.public_key()):
        assert member.post("/api/auth/google", json={"credential": _make_token(sub="m-1", email="target@inha.edu")}, headers=_ORIGIN).status_code == 200

    boss_id = next(u["id"] for u in client.get("/api/users?q=boss", headers=AUTH).json()["users"])
    assert client.post(f"/api/users/{boss_id}/block", json={"blocked": True}, headers=AUTH).status_code == 400
    assert client.delete(f"/api/users/{boss_id}", headers=AUTH).status_code == 400
    assert client.delete(f"/api/users/{uid}", headers=AUTH).json() == {"deleted": True}
    assert client.get(f"/api/users/{uid}", headers=AUTH).status_code == 404
    with db._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM metrics WHERE visitor_id = ?", (f"user:{uid}",)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (uid,)).fetchone()[0] == 0


@case("법령 더 물어보기: 로그인·Origin 필요, 질문·이력의 연락처는 모델에 안 감, 없는 조문 인용은 지우고 근거 칩은 대조된 것만, 대조 실패는 링크만, 모델 실패 503")
def _():
    from app import auth
    from app.agents import claude_agents
    from app.law import service as law

    body = {"question": "축제 강사비 문의 010-1234-5678", "topic": "fee", "history": [{"q": "앞 질문 010-2222-3333", "a": "앞 답"}]}
    c = _https_client()
    assert c.post("/api/law/ask", json=body, headers=_ORIGIN).status_code == 401
    with patch.object(auth, "_google_signing_key", lambda _t: _KEY.public_key()):
        c.post("/api/auth/google", json={"credential": _make_token(sub="lawasker", email="lawasker@inha.edu")}, headers=_ORIGIN)
    assert c.post("/api/law/ask", json=body).status_code == 403  # Origin 없음
    assert c.post("/api/law/ask", json={**body, "history": [{"q": "q", "a": "a"}] * 4}, headers=_ORIGIN).status_code == 422
    mock = c.post("/api/law/ask", json=body, headers=_ORIGIN)  # 목업: 바깥 MCP를 부르지 않는다
    assert mock.status_code == 200 and mock.json()["verified"] is False and mock.json()["citations"], mock.text

    seen = {}

    async def fake(system, user, url, tools, **kw):
        seen["user"], seen["tools"] = user, tools
        return "기타소득이에요. 출처: https://x\n\n근거\n- 「소득세법」 제21조(기타소득) (확인함)\n- 「소득세법」 제999조(없는 조)"

    async def verify(tool, args, timeout=20):
        assert tool == "verify_citations" and "http" not in args["text"] and "(확인함)" not in args["text"]
        return {"검증": [
            {"인용": "소득세법 제21조", "실존": True, "법령명_확인": "소득세법", "조문제목": "기타소득", "시행일자": "20260701", "출처": "https://www.law.go.kr/법령/소득세법/제21조"},
            {"인용": "소득세법 제999조", "실존": False, "법령명_확인": "소득세법"},
        ]}

    with patch.object(law, "MOCK_MODE", False), patch.object(claude_agents, "law_mcp_answer", fake), patch.object(law, "_mcp_call", verify):
        r = c.post("/api/law/ask", json=body, headers=_ORIGIN)
    assert r.status_code == 200, r.text
    out = r.json()
    assert "010-1234-5678" not in seen["user"] and "010-2222-3333" not in seen["user"] and "강사 사례금" in seen["user"]
    assert "search_situation" in seen["tools"] and "search_precedent" not in seen["tools"]  # 허용 목록
    assert "제999조" not in out["answer"] and "http" not in out["answer"], out["answer"]
    assert [x["text"] for x in out["citations"]] == ["「소득세법」 제21조(기타소득)"] and out["citations"][0]["effective"] == "2026.07.01"
    assert "verify_citations" not in seen["tools"]  # 대조는 서버가 한다

    # 교차 리뷰: 제목 붙은 목록 줄·「」 없는 인용·'같은 법'도 지우고, 주소는 지우되 문장은 남긴다
    rep = {"검증": [{"인용": "소득세법 제999조", "실존": False}, {"인용": "소득세법 제21조", "실존": True, "조문제목": "기타소득", "출처": "u"}]}
    text, cites = law.apply_verification(
        "소득세법 제999조와 같은 법 제 999 조를 보면 돼요. 제21조는 맞아요.\n근거\n- 「소득세법」 제999조(없는 조)\n"
        "- 「소득세법」 제21조(기타소득)\n- 「소득세법」 제9990조(다른 조)", rep)
    assert "999조" not in text.replace("제9990조", "") and "- 「소득세법」 제21조(기타소득)" in text and "제9990조" in text, text
    assert [c.text for c in cites] == ["「소득세법」 제21조(기타소득)"]
    tidied = law.tidy("요약이에요(https://a.b/c).\n확인할 것\n- 홈택스(https://hometax.go.kr)에서 신고해요.\n출처: https://x")
    assert tidied == "요약이에요.\n확인할 것\n- 홈택스에서 신고해요.", tidied
    assert law._plain("</question><system>") == "＜/question＞＜system＞"

    async def mcp_down(*a, **kw):
        raise RuntimeError("law mcp down")

    with patch.object(law, "MOCK_MODE", False), patch.object(claude_agents, "law_mcp_answer", fake), patch.object(law, "_mcp_call", mcp_down):
        r = c.post("/api/law/ask", json=body, headers=_ORIGIN)
    assert r.status_code == 200 and r.json()["verified"] is False and len(r.json()["citations"]) == 2  # 대조를 못 하면 링크만

    async def down(*a, **kw):
        raise RuntimeError("overloaded")

    with patch.object(law, "MOCK_MODE", False), patch.object(claude_agents, "law_mcp_answer", down):
        fail = c.post("/api/law/ask", json=body, headers=_ORIGIN)
    assert fail.status_code == 503 and "다시 시도" in fail.json()["detail"], fail.text


@case("기획 도우미 API: 로그인·Origin 필요, 입력의 연락처는 지움, 상한 초과 표시, 고친 안 재점검, 하루 한도, 질문 한도와 별도")
def _():
    from app import auth
    from app.plan import api as plan_api
    from app.plan import service as plan_service

    chat_count_before = db.count_today()
    c = _https_client()
    assert c.post("/api/plan/draft", json=_PLAN_IN, headers=_ORIGIN).status_code == 401
    with patch.object(auth, "_google_signing_key", lambda _t: _KEY.public_key()):
        c.post("/api/auth/google", json={"credential": _make_token(sub="planner", email="planner@inha.edu")}, headers=_ORIGIN)
    assert c.post("/api/plan/draft", json=_PLAN_IN).status_code == 403  # Origin 없음
    bad = c.post("/api/plan/draft", json={**_PLAN_IN, "end": "2026-04-01"}, headers=_ORIGIN)
    assert bad.status_code == 422, bad.text

    seen = {}

    async def fake_structured(system, user, schema, **kw):
        seen["user"] = user
        return _plan_draft()

    from app.agents import claude_agents

    with patch.object(plan_service, "MOCK_MODE", False), patch.object(claude_agents, "structured", fake_structured):
        r = c.post("/api/plan/draft", json=_PLAN_IN, headers=_ORIGIN)
    assert r.status_code == 200, r.text
    out = r.json()
    assert "010-1234-5678" not in seen["user"] and "010-1234-5678" not in r.text, "연락처가 모델·결과에 남았다"
    assert out["plan"]["method"] == "ai" and any(f["code"] == "plan_cap" for f in out["findings"]), out["findings"]

    # 고친 안: 수량을 줄여 상한 안으로, 현금 지급 문구 추가 → 상한 지적은 사라지고 본문 검사가 다시 돈다
    plan = out["plan"]
    edit = {
        "request": plan["request"], "intent": plan["intent"] + " 상금은 현금 200,000원 지급.", "steps": plan["steps"],
        "expected": plan["expected"], "cautions": plan["cautions"], "reserve": 0, "method": "ai",
        "lines": [{"item": "간식 기프티콘", "unit_price": 7_700, "qty": 40, "unit": "개", "basis": ""}],
    }
    again = c.post("/api/plan/rebuild", json=edit, headers=_ORIGIN)
    assert again.status_code == 200, again.text
    codes = [f["code"] for f in again.json()["findings"]]
    assert "plan_cap" not in codes and "cash" in codes, codes
    assert again.json()["plan"]["expense_total"] == 308_000

    # 목업(규칙 기반) 뼈대도 같은 모양
    mock = c.post("/api/plan/draft", json=_PLAN_IN, headers=_ORIGIN).json()
    assert mock["plan"]["method"] == "rule" and mock["plan"]["steps"], mock
    with patch.object(plan_api, "DAILY_LIMIT", 2):
        assert c.post("/api/plan/draft", json=_PLAN_IN, headers=_ORIGIN).status_code == 429
    assert db.count_today() == chat_count_before, "기획 초안이 규정 질문 한도를 썼다"



@case("기획 도우미: 초안이 예산 상한을 넘으면 넘은 금액을 알려 한 번만 다시 쓰게 한다")
def _():
    import asyncio

    from app.agents import claude_agents
    from app.plan import service as plan_service
    from app.plan.models import DraftLine, PlanIn

    calls = []

    async def fake(system, user, schema, **kw):
        calls.append(user)
        qty = 60 if len(calls) == 1 else 40
        return _plan_draft(lines=[DraftLine(item="간식 기프티콘", unit_price=7_700, qty=qty)], reserve_rate=0.05)

    with patch.object(plan_service, "MOCK_MODE", False), patch.object(claude_agents, "structured", fake):
        res, _ = asyncio.run(plan_service.draft(PlanIn(**_PLAN_IN)))
    assert len(calls) == 2, len(calls)
    assert "85,100원 넘었다" in calls[1], calls[1][-200:]
    assert res.plan.over_cap == 0 and res.plan.lines[0].qty == 40, res.plan



@case("회의록 정리: 모델이 지어낸 날짜·연락처는 버리고, 서식·할 일을 만든다. 로그인·Origin·한도·질문 한도와 별도")
def _():
    from app import auth
    from app.agents import claude_agents
    from app.minutes import api as minutes_api
    from app.minutes import service as minutes_service
    from app.minutes.service import AgendaItem, Minutes, Todo

    seen = {}

    async def fake(system, user, schema, **kw):
        seen["user"] = user
        return Minutes(
            title="3차 집행부 회의", held_on="2026-03-04", place="학생회실", attendees=9,
            agenda=[AgendaItem(title="새터 버스", discussion="버스 2대로 함. 문의 010-9876-5432", result="결정")],
            decisions=["버스 2대 대절"],
            todos=[Todo(task="버스 계약", owner="재무국장", due="2026-03-06"),
                   Todo(task="현수막", owner="홍보팀", due="2031-01-01"),  # 회의일에서 1년 넘게 떨어진 날짜 → 버림
                   Todo(task="명단 정리", owner="", due="다음주")],
            next_agenda=["MT 장소"],
        )

    chat_before = db.count_today()
    c = _https_client()
    body = {"text": "3/4 집행부 회의. 새터 버스 2대로 결정. 재무국장 3/6까지 계약. 문의 010-9876-5432", "held_on": "2026-03-04"}
    assert c.post("/api/minutes", json=body, headers=_ORIGIN).status_code == 401
    with patch.object(auth, "_google_signing_key", lambda _t: _KEY.public_key()):
        c.post("/api/auth/google", json={"credential": _make_token(sub="minutes", email="minutes@inha.edu")}, headers=_ORIGIN)
    assert c.post("/api/minutes", json=body).status_code == 403
    with patch.object(minutes_service, "MOCK_MODE", False), patch.object(claude_agents, "structured", fake):
        r = c.post("/api/minutes", json=body, headers=_ORIGIN)
    assert r.status_code == 200, r.text
    out = r.json()
    assert "010-9876-5432" not in seen["user"] and "010-9876-5432" not in r.text
    assert [t["due"] for t in out["minutes"]["todos"]] == ["2026-03-06", None, None]
    assert "일시: 2026-03-04" in out["text"] and "- 버스 계약 / 재무국장 / ~2026-03-06" in out["text"], out["text"]
    mock = c.post("/api/minutes", json={"text": "- 간식 업체 정함\n- 홍보물 다음 주 게시\n회의 끝"}, headers=_ORIGIN).json()
    assert mock["method"] == "rule" and mock["minutes"]["decisions"] == ["간식 업체 정함", "홍보물 다음 주 게시"], mock  # 머리표 없는 줄은 뺀다
    with patch.object(minutes_api, "DAILY_LIMIT", 2):
        assert c.post("/api/minutes", json=body, headers=_ORIGIN).status_code == 429
    assert db.count_today() == chat_before



@case("기획 도우미 자체 점검: 상한 재작성이 실패해도 첫 초안 유지, 수량 0은 0원, '예비 물품'은 남기고 '예비비'만 뺀다, 21줄은 거부")
def _():
    import asyncio

    from app.agents import claude_agents
    from app.plan import service as plan_service
    from app.plan.build import assemble
    from app.plan.models import DraftLine, EditLine, PlanEdit, PlanIn

    calls = []

    async def flaky(system, user, schema, **kw):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("overloaded")
        return _plan_draft(lines=[DraftLine(item="간식 기프티콘", unit_price=7_700, qty=60)])

    with patch.object(plan_service, "MOCK_MODE", False), patch.object(claude_agents, "structured", flaky):
        res, _ = asyncio.run(plan_service.draft(PlanIn(**_PLAN_IN)))
    assert len(calls) == 2 and res.plan.method == "ai" and res.plan.lines[0].qty == 60, res.plan
    assert any(f.code == "plan_cap" for f in res.findings)

    req = PlanIn(**_PLAN_IN)
    plan = assemble(req, _plan_draft(lines=[
        DraftLine(item="예비 물품(건전지)", unit_price=5_000, qty=2),
        DraftLine(item="예비비 (변동)", unit_price=50_000, qty=1),
        DraftLine(item="취소된 항목", unit_price=9_000, qty=0),
    ]), "ai")
    assert [(l.item, l.amount) for l in plan.lines] == [("예비 물품(건전지)", 10_000), ("취소된 항목", 0)], plan.lines

    for bad in ({"unit_price": 12_000_000, "qty": 1}, {"unit_price": 1, "qty": -1}):
        try:
            EditLine(item="x", **bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"범위 밖 숫자를 받아 조용히 깎는다: {bad}")
    line = EditLine(item="x", unit_price=1, qty=1)
    base = {"request": req, "intent": "i", "steps": [], "reserve": 0}
    PlanEdit(**base, lines=[line] * 20)
    try:
        PlanEdit(**base, lines=[line] * 21)
    except ValueError:
        pass
    else:
        raise AssertionError("21줄을 받아 뒤를 조용히 버릴 수 있다")



@case("규정 메모 근거: 같은 규정의 같은 조각에 있는 조만 남기고, 확인 안 되는 항은 떼고, 다른 규정의 같은 번호는 버린다")
def _():
    from app.review.service import _verified_basis

    parts = [
        # 색인 원문 모양: 조 제목 뒤 '1 …', 다음 줄 '2 …' (PDF 추출로 ①이 숫자가 된다), 여러 조가 한 조각에
        ("재정·회계 세칙", "제23조(집행의 원칙) 1 예산은 목적 외로 쓸 수 없다.\n2 주류 구매는 …\n"
                         "제24조(전용 금지) 1 목 간 전용 금지.\n2 제23조제2항에도 불구하고 …\n3 예외"),
        ("중앙학생회칙", "제40조(학생회비) 학생회비는 …"),
    ]
    assert _verified_basis("「재정·회계 세칙」 제23조 제2항", parts) == "「재정·회계 세칙」 제23조 제2항"
    assert _verified_basis("「재정ㆍ회계세칙」 제23조 제5항", parts) == "「재정ㆍ회계세칙」 제23조"  # 없는 항은 떼고 조까지
    assert _verified_basis("「재정·회계 세칙」 제23조 제3항", parts) == "「재정·회계 세칙」 제23조"  # 3항은 다음 조(제24조)의 것
    assert _verified_basis("「중앙학생회칙」 제23조", parts) == ""  # 다른 규정
    parts_ref = [("재정·회계 세칙", "제30조(기타) 제23조에 따른 …")]
    assert _verified_basis("「재정·회계 세칙」 제23조", parts_ref) == ""  # 본문 속 참조는 조 본문이 아니다
    assert _verified_basis("「재정·회계 세칙」 제40조", parts) == ""  # 번호는 있지만 다른 규정의 조
    assert _verified_basis("제23조", parts) == ""  # 규정 이름이 없으면 확인할 수 없다
    assert _verified_basis("「중앙학생회칙」 제40조, 「재정·회계 세칙」 제99조", parts) == "「중앙학생회칙」 제40조"



@case("공지: 관리자만 올리고 내리며, 링크는 사이트 안 경로만, 끝나는 날이 지나면 공개 조회에서 숨는다")
def _():
    from datetime import date

    from app import notice

    assert client.put("/api/settings/notice", json={"text": "점검"}).status_code == 401
    assert client.put("/api/settings/notice", json={"text": "x", "href": "https://evil.example"}, headers=AUTH).status_code == 422
    assert client.put("/api/settings/notice", json={"text": "x", "href": "//evil.example"}, headers=AUTH).status_code == 422
    assert client.put("/api/settings/notice", json={"text": "   "}, headers=AUTH).status_code == 422

    r = client.put("/api/settings/notice", json={"text": " 12월 5일부터  개인정보처리방침이 바뀌어요 ", "href": "/privacy", "until": "2026-12-05"}, headers=AUTH)
    assert r.status_code == 200, r.text
    first = r.json()["notice"]
    assert first["text"] == "12월 5일부터 개인정보처리방침이 바뀌어요" and first["href"] == "/privacy"
    assert client.get("/api/notice").json()["notice"]["id"] == first["id"]
    assert notice.current(date(2026, 12, 5)) and notice.current(date(2026, 12, 6)) is None

    again = client.put("/api/settings/notice", json={"text": "고친 공지"}, headers=AUTH).json()["notice"]
    assert again["id"] != first["id"] and again["until"] is None  # 다시 올리면 닫았던 사람에게도 다시 보인다

    assert client.delete("/api/settings/notice", headers=AUTH).status_code == 200
    assert client.get("/api/notice").json() == {"notice": None}
    assert client.get("/api/settings/notice", headers=AUTH).json() == {"notice": None}


@case("공고문 → 공지 초안: 관리자만, 사진·PDF만(머리 바이트로 판별), 전화번호는 지우고 지난 날짜는 끝나는 날로 두지 않는다")
def _():
    from datetime import date

    from app import notice

    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
    assert client.post("/api/settings/notice/draft", content=png).status_code == 401
    assert client.post("/api/settings/notice/draft", content=b"MZ\x90\x00 exe", headers=AUTH).status_code == 400
    assert client.post("/api/settings/notice/draft", content=b"", headers=AUTH).status_code == 400
    assert client.post("/api/settings/notice/draft", content=b"%PDF-" + b"0" * notice.DRAFT_MAX_BYTES, headers=AUTH).status_code == 413
    r = client.post("/api/settings/notice/draft", content=png, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["draft"]["text"] and r.json()["draft"]["href"] is None  # 목업 초안
    assert notice.sniff(b"RIFF\0\0\0\0WEBPVP8 ") == "image/webp" and notice.sniff(b"\xff\xd8\xff\xe0") == "image/jpeg"
    assert client.post("/api/settings/notice/draft", content=b"GIF89a" + b"\0" * 32, headers=AUTH).status_code == 400

    import io

    from pypdf import PdfWriter

    def pdf(pages: int) -> bytes:
        w, buf = PdfWriter(), io.BytesIO()
        for _ in range(pages):
            w.add_blank_page(width=200, height=200)
        w.write(buf)
        return buf.getvalue()

    assert notice.sniff(pdf(notice.DRAFT_MAX_PAGES)) == "application/pdf"
    r = client.post("/api/settings/notice/draft", content=pdf(notice.DRAFT_MAX_PAGES + 1), headers=AUTH)
    assert r.status_code == 400 and "쪽까지" in r.json()["detail"]  # 긴 PDF로 입력 토큰이 불어나지 않게
    assert client.post("/api/settings/notice/draft", content=b"%PDF-1.7 broken", headers=AUTH).status_code == 400

    raw = notice.NoticeDraft(text="11월 30일(월) 정기총회가 열려요. 문의 010-7149-0367", until="2026-11-30")
    d = notice.tidy_draft(raw, date(2026, 11, 28))
    assert "0367" not in d["text"] and d["until"] == "2026-11-30"
    assert notice.tidy_draft(raw, date(2026, 12, 1))["until"] is None  # 이미 지난 날
    assert notice.tidy_draft(notice.NoticeDraft(text="x", until="11월 30일"), date(2026, 11, 28))["until"] is None
    assert len(notice.tidy_draft(notice.NoticeDraft(text="가" * 500, until=""))["text"]) == 200
    try:
        notice.tidy_draft(notice.NoticeDraft(text="  ", until=""))
        raise AssertionError("빈 초안은 올리지 않는다")
    except ValueError:
        pass



@case("기획 재원: 세칙 구분(학생회비·교비지원금·기금)만 받고, 교비지원금·기금은 비고에 근거 조항을 한 번만 붙인다")
def _():
    from app.plan.build import FUND_NOTES, assemble
    from app.plan.models import DraftLine, PlanEdit, PlanIn

    try:
        PlanIn(**{**_PLAN_IN, "fund": "과자치비"})
    except ValueError:
        pass
    else:
        raise AssertionError("세칙에 없는 재원 구분을 받았다")
    req = PlanIn(**{**_PLAN_IN, "fund": "교비지원금"})
    plan = assemble(req, _plan_draft(lines=[DraftLine(item="간식", unit_price=5_000, qty=10)]), "ai")
    assert plan.cautions[0] == FUND_NOTES["교비지원금"], plan.cautions
    edit = PlanEdit(request=req, intent=plan.intent, steps=plan.steps, expected=plan.expected, cautions=plan.cautions,
                    lines=[], reserve=0)
    again = assemble(req, edit, "ai")
    assert again.cautions.count(FUND_NOTES["교비지원금"]) == 1, again.cautions  # 다시 계산해도 겹치지 않는다
    assert FUND_NOTES.get("학생회비") is None
    assert assemble(PlanIn(**_PLAN_IN), _plan_draft(), "ai").cautions == [c for c in _plan_draft().cautions[:3] if c.strip()]



def _hwp_rec(tag, level, payload):
    import struct

    size = len(payload)
    if size < 0xFFF:
        return struct.pack("<I", tag | level << 10 | size << 20) + payload
    return struct.pack("<I", tag | level << 10 | 0xFFF << 20) + struct.pack("<I", size) + payload


def _hwp_para(text, level):
    return _hwp_rec(0x10 + 51, level, (text + "\r").encode("utf-16-le"))


@case("한글(HWP) 본문: 문단은 한 줄, 표는 행마다 '칸 | 칸', 컨트롤 문자는 건너뛰고 긴 레코드도 읽는다")
def _():
    import struct

    from app.review.office import hwp_section_lines

    tab = "\t" + "\x00" * 7  # 탭은 8글자 차지 (인라인 컨트롤)
    field = "\x0b" + "\x00" * 7  # 확장 컨트롤(표·그림 자리)도 8글자
    cell = lambda col, row: _hwp_rec(0x10 + 56, 2, struct.pack("<hHI", 1, 0, 0) + struct.pack("<HH", col, row))  # noqa: E731
    body = b"".join([
        _hwp_para("사업명" + tab + "기말고사 간식드리미", 0),
        _hwp_para(field + "Ⅲ. 예산운영 계획서", 0),
        _hwp_rec(0x10 + 55, 1, b" lbt" + b"\x00" * 8),
        cell(0, 0), _hwp_para("구분", 3), cell(1, 0), _hwp_para("금액", 3),
        cell(0, 1), _hwp_para("간식", 3), cell(1, 1), _hwp_para("385,000", 3),
        _hwp_para("가" * 2100, 0),  # 4KB가 넘는 문단은 길이를 따로 적는다
    ])
    lines = hwp_section_lines(body)
    assert lines[:4] == ["사업명 기말고사 간식드리미", "Ⅲ. 예산운영 계획서", "구분 | 금액", "간식 | 385,000"], lines[:4]
    assert lines[4] == "가" * 2100


@case("한글(HWPX)·워드(DOCX): 표를 행 단위로 읽고, 구역은 번호순, 압축 폭탄·손상·예전 형식은 사용자 문구로 거절한다")
def _():
    import io
    import zipfile

    from app.review import office
    from app.review.extract import UnsupportedFile, extract_file

    hp = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'

    def p(text):
        return f"<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>"

    def tc(text):
        return f"<hp:tc><hp:subList>{p(text)}</hp:subList></hp:tc>"

    table = f"<hp:p><hp:run><hp:tbl><hp:tr>{tc('구분')}{tc('금액')}</hp:tr><hp:tr>{tc('간식')}{tc('385,000')}</hp:tr></hp:tbl></hp:run></hp:p>"

    def zipped(files):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, body in files.items():
                z.writestr(name, body)
        return buf.getvalue()

    hwpx = zipped({
        "Contents/section10.xml": f"<sec {hp}>{p('마지막 구역')}</sec>",
        "Contents/section0.xml": f"<sec {hp}><hp:p><hp:run><hp:t>사업명<hp:tab/>간식드리미</hp:t></hp:run></hp:p>{table}</sec>",
        "Contents/section2.xml": f"<sec {hp}>{p('둘째 구역')}</sec>",
    })
    assert office.hwpx_text(hwpx).split("\n") == ["사업명 간식드리미", "구분 | 금액", "간식 | 385,000", "둘째 구역", "마지막 구역"]
    got = extract_file("예산안.HWPX", hwpx)
    assert got.kind == "hwpx" and "간식 | 385,000" in got.text

    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    wc = lambda x: f"<w:tc><w:p><w:r><w:t>{x}</w:t></w:r></w:p></w:tc>"  # noqa: E731
    docx = zipped({"word/document.xml": f"<w:document {w}><w:body><w:p><w:r><w:t>예산안</w:t><w:tab/><w:t>2학기</w:t></w:r></w:p>"
                   f"<w:tbl><w:tr>{wc('항목')}{wc('금액')}</w:tr><w:tr>{wc('예비비')}{wc('11,058')}</w:tr></w:tbl>"
                   "<w:p><w:r><w:t>예비비는 일반회계 예산총액 10분의 1 이내로 편성함</w:t></w:r></w:p></w:body></w:document>"})
    assert extract_file("a.docx", docx).text.split("\n")[:3] == ["예산안 2학기", "항목 | 금액", "예비비 | 11,058"]

    with patch.object(office, "MAX_UNPACKED", 1000):
        try:
            office.hwpx_text(zipped({"Contents/section0.xml": f"<sec {hp}>{p('가' * 2000)}</sec>"}))
        except office.OfficeError as e:
            assert "너무 커요" in str(e)
        else:
            raise AssertionError("압축을 풀면 큰 파일을 그대로 읽었다")
        try:
            office._inflate(__import__("zlib").compress(b"0" * 5000)[2:-4], 1000)
        except office.OfficeError:
            pass
        else:
            raise AssertionError("HWP 본문 압축 폭탄을 그대로 풀었다")

    for name, data, why in [
        ("a.hwp", bytes.fromhex("d0cf11e0a1b11ae1") + b"\x00" * 600, "열지 못했어요"),
        ("a.hwpx", b"PK\x03\x04broken", "열지 못했어요"),
        ("a.xls", b"\x00" * 100, "예전 형식"),
        ("a.hwp", b"not an ole file", "확장자와 내용이 다른"),
    ]:
        try:
            extract_file(name, data)
        except UnsupportedFile as e:
            assert why in str(e), (name, str(e))
        else:
            raise AssertionError(f"{name}을 받았다")



@case("엑셀: 한셀·구글 시트 등에서 만든 파일(이름 없는 사용자 속성, 없는 서식 번호, x: 접두어)도 값을 읽는다")
def _():
    import io
    import re
    import zipfile

    from openpyxl import Workbook

    from app.review.sheets import check_workbook, workbook_text

    wb = Workbook()
    ws = wb.active
    ws["A1"], ws["B1"], ws["A2"], ws["B2"] = "항목", "금액", "간식", 385000
    buf = io.BytesIO()
    wb.save(buf)

    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            body = src.read(info)
            if info.filename == "xl/worksheets/sheet1.xml":
                text = body.decode("utf-8")
                text = re.sub(r"<c r=", '<c s="77" r=', text)  # 서식 표에 없는 번호
                text = text.replace("<sheetData>", '<cols><col min="1" max="2" width="12" style="55"/></cols><sheetData>')
                body = text.encode("utf-8")
            dst.writestr(info, body)
        dst.writestr("docProps/custom.xml", '<?xml version="1.0"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
                     'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2">'
                     '<vt:lpwstr>x</vt:lpwstr></property></Properties>')
    broken = out.getvalue()
    text = workbook_text(broken)
    assert "A2=간식" in text and "B2=385000" in text, text
    assert check_workbook(broken) == []



@case("개선 자료 가명 처리: 학번·주민번호·직책 뒤 이름·연락처는 가리고, 금액·셀 값·'회장 선거' 같은 말은 남긴다")
def _():
    from app.contrib import deidentify

    src = ("책임자: 홍길동 | 학생회장 한민유 대상자: 학생회비 납부자\n성명 | 김철수 | 12251852 | 010-1234-5678\n"
           "예금주 이영희 900101-1234567\n회장 선거 일정 · 위원장 직무대행 · 총액 12,000,000원 · B2=385000 · 2026.09.28")
    out = deidentify(src)
    for leaked in ("홍길동", "한민유", "김철수", "12251852", "010-1234-5678", "이영희", "900101-1234567"):
        assert leaked not in out, (leaked, out)
    for kept in ("회장 선거", "위원장 직무대행", "12,000,000원", "B2=385000", "2026.09.28", "대상자: 학생회비 납부자"):
        assert kept in out, (kept, out)
    assert out.count("[이름]") >= 3 and "[학번]" in out and "[주민번호]" in out, out  # 등록 실명은 ○○○로 먼저 가려진다


@case("개선 자료: 허락(contribute)한 요청만 가명 처리해 보관, 고친 값은 본인 자료에만 붙고, 본인이 모두 지울 수 있다")
def _():
    import io
    import json
    import zipfile

    from app import auth
    from app import db as app_db

    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    para = lambda x: f"<w:p><w:r><w:t>{x}</w:t></w:r></w:p>"  # noqa: E731
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w:document {w}><w:body>{para('기말고사 간식드리미 예산안 책임자 학생회장 홍길동 12251852')}"
                   f"{para('간식 기프티콘 7,700원 × 50개 = 385,000원')}{para('총액 385,000원 예비비 0원 수입 학생회비 385,000원')}</w:body></w:document>")
    docx = buf.getvalue()

    def login(sub):
        c = _https_client()
        with patch.object(auth, "_google_signing_key", lambda _t: _KEY.public_key()):
            c.post("/api/auth/google", json={"credential": _make_token(sub=sub, email=f"{sub}@inha.edu")}, headers=_ORIGIN)
        return c

    a, b = login("contrib-a"), login("contrib-b")
    plain = a.post("/api/review/extract?filename=a.docx", content=docx, headers=_ORIGIN)
    assert plain.status_code == 200 and plain.json()["contribution_id"] is None, plain.text
    assert a.get("/api/contributions/mine").json() == {"count": 0}

    got = a.post("/api/review/extract?filename=홍길동 예산안.docx&contribute=true", content=docx, headers=_ORIGIN).json()
    cid = got["contribution_id"]
    assert cid
    with app_db._connect() as conn:
        row = dict(conn.execute("SELECT * FROM contributions WHERE id = ?", (cid,)).fetchone())
    stored = row["text"] + row["source"] + row["result"]
    assert "홍길동" not in stored and "12251852" not in stored and "385,000" in row["text"], stored
    assert row["consent"] and row["corrected"] is None

    doc = got["doc"] | {"title": "고친 사업명"}
    # 남의 자료에는 붙지 않는다
    b.post("/api/review/check", json={"doc": doc, "source": [], "contribution_id": cid}, headers=_ORIGIN)
    with app_db._connect() as conn:
        assert conn.execute("SELECT corrected FROM contributions WHERE id = ?", (cid,)).fetchone()[0] is None
    assert a.post("/api/review/check", json={"doc": doc, "source": [], "contribution_id": cid}, headers=_ORIGIN).status_code == 200
    with app_db._connect() as conn:
        corrected = json.loads(conn.execute("SELECT corrected FROM contributions WHERE id = ?", (cid,)).fetchone()[0])
    assert corrected["doc"]["title"] == "고친 사업명"

    assert a.post("/api/plan/draft?contribute=true", json=_PLAN_IN, headers=_ORIGIN).status_code == 200
    minutes = {"text": "- 회의 결과 축제 부스 운영을 가결함. 회장 홍길동이 금요일까지 업체 연락", "held_on": "2026-09-01"}
    assert a.post("/api/minutes?contribute=true", json=minutes, headers=_ORIGIN).status_code == 200
    assert a.post("/api/minutes", json=minutes, headers=_ORIGIN).status_code == 200  # 허락하지 않은 요청은 보관하지 않는다
    assert a.get("/api/contributions/mine").json() == {"count": 3}
    with app_db._connect() as conn:
        kinds = [r[0] for r in conn.execute("SELECT kind FROM contributions WHERE user_id = (SELECT id FROM users WHERE google_sub = 'contrib-a') ORDER BY id")]
        texts = "".join(r[0] for r in conn.execute("SELECT text FROM contributions"))
    assert kinds == ["review", "plan", "minutes"] and "홍길동" not in texts

    assert a.delete("/api/contributions/mine").status_code == 403  # Origin 없음
    assert a.delete("/api/contributions/mine", headers=_ORIGIN).json() == {"deleted": 3}
    assert a.get("/api/contributions/mine").json() == {"count": 0}
    assert client.get("/api/contributions").status_code == 401
    assert client.get("/api/contributions", headers=AUTH).status_code == 200



@case("다가오는 일정: 관리자만 고치고, 날짜순 정렬, 지난 일정은 공개 조회에서 빠지고, 링크는 사이트 안 경로만")
def _():
    from datetime import date

    from app import events

    body = {"events": [
        {"date": "2026-12-05", "title": " 총대의원회  5차 정기총회 ", "href": "/plan"},
        {"date": "2026-11-20", "title": "지난 임시총회"},
        {"date": "2026-12-01", "title": "총회 자료 제출 마감"},
    ]}
    assert client.put("/api/settings/events", json=body).status_code == 401
    saved = client.put("/api/settings/events", json=body, headers=AUTH).json()["events"]
    assert [e["date"] for e in saved] == ["2026-11-20", "2026-12-01", "2026-12-05"] and saved[2]["title"] == "총대의원회 5차 정기총회"
    assert [e["title"] for e in events.upcoming(date(2026, 12, 1))] == ["총회 자료 제출 마감", "총대의원회 5차 정기총회"]
    assert events.upcoming(date(2026, 12, 6)) == []
    assert client.put("/api/settings/events", json={"events": [{"date": "2026-12-05", "title": "x", "href": "https://evil.example"}]}, headers=AUTH).status_code == 422
    assert client.put("/api/settings/events", json={"events": [{"date": "2026-12-05", "title": "x"}] * 31}, headers=AUTH).status_code == 422
    assert client.get("/api/events").status_code == 200
    assert client.put("/api/settings/events", json={"events": []}, headers=AUTH).json() == {"events": []}
    assert client.get("/api/settings/events", headers=AUTH).json() == {"events": []}


@case("기획 증빙: 파는 음식 재료는 보건증 사본·먹거리 점검표로, 상영·음원은 이용 허락서·저작권 점검표로 잇는다")
def _():
    from app.plan.evidence import papers_for

    kind, papers, topic = papers_for("떡볶이 조리 재료비")
    assert "조리·판매 인원 보건증 사본" in papers and topic == "liquor", (kind, papers, topic)
    assert papers_for("영화 상영권")[2] == "copyright"
    assert papers_for("간식 기프티콘")[2] is None  # 나눠 주는 간식은 판매가 아니다


@case("총회 자료에서 찾은 표기 오류: 표 한 줄의 식↔금액, 금액 표기 오기, 연도 없는 날짜의 요일, 두 자리 연도 — 나열·소수·식 여러 개는 지나간다")
def _():
    from app.review.textcheck import check_number_format, check_row_formulas, check_schedule_years, check_weekdays

    swapped = "콜라(맘스터치) | 2,000*90 | 171,000원 | 과자치비\n콜라(행컵) | 1,900*90 | 180,000원 | 과자치비"
    assert [f.code for f in check_row_formulas(swapped)] == ["row_formula", "row_formula"]
    for ok in ("진행비 | 간식 구매 (6,000원*60명) | 360,000원 | 자치비", "예비비 | 140,000*0.1 | 14,000원",
               "- | 20,000*2 10,000*1 | 50,000 | 학생회비", "구분 | 17원/명*450 *15회 | 114,750원", "상품 | 5700x20 | 114,000원"):
        assert check_row_formulas(ok) == [], ok

    bad = {f.title.split("'")[1] for f in check_number_format("미니게임 250.000원 · 예비비 \\480,00 · 물 4,0000원 · 간식 9,50원")}
    assert bad == {"250.000원", "480,00", "4,0000", "9,50원"}, bad
    assert check_number_format("지하 1,2 층 · 별첨 3,4 · 11,12월 · 1,2등 · 3.5% · 250,000원") == []

    assert [f.title for f in check_weekdays("일시 2026년 11월 3일\n체전 11월 30일 (화)")] == ["2026.11.30은 화요일이 아니라 월요일이에요"]
    assert check_weekdays("11월 30일 (화)") == []  # 연도를 모르면 판단하지 않는다
    assert [f.title for f in check_schedule_years("작성 2026. 9. 1.\n시기 | 25. 10. 5.(일)")] == ["사업 연도(2025)가 문서 연도(2026)와 달라요"]


@case("예비비: 총액 대비 10% 초과는 위반 소지, 총액 안이지만 사업비 대비 10% 초과는 확인 필요, 총액에 빠진 예비비는 따로 알린다")
def _():
    from app.review.models import BudgetDoc, Line
    from app.review.rules import check_budget

    def doc(lines, total):
        return BudgetDoc(title="t", expense=[Line(item=i, amount=a) for i, a in lines], expense_total=total)

    codes = lambda d: [f.code for f in check_budget(d)]  # noqa: E731
    assert codes(doc([("상품", 3_500_000), ("예비비", 383_500)], 3_883_500)) == ["reserve_project"]  # 9.9% / 11.0%
    assert codes(doc([("간식", 84_800), ("예비비", 15_200)], 100_000)) == ["reserve"]  # 15.2%
    assert codes(doc([("간식", 360_000), ("예비비", 36_000)], 396_000)) == []  # 사업비의 정확히 10%
    assert codes(doc([("간식", 360_000), ("예비 물품", 36_000)], 396_000)) == []  # '예비 물품'은 예비비가 아니다
    outside = check_budget(doc([("카라티", 1_118_300), ("예비비", 111_830)], 1_118_300))
    assert [f.code for f in outside] == ["reserve_outside_total"] and "총액에 들어 있지 않아요" in outside[0].title


@case("기획 일정: 모델이 부호를 반대로 줘도 준비는 시작 전, 마무리는 끝난 뒤, 진행은 기간 안 · 준비는 오늘보다 과거로 가지 않고, 인준은 적은 회의일")
def _():
    from datetime import date

    from app.plan import build
    from app.plan.build import assemble
    from app.plan.models import DraftStep, PlanIn

    req = PlanIn(**{**_PLAN_IN, "start": "2026-12-10", "end": "2026-12-12"})
    steps = [
        DraftStep(phase="준비", text="홍보", days_before=-14),
        DraftStep(phase="준비", text="구매", days_before=0),
        DraftStep(phase="진행", text="나눔", days_before=-1),
        DraftStep(phase="마무리", text="정산", days_before=7),
    ]
    with patch.object(build, "today_kst", return_value=date(2026, 11, 1)):
        got = {s.text: str(s.date) for s in assemble(req, _plan_draft(steps=steps), "ai").steps}
    assert got == {"홍보": "2026-11-26", "구매": "2026-12-09", "나눔": "2026-12-11", "정산": "2026-12-19"}, got
    with patch.object(build, "today_kst", return_value=date(2026, 11, 28)):
        got = {s.text: str(s.date) for s in assemble(req, _plan_draft(steps=steps), "ai").steps}
    assert got["홍보"] == "2026-11-28", got  # 14일 전(11.26)은 이미 지났다 — 오늘로
    req = PlanIn(**{**_PLAN_IN, "start": "2026-12-10", "end": None, "meeting_date": "2026-11-30"})
    with patch.object(build, "today_kst", return_value=date(2026, 11, 1)):
        plan = assemble(req, _plan_draft(steps=[DraftStep(phase="준비", text="사업 계획·예산 인준", days_before=14)]), "ai")
    assert str(plan.steps[0].date) == "2026-11-30", plan.steps

@case("예산 세부 내역 판단 자료: 사업별·묶음(월·상시)·학기 합계를 단계마다 다시 더하고, 맞는 표는 조용하다")
def _():
    from app.review.textcheck import check_subtotals

    ok = "\n".join([
        "시기 | 사업명 | 구분 | 세부 내용 | 금액 | 비고",
        "10월 | 에너지의 날 | 일반사업비 | 숙소 지원비 | 800,000원 | 학생회비",
        "사업별 총 비용 | 800,000원",
        "10월 총 사업 진행 비용 | 800,000원",
        "11월 | 간식드리미 | 일반사업비 | 간식 (45개 * 6000원) | 270,000원 | 인당 6000원 45명 기준",
        "사업별 총 비용 | 270,000원",
        "상시 | 사무용품 | 사무경상비 | 사무용품 | 30,000원 | 학생회비",
        "멘토멘티 | 일반사업비 | 상품 | 120,000원 | 학생회비",
        "상시사업 총 사업 진행 비용 | 150,000원",
        "2026년도 2학기 총 사업 진행 비용 | 1,220,000원",
    ])
    assert check_subtotals(ok) == [], [f.title for f in check_subtotals(ok)]
    bad = ok.replace("사업별 총 비용 | 270,000원", "사업별 총 비용 | 300,000원").replace("1,220,000원", "1,250,000원")
    got = [f.title for f in check_subtotals(bad)]
    assert got == ["사업별 총 비용이 아래 단계 합과 30,000원 달라요"], got  # 학기 합은 적힌 사업 합계(300,000)로 맞으니 한 번만


@case("예산표 블록: 줄 합 + 예비비 = 총액, 이름 없는 소계는 단계별로, 식으로 적은 금액·병합 칸을 읽고, 일부 재원 총액·수입표는 비교하지 않는다")
def _():
    from app.review.blocks import check_block_totals, parse_blocks

    wrong = "\n".join([
        "산공인의 밤",
        "시기 | 11월 中",
        "예산운영 | 구분 | 세부내용(개수) | 비용 | 예산 출처",
        "답례품비 | 답례품 (10개 예정) | 10 * 50,000원 = 500,000원 | 자치비",
        "예비비 | 50,000원",
        "총액 | 555,000원",
    ])
    got = check_block_totals(wrong)
    assert [f.title for f in got] == ["산공인의 밤 예산표 총액이 줄 합과 5,000원 달라요"], [f.title for f in got]
    assert parse_blocks(wrong)[0].project == "산공인의 밤"
    split = "예산 내용 | 구분 | 가격 | 예산 출처 / 컨셉 소품 | 200,000 | 교비 / 상품비 | 100,000 | 교비 / 예비비 | 30,000 | 교비 / 330,000 / 가게 대관료 | 400,000 | 자치비 / 예비비 | 40,000 | 자치비 / 440,000 / 총 합계 | 770,000"
    assert check_block_totals(split) == []
    sub_bad = [f for f in check_block_totals(split.replace("/ 440,000 /", "/ 450,000 /").replace("770,000", "780,000"))]
    assert [f.detail for f in sub_bad] == ["줄 합 440,000원 = 440,000원 · 적힌 소계 450,000원"], [f.detail for f in sub_bad]
    for ok in (
        "구분 | 세부내용 | 비용 | 예산 출처\n숙소 | 1,300,000원 | 자치비\n예비비 | 130,000원\n총액 (학과 지원금 제외) | 1,300,000원",
        "구분 | 세부내용 | 비용 | 예산 출처\n숙소 | 800,000원 | 자치비\n버스 | 1,012,000원 | 각출비\n총액 | 800,000원(자치비)+1,012,000원(각출비)",
        "항목 | 금액 | 비고\n자치비 | 4,592,536원 | 이월\nmt숙소비에 사용 | 500,000원 | -\n합계 | 4,092,536원 | -",
        "구분 | 세부내용 | 비용 | 예산 출처\n상금 | 1,500,000원 | 자치비\n총액 | 1,650,000원 (예비비 10% 포함)",
    ):
        assert check_block_totals(ok) == [], ok


@case("표끼리 대조: 같은 사업의 금액이 세부 사업 계획서·지출표·판단 자료에서 다르면 알리고, 같은 이름이 두 번이면 건너뛴다")
def _():
    from app.review.blocks import check_cross_tables

    doc = "\n".join([
        "산공인의 밤",
        "예산운영 | 구분 | 세부내용(개수) | 비용 | 예산 출처",
        "답례품비 | 답례품 | 500,000원 | 자치비",
        "예비비 | 55,000원",
        "총액 | 555,000원",
        "2) 지출",
        "관 | 금액 | 비고",
        "사업비 | 2,400,000원 | 일일호프",
        "500,000원 | 제4회 산공인의 밤",
        "합계 | 2,900,000원",
    ])
    got = check_cross_tables(doc)
    assert [f.detail for f in got] == ["세부 사업 계획서 555,000원 · 지출표 500,000원"], [f.detail for f in got]
    twice = "관 | 금액 | 비고\n사업비 | 396,000원 | 간식드리미\n396,000원 | 간식드리미\n합계 | 792,000원\n" \
            "시기 | 사업명 | 구분 | 세부 내용 | 금액 | 비고\n10월 | 중간 간식드리미 | 사업비 | 간식 | 360,000원\n" \
            "11월 | 기말 간식드리미 | 사업비 | 간식 | 360,000원\n사업별 총 비용 | 792,000원 | -"
    assert check_cross_tables(twice) == []


@case("엑셀 재원별 열: 과 지원금·학생회비·기금의 합이 총계와 다르면 처음 한 번만 알린다 (소계·총계로 번진 것은 묶음)")
def _():
    import io

    from openpyxl import Workbook

    from app.review.sheets import check_workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["항목", "과 지원금", "학생회비", "기금", "총계"])
    ws.append(["숙소", 2_870_000, 0, 1_000_000, 3_870_000])
    ws.append(["현수막", 0, 14_900, 0, 0])
    ws.append(["소계", 2_870_000, 14_900, 1_000_000, 3_870_000])
    buf = io.BytesIO()
    wb.save(buf)
    got = [f for f in check_workbook(buf.getvalue()) if f.code == "fund_columns"]
    assert [f.title for f in got] == ["현수막: 재원별 금액 합이 총계와 14,900원 달라요"], [f.title for f in got]


@case("대체 추출(AI 실패·목업): 표 줄을 값 모양으로 읽고, 병합 칸·이름 없는 소계·뒤에 또 나온 같은 표·못 읽은 금액을 안전하게 다룬다")
def _():
    from app.review.heuristic import heuristic_extract
    from app.review.rules import check_budget

    text = "\n".join([
        "2) 지출",
        "구분 | 사업 | 항목 | 금액 | 비고",
        "미화 | 사무실 미화 | 바닥 청소 | 300,000 | 자치비",
        "예비비 | 30,000",
        "330,000원",
        "관 | 금액 | 비고",
        "500,000원 | 제4회 산공인의 밤",
        "합계 | 830,000원",
        "3) 수입/지출 총계",
        "지 출 금 | 830,000원",
        "2) 지출",
        "사업비 | 9,999,000원 | 다른 회의 자료",
        "합계 | 9,999,000원",
        "3) 수입/지출 총계",
        "지 출 금 | 9,999,000원",
    ])
    doc = heuristic_extract("a.hwp", text)
    assert [(l.item, l.amount) for l in doc.expense] == [("바닥 청소", 300_000), ("예비비", 30_000), ("제4회 산공인의 밤", 500_000)], doc.expense
    assert doc.expense_total == 830_000 and doc.summary_expense == 830_000
    assert [f.code for f in check_budget(doc)] == []

    single = "간식드리미\n예산운영 | 구분 | 세부내용(개수) | 비용 | 예산 출처\n진행비 | 간식 구매 | 360,000원 | 자치비\n홍보비 | 포스터 | 견적 후 결정 | 자치비\n예비비 | 36,000원\n총액 | 420,000원"
    doc = heuristic_extract("b.hwp", single)
    assert doc.expense_total is None and any(l.amount is None for l in doc.expense), doc  # 못 읽은 줄이 있으면 총액과 비교하지 않는다
    assert check_budget(doc) == []


@case("유료 호출 기록(metered): 실패해도 그때까지 쓴 비용이 남고, 유료 호출 전 오류(free)는 기록·한도에서 빠진다")
def _():
    from unittest.mock import patch

    from app import quota

    user = {"id": 1, "role": "member"}
    rows = []
    with patch.object(quota.db, "record_metric", side_effect=lambda **kw: rows.append(kw)), \
            patch.object(quota.db, "count_review_today", return_value=0):

        async def paid_then_fail():
            async with quota.metered(user, "review-test", 5, "한도") as usage:
                usage.add({"usage": {"input_tokens": 1000, "output_tokens": 100}})
                raise RuntimeError("overloaded")

        async def free_error():
            async with quota.metered(user, "review-test", 5, "한도", free=(ValueError,)):
                raise ValueError("지원하지 않는 파일")

        for coro, exc in ((paid_then_fail, RuntimeError), (free_error, ValueError)):
            try:
                _run(coro())
            except exc:
                pass
            else:
                raise AssertionError("오류가 그대로 올라가야 한다")
    assert len(rows) == 1 and rows[0]["status"] == "error" and rows[0]["cost_usd"] > 0, rows
    assert rows[0]["input_tokens"] == 1000 and "overloaded" in rows[0]["error"]
    assert not quota._inflight, "끝나면 진행 중 수에서 빠진다"


@case("HWP 크기 상한: 비압축 구역·OLE 중복 참조로 같은 본문을 여러 번 읽게 해도 40MB 상한에서 멈춘다 (Codex 재현)")
def _():
    import io
    import struct

    import olefile

    from app.review.office import MAX_UNPACKED, OfficeError, hwp_text

    E, F, N, size = 0xFFFFFFFE, 0xFFFFFFFF, 41, 1024 * 1024
    nd = (N + 6) // 4
    nf = (nd + 8 + size // 512 + 126) // 127
    fh = nf + nd
    body = fh + 8
    fat = [0xFFFFFFFD] * nf + list(range(nf + 1, nf + nd)) + [E] + list(range(fh + 1, fh + 8)) + [E] \
        + list(range(body + 1, body + size // 512)) + [E]
    fat += [F] * (nf * 128 - len(fat))
    header = bytes.fromhex("d0cf11e0a1b11ae1") + bytes(16) + struct.pack("<HHHHH", 62, 3, 65534, 9, 6) + bytes(6) \
        + struct.pack("<IIIIIIIII", 0, nf, nf, 0, 4096, E, 0, E, 0) + struct.pack("<109I", *list(range(nf)), *([F] * (109 - nf)))

    def entry(name, kind, right=F, child=F, start=E, length=0):
        n = (name + "\0").encode("utf-16-le")
        return n.ljust(64, b"\0") + struct.pack("<HBBIII", len(n), kind, 1, F, right, child) + bytes(36) + struct.pack("<IQ", start, length)

    directory = entry("Root Entry", 5, child=1) + entry("FileHeader", 2, right=2, start=fh, length=4096) + entry("BodyText", 1, child=3)
    directory += b"".join(entry("Section" + str(i), 2, right=4 + i if i < N - 1 else F, start=body, length=size) for i in range(N))
    directory = directory.ljust(nd * 512, b"\0")
    para = "budget test\r".encode("utf-16-le")
    tail = struct.pack("<I", 67 | (len(para) << 20)) + para
    section = struct.pack("<II", 1023 | (4095 << 20), size - 8 - len(tail)) + bytes(size - 8 - len(tail)) + tail
    data = header + struct.pack("<" + str(len(fat)) + "I", *fat) + directory + bytes(4096) + section
    with olefile.OleFileIO(io.BytesIO(data)) as o:
        assert sum(o.get_size(p) for p in o.listdir() if p[0] == "BodyText") > MAX_UNPACKED  # 업로드는 1MB, 선언 본문은 41MB
    try:
        hwp_text(data)
    except OfficeError as e:
        assert "너무 커요" in str(e)
    else:
        raise AssertionError("상한을 넘는 본문을 끝까지 읽었다")


@case("개선 자료 가명 처리: 참석자 명단·성명 칸·호칭에서 찾은 이름은 본문과 결과 어디서든 가린다 (Codex 재현)")
def _():
    from app.contrib import _deidentify_obj, deidentify, listed_names

    src = "참석자: 가나다, 라마바\n- 가나다가 행사 준비를 맡음\n사파아 학우가 질문함"
    names = listed_names(src)
    assert {"가나다", "라마바", "사파아"} <= names, names
    out = deidentify(src, names)
    assert "가나다" not in out and "라마바" not in out and "사파아" not in out, out
    assert "행사 준비를 맡음" in out  # 이름이 아닌 내용은 남는다
    res = _deidentify_obj({"decisions": ["가나다가 행사 준비를 맡음"], "todos": [{"owner": "라마바"}]}, names)
    assert "가나다" not in str(res) and "라마바" not in str(res), res
    # 직책·흔한 말은 이름으로 모으지 않는다
    assert not listed_names("참석: 학생회장, 부회장, 사무국장\n명단: 확인") & {"학생회장", "부회장", "사무국장", "확인"}


@case("소계·표끼리 대조 오탐: 못 읽은 금액('10만원')이 있으면 그 단계는 비교하지 않고, 일부 재원 총액은 사업 전체와 대조하지 않는다 (Codex 재현)")
def _():
    from app.review.blocks import check_block_totals, check_cross_tables
    from app.review.textcheck import check_subtotals

    s = "시기 | 사업명 | 구분 | 세부 내용 | 금액 | 비고\n11월 | 행사 | 사업비 | 간식 | 100,000원 | 학생회비\n행사 | 사업비 | 음료 | 10만원 | 학생회비\n사업별 총 비용 | 200,000원"
    assert check_subtotals(s) == []
    wrong = s.replace("200,000원", "250,000원").replace("10만원", "100,000원")
    assert [f.code for f in check_subtotals(wrong)] == ["subtotal"]  # 다 읽히면 여전히 잡는다
    partial = (
        "간식드리미\n구분 | 세부내용 | 비용 | 예산 출처\n간식 | 간식 구매 | 800,000원 | 자치비\n음료 | 음료 구매 | 200,000원 | 각출비\n"
        "총액(자치비) | 800,000원\n2) 지출\n관 | 금액 | 비고\n사업비 | 1,000,000원 | 간식드리미\n합계 | 1,000,000원"
    )
    assert check_block_totals(partial) == [] and check_cross_tables(partial) == []



@case("재검토 반영: 표 '성명' 칸 아래 이름·고친 값의 같은 이름도 가리고, 못 읽은 사업 합계는 학기 합계 비교를 멈추고, 묶인 위치도 가린다")
def _():
    import json
    from unittest.mock import patch

    from app import contrib
    from app.review.models import Finding
    from app.review.service import merge
    from app.review.textcheck import check_subtotals

    saved = {}
    with patch.object(contrib.db, "add_contribution", side_effect=lambda **kw: saved.update(kw) or 7):
        contrib.save(1, "review", "명단", "성명 | 학번\n가나다 | 12251852\n라마바 | 12251853", {"title": "가나다 지원금"})
    assert "가나다" not in saved["text"] + saved["result"] and "라마바" not in saved["text"], saved
    keys = saved["name_keys"]
    with patch.object(contrib.db, "contribution_name_keys", return_value=keys), \
            patch.object(contrib.db, "set_contribution_correction", side_effect=lambda cid, uid, body: body) as put:
        contrib.attach_correction(1, 7, {"doc": {"title": "가나다지원금 정산", "note": "라마바 확인"}})
    body = put.call_args.args[2]
    assert "가나다" not in body and "라마바" not in body and "정산" in body, body
    assert "가나다" not in keys and json.loads(keys), keys  # 이름 대신 열쇠만 남는다
    with patch.object(contrib.db, "contribution_name_keys", return_value=None):
        assert contrib.attach_correction(2, 7, {"doc": {}}) is False  # 남의 자료

    s = ("시기 | 사업명 | 구분 | 세부 내용 | 금액 | 비고\n11월 | 행사1 | 사업비 | 간식 | 100,000원 | 학생회비\n사업별 총 비용 | 10만원\n"
         "12월 | 행사2 | 사업비 | 간식 | 50,000원 | 학생회비\n사업별 총 비용 | 50,000원\n2학기 총 사업 진행 비용 | 150,000원")
    assert check_subtotals(s) == []

    f = lambda w: Finding(code="unit_qty", level="보완 필요", title="단가 × 수량이 금액과 달라요", where=w)  # noqa: E731
    with patch("app.review.service.mask_text", side_effect=lambda x: (x or "").replace("홍길순", "○○○")):
        out = merge([f("홍길순 2행"), f("홍길순 3행")])
    assert "홍길순" not in out[0].where and out[0].where.count("○○○") == 2, out[0].where



@case("CSRF: 로그인(쿠키) 라우터의 모든 쓰기 경로는 라우터 단위 Origin 검사를 거치고, 앱에 바로 붙은 쓰기 경로는 익명 공개 3개뿐이다")
def _():
    from app import auth, contrib, ledger
    from app.auth import origin_guard
    from app.minutes import api as minutes_api
    from app.plan import api as plan_api
    from app.review import api as review_api

    writes = 0
    for m in (auth, contrib, ledger, minutes_api, plan_api, review_api):
        for route in m.router.routes:
            methods = getattr(route, "methods", set()) - {"GET", "HEAD", "OPTIONS"}
            if not methods:
                continue
            guards = [d.dependency for d in getattr(route, "dependencies", [])]
            assert origin_guard in guards, f"{sorted(methods)} {route.path}: Origin 검사 없음"
            writes += 1
    assert writes >= 11, writes
    direct = {getattr(r, "path", "") for r in main.app.routes if getattr(r, "methods", set()) - {"GET", "HEAD", "OPTIONS"}}
    assert direct == {"/api/chat", "/api/feedback", "/api/track"}, direct  # 쿠키 경로는 라우터에 — 여기 새로 붙이면 Origin 검사가 빠진다
    # 읽기 요청은 Origin 없이도 된다 (검사는 쓰기만)
    assert client.get("/api/events").status_code == 200



@case("예산표 판독 규칙 한 곳: 표 종류는 Block.kind 하나로 정하고, 판단 자료 소계도 예산표와 같은 줄 해석(만원)을 쓰고, '(교비지원금)' 총액도 일부 재원으로 본다")
def _():
    from app.review.blocks import check_block_totals, check_cross_tables, parse_blocks
    from app.review.textcheck import check_subtotals

    kinds = {
        "관 | 금액 | 비고\n사업비 | 1,000원 | 간식": "expense",
        "시기 | 사업명 | 구분 | 세부 내용 | 금액 | 비고\n11월 | 행사 | 사업비 | 간식 | 1,000원 | -": "detail",
        "항목 | 금액 | 비고\n자치비 | 1,000원 | 이월": "list",
        "구분 | 세부내용 | 비용 | 예산 출처\n간식 | 간식 | 1,000원 | 자치비": "budget",
    }
    for text, want in kinds.items():
        assert [b.kind for b in parse_blocks(text)] == [want], (text, want)

    # 판단 자료의 사업별 합계를 '10만원'으로 적어도 읽어서 비교한다
    detail = "시기 | 사업명 | 구분 | 세부 내용 | 금액 | 비고\n11월 | 행사 | 사업비 | 간식 | {item} | 학생회비\n사업별 총 비용 | 10만원"
    assert check_subtotals(detail.format(item="100,000원")) == []
    wrong = check_subtotals(detail.format(item="90,000원"))
    assert [f.code for f in wrong] == ["subtotal"] and "10,000원" in wrong[0].title, [f.title for f in wrong]

    # '총액(교비지원금)'은 일부 재원만 더한 총액 — 줄 합·지출표 전체 금액과 비교하지 않는다
    partial = (
        "간식드리미\n구분 | 세부내용 | 비용 | 예산 출처\n간식 | 간식 구매 | 800,000원 | 교비지원금\n음료 | 음료 구매 | 200,000원 | 자치비\n"
        "총액(교비지원금) | 800,000원\n2) 지출\n관 | 금액 | 비고\n사업비 | 1,000,000원 | 간식드리미\n합계 | 1,000,000원"
    )
    assert check_block_totals(partial) == [] and check_cross_tables(partial) == []



@case("파일럿 반영(대체 추출): 끝 칸이 빈 표 줄('대관료 | 200,000원 | ')도 읽고, 항목은 금액 바로 왼쪽 칸 — 산출식·비고는 항목으로 쓰지 않고, 지출표의 관 이름이면 비고의 사업명")
def _():
    from app.review.blocks import cells_of
    from app.review.heuristic import heuristic_extract
    from app.review.rules import check_budget

    assert cells_of("합계 | | 1,700,000원 |") == ["합계", "", "1,700,000원", ""]
    text = "2) 지출\n구분 | 항목 | 금액 | 비고\n사업비 | 간식 | 1,200,000원 | 15,000원 * 80명\n사업비 | 대관료 | 200,000원 | \n예비비 | 예비비 | 300,000원 | \n합계 | | 1,700,000원 | "
    doc = heuristic_extract("t.docx", text)
    assert [(l.item, l.amount) for l in doc.expense] == [("간식", 1_200_000), ("대관료", 200_000), ("예비비", 300_000)], doc.expense
    assert doc.expense_total == 1_700_000 and "reserve" in [f.code for f in check_budget(doc)]
    jichul = heuristic_extract("j.hwp", "2) 지출\n관 | 금액 | 비고\n사업비 | 2,400,000원 | 일일호프\n합계 | 2,400,000원")
    assert [l.item for l in jichul.expense] == ["일일호프"], jichul.expense


@case("파일럿 반영(현금·마스킹): '현금 대신 계좌이체'·'현금 지급 금지'는 현금 지출이 아니고, 이어 붙은 다른 문장의 금액을 섞지 않는다 · 엑셀 소수는 전화번호로 가리지 않는다")
def _():
    from app.privacy import mask_text
    from app.review.textcheck import check_cash

    assert check_cash("비고 | 예산 상한 300,000원을 초과하므로 조정 / ※ 사례금은 현금 대신 계좌이체로 지급할 것") == []
    assert check_cash("상금 200,000원은 현금 지급 금지, 계좌이체") == []
    for real in ("강사 사례금 300,000원 현금 지급", "사례금 | 300,000원 | 현금", "운영비 200,000원을 현금으로 받아 지출했어요. 현금영수증 첨부"):
        assert [f.code for f in check_cash(real)] == ["cash"], real
    assert mask_text("B3=0.07450192837465123") == "B3=0.07450192837465123"
    assert "5678" not in mask_text("연락처 010-1234-5678") and "5678" not in mask_text("전화01012345678")


@case("파일럿 반영(규정 메모): 문서 원문에 없는 구절을 근거로 한 메모(일반론)는 내보내지 않는다")
def _():
    from app.agents import claude_agents
    from app.review import service
    from app.review.models import BudgetDoc
    from app.review.service import _Note, _Notes

    async def fake(system, user, schema, **kw):
        return _Notes(notes=[
            _Note(level="확인 필요", title="주류 구매 재원을 확인해 주세요", quote="맥주 20캔  주류"),
            _Note(level="보완 필요", title="증빙 계획이 없어요", quote="영수증 원본 보관 계획"),
            _Note(level="확인 필요", title="인용 없는 메모", quote=""),
        ])

    text = "사업비 | 맥주 20캔 | 주류 | 80,000원"
    with patch.object(service, "MOCK_MODE", False), patch.object(claude_agents, "structured", fake), \
            patch.object(service, "_regulations", lambda _t: []):
        found, _ = _run(service.notes(BudgetDoc(title="t"), text, []))
    assert [f.title for f in found] == ["주류 구매 재원을 확인해 주세요"], [f.title for f in found]



@case("교차 리뷰 반영: 진짜 현금 지출은 문장이 나뉘거나 '불가피·하지 않으면·안전하게'가 있어도 잡고, 마침표 뒤 전화번호도 가린다")
def _():
    from app.privacy import mask_text
    from app.review.textcheck import check_cash

    for real in ("강사 사례금 300,000원 ※ 현금 지급", "버스 대절 | 현금 지급 / 학생 수납금에서 지출 | 500,000원", "대관료 400,000원. 현금 결제",
                 "강사 사례금 300,000원 현금 지급 불가피", "사례금 | 300,000원 | 현금 지급(계좌이체 불가)",
                 "상금 200,000원을 현금으로 지급하지 않으면 참여율이 낮음", "현금은 안전하게 봉투에 담아 강사에게 300,000원 지급"):
        assert [f.code for f in check_cash(real)] == ["cash"], real
    assert check_cash("예산 상한 300,000원을 초과 / ※ 사례금은 현금 대신 계좌이체로 지급") == []
    for phone in ("H.P.01012345678", "연락처.010 1234 5678", "총무(M.01012345678)", "문의.010.1234.5678"):
        assert "5678" not in mask_text(phone), phone


@case("교차 리뷰 반영(기획 일정): 인준 단계만 적은 회의일로, 인준 뒤 준비는 회의일 이후, 회의일이 시작일 이후여도 지어낸 날짜를 쓰지 않는다")
def _():
    from datetime import date

    from app.plan import build
    from app.plan.build import assemble
    from app.plan.models import DraftStep, PlanIn

    steps = [
        DraftStep(phase="준비", text="인준 자료(사업안·예산안) 작성", days_before=20),
        DraftStep(phase="준비", text="사업 계획·예산 인준", days_before=14),
        DraftStep(phase="준비", text="물품 구매", days_before=3),
        DraftStep(phase="준비", text="홍보", days_before=10),
    ]
    with patch.object(build, "today_kst", return_value=date(2026, 11, 1)):
        plan = assemble(PlanIn(**{**_PLAN_IN, "start": "2026-12-20", "end": None, "meeting_date": "2026-12-18"}), _plan_draft(steps=steps), "ai")
        got = {s.text: str(s.date) for s in plan.steps}
        assert got["사업 계획·예산 인준"] == "2026-12-18" and got["인준 자료(사업안·예산안) 작성"] == "2026-11-30", got
        assert got["물품 구매"] == "2026-12-18" and got["홍보"] == "2026-12-18", got  # 인준 전에 구매·홍보하지 않는다
        late = assemble(PlanIn(**{**_PLAN_IN, "start": "2026-12-20", "end": None, "meeting_date": "2026-12-22"}), _plan_draft(steps=steps), "ai")
    assert {s.text: str(s.date) for s in late.steps}["사업 계획·예산 인준"] == "2026-12-22"  # 적은 날짜 그대로 (사후 인준은 점검이 잡는다)


@case("교차 리뷰 반영(메모 인용·대체 추출): 따옴표·말줄임·쌍점이 달라도 원문 구절이면 인정하고 너무 짧은 인용은 거절 · 표 가운데 '…합계' 줄은 항목이 아니다 · 이름에 식이 든 항목")
def _():
    from app.review.heuristic import heuristic_extract
    from app.review.service import _quoted, _squash_text

    source = _squash_text("사업비 | 주류 구매 | 맥주 20박스 | 600,000원 | 학생회비\n강사 사례금은 현금으로 지급함\n문화상품권 10,000원권을 지급함")
    for q in ("'주류 구매'", "강사 사례금은 “현금”으로", "주류 구매: 맥주 20박스", "문화상품권 10,000원권을 지급함…", "주류 구매 … 학생회비"):
        assert _quoted(q, source), q
    for q in ("원", "|", "", "없는 문장입니다"):
        assert not _quoted(q, source), q
    income = heuristic_extract("i.docx", "1) 수입\n항목 | 금액 | 비고\n참가비 | 2,000,000원 | \n임원 참가비 | 300,000원 | \n수납금 합계 | 2,300,000원 | \n학생회비 | 1,000,000원 | \n합계 | 3,300,000원 | ")
    assert [l.item for l in income.income] == ["참가비", "임원 참가비", "학생회비"] and income.income_total == 3_300_000, income.income
    named = heuristic_extract("n.docx", "2) 지출\n항목 | 금액 | 비고\n생수 500ml*40 | 20,000원 | 쿠팡 구매\n행사비 | 500,000원 | 견적서 첨부\n합계 | 520,000원")
    assert [l.item for l in named.expense] == ["생수 500ml*40", "행사비"], named.expense



@case("기획 도우미 참가비: 쓸 수 있는 돈은 예산 상한 + 참가비×인원, 수입표에 참가비 줄, 상한 지적·예비비도 그 기준, 수입 비고에 '고쳐 주세요' 같은 자리표시가 남지 않는다")
def _():
    from app.plan.build import assemble, to_budget_doc
    from app.plan.models import DraftLine, PlanIn
    from app.review.rules import check_budget

    req = PlanIn(**{**_PLAN_IN, "title": "MT", "headcount": 60, "budget_cap": 3_000_000, "fee": 30_000, "start": "2026-03-20", "end": "2026-03-21"})
    assert req.fee_income == 1_800_000 and req.spend_limit == 4_800_000
    lines = [DraftLine(item="숙소", unit_price=250_000, qty=12, unit="실"), DraftLine(item="식비", unit_price=20_000, qty=60, unit="명")]
    plan = assemble(req, _plan_draft(lines=lines, reserve_rate=0.1), "ai")
    assert plan.expense_total == 3_000_000 + 1_200_000 + 420_000 and plan.over_cap == 0, (plan.expense_total, plan.over_cap)  # 상한만이면 넘지만 참가비로 충당
    doc = to_budget_doc(plan)
    assert [(l.item, l.amount) for l in doc.income] == [("학생회비", 3_000_000), ("참가비", 1_800_000)], doc.income
    assert doc.income_total == 4_800_000 and "1인 30,000원 × 60명" in doc.income[1].note
    assert not any("고쳐 주세요" in l.note for l in doc.income)
    assert "income_total" not in [f.code for f in check_budget(doc)]
    over = assemble(req.model_copy(update={"fee": 10_000}), _plan_draft(lines=lines, reserve_rate=0.1), "ai")
    assert over.over_cap > 0  # 참가비가 적으면 상한(3,600,000원)을 넘는다
    plain = to_budget_doc(assemble(PlanIn(**{**_PLAN_IN, "budget_cap": None}), _plan_draft(), "ai"))
    assert [l.item for l in plain.income] == ["학생회비"] and plain.income[0].note == "지출 합계"
    # 참가비만 적고 인원을 비우면 수입을 셀 수 없다 — 조용히 빼지 않고 막는다
    try:
        PlanIn(**{**_PLAN_IN, "fee": 10_000, "headcount": None})
        raise AssertionError("인원 없는 참가비가 통과했다")
    except ValueError as e:
        assert "예상 인원" in str(e)
    # 상한 없이 참가비가 지출을 다 덮으면 '학생회비 0원' 줄을 두지 않고, 예산 출처 칸에 참가비를 함께 적는다
    small = [DraftLine(item="간식", unit_price=5_000, qty=30, unit="개")]
    covered = assemble(PlanIn(**{**_PLAN_IN, "budget_cap": None, "fee": 10_000, "headcount": 30}), _plan_draft(lines=small, reserve_rate=0), "ai")
    assert [l.item for l in to_budget_doc(covered).income] == ["참가비"], to_budget_doc(covered).income
    from app.plan.build import to_blocks
    assert "학생회비·참가비" in json.dumps(to_blocks(covered), ensure_ascii=False)



@case("규정 용어 확장: 개인·회장 통장 → 공금전용계좌, 영수증 → 증명서류를 색인의 낱말 그대로만 더한다 (2-gram 없이), 중립적인 '통장 명의'는 넓히지 않는다")
def _():
    from app.rag.store import _expand_terms

    vocab = {"공금전용계좌", "공금전용계좌로", "증명서류", "증명서류를", "서류", "명서", "계좌", "수입"}
    assert _expand_terms("회장 개인 통장으로 참가비를 걷어도 되나요?", vocab) == {"공금전용계좌", "공금전용계좌로"}
    assert _expand_terms("카드 영수증을 잃어버렸어요", vocab) == {"증명서류", "증명서류를"}
    assert _expand_terms("통장 명의 변경은 언제까지 해야 하나요?", vocab) == set()


@case("규정 메모 맥락: 계산 검사(합계·예비비) 결과도 '이미 나온 지적'으로 넘겨 같은 차이를 되풀이하지 않게 · 원문 조각은 금액 가운데서 자르지 않는다")
def _():
    from app.agents import claude_agents
    from app.review import service
    from app.review.models import BudgetDoc, Line
    from app.review.service import _Notes
    from app.review.textcheck import _snippet

    seen = {}

    async def fake(system, user, schema, **kw):
        seen["user"] = user
        return _Notes(notes=[])

    doc = BudgetDoc(title="t", expense=[Line(item="간식", amount=100_000)], expense_total=120_000)
    with patch.object(service, "MOCK_MODE", False), patch.object(claude_agents, "structured", fake), \
            patch.object(service, "_regulations", lambda _t: []):
        _run(service.notes(doc, "간식 100,000원", []))
    already = seen["user"].split("<already>")[1].split("</already>")[0]
    assert "지출 합계" in already, already

    # 서버가 확정 전 추출값으로 낸 예비비 지적은 모델에 알리기만 하고, 관련 메모를 기계적으로 지우지는 않는다 (화면이 보낸 지적만 거름)
    from app.review.models import Finding
    from app.review.service import _Note

    async def reserve_note(system, user, schema, **kw):
        return _Notes(notes=[_Note(level="확인 필요", title="예비비 사용 계획을 적어 주세요", quote="예비비 50,000원")])

    big = BudgetDoc(title="t", expense=[Line(item="간식", amount=100_000), Line(item="예비비", amount=50_000)], expense_total=150_000)
    with patch.object(service, "MOCK_MODE", False), patch.object(claude_agents, "structured", reserve_note), \
            patch.object(service, "_regulations", lambda _t: []):
        kept, _ = _run(service.notes(big, "간식 100,000원 예비비 50,000원", []))
        dropped, _ = _run(service.notes(big, "간식 100,000원 예비비 50,000원", [Finding(code="reserve", level="위반 소지", title="예비비 초과")]))
    assert [f.title for f in kept] == ["예비비 사용 계획을 적어 주세요"], kept
    assert dropped == [], dropped
    text = "행사 운영비 중 강사 사례금 300,000원은 현금으로 지급할 예정입니다 그리고 나머지는 계좌이체"
    i = text.index("현금")
    snip = _snippet(text, i, i + 2, pad=12)
    assert "300,000원은" in snip and not snip.startswith("000"), snip
    # 넓히는 한도 끝이 전화번호 가운데에 걸려도 번호 덩어리 끝까지 넓혀 마스킹한다 (Fable 리뷰: '10-1234-5678'이 남았다)
    text = "문의 010-1234-5678 " + "가" * 22 + " 현금으로 지급 예정"
    i = text.index("현금")
    snip = _snippet(text, i, i + 2)
    assert "1234-5678" not in snip and "10-1234" not in snip, snip


failed = [(n, why) for n, why in _results if why]
print(f"\n{len(_results) - len(failed)}/{len(_results)} 통과")
shutil.rmtree(_SCRATCH, ignore_errors=True)
sys.exit(1 if failed else 0)
