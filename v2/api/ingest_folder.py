"""documents/ 폴더의 PDF를 일괄 색인하는 CLI.

사용법:
    python ingest_folder.py [폴더경로]

폴더 인자를 생략하면 저장소 루트의 documents/ 폴더를 사용한다.
이미 색인된 파일명(documents 테이블 기준)은 건너뛴다.
"""

import sys
from pathlib import Path

from app import db
from app.config import MOCK_MODE
from app.rag.ingest import IngestError, ingest_pdf

DEFAULT_DIR = Path(__file__).resolve().parent.parent.parent / "documents"


def main() -> None:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    if not folder.is_dir():
        print(f"폴더가 없습니다: {folder}")
        sys.exit(1)

    if MOCK_MODE:
        print("경고: GEMINI_API_KEY가 없어 목업 임베딩으로 색인됩니다. (실서비스용 아님)")

    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(f"'{folder}'에 PDF가 없습니다.")
        return

    already = {d["filename"] for d in db.list_documents()}
    ok, skipped, failed = 0, 0, 0

    for pdf in pdfs:
        if pdf.name in already:
            print(f"[건너뜀] {pdf.name} — 이미 색인됨")
            skipped += 1
            continue
        try:
            doc_id, chunks = ingest_pdf(pdf.read_bytes(), pdf.name)
            db.add_document(doc_id, pdf.name, chunks)
            print(f"[완료]   {pdf.name} — {chunks}개 청크")
            ok += 1
        except IngestError as e:
            print(f"[실패]   {pdf.name} — {e}")
            failed += 1

    print(f"\n색인 {ok}건, 건너뜀 {skipped}건, 실패 {failed}건")


if __name__ == "__main__":
    main()
