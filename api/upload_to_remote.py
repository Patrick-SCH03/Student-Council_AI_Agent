"""documents/ 폴더의 PDF를 배포된 서버에 업로드·색인하는 CLI.

로컬 색인(ingest_folder.py)은 벡터 DB에 직접 쓰지만, 배포 서버는 원격이므로
관리자 API를 통해 업로드한다. 서버가 추출·청킹·임베딩을 수행한다.

사용법:
    python upload_to_remote.py https://xxx.up.railway.app [--token ADMIN_TOKEN]

토큰을 생략하면 환경변수 ADMIN_TOKEN(또는 .env)에서 읽는다.
이미 서버에 색인된 파일명은 건너뛴다.
"""

import argparse
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from app.config import ADMIN_TOKEN

DOCS_DIR = Path(__file__).resolve().parent.parent / "documents"
TIMEOUT = 600  # 큰 PDF의 멀티모달 추출·임베딩까지 고려


def _request(url: str, token: str, *, data: bytes | None = None, content_type: str | None = None):
    req = urllib.request.Request(url, data=data)
    req.add_header("Authorization", f"Bearer {token}")
    if content_type:
        req.add_header("Content-Type", content_type)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        import json

        return json.loads(res.read().decode("utf-8"))


def _multipart(path: Path) -> tuple[bytes, str]:
    """단일 파일 multipart/form-data 본문 생성."""
    boundary = f"----upload{uuid.uuid4().hex}"
    filename = path.name.encode("utf-8").decode("latin-1")  # 헤더 인코딩 회피
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("latin-1"),
        b"Content-Type: application/pdf\r\n\r\n",
        path.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    return body, f"multipart/form-data; boundary={boundary}"


def main() -> None:
    parser = argparse.ArgumentParser(description="배포 서버에 규정 PDF 업로드")
    parser.add_argument("base_url", help="예: https://xxx.up.railway.app")
    parser.add_argument("--token", default=ADMIN_TOKEN, help="관리자 토큰 (기본: .env의 ADMIN_TOKEN)")
    parser.add_argument("--dir", default=str(DOCS_DIR), help="PDF 폴더 경로")
    args = parser.parse_args()

    if not args.token:
        print("ADMIN_TOKEN이 필요합니다. --token 으로 전달하거나 .env에 설정하세요.")
        sys.exit(1)

    base = args.base_url.rstrip("/")
    folder = Path(args.dir)
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(f"'{folder}'에 PDF가 없습니다.")
        return

    # 서버에 이미 있는 문서 확인
    try:
        remote = _request(f"{base}/api/documents", args.token)
    except urllib.error.HTTPError as e:
        print(f"서버 연결 실패 ({e.code}): {e.read().decode('utf-8', 'replace')[:200]}")
        sys.exit(1)
    except Exception as e:
        print(f"서버 연결 실패: {e}")
        sys.exit(1)

    already = {d["filename"] for d in remote["documents"]}
    print(f"서버 현재 상태: {len(already)}개 문서 / {remote['indexed_chunks']}청크")
    print(f"로컬 PDF: {len(pdfs)}건\n")

    ok, skipped, failed = 0, 0, 0
    for i, pdf in enumerate(pdfs, 1):
        if pdf.name in already:
            print(f"[{i:2d}/{len(pdfs)}] 건너뜀  {pdf.name}")
            skipped += 1
            continue
        print(f"[{i:2d}/{len(pdfs)}] 업로드  {pdf.name} ...", end=" ", flush=True)
        try:
            body, ctype = _multipart(pdf)
            res = _request(f"{base}/api/documents", args.token, data=body, content_type=ctype)
            print(f"완료 ({res['chunks']}청크)")
            ok += 1
        except urllib.error.HTTPError as e:
            print(f"실패 ({e.code}) {e.read().decode('utf-8', 'replace')[:120]}")
            failed += 1
        except Exception as e:  # noqa: BLE001 - 한 건 실패가 전체를 멈추지 않도록
            print(f"오류 {type(e).__name__}: {e}")
            failed += 1

    final = _request(f"{base}/api/documents", args.token)
    print(
        f"\n업로드 {ok}건, 건너뜀 {skipped}건, 실패 {failed}건"
        f" / 서버 총 {len(final['documents'])}문서 · {final['indexed_chunks']}청크"
    )


if __name__ == "__main__":
    main()
