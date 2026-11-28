"""SQLite 저장소: 색인 문서 목록, 분석 이력, 운영 지표, 답변 캐시.

단일 인스턴스 운영 규모라 별도 DB 서버 없이 볼륨에 파일로 보존한다.
"""

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone

from app.config import SQLITE_PATH
from app.privacy import find_private_name, mask_obj, mask_text

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id     TEXT PRIMARY KEY,
    filename   TEXT NOT NULL,
    chunks     INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    query      TEXT NOT NULL,
    risk_level TEXT,
    result     TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS metrics (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             TEXT NOT NULL,
    route          TEXT,
    risk_level     TEXT,
    status         TEXT NOT NULL,           -- ok | error
    elapsed        REAL,
    input_tokens   INTEGER DEFAULT 0,
    output_tokens  INTEGER DEFAULT 0,
    query_preview  TEXT
);
CREATE TABLE IF NOT EXISTS visits (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    visitor_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS answer_cache (
    query_key   TEXT PRIMARY KEY,      -- 정규화된 질문
    ts          TEXT NOT NULL,
    analysis_id INTEGER NOT NULL,
    result      TEXT NOT NULL,
    hits        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS feedback (
    analysis_id INTEGER PRIMARY KEY,   -- 답변당 1건 (재평가 시 갱신)
    ts          TEXT NOT NULL,
    helpful     INTEGER NOT NULL,      -- 1 = 도움됨, 0 = 부족함
    visitor_id  TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    google_sub    TEXT NOT NULL UNIQUE,  -- Google 계정 고유 ID (이메일은 바뀔 수 있어 식별자로 쓰지 않는다)
    email         TEXT NOT NULL,
    name          TEXT,
    role          TEXT NOT NULL DEFAULT 'member',
    created_at    TEXT NOT NULL,
    last_login_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    prefix      TEXT NOT NULL,
    year        INTEGER NOT NULL,
    seq         INTEGER NOT NULL,
    issued_on   TEXT NOT NULL,
    title       TEXT NOT NULL,
    recipient   TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contributions (
    -- 서비스 개선용 자료: 이용자가 허락한 요청만, 가명 처리한 본문·결과 (app/contrib.py)
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    kind        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT '',
    text        TEXT NOT NULL DEFAULT '',
    result      TEXT NOT NULL DEFAULT '{}',
    corrected   TEXT,
    consent     TEXT NOT NULL,
    name_keys   TEXT NOT NULL DEFAULT '[]'  -- 처음 저장 때 찾은 이름의 해시 — 나중에 붙는 고친 값에서도 같은 이름을 가린다
);
CREATE INDEX IF NOT EXISTS idx_contributions_user ON contributions(user_id);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    revoked_at  TEXT
);
"""


_initialized = False


def _connect() -> sqlite3.Connection:
    global _initialized
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    if _initialized:
        return conn
    # v3 개발 중 잠깐 쓴 이메일 기준 users 표(google_sub 없음)는 새 형태로 다시 만든다.
    # 운영에는 배포된 적 없는 표라 지워도 잃는 데이터가 없다.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    if cols and "google_sub" not in cols:
        conn.executescript("DROP TABLE IF EXISTS sessions; DROP TABLE IF EXISTS users;")
    conn.executescript(_SCHEMA)
    # 스키마 확장 마이그레이션 (기존 DB 호환)
    for stmt in (
        "ALTER TABLE metrics ADD COLUMN analysis_id INTEGER",
        "ALTER TABLE metrics ADD COLUMN visitor_id TEXT",
        # visitor_id는 클라이언트가 보내는 값이라 저장소를 비우면 초기화된다.
        # 우회가 어려운 보조 기준으로 IP 해시를 함께 기록한다 (원문은 저장하지 않음).
        "ALTER TABLE metrics ADD COLUMN ip_hash TEXT",
        # 운영자가 직접 돌리는 질의(회귀 테스트 등). 지표에는 남기되 한도 계산에서는 뺀다.
        "ALTER TABLE metrics ADD COLUMN is_admin INTEGER DEFAULT 0",
        # 실패 사유. status만 남기면 대시보드를 봐도 무엇이 문제인지 알 수 없다.
        "ALTER TABLE metrics ADD COLUMN error TEXT",
        # 단계별 소요 시간(초)·사고 토큰 JSON. 응답이 느려졌을 때 어느 단계인지 가른다.
        "ALTER TABLE metrics ADD COLUMN stage_timings TEXT",
        # 요청별 추정 비용(USD). 모델 공급자가 섞이면 토큰 합 × 한 단가로는 비용을 낼 수 없다.
        "ALTER TABLE metrics ADD COLUMN cost_usd REAL",
        # 낮춘 경로로 이어간 단계 (쉼표 구분: 검색 키워드만·분류 실패). 조용히 일어나 로그만으로는 놓친다.
        "ALTER TABLE metrics ADD COLUMN fallback TEXT",
        "ALTER TABLE contributions ADD COLUMN name_keys TEXT NOT NULL DEFAULT '[]'",
        # 관리자가 이용을 막은 계정 (막힌 동안 로그인·세션이 통하지 않는다)
        "ALTER TABLE users ADD COLUMN blocked_at TEXT",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # 이미 존재
    # 한도 계산·일별 집계가 매 요청 ts 범위를 훑는다. 인덱스가 있어야 행이 쌓여도 비용이 일정하다.
    for stmt in (
        "CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(ts)",
        "CREATE INDEX IF NOT EXISTS idx_metrics_visitor ON metrics(visitor_id, ts)",
        "CREATE INDEX IF NOT EXISTS idx_metrics_ip ON metrics(ip_hash, ts)",
        "CREATE INDEX IF NOT EXISTS idx_visits_ts ON visits(ts)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_ledger_user ON ledger(user_id, prefix, year, seq)",
    ):
        conn.execute(stmt)
    conn.commit()
    _initialized = True
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- documents

def add_document(doc_id: str, filename: str, chunks: int) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO documents (doc_id, filename, chunks, created_at) VALUES (?, ?, ?, ?)",
            (doc_id, filename, chunks, _now()),
        )


def list_documents() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT doc_id, filename, chunks, created_at FROM documents ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_all_documents() -> int:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM documents")
    return cur.rowcount


def delete_document(doc_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    return cur.rowcount > 0


# ---------------------------------------------------------------- analyses

def add_analysis(query: str, risk_level: str | None, result: dict) -> int:
    # 질의 원문도 답변과 같은 기준으로 지운다. 관리자 로그·CSV에 실명·연락처가 남지 않게.
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO analyses (query, risk_level, result, created_at) VALUES (?, ?, ?, ?)",
            (mask_text(query), risk_level, json.dumps(mask_obj(result), ensure_ascii=False), _now()),
        )
    return cur.lastrowid


def record_metric(
    route: str | None,
    risk_level: str | None,
    status: str,
    elapsed: float,
    input_tokens: int,
    output_tokens: int,
    query_preview: str,
    analysis_id: int | None = None,
    visitor_id: str | None = None,
    ip_hash: str | None = None,
    is_admin: bool = False,
    error: str | None = None,
    stage_timings: dict | None = None,
    cost_usd: float | None = None,
    fallback: str | None = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO metrics (ts, route, risk_level, status, elapsed, input_tokens, output_tokens, "
            "query_preview, analysis_id, visitor_id, ip_hash, is_admin, error, stage_timings, cost_usd, fallback) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _now(), route, risk_level, status, elapsed, input_tokens, output_tokens,
                # 자르기 전에 마스킹한다 — 잘린 경계에 걸친 이름·번호가 남지 않도록
                mask_text(query_preview)[:500], analysis_id, visitor_id, ip_hash, int(is_admin),
                (error or None) and mask_text(error)[:300],
                json.dumps(stage_timings) if stage_timings else None,
                cost_usd,
                fallback,
            ),
        )


# ---------------------------------------------------------------- 설정 / 사용량 제한

def get_settings(defaults: dict[str, int]) -> dict[str, int]:
    """저장된 설정을 기본값과 병합해 반환한다."""
    with _connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    stored = {r["key"]: r["value"] for r in rows}
    result = {}
    for key, default in defaults.items():
        try:
            result[key] = int(stored[key]) if key in stored else default
        except (TypeError, ValueError):
            result[key] = default
    return result


def set_settings(values: dict[str, int]) -> None:
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [(k, str(v)) for k, v in values.items()],
        )


def get_raw_setting(key: str) -> str | None:
    """숫자가 아닌 설정(예: 공지 JSON)을 그대로 읽는다."""
    with _connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_raw_setting(key: str, value: str | None) -> None:
    """None이면 지운다."""
    with _connect() as conn:
        if value is None:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        else:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )


# ---------------------------------------------------------------- 답변 캐시

def normalize_query(query: str) -> str:
    """캐시 키 생성: 공백·문장부호를 제거해 표기 차이를 흡수한다.

    숫자 사이의 마침표는 남긴다 — "1.5%"와 "15%"가 같은 키로 합쳐지면
    앞 질문의 답이 뒤 질문에 그대로 나간다.
    """
    query = re.sub(r"(?<!\d)\.|\.(?!\d)", "", query)
    return re.sub(r"[\s?!,·…]+", "", query).lower()


def get_cached_answer(query_key: str, ttl_hours: int) -> dict | None:
    """TTL 이내의 캐시된 답변을 반환하고 적중 횟수를 올린다."""
    if ttl_hours <= 0:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT analysis_id, result FROM answer_cache "
            "WHERE query_key = ? AND datetime(ts) >= datetime('now', ?)",
            (query_key, f"-{ttl_hours} hours"),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE answer_cache SET hits = hits + 1 WHERE query_key = ?", (query_key,)
        )
    return {"analysis_id": row["analysis_id"], **json.loads(row["result"])}


def save_cached_answer(
    query_key: str, analysis_id: int, result: dict, generation: int | None = None
) -> None:
    with _cache_lock:
        if generation is not None and generation != _cache_generation:
            return  # 요청 도중 캐시가 비워졌다 — 이 답은 옛 색인 기준일 수 있다
        with _connect() as conn:
            conn.execute(
                "INSERT INTO answer_cache (query_key, ts, analysis_id, result, hits) "
                "VALUES (?, ?, ?, ?, 0) ON CONFLICT(query_key) DO UPDATE SET "
                "ts = excluded.ts, analysis_id = excluded.analysis_id, "
                "result = excluded.result, hits = 0",
                (query_key, _now(), analysis_id, json.dumps(result, ensure_ascii=False)),
            )


def cache_stats() -> dict:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS entries, COALESCE(SUM(hits), 0) AS hits FROM answer_cache"
        ).fetchone()
    return dict(row)


# 캐시를 비울 때마다 1씩 오른다. 비우기 전에 시작된 요청은 완료돼도 저장하지
# 못하게 해서, 옛 색인으로 만든 답이 새 캐시에 들어가는 일을 막는다.
_cache_generation = 0
# 세대 검사와 INSERT, 세대 증가와 DELETE는 각각 한 덩어리여야 한다. 스레드풀에서
# 도는 문서 삭제가 검사와 저장 사이에 끼면 지운 문서의 답이 새 캐시에 남는다.
_cache_lock = threading.Lock()


def cache_generation() -> int:
    return _cache_generation


def clear_cache() -> int:
    global _cache_generation
    with _cache_lock:
        _cache_generation += 1
        with _connect() as conn:
            cur = conn.execute("DELETE FROM answer_cache")
    return cur.rowcount


def add_feedback(analysis_id: int, helpful: bool, visitor_id: str | None) -> None:
    """답변 만족도 기록. 같은 방문자가 다시 누르면 갱신된다.

    analysis_id는 순번이라 누구나 추측할 수 있다. 다른 방문자가 남긴 평가를
    덮어쓰지 못하도록, 갱신은 처음 남긴 방문자(또는 익명 기록)에게만 허용한다.
    """
    with _connect() as conn:
        conn.execute(
            "INSERT INTO feedback (analysis_id, ts, helpful, visitor_id) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(analysis_id) DO UPDATE SET "
            "helpful = excluded.helpful, ts = excluded.ts, visitor_id = excluded.visitor_id "
            "WHERE feedback.visitor_id IS NULL OR feedback.visitor_id = excluded.visitor_id",
            (analysis_id, _now(), 1 if helpful else 0, visitor_id),
        )


# 한도 계산에서는 운영자 질의를 제외한다. 회귀 테스트를 돌리다 실사용자 몫을
# 소진시키거나, 반대로 점검이 한도에 막히는 일을 둘 다 막는다.
_NOT_ADMIN = "COALESCE(is_admin, 0) = 0"
# 문서 검토 기록(route='review-…')은 규정 질문 한도에 세지 않는다 — 한도가 따로 있다
_NOT_REVIEW = "COALESCE(route, '') NOT LIKE 'review%'"
# '오늘'은 한국 자정 기준이다. ts는 UTC ISO 문자열이므로 KST 자정을 UTC로 옮긴
# 경계('T' 구분자를 맞춰야 문자열 비교가 시간순이 된다)와 비교한다 — 색인을 탄다.
_TODAY = (
    "ts >= strftime('%Y-%m-%dT%H:%M:%S', date('now', '+9 hours'), '-9 hours') "
    "AND ts < strftime('%Y-%m-%dT%H:%M:%S', date('now', '+9 hours'), '+15 hours')"
)


def count_today(visitor_id: str | None = None) -> int:
    """오늘 처리한 질의 수 (운영자 질의 제외). visitor_id를 주면 해당 사용자 기준."""
    with _connect() as conn:
        if visitor_id:
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM metrics "
                f"WHERE {_TODAY} AND {_NOT_ADMIN} AND {_NOT_REVIEW} AND visitor_id = ?",
                (visitor_id,),
            ).fetchone()
        else:
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM metrics "
                f"WHERE {_TODAY} AND {_NOT_ADMIN} AND {_NOT_REVIEW}"
            ).fetchone()
    return row["n"]


def count_review_today(user_key: str, route: str = "review-extract") -> int:
    """오늘 이 사용자가 문서 검토의 한 단계(추출·메모)를 부른 횟수."""
    with _connect() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM metrics WHERE {_TODAY} AND route = ? AND visitor_id = ?",
            (route, user_key),
        ).fetchone()
    return row["n"]


def count_today_by_ip(ip_hash: str) -> int:
    """오늘 같은 IP에서 처리한 질의 수 (운영자 질의 제외)."""
    with _connect() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM metrics "
            f"WHERE {_TODAY} AND {_NOT_ADMIN} AND {_NOT_REVIEW} AND ip_hash = ?",
            (ip_hash,),
        ).fetchone()
    return row["n"]


def add_visit(visitor_id: str) -> None:
    """방문 기록. 방문자당 하루 1행만 남긴다 (무인증 엔드포인트라 무한 INSERT를 막는다)."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO visits (ts, visitor_id) SELECT ?, ? WHERE NOT EXISTS ("
            f"SELECT 1 FROM visits WHERE visitor_id = ? AND {_TODAY})",
            (_now(), visitor_id, visitor_id),
        )


def _csv_safe(value) -> str:
    """스프레드시트가 수식으로 해석하는 선행 문자(=, +, -, @)를 무력화한다 (CSV 인젝션)."""
    s = (value or "").replace('"', '""')
    return ("'" + s) if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def export_metrics_csv() -> str:
    """포트폴리오/분석용 전체 지표 CSV 덤프."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT ts, route, risk_level, status, elapsed, input_tokens, output_tokens, query_preview "
            "FROM metrics ORDER BY id"
        ).fetchall()
    lines = ["ts,route,risk_level,status,elapsed,input_tokens,output_tokens,query"]
    for r in rows:
        query = _csv_safe(r["query_preview"])
        lines.append(
            f'{r["ts"]},{r["route"] or ""},{r["risk_level"] or ""},{r["status"]},'
            f'{r["elapsed"] or 0},{r["input_tokens"]},{r["output_tokens"]},"{query}"'
        )
    return "\n".join(lines)


def get_stats(days: int = 14) -> dict:
    """관측 대시보드용 집계. 일별 추이 / 누적 / 위험도 분포 / 최근 질의."""
    with _connect() as conn:
        totals = dict(conn.execute(
            # 캐시 적중은 LLM을 호출하지 않으므로 평균 응답 시간 계산에서 제외한다
            "SELECT COUNT(*) AS count, "
            "COALESCE(AVG(CASE WHEN status != 'cached' THEN elapsed END), 0) AS avg_elapsed, "
            "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
            "COALESCE(SUM(output_tokens), 0) AS output_tokens, "
            "COALESCE(SUM(cost_usd), 0) AS cost_usd, "
            # cost_usd 도입 전 행은 토큰으로 비용을 추정한다 (main.py가 당시 단가로 환산)
            "COALESCE(SUM(CASE WHEN cost_usd IS NULL THEN input_tokens END), 0) AS legacy_input_tokens, "
            "COALESCE(SUM(CASE WHEN cost_usd IS NULL THEN output_tokens END), 0) AS legacy_output_tokens, "
            # 'cached'는 정상 응답이므로 오류로 세지 않는다
            "COALESCE(SUM(CASE WHEN status NOT IN ('ok', 'cached', 'cancelled') THEN 1 ELSE 0 END), 0) AS errors, "
            "COUNT(fallback) AS fallbacks "
            "FROM metrics"
        ).fetchone())

        today = dict(conn.execute(
            # 캐시 적중은 LLM을 호출하지 않으므로 평균 응답 시간 계산에서 제외한다
            "SELECT COUNT(*) AS count, "
            "COALESCE(AVG(CASE WHEN status != 'cached' THEN elapsed END), 0) AS avg_elapsed, "
            "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
            "COALESCE(SUM(output_tokens), 0) AS output_tokens, "
            "COALESCE(SUM(cost_usd), 0) AS cost_usd, "
            # cost_usd 도입 전 행은 토큰으로 비용을 추정한다 (main.py가 당시 단가로 환산)
            "COALESCE(SUM(CASE WHEN cost_usd IS NULL THEN input_tokens END), 0) AS legacy_input_tokens, "
            "COALESCE(SUM(CASE WHEN cost_usd IS NULL THEN output_tokens END), 0) AS legacy_output_tokens, "
            # IP 상한이 실제로 클라이언트를 구분하는지 확인하는 용도.
            # 프록시가 실제 IP를 넘겨주지 않으면 트래픽이 늘어도 1에서 멈춘다.
            "COUNT(DISTINCT ip_hash) AS unique_ips, "
            "COUNT(fallback) AS fallbacks "
            f"FROM metrics WHERE {_TODAY}"
        ).fetchone())

        daily = [dict(r) for r in conn.execute(
            "SELECT date(ts, '+9 hours') AS date, COUNT(*) AS count, "
            "COALESCE(AVG(CASE WHEN status != 'cached' THEN elapsed END), 0) AS avg_elapsed, "
            "COALESCE(SUM(input_tokens + output_tokens), 0) AS tokens "
            "FROM metrics WHERE ts >= datetime('now', ?) "
            "GROUP BY date(ts, '+9 hours') ORDER BY date",
            (f"-{days} days",),
        ).fetchall()]

        risk = {r["risk_level"]: r["n"] for r in conn.execute(
            "SELECT risk_level, COUNT(*) AS n FROM metrics "
            "WHERE risk_level IS NOT NULL GROUP BY risk_level"
        ).fetchall()}

        routes = {r["route"] or "unknown": r["n"] for r in conn.execute(
            "SELECT route, COUNT(*) AS n FROM metrics GROUP BY route"
        ).fetchall()}

        recent = [dict(r) for r in conn.execute(
            "SELECT m.id, m.analysis_id, m.ts, m.route, m.risk_level, m.status, m.elapsed, "
            "m.input_tokens + m.output_tokens AS tokens, m.query_preview, m.error, m.fallback, f.helpful "
            "FROM metrics m LEFT JOIN feedback f ON f.analysis_id = m.analysis_id "
            "ORDER BY m.id DESC LIMIT 20"
        ).fetchall()]

        fb = dict(conn.execute(
            "SELECT COALESCE(SUM(helpful), 0) AS helpful, "
            "COALESCE(SUM(1 - helpful), 0) AS unhelpful FROM feedback"
        ).fetchone())

        # 부족하다고 평가된 답변 — 개선 대상 목록
        fb["recent_unhelpful"] = [dict(r) for r in conn.execute(
            "SELECT f.analysis_id, f.ts, a.query, a.risk_level "
            "FROM feedback f JOIN analyses a ON a.id = f.analysis_id "
            "WHERE f.helpful = 0 ORDER BY f.ts DESC LIMIT 10"
        ).fetchall()]

        visits = {
            "today_visitors": conn.execute(
                f"SELECT COUNT(DISTINCT visitor_id) AS n FROM visits WHERE {_TODAY}"
            ).fetchone()["n"],
            "total_visitors": conn.execute(
                "SELECT COUNT(DISTINCT visitor_id) AS n FROM visits"
            ).fetchone()["n"],
            "total_visits": conn.execute("SELECT COUNT(*) AS n FROM visits").fetchone()["n"],
        }

        # 최근 완료된 규정 질의의 단계별 중앙값 — 느려졌을 때 병목 단계를 바로 본다
        stage_rows = [json.loads(r["stage_timings"]) for r in conn.execute(
            "SELECT stage_timings FROM metrics WHERE status = 'ok' AND route = 'regulation' "
            "AND stage_timings IS NOT NULL ORDER BY id DESC LIMIT ?",
            (STAGE_SAMPLE,),
        ).fetchall()]

        daily_visits = [dict(r) for r in conn.execute(
            "SELECT date(ts, '+9 hours') AS date, COUNT(DISTINCT visitor_id) AS visitors "
            "FROM visits WHERE ts >= datetime('now', ?) GROUP BY date(ts, '+9 hours') ORDER BY date",
            (f"-{days} days",),
        ).fetchall()]

    return {
        "totals": totals,
        "today": today,
        "daily": daily,
        "risk": risk,
        "routes": routes,
        "recent": recent,
        "visits": visits,
        "daily_visits": daily_visits,
        "feedback": fb,
        "cache": cache_stats(),
        "stages": summarize_stages(stage_rows),
    }


STAGE_SAMPLE = 50
STAGE_KEYS = ("router", "retrieve", "reviewer", "auditor", "coordinator_ttft", "coordinator")


def summarize_stages(rows: list[dict]) -> dict:
    """단계별 중앙값. 표본이 없는 단계는 뺀다."""
    out: dict = {"samples": len(rows)}
    for key in STAGE_KEYS:
        values = sorted(r[key] for r in rows if isinstance(r.get(key), (int, float)))
        if values:
            mid = len(values) // 2
            median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
            out[key] = round(median, 2)
    return out


def get_analysis(analysis_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, query, risk_level, result, created_at FROM analyses WHERE id = ?",
            (analysis_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["result"] = json.loads(item["result"])
    return item


def list_analyses(limit: int = 20) -> list[dict]:
    limit = max(1, min(limit, 100))  # 음수는 SQLite에서 '무제한'이 된다
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, query, risk_level, result, created_at FROM analyses "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    items = []
    for r in rows:
        item = dict(r)
        item["result"] = json.loads(item["result"])
        items.append(item)
    return items


def _ts_column(conn: sqlite3.Connection, table: str) -> str:
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    return "ts" if "ts" in cols else "created_at"


def snapshot(dest: str) -> None:
    """운영 중인 DB를 일관된 한 시점으로 복사한다 (백업용).

    파일을 그대로 복사하면 쓰기 도중의 페이지가 섞일 수 있다. SQLite 온라인 백업 API는
    진행 중인 쓰기와 충돌하지 않게 페이지 단위로 복사한다.
    """
    with _connect() as src, sqlite3.connect(dest) as dst:
        src.backup(dst)
    dst.close()


def purge_old(days: int) -> dict[str, int]:
    """보존 기간이 지난 지표·방문·분석 기록을 지운다. 답변 캐시는 7일이 지나면 지운다.

    질의 원문과 답변을 무기한 쌓아둘 이유가 없다 — 운영 지표는 집계면 충분하다.
    """
    if days <= 0:
        return {}
    cutoff = f"-{days} days"
    removed: dict[str, int] = {}
    with _connect() as conn:
        for table in ("metrics", "visits", "analyses"):
            col = _ts_column(conn, table)
            if table == "analyses":
                removed["feedback"] = conn.execute(
                    f"DELETE FROM feedback WHERE analysis_id IN "
                    f"(SELECT id FROM analyses WHERE datetime({col}) < datetime('now', ?))",
                    (cutoff,),
                ).rowcount
            removed[table] = conn.execute(
                f"DELETE FROM {table} WHERE datetime({col}) < datetime('now', ?)", (cutoff,)
            ).rowcount
        removed["answer_cache"] = conn.execute(
            "DELETE FROM answer_cache WHERE datetime(ts) < datetime('now', '-7 days')"
        ).rowcount
        removed["contributions"] = conn.execute(
            "DELETE FROM contributions WHERE datetime(created_at) < datetime('now', ?)", (cutoff,)
        ).rowcount
    return removed


def mask_stored_text() -> dict[str, int]:
    """이미 저장된 질의 원문·결과·오류 문구를 소급해 마스킹한다 (멱등).

    원문 마스킹을 넣기 전에 쌓인 행에는 실명이 든 질의가 그대로 있다. 바뀌는 행만
    갱신하므로 두 번째 실행부터는 0건이다. 실명이 든 캐시 키는 아예 지운다.
    """
    changed = {"analyses": 0, "metrics": 0, "answer_cache": 0}
    with _connect() as conn:
        for row in conn.execute("SELECT id, query, result FROM analyses").fetchall():
            query = mask_text(row["query"] or "")
            try:
                result = json.dumps(mask_obj(json.loads(row["result"])), ensure_ascii=False)
            except (TypeError, ValueError):
                result = row["result"]
            if query != (row["query"] or "") or result != row["result"]:
                conn.execute("UPDATE analyses SET query = ?, result = ? WHERE id = ?", (query, result, row["id"]))
                changed["analyses"] += 1
        for row in conn.execute("SELECT id, query_preview, error FROM metrics").fetchall():
            preview = mask_text(row["query_preview"] or "")
            error = mask_text(row["error"]) if row["error"] else row["error"]
            if preview != (row["query_preview"] or "") or error != row["error"]:
                conn.execute("UPDATE metrics SET query_preview = ?, error = ? WHERE id = ?", (preview, error, row["id"]))
                changed["metrics"] += 1
        for row in conn.execute("SELECT query_key FROM answer_cache").fetchall():
            if find_private_name(row["query_key"]) or mask_text(row["query_key"]) != row["query_key"]:
                conn.execute("DELETE FROM answer_cache WHERE query_key = ?", (row["query_key"],))
                changed["answer_cache"] += 1
    return changed


# ---------------------------------------------------------------- users·sessions (v3 로그인)
# 세션 토큰 원문은 쿠키에만 있고 DB에는 해시만 둔다 — DB가 새도 세션을 훔칠 수 없다.

def upsert_user(google_sub: str, email: str, name: str | None, role: str) -> dict:
    """로그인한 학교 계정을 Google 고유 ID로 기록한다. 이메일·이름·역할은 매 로그인마다 최신으로 맞춘다.

    같은 이메일이라도 sub가 다르면 다른 사람이다 (학교가 메일 주소를 다시 배정하는 경우) — 합치지 않는다.
    """
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO users (google_sub, email, name, role, created_at, last_login_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(google_sub) DO UPDATE SET email = excluded.email, name = excluded.name, "
            "role = excluded.role, last_login_at = excluded.last_login_at",
            (google_sub, email, name, role, now, now),
        )
        row = conn.execute("SELECT id, email, name, role, blocked_at FROM users WHERE google_sub = ?", (google_sub,)).fetchone()
    return dict(row)


def create_session(token_hash: str, user_id: int, expires_at: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash, user_id, _now(), expires_at),
        )


def get_session_user(token_hash: str) -> dict | None:
    """유효한(폐기·만료되지 않은) 세션의 사용자. 없으면 None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT u.id, u.email, u.name, u.role FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ? AND s.revoked_at IS NULL AND s.expires_at > ? AND u.blocked_at IS NULL",
            (token_hash, _now()),
        ).fetchone()
    return dict(row) if row else None


def revoke_session(token_hash: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
            (_now(), token_hash),
        )


# ---------------------------------------------------------------- 관리자: 회원 관리 (v3)
# 활동은 업무 도구 지표(metrics.visitor_id = 'user:<id>')만 본다 — 규정 질문은 익명이라 계정과 잇지 않는다. 내용은 저장하지 않는다.

_USER_COLS = """u.id, u.email, u.name, u.created_at, u.last_login_at, u.blocked_at,
    (SELECT COUNT(*) FROM sessions s WHERE s.user_id = u.id AND s.revoked_at IS NULL AND s.expires_at > :now) AS active_sessions,
    (SELECT COUNT(*) FROM metrics m WHERE m.visitor_id = 'user:' || u.id AND datetime(m.ts) >= datetime('now', '-30 days')) AS uses_30d,
    (SELECT COALESCE(SUM(m.cost_usd), 0) FROM metrics m WHERE m.visitor_id = 'user:' || u.id) AS cost_usd,
    (SELECT MAX(m.ts) FROM metrics m WHERE m.visitor_id = 'user:' || u.id) AS last_used_at"""


def list_users(query: str = "", limit: int = 300) -> list[dict]:
    """최근 로그인 순. query는 이메일·이름 일부."""
    like = f"%{query.strip()}%"
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT {_USER_COLS} FROM users u WHERE (:q = '' OR u.email LIKE :like OR COALESCE(u.name, '') LIKE :like) "
            "ORDER BY u.last_login_at DESC LIMIT :limit",
            {"now": _now(), "q": query.strip(), "like": like, "limit": limit},
        ).fetchall()
    return [dict(r) for r in rows]


def count_users() -> dict[str, int]:
    with _connect() as conn:
        total, blocked, week = conn.execute(
            "SELECT COUNT(*), COUNT(blocked_at), SUM(datetime(last_login_at) >= datetime('now', '-7 days')) FROM users"
        ).fetchone()
    return {"total": int(total or 0), "blocked": int(blocked or 0), "active_7d": int(week or 0)}


def user_detail(user_id: int) -> dict | None:
    key = f"user:{user_id}"
    with _connect() as conn:
        user = conn.execute(f"SELECT {_USER_COLS} FROM users u WHERE u.id = :id", {"now": _now(), "id": user_id}).fetchone()
        if not user:
            return None
        by_route = conn.execute(
            "SELECT route, COUNT(*) AS uses, SUM(status != 'ok') AS errors, COALESCE(SUM(cost_usd), 0) AS cost_usd, MAX(ts) AS last_at "
            "FROM metrics WHERE visitor_id = ? GROUP BY route ORDER BY uses DESC",
            (key,),
        ).fetchall()
        recent = conn.execute(
            "SELECT ts, route, status, elapsed, cost_usd FROM metrics WHERE visitor_id = ? ORDER BY id DESC LIMIT 30", (key,)
        ).fetchall()
        sessions = conn.execute(
            "SELECT created_at, expires_at, revoked_at FROM sessions WHERE user_id = ? ORDER BY created_at DESC LIMIT 20", (user_id,)
        ).fetchall()
        ledger = conn.execute("SELECT COUNT(*) FROM ledger WHERE user_id = ?", (user_id,)).fetchone()[0]
        contrib = conn.execute("SELECT COUNT(*) FROM contributions WHERE user_id = ?", (user_id,)).fetchone()[0]
    now = _now()
    return {
        "user": dict(user),
        "by_route": [dict(r) for r in by_route],
        "recent": [dict(r) for r in recent],
        "sessions": [{**dict(s), "active": not s["revoked_at"] and s["expires_at"] > now} for s in sessions],
        "ledger": int(ledger),
        "contributions": int(contrib),
    }


def is_blocked(google_sub: str) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT blocked_at FROM users WHERE google_sub = ?", (google_sub,)).fetchone()
    return bool(row and row[0])


def revoke_user_sessions(user_id: int) -> int:
    with _connect() as conn:
        return conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (_now(), user_id)
        ).rowcount


def set_user_blocked(user_id: int, blocked: bool) -> bool:
    """막으면 그 자리에서 모든 세션도 끊는다."""
    with _connect() as conn:
        ok = conn.execute(
            "UPDATE users SET blocked_at = ? WHERE id = ?", (_now() if blocked else None, user_id)
        ).rowcount > 0
        if ok and blocked:
            conn.execute("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (_now(), user_id))
    return ok


def delete_user(user_id: int) -> bool:
    """계정과 그 계정의 세션·문서 번호 대장·개선용 자료를 지운다. 지표는 남기되 계정과의 연결(visitor_id)을 끊는다."""
    with _connect() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
            return False
        for table in ("sessions", "ledger", "contributions"):
            conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        conn.execute("UPDATE metrics SET visitor_id = NULL WHERE visitor_id = ?", (f"user:{user_id}",))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return True


def purge_sessions(inactive_days: int) -> dict[str, int]:
    """만료됐거나 폐기한 지 7일 지난 세션, 그리고 inactive_days 동안 로그인하지 않은 계정을 지운다 (기동 시).

    계정 행에는 이메일·이름이 있다 — 쓰지 않는 사람의 정보를 무기한 들고 있지 않는다.
    """
    with _connect() as conn:
        sessions = conn.execute(
            "DELETE FROM sessions WHERE expires_at < ? OR datetime(revoked_at) < datetime('now', '-7 days')",
            (_now(),),
        ).rowcount
        users = 0
        if inactive_days > 0:
            stale = "SELECT id FROM users WHERE datetime(last_login_at) < datetime('now', ?)"
            cutoff = (f"-{inactive_days} days",)
            conn.execute(f"DELETE FROM sessions WHERE user_id IN ({stale})", cutoff)
            conn.execute(f"DELETE FROM ledger WHERE user_id IN ({stale})", cutoff)
            conn.execute(f"DELETE FROM contributions WHERE user_id IN ({stale})", cutoff)
            users = conn.execute(f"DELETE FROM users WHERE id IN ({stale})", cutoff).rowcount
    return {"sessions": sessions, "users": users}


# ---------------------------------------------------------------- 서비스 개선용 자료 (v3, 선택 동의)

def add_contribution(user_id: int, kind: str, source: str, text: str, result: str, consent: str, name_keys: str = "[]") -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO contributions (user_id, kind, created_at, source, text, result, consent, name_keys) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, kind, _now(), source, text, result, consent, name_keys),
        )
        return int(cur.lastrowid)


def contribution_name_keys(contribution_id: int, user_id: int) -> str | None:
    """본인 자료의 이름 열쇠(JSON). 남의 자료·없는 번호면 None."""
    with _connect() as conn:
        row = conn.execute("SELECT name_keys FROM contributions WHERE id = ? AND user_id = ?", (contribution_id, user_id)).fetchone()
    return row[0] if row else None


def set_contribution_correction(contribution_id: int, user_id: int, corrected: str) -> bool:
    with _connect() as conn:
        return conn.execute(
            "UPDATE contributions SET corrected = ? WHERE id = ? AND user_id = ?", (corrected, contribution_id, user_id)
        ).rowcount > 0


def count_contributions(user_id: int) -> int:
    with _connect() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM contributions WHERE user_id = ?", (user_id,)).fetchone()[0])


def delete_contributions(user_id: int) -> int:
    with _connect() as conn:
        return conn.execute("DELETE FROM contributions WHERE user_id = ?", (user_id,)).rowcount


def list_contributions(limit: int = 50) -> list[dict]:
    """관리자용: 최근 자료 (본문은 앞부분만)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, kind, created_at, source, substr(text, 1, 500) AS preview, length(text) AS chars, "
            "corrected IS NOT NULL AS corrected FROM contributions ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- 공문 번호 대장 (v3)

def list_ledger(user_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, prefix, year, seq, issued_on, title, recipient FROM ledger WHERE user_id = ? "
            "ORDER BY prefix, year, seq, id",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def count_ledger(user_id: int) -> int:
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM ledger WHERE user_id = ?", (user_id,)).fetchone()[0]


def next_ledger_seq(user_id: int, prefix: str, year: int) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT MAX(seq) FROM ledger WHERE user_id = ? AND prefix = ? AND year = ?", (user_id, prefix, year)
        ).fetchone()
    return (row[0] or 0) + 1


def add_ledger(user_id: int, prefix: str, year: int, seq: int | None, issued_on: str, title: str, recipient: str) -> None:
    """seq가 없으면 다음 번호를 같은 쓰기 트랜잭션 안에서 정한다 — 동시에 두 건을 등록해도 번호가 겹치지 않게."""
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if seq is None:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM ledger WHERE user_id = ? AND prefix = ? AND year = ?",
                (user_id, prefix, year),
            ).fetchone()
            seq = row[0]
        conn.execute(
            "INSERT INTO ledger (user_id, prefix, year, seq, issued_on, title, recipient, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, prefix, year, seq, issued_on, title, recipient, _now()),
        )


def delete_ledger(user_id: int, entry_id: int) -> bool:
    """남의 기록은 지울 수 없다 — user_id를 함께 건다."""
    with _connect() as conn:
        return conn.execute("DELETE FROM ledger WHERE id = ? AND user_id = ?", (entry_id, user_id)).rowcount > 0
