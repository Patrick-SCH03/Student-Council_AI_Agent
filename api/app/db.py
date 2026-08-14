"""SQLite 저장소: 색인 문서 목록과 분석 이력.

v1은 분석 결과를 외부 Notion에 기록했지만, v2는 자체 DB에 저장해
서비스 기능(이력 조회)으로 노출한다.
"""

import json
import re
import sqlite3
from datetime import datetime, timezone

from app.config import SQLITE_PATH

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
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    # 스키마 확장 마이그레이션 (기존 DB 호환)
    for stmt in (
        "ALTER TABLE metrics ADD COLUMN analysis_id INTEGER",
        "ALTER TABLE metrics ADD COLUMN visitor_id TEXT",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # 이미 존재
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


def delete_document(doc_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    return cur.rowcount > 0


# ---------------------------------------------------------------- analyses

def add_analysis(query: str, risk_level: str | None, result: dict) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO analyses (query, risk_level, result, created_at) VALUES (?, ?, ?, ?)",
            (query, risk_level, json.dumps(result, ensure_ascii=False), _now()),
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
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO metrics (ts, route, risk_level, status, elapsed, input_tokens, output_tokens, "
            "query_preview, analysis_id, visitor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _now(), route, risk_level, status, elapsed, input_tokens, output_tokens,
                query_preview[:500], analysis_id, visitor_id,
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


# ---------------------------------------------------------------- 답변 캐시

def normalize_query(query: str) -> str:
    """캐시 키 생성: 공백·문장부호를 제거해 표기 차이를 흡수한다."""
    return re.sub(r"[\s?!.,·…]+", "", query).lower()


def get_cached_answer(query_key: str, ttl_hours: int) -> dict | None:
    """TTL 이내의 캐시된 답변을 반환하고 적중 횟수를 올린다."""
    if ttl_hours <= 0:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT analysis_id, result FROM answer_cache "
            "WHERE query_key = ? AND ts >= datetime('now', ?)",
            (query_key, f"-{ttl_hours} hours"),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE answer_cache SET hits = hits + 1 WHERE query_key = ?", (query_key,)
        )
    return {"analysis_id": row["analysis_id"], **json.loads(row["result"])}


def save_cached_answer(query_key: str, analysis_id: int, result: dict) -> None:
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


def clear_cache() -> int:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM answer_cache")
    return cur.rowcount


def add_feedback(analysis_id: int, helpful: bool, visitor_id: str | None) -> None:
    """답변 만족도 기록. 같은 답변에 다시 누르면 갱신된다."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO feedback (analysis_id, ts, helpful, visitor_id) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(analysis_id) DO UPDATE SET "
            "helpful = excluded.helpful, ts = excluded.ts",
            (analysis_id, _now(), 1 if helpful else 0, visitor_id),
        )


def count_today(visitor_id: str | None = None) -> int:
    """오늘 처리한 질의 수. visitor_id를 주면 해당 사용자 기준으로 센다."""
    with _connect() as conn:
        if visitor_id:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM metrics "
                "WHERE date(ts) = date('now') AND visitor_id = ?",
                (visitor_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM metrics WHERE date(ts) = date('now')"
            ).fetchone()
    return row["n"]


def add_visit(visitor_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO visits (ts, visitor_id) VALUES (?, ?)", (_now(), visitor_id)
        )


def export_metrics_csv() -> str:
    """포트폴리오/분석용 전체 지표 CSV 덤프."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT ts, route, risk_level, status, elapsed, input_tokens, output_tokens, query_preview "
            "FROM metrics ORDER BY id"
        ).fetchall()
    lines = ["ts,route,risk_level,status,elapsed,input_tokens,output_tokens,query"]
    for r in rows:
        query = (r["query_preview"] or "").replace('"', '""')
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
            "COALESCE(SUM(CASE WHEN status != 'ok' THEN 1 ELSE 0 END), 0) AS errors "
            "FROM metrics"
        ).fetchone())

        today = dict(conn.execute(
            # 캐시 적중은 LLM을 호출하지 않으므로 평균 응답 시간 계산에서 제외한다
            "SELECT COUNT(*) AS count, "
            "COALESCE(AVG(CASE WHEN status != 'cached' THEN elapsed END), 0) AS avg_elapsed, "
            "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
            "COALESCE(SUM(output_tokens), 0) AS output_tokens "
            "FROM metrics WHERE date(ts) = date('now')"
        ).fetchone())

        daily = [dict(r) for r in conn.execute(
            "SELECT date(ts) AS date, COUNT(*) AS count, "
            "COALESCE(AVG(CASE WHEN status != 'cached' THEN elapsed END), 0) AS avg_elapsed, "
            "COALESCE(SUM(input_tokens + output_tokens), 0) AS tokens "
            "FROM metrics WHERE ts >= datetime('now', ?) "
            "GROUP BY date(ts) ORDER BY date",
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
            "m.input_tokens + m.output_tokens AS tokens, m.query_preview, f.helpful "
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
                "SELECT COUNT(DISTINCT visitor_id) AS n FROM visits WHERE date(ts) = date('now')"
            ).fetchone()["n"],
            "total_visitors": conn.execute(
                "SELECT COUNT(DISTINCT visitor_id) AS n FROM visits"
            ).fetchone()["n"],
            "total_visits": conn.execute("SELECT COUNT(*) AS n FROM visits").fetchone()["n"],
        }

        daily_visits = [dict(r) for r in conn.execute(
            "SELECT date(ts) AS date, COUNT(DISTINCT visitor_id) AS visitors "
            "FROM visits WHERE ts >= datetime('now', ?) GROUP BY date(ts) ORDER BY date",
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
    }


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
