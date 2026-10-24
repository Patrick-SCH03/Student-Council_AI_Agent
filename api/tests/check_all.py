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
    VOYAGE_API_KEY="",
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


@case("/api/health가 실제로 쓰는 Claude 모델과 임베딩 모델을 알려준다")
def _():
    from app.config import CLAUDE_MODEL, VOYAGE_EMBEDDING_MODEL

    body = client.get("/api/health").json()
    assert body["model"] == CLAUDE_MODEL and body["embedding_model"] == VOYAGE_EMBEDDING_MODEL, body
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
    rv = ReviewerResult(violation="위반 없음", risk_level=RiskLevel.LOW, reasoning="r", recommendation="c")
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
        raise ca.StreamStarted("cut", partial="### 핵심 요약 부분")

    state = {
        "query": "q",
        "reviewer": ReviewerResult(violation="위반 없음", risk_level=RiskLevel.LOW, reasoning="r", recommendation="c"),
        "auditor": AuditorResult(compliance="준수", sanction_likelihood=RiskLevel.LOW, reasoning="r", recommendation="c"),
    }
    with patch.object(gr, "MOCK_MODE", False), patch.object(ca, "coordinate", cut):
        out = _run(gr.coordinator_node(state))
    assert out["final_markdown"].startswith("### 핵심 요약 부분"), out
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


@case("Voyage 임베딩은 문서·질의를 input_type으로 구분해 요청한다")
def _():
    calls = []

    def fake(texts, input_type):
        calls.append(input_type)
        return [[0.1, 0.2] for _ in texts]

    with patch.object(store, "MOCK_MODE", False), patch.object(store, "_voyage_embed", fake):
        store.embed_query("증빙서류")
        store._embed(["본문"])
    assert calls == ["query", "document"], calls


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


@case("Voyage 429(무료 한도)를 받으면 저속 모드로 바꿔 작은 배치·요청 간격으로 문서 색인을 끝낸다")
def _():
    calls, sleeps = [], []

    def fake(texts, input_type):
        calls.append(len(texts))
        if len(calls) == 1:
            raise RuntimeError("Voyage 임베딩 오류 429: reduced rate limits of 3 RPM and 10K TPM")
        return [[0.0] for _ in texts]

    texts = ["가" * 1000] * 20  # 2만 자 — 저속 모드 배치(6천 자)로 4번 이상 나뉘어야 한다
    with patch.object(store, "MOCK_MODE", False), patch.object(store, "_voyage_embed", fake),             patch.object(store, "_throttled", False), patch.object(store.time, "sleep", sleeps.append):
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


@case("잘린 OCR은 재시도하지 않고(과금 반복 방지), Voyage 네트워크 타임아웃은 재시도한다")
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

    def flaky(texts, input_type):
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ReadTimeout("")
        return [[0.0] for _ in texts]

    with patch.object(store, "MOCK_MODE", False), patch.object(store, "_voyage_embed", flaky), \
            patch.object(store.time, "sleep", lambda _s: None):
        assert len(store._embed(["본문"])) == 1
    assert len(attempts) == 2, attempts


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


@case("문서 삭제 뒤 그래프 재생성이 실패해도 삭제는 성공으로 끝나고 그래프는 다시 만들 대상이 된다")
def _():
    db.add_document("graph-fail-doc", "graph-fail.pdf", 1)
    with patch.object(main.citation_graph, "get_graph", side_effect=RuntimeError("graph down")):
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


@case("업로드 상한은 다 읽기 전에 끊는다 (413)")
def _():
    read_sizes: list[int] = []
    from starlette.datastructures import UploadFile as StarletteUploadFile

    original_read = StarletteUploadFile.read

    async def counting_read(self, size=-1):
        data = await original_read(self, size)
        read_sizes.append(len(data))
        return data

    with patch.object(main, "MAX_UPLOAD_BYTES", 2 * 1024 * 1024), patch.object(
        main, "ingest_pdf"
    ) as ingest, patch.object(StarletteUploadFile, "read", counting_read):
        big = b"%PDF-1.4\n" + b"0" * (5 * 1024 * 1024)
        r = client.post("/api/documents", headers=AUTH, files={"file": ("big.pdf", big, "application/pdf")})
        assert r.status_code == 413, r.status_code
        assert not ingest.called, "상한을 넘은 파일을 색인했다"
        assert sum(read_sizes) <= 3 * 1024 * 1024, f"상한을 넘겨 {sum(read_sizes)}바이트를 읽었다"
        ok = client.post("/api/documents", headers=AUTH, files={"file": ("small.pdf", b"%PDF-1.4 tiny", "application/pdf")})
        assert ok.status_code != 413, "상한 이하 파일을 거절했다"


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
    kw = spy.call_args.kwargs
    assert (kw["max_retries"], kw["backoff_base"]) == (2, 2), kw
    assert kw.get("input_type") == "query", kw  # Voyage는 질의·문서 임베딩을 구분한다


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


failed = [(n, why) for n, why in _results if why]
print(f"\n{len(_results) - len(failed)}/{len(_results)} 통과")
shutil.rmtree(_SCRATCH, ignore_errors=True)
sys.exit(1 if failed else 0)
