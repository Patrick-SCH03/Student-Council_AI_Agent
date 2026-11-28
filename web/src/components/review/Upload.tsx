"use client";

import { useRef, useState } from "react";

import { NavIcon } from "@/components/shell/nav";
import { ACCEPT_ATTR, fileProblem } from "@/lib/review";

/** 파일 고르기: 끌어다 놓기 또는 눌러서 선택 */
export default function Upload({ onFile, error }: { onFile: (file: File) => void; error: string | null }) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const pick = (file: File | undefined) => {
    if (!file) return;
    const p = fileProblem(file);
    setProblem(p);
    if (!p) onFile(file);
  };

  const message = problem ?? error;
  return (
    <div>
      <button
        type="button"
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          pick(e.dataTransfer.files[0]);
        }}
        className={`flex w-full flex-col items-center justify-center gap-3 rounded-3xl border-2 border-dashed px-6 py-12 text-center transition ${
          dragging ? "border-indigo-500 bg-indigo-50" : "border-indigo-200 bg-white hover:border-indigo-400 hover:bg-indigo-50/40"
        }`}
      >
        <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-950 text-white">
          <NavIcon path={<path d="M12 16V4m0 0l-4 4m4-4l4 4M4 20h16" />} />
        </span>
        <span className="text-[16px] font-bold text-slate-950">사업계획서·예산안·결산서 올리기</span>
        <span className="text-[13px] text-slate-500">PDF·한글·워드·엑셀 · 15MB까지 · 파일은 저장하지 않아요</span>
      </button>
      <input
        ref={input}
        type="file"
        accept={ACCEPT_ATTR}
        className="hidden"
        onChange={(e) => {
          pick(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      {message && (
        <p role="alert" className="mt-3 text-center text-[13px] font-medium text-rose-600">
          {message}
        </p>
      )}
    </div>
  );
}
