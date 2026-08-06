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
    <div className="py-8">
      <h1 className="text-xl font-bold">규정 문서 관리</h1>
      <p className="mt-1 text-sm text-zinc-500">
        업로드한 PDF는 즉시 청킹·임베딩되어 AI 분석의 근거 문서로 사용됩니다.
      </p>

      {health && (
        <div className="mt-4 flex flex-wrap gap-3 text-xs text-zinc-500">
          <span className="rounded-md bg-zinc-100 px-2 py-1 dark:bg-zinc-900">
            모델: {health.mock_mode ? "목업 모드" : health.model}
          </span>
          <span className="rounded-md bg-zinc-100 px-2 py-1 dark:bg-zinc-900">
            색인된 청크: {chunks}개
          </span>
        </div>
      )}

      <label
        className={`mt-6 flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-zinc-300 bg-white py-10 text-sm text-zinc-500 transition hover:border-blue-400 dark:border-zinc-700 dark:bg-zinc-900 ${
          busy ? "pointer-events-none opacity-50" : ""
        }`}
      >
        <span className="text-2xl" aria-hidden>
          📄
        </span>
        {busy ? "색인 중... (문서 크기에 따라 수십 초 걸릴 수 있습니다)" : "클릭하여 규정 PDF 업로드 (최대 20MB)"}
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
        <p className="mt-3 text-sm text-zinc-600 dark:text-zinc-400">{message}</p>
      )}

      <div className="mt-8">
        <h2 className="mb-3 text-sm font-semibold text-zinc-500">
          색인된 문서 ({documents.length})
        </h2>
        {documents.length === 0 ? (
          <p className="text-sm text-zinc-400">
            아직 색인된 문서가 없습니다. 규정·세칙·감사보고서 PDF를 업로드하세요.
          </p>
        ) : (
          <ul className="divide-y divide-zinc-200 rounded-xl border border-zinc-200 bg-white dark:divide-zinc-800 dark:border-zinc-800 dark:bg-zinc-900">
            {documents.map((doc) => (
              <li
                key={doc.doc_id}
                className="flex items-center justify-between gap-3 px-4 py-3"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{doc.filename}</p>
                  <p className="text-xs text-zinc-400">
                    {doc.chunks}개 청크 ·{" "}
                    {new Date(doc.created_at).toLocaleString("ko-KR")}
                  </p>
                </div>
                <button
                  onClick={() => onDelete(doc)}
                  className="shrink-0 rounded-lg border border-zinc-200 px-3 py-1.5 text-xs text-zinc-500 transition hover:border-red-300 hover:text-red-600 dark:border-zinc-700"
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
