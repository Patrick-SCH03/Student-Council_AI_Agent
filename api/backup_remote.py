"""배포 서버의 운영 데이터(SQLite·OCR 캐시)를 받아 로컬에 보관하는 CLI. LLM 미호출, 무료.

Railway 볼륨 백업은 Pro 요금제 전용이라, 관리자 API(/api/backup)로 받아 api/backups/에 쌓는다.
받은 파일은 zip·SQLite 무결성을 확인한 뒤에만 남기고, 최근 KEEP개만 유지한다.

사용법:
    python backup_remote.py https://xxx.up.railway.app [--token ADMIN_TOKEN]

토큰을 생략하면 환경변수 ADMIN_TOKEN(또는 .env)에서 읽는다.
백업에는 마스킹된 질의 원문·IP 해시가 들어 있다 — api/backups/는 git에서 제외돼 있다.
"""

import argparse
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from app.config import ADMIN_TOKEN

BACKUP_DIR = Path(__file__).resolve().parent / "backups"
KEEP = 10
TIMEOUT = 120


def _verify(path: Path) -> dict:
    """zip이 온전하고 SQLite가 열리는지 확인한다. 실패하면 예외."""
    with zipfile.ZipFile(path) as zf:
        if (bad := zf.testzip()) is not None:
            raise ValueError(f"zip 손상: {bad}")
        names = zf.namelist()
        if "app.sqlite3" not in names:
            raise ValueError("app.sqlite3 없음")
        with tempfile.TemporaryDirectory() as tmp:
            zf.extract("app.sqlite3", tmp)
            conn = sqlite3.connect(Path(tmp) / "app.sqlite3")
            try:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("SQLite 무결성 검사 실패")
                metrics = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
            finally:
                conn.close()
    return {"metrics": metrics, "ocr_cache_files": sum(n.startswith("ocr_cache/") for n in names)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", help="배포 서버 주소 (예: https://xxx.up.railway.app)")
    parser.add_argument("--token", default=ADMIN_TOKEN, help="관리자 토큰 (기본: ADMIN_TOKEN)")
    args = parser.parse_args()
    if not args.token:
        print("관리자 토큰이 없습니다 (--token 또는 ADMIN_TOKEN)", file=sys.stderr)
        return 1

    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"backup-{stamp}.zip"
    partial = dest.with_suffix(".part")

    req = urllib.request.Request(f"{args.url.rstrip('/')}/api/backup")
    req.add_header("Authorization", f"Bearer {args.token}")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            partial.write_bytes(res.read())
    except urllib.error.HTTPError as e:
        print(f"백업 요청 실패: HTTP {e.code} (401이면 토큰 확인)", file=sys.stderr)
        return 1
    try:
        info = _verify(partial)
    except Exception as e:  # noqa: BLE001 - 손상된 백업은 남기지 않는다
        partial.unlink(missing_ok=True)
        print(f"백업 검증 실패: {e}", file=sys.stderr)
        return 1
    partial.rename(dest)

    old = sorted(BACKUP_DIR.glob("backup-*.zip"))[:-KEEP]
    for f in old:
        f.unlink()
    size_kb = dest.stat().st_size / 1024
    kept = len(list(BACKUP_DIR.glob("backup-*.zip")))
    print(f"저장: {dest.name} ({size_kb:.0f}KB) · 지표 {info['metrics']}행 · OCR 캐시 {info['ocr_cache_files']}개"
          f" · 보관 {kept}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
