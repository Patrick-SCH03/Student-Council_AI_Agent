"use client";

// 감사자료 첨부: 폴더나 파일을 고르면 이름은 브라우저에서 바로 읽고(서버로 보내지 않음),
// 사업계획서·예산·정산 문서는 로그인하면 문서 검토와 같은 방식으로 내용까지 점검한다(원본 저장 안 함).

import Link from "next/link";
import { useRef, useState } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { Spinner } from "@/components/chat/parts";
import { MAX_CONTENT_FILES, contentTargets, matchSubmissions } from "@/lib/audit";
import { type Finding, MAX_BYTES, checkDoc, extractFile, won } from "@/lib/review";
import { BTN_MD, BTN_PRIMARY, BTN_SECONDARY, SECTION_TITLE } from "@/lib/ui";

export type Picked = { path: string; size: number; file: File };

type Result =
  | { state: "wait" | "run" }
  | { state: "done"; title: string; total: number | null; findings: Finding[] }
  | { state: "error"; message: string };

const pathOf = (f: File) => (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;

/** 끌어다 놓은 폴더를 끝까지 펼친다 (브라우저 파일 API) */
async function walkEntry(entry: FileSystemEntry, prefix: string, out: Picked[]): Promise<void> {
  if (entry.isFile) {
    const file = await new Promise<File>((ok, fail) => (entry as FileSystemFileEntry).file(ok, fail));
    out.push({ path: `${prefix}${file.name}`, size: file.size, file });
    return;
  }
  const reader = (entry as FileSystemDirectoryEntry).createReader();
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((ok, fail) => reader.readEntries(ok, fail));
    if (!batch.length) break;
    for (const child of batch) await walkEntry(child, `${prefix}${entry.name}/`, out);
  }
}

export default function AuditFiles({ files, onFiles }: { files: Picked[]; onFiles: (files: Picked[]) => void }) {
  // 어느 제출 자료에도 맞지 않는 파일 이름 (예: IMG_2231.JPG, 새 문서(2).hwp)
  const matched = new Set(Object.values(matchSubmissions(files.map((f) => f.path))).flat());
  const unmatched = files.map((f) => f.path.trim()).filter((p) => p && !matched.has(p)).map((p) => p.split("/").pop() ?? p);
  const { user } = useAuth();
  const folderInput = useRef<HTMLInputElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [results, setResults] = useState<Record<string, Result>>({});
  const [running, setRunning] = useState(false);

  const take = (list: FileList | null) => {
    if (!list) return;
    onFiles(Array.from(list, (file) => ({ path: pathOf(file), size: file.size, file })));
    setResults({});
  };

  const drop = async (e: React.DragEvent) => {
    e.preventDefault();
    setOver(false);
    const entries = Array.from(e.dataTransfer.items, (i) => i.webkitGetAsEntry?.()).filter((x): x is FileSystemEntry => !!x);
    if (!entries.length) return take(e.dataTransfer.files);
    const out: Picked[] = [];
    for (const entry of entries) await walkEntry(entry, "", out);
    onFiles(out);
    setResults({});
  };

  const targets = contentTargets(files, MAX_BYTES);

  const runContent = async () => {
    setRunning(true);
    setResults(Object.fromEntries(targets.map((t) => [t.path, { state: "wait" } as Result])));
    for (const t of targets) {
      setResults((r) => ({ ...r, [t.path]: { state: "run" } }));
      try {
        const ext = await extractFile(t.file);
        const findings = await checkDoc(ext.doc, ext.source);
        setResults((r) => ({
          ...r,
          [t.path]: { state: "done", title: ext.doc.title || t.file.name, total: ext.doc.expense_total, findings },
        }));
      } catch (err) {
        setResults((r) => ({ ...r, [t.path]: { state: "error", message: err instanceof Error ? err.message : "읽지 못했어요." } }));
      }
    }
    setRunning(false);
  };

  return (
    <>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
        className={`mt-3 flex flex-col items-center gap-3 rounded-2xl border-2 border-dashed px-4 py-8 text-center transition ${
          over ? "border-slate-900 bg-slate-50" : "border-slate-200"
        }`}
      >
        <p className="text-[14px] text-slate-600">감사자료 폴더를 여기에 끌어다 놓거나 골라 주세요.</p>
        <div className="flex flex-wrap justify-center gap-2">
          <button type="button" onClick={() => folderInput.current?.click()} className={`${BTN_MD} ${BTN_PRIMARY}`}>
            폴더 고르기
          </button>
          <button type="button" onClick={() => fileInput.current?.click()} className={`${BTN_MD} ${BTN_SECONDARY}`}>
            파일 고르기
          </button>
        </div>
        {files.length > 0 && <p className="text-[13px] font-semibold text-slate-700">파일 {files.length}개를 읽었어요.</p>}
        {unmatched.length > 0 && (
          <p className="text-[13px] text-amber-700">
            제출 자료 종류를 알 수 없는 파일 {unmatched.length}개 ({unmatched.slice(0, 3).join(", ")}
            {unmatched.length > 3 ? " 등" : ""}) — 파일 이름에 결산서·영수증·회의록처럼 자료 종류를 넣으면 더 정확히 점검해요.
          </p>
        )}
        <input
          ref={folderInput}
          type="file"
          className="hidden"
          // 폴더 통째로 고르기 (크롬·엣지·사파리·파이어폭스 지원)
          {...{ webkitdirectory: "", directory: "" }}
          onChange={(e) => take(e.target.files)}
        />
        <input ref={fileInput} type="file" multiple className="hidden" onChange={(e) => take(e.target.files)} />
      </div>

      {targets.length > 0 && (
        <div className="mt-5">
          <h3 className={SECTION_TITLE}>문서 내용 점검</h3>
          <p className="mt-1 text-[13px] text-slate-500">
            사업계획서·예산·정산 문서 {targets.length}개의 금액과 계산을 확인해요
            {targets.length === MAX_CONTENT_FILES ? ` (많아서 앞의 ${MAX_CONTENT_FILES}개만)` : ""}. 원본은 저장하지 않아요.
          </p>
          {user === null ? (
            <p className="mt-3 text-[14px] text-slate-700">
              <Link href="/login?next=/audit" className="font-semibold text-indigo-600 hover:underline">
                학교 계정으로 로그인
              </Link>
              하면 내용까지 점검할 수 있어요.
            </p>
          ) : (
            !Object.keys(results).length && (
              <button type="button" disabled={!user || running} onClick={runContent} className={`mt-3 ${BTN_MD} ${BTN_PRIMARY}`}>
                내용 점검 시작
              </button>
            )
          )}
          {Object.keys(results).length > 0 && (
            <ul className="mt-3 space-y-2">
              {targets.map((t) => {
                const r = results[t.path];
                return (
                  <li key={t.path} className="rounded-2xl border border-slate-200 p-4 text-[14px]">
                    <p className="truncate font-semibold text-slate-900">{t.path}</p>
                    {(!r || r.state === "wait") && <p className="mt-1 text-slate-500">기다리는 중</p>}
                    {r?.state === "run" && (
                      <p className="mt-1 flex items-center gap-2 text-slate-500">
                        <Spinner /> 읽는 중
                      </p>
                    )}
                    {r?.state === "error" && <p className="mt-1 text-rose-600">{r.message}</p>}
                    {r?.state === "done" && (
                      <>
                        <p className="mt-1 text-slate-600">
                          {r.title}
                          {r.total != null && ` · 지출 ${won(r.total)}`}
                        </p>
                        {r.findings.length === 0 ? (
                          <p className="mt-1 font-semibold text-emerald-600">계산에서 찾은 문제가 없어요.</p>
                        ) : (
                          <ul className="mt-2 space-y-1">
                            {r.findings.map((f) => (
                              <li key={`${f.code}-${f.where}-${f.title}`} className="text-slate-700">
                                <span className={f.level === "확인 필요" ? "font-semibold text-amber-600" : "font-semibold text-rose-600"}>
                                  [{f.level}]
                                </span>{" "}
                                {f.title}
                              </li>
                            ))}
                          </ul>
                        )}
                      </>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {!running && Object.values(results).some((r) => r.state === "done") && (
            <p className="mt-3 text-[13px] text-slate-500">
              규정 메모와 고칠 곳까지 보려면{" "}
              <Link href="/review" className="font-semibold text-indigo-600 hover:underline">
                문서 검토
              </Link>
              에 그 파일을 올려 주세요.
            </p>
          )}
        </div>
      )}
    </>
  );
}
