"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  type DocumentInfo,
  type HealthInfo,
  deleteDocument,
  fetchDocuments,
  fetchHealth,
  uploadDocument,
} from "@/lib/api";

const CARD_SHADOW =
  "shadow-[0px_12px_16px_-4px_rgba(16,24,40,0.08),0px_4px_6px_-2px_rgba(16,24,40,0.03)]";

export default function AdminPage() {
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [chunks, setChunks] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const [docs, h] = await Promise.all([fetchDocuments(), fetchHealth()]);
      setDocuments(docs.documents);
      setChunks(docs.indexed_chunks);
      setHealth(h);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "백엔드 연결 실패");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const onUpload = async (file: File) => {
    setBusy(true);
    setMessage(null);
    try {
      const info = await uploadDocument(file);
      setMessage(`✅ '${info.filename}' 색인 완료 (${info.chunks}개 청크)`);
      await refresh();
    } catch (e) {
      setMessage(`❌ ${e instanceof Error ? e.message : "업로드 실패"}`);
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const onDelete = async (doc: DocumentInfo) => {
    if (!confirm(`'${doc.filename}' 문서와 색인을 삭제할까요?`)) return;
    try {
      await deleteDocument(doc.doc_id);
      await refresh();
    } catch (e) {
      setMessage(`❌ ${e instanceof Error ? e.message : "삭제 실패"}`);
    }
  };

  return (
    <div className="py-10">
      <h1 className="text-[30px] font-extrabold tracking-tight text-slate-800">
        규정 문서 관리
      </h1>
      <p className="mt-1.5 text-[15px] font-medium text-slate-500">
        업로드한 PDF는 즉시 청킹·임베딩되어 AI 분석의 근거 문서로 사용됩니다.
      </p>

      {health && (
        <div className="mt-5 flex flex-wrap gap-2 text-xs font-bold">
          <span className="rounded-full bg-indigo-50 px-3 py-1.5 text-indigo-600">
            {health.mock_mode ? "목업 모드" : health.model}
          </span>
          <span className="rounded-full bg-slate-100 px-3 py-1.5 text-slate-600">
            색인된 청크 {chunks}개
          </span>
        </div>
      )}

      <label
        className={`mt-6 flex cursor-pointer flex-col items-center justify-center gap-2.5 rounded-[24px] border-2 border-dashed border-slate-300 bg-white py-12 text-sm font-medium text-slate-500 transition hover:border-indigo-400 hover:text-indigo-600 ${CARD_SHADOW} ${
          busy ? "pointer-events-none opacity-50" : ""
        }`}
      >
        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-indigo-50 text-xl" aria-hidden>
          📄
        </span>
        {busy
          ? "색인 중... (문서 크기에 따라 수십 초 걸릴 수 있습니다)"
          : "클릭하여 규정 PDF 업로드 (최대 20MB)"}
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf"
          className="hidden"
          disabled={busy}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onUpload(f);
          }}
        />
      </label>

      {message && (
        <p className="mt-3 text-sm font-medium text-slate-600">{message}</p>
      )}

      <div className="mt-10">
        <h2 className="mb-3 text-sm font-bold text-slate-500">
          색인된 문서 ({documents.length})
        </h2>
        {documents.length === 0 ? (
          <p className="text-sm font-medium text-slate-400">
            아직 색인된 문서가 없습니다. 규정·세칙·감사보고서 PDF를 업로드하세요.
          </p>
        ) : (
          <ul
            className={`divide-y divide-slate-100 rounded-2xl border border-slate-200 bg-white ${CARD_SHADOW}`}
          >
            {documents.map((doc) => (
              <li
                key={doc.doc_id}
                className="flex items-center justify-between gap-3 px-5 py-4"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-bold text-slate-700">
                    {doc.filename}
                  </p>
                  <p className="mt-0.5 text-xs font-medium text-slate-400">
                    {doc.chunks}개 청크 ·{" "}
                    {new Date(doc.created_at).toLocaleString("ko-KR")}
                  </p>
                </div>
                <button
                  onClick={() => onDelete(doc)}
                  className="shrink-0 rounded-full border border-slate-200 px-4 py-1.5 text-xs font-bold text-slate-500 transition hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600"
                >
                  삭제
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
