"""로컬 색인(추출·청킹·임베딩 완료)을 배포 서버로 옮기는 CLI. LLM·임베딩 API를 부르지 않는다.

먼저 ingest_folder.py로 로컬 색인을 만든 뒤 실행한다. 서버에 없는 문서(파일명 기준)만 보낸다.
서버가 직접 OCR·임베딩하는 upload_to_remote.py와 달리 요청이 몇 초 안에 끝나고,
로컬과 운영 색인이 똑같아진다.

사용법:
    python sync_index_to_remote.py https://xxx.up.railway.app [--token ADMIN_TOKEN]
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

from app import db
from app.config import ADMIN_TOKEN, MOCK_MODE
from app.rag import store

TIMEOUT = 120


def _request(url: str, token: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data)
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return json.loads(res.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", help="배포 서버 주소")
    parser.add_argument("--token", default=ADMIN_TOKEN, help="관리자 토큰 (기본: ADMIN_TOKEN)")
    args = parser.parse_args()
    if not args.token:
        print("관리자 토큰이 없습니다 (--token 또는 ADMIN_TOKEN)", file=sys.stderr)
        return 1
    if MOCK_MODE:
        print("로컬이 목업 모드라 목업 임베딩을 운영에 올리게 됩니다 — 중단", file=sys.stderr)
        return 1

    base = args.url.rstrip("/")
    remote = {d["filename"] for d in _request(f"{base}/api/documents", args.token)["documents"]}
    local = sorted(db.list_documents(), key=lambda d: d["filename"])
    print(f"로컬 {len(local)}건 · 서버 {len(remote)}건")

    sent = failed = 0
    for i, doc in enumerate(local, 1):
        name = doc["filename"]
        if name in remote:
            continue
        chunks, embeddings = store.export_doc(doc["doc_id"])
        try:
            res = _request(f"{base}/api/index/import", args.token,
                           {"filename": name, "chunks": chunks, "embeddings": embeddings})
            print(f"[{i:2d}/{len(local)}] 전송 {name} — {res['chunks']}청크")
            sent += 1
        except urllib.error.HTTPError as e:
            print(f"[{i:2d}/{len(local)}] 실패 {name} — HTTP {e.code} {e.read().decode('utf-8', 'replace')[:120]}")
            failed += 1
    final = _request(f"{base}/api/documents", args.token)
    print(f"\n전송 {sent}건, 실패 {failed}건 / 서버 총 {len(final['documents'])}문서 · {final['indexed_chunks']}청크")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
