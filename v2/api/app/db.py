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
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
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
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO metrics (ts, route, risk_level, status, elapsed, input_tokens, output_tokens, query_preview) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (_now(), route, risk_level, status, elapsed, input_tokens, output_tokens, query_preview[:80]),
        )


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
            "SELECT ts, route, risk_level, status, elapsed, "
            "input_tokens + output_tokens AS tokens, query_preview "
            "FROM metrics ORDER BY id DESC LIMIT 20"
        ).fetchall()]

    return {
        "totals": totals,
        "today": today,
        "daily": daily,
        "risk": risk,
        "routes": routes,
        "recent": recent,
    }


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
