"""documents/ 폴더와 색인을 동기화하는 CLI.

사용법:
    python ingest_folder.py [폴더경로]

폴더 인자를 생략하면 저장소 루트의 documents/ 폴더를 사용한다.

동작 (폴더가 진실의 원천):
- 신규 파일  → 색인
- 수정 파일  → 파일 수정 시각이 색인 시각보다 나중이면 기존 색인 삭제 후 재색인
- 삭제 파일  → 폴더에 없는 색인 항목 제거 (이름이 바뀐 옛 항목 포함)
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

from app import db
from app.config import MOCK_MODE
from app.rag import store
from app.rag.ingest import IngestError, ingest_pdf

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "documents"


def _file_mtime_utc(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def main() -> None:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    if not folder.is_dir():
        print(f"폴더가 없습니다: {folder}")
        sys.exit(1)

    if MOCK_MODE:
        print("경고: GEMINI_API_KEY가 없어 목업 임베딩으로 색인됩니다. (실서비스용 아님)")

    pdfs = {p.name: p for p in sorted(folder.glob("*.pdf"))}
    indexed = {d["filename"]: d for d in db.list_documents()}

    added, updated, removed, skipped, failed = 0, 0, 0, 0, 0

    # 1) 폴더에 없는 색인 항목 제거 (삭제되었거나 파일명이 바뀐 옛 항목)
    for name, doc in indexed.items():
        if name not in pdfs:
            store.delete_doc(doc["doc_id"])
            db.delete_document(doc["doc_id"])
            print(f"[제거]   {name} — 폴더에 없음")
            removed += 1

    # 2) 신규/수정 파일 색인
    for name, pdf in pdfs.items():
        doc = indexed.get(name)
        is_update = False

        if doc:
            indexed_at = datetime.fromisoformat(doc["created_at"])
            if _file_mtime_utc(pdf) <= indexed_at:
                skipped += 1
                continue
            # 색인 이후 파일이 수정됨 → 기존 색인 삭제 후 재색인
            store.delete_doc(doc["doc_id"])
            db.delete_document(doc["doc_id"])
            is_update = True

        try:
            doc_id, chunks = ingest_pdf(pdf.read_bytes(), name)
            db.add_document(doc_id, name, chunks)
            label = "갱신" if is_update else "완료"
            print(f"[{label}]   {name} — {chunks}개 청크")
            if is_update:
                updated += 1
            else:
                added += 1
        except IngestError as e:
            print(f"[실패]   {name} — {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001 - 한 문서 실패가 전체를 중단시키지 않도록
            print(f"[오류]   {name} — {type(e).__name__}: {e}")
            failed += 1

    if added or updated or removed:
        # 인용 그래프는 색인의 파생물 — 색인이 바뀌면 함께 재생성해 낡음을 방지한다
        from app.rag import citation_graph

        citation_graph.get_graph(rebuild=True)
        # 서버 업로드 경로와 같은 이유 — 옛 근거로 만든 답변이 캐시에서 계속 나가면 안 된다
        cleared = db.clear_cache()
        print(f"인용 그래프 재생성 완료 · 답변 캐시 {cleared}건 삭제")

    print(
        f"\n신규 {added}건, 갱신 {updated}건, 제거 {removed}건, "
        f"변경 없음 {skipped}건, 실패 {failed}건 / 총 청크: {store.chunk_count()}"
    )


if __name__ == "__main__":
    main()
