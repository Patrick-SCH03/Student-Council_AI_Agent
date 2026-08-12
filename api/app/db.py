"""SQLite 저장소: 색인 문서 목록과 분석 이력.

v1은 분석 결과를 외부 Notion에 기록했지만, v2는 자체 DB에 저장해
서비스 기능(이력 조회)으로 노출한다.
"""

import json
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
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    # 스키마 확장 마이그레이션 (기존 DB 호환)
    try:
        conn.execute("ALTER TABLE metrics ADD COLUMN analysis_id INTEGER")
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
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO metrics (ts, route, risk_level, status, elapsed, input_tokens, output_tokens, query_preview, analysis_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_now(), route, risk_level, status, elapsed, input_tokens, output_tokens, query_preview[:500], analysis_id),
        )


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
            "SELECT COUNT(*) AS count, COALESCE(AVG(elapsed), 0) AS avg_elapsed, "
            "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
            "COALESCE(SUM(output_tokens), 0) AS output_tokens, "
            "COALESCE(SUM(CASE WHEN status != 'ok' THEN 1 ELSE 0 END), 0) AS errors "
            "FROM metrics"
        ).fetchone())

        today = dict(conn.execute(
            "SELECT COUNT(*) AS count, COALESCE(AVG(elapsed), 0) AS avg_elapsed, "
            "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
            "COALESCE(SUM(output_tokens), 0) AS output_tokens "
            "FROM metrics WHERE date(ts) = date('now')"
        ).fetchone())

        daily = [dict(r) for r in conn.execute(
            "SELECT date(ts) AS date, COUNT(*) AS count, "
            "COALESCE(AVG(elapsed), 0) AS avg_elapsed, "
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
            "SELECT id, analysis_id, ts, route, risk_level, status, elapsed, "
            "input_tokens + output_tokens AS tokens, query_preview "
            "FROM metrics ORDER BY id DESC LIMIT 20"
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
