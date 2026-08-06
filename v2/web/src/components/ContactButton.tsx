"use client";

// 오류 신고·문의 버튼: mailto는 기본 메일 앱이 없으면 무반응이므로
// 클릭 시 주소 복사 팝오버를 제공한다.

import { useEffect, useRef, useState } from "react";

const EMAIL = "wwoo5241@inha.edu";
const MAILTO = `mailto:${EMAIL}?subject=${encodeURIComponent("[학생회 규정 AI] 오류 신고 / 문의")}`;

export default function ContactButton() {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(EMAIL);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // 클립보드 권한 거부 시 무시 (주소는 화면에 표시되어 있음)
    }
  };

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-full border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-500 transition hover:border-indigo-300 hover:text-indigo-600"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.6}
          strokeLinecap="round"
          strokeLinejoin="round"
          className="h-3.5 w-3.5"
          aria-hidden
        >
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <path d="m3 7 9 6 9-6" />
        </svg>
        오류 신고·문의
      </button>

      {open && (
        <div className="absolute right-0 top-full z-20 mt-2 w-64 rounded-2xl border border-slate-200 bg-white p-4 shadow-[0px_12px_16px_-4px_rgba(16,24,40,0.12),0px_4px_6px_-2px_rgba(16,24,40,0.05)]">
          <p className="text-xs font-bold text-slate-800">
            오류나 개선 의견을 보내주세요
          </p>
          <p className="mt-2 select-all rounded-lg bg-slate-50 px-3 py-2 text-center text-sm font-bold text-indigo-600">
            {EMAIL}
          </p>
          <div className="mt-2.5 flex gap-1.5">
            <button
              type="button"
              onClick={copy}
              className="flex-1 rounded-full bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white transition hover:bg-indigo-700"
            >
              {copied ? "✓ 복사됨" : "주소 복사"}
            </button>
            <a
              href={MAILTO}
              className="flex-1 rounded-full border border-slate-200 px-3 py-1.5 text-center text-xs font-medium text-slate-500 transition hover:border-indigo-300 hover:text-indigo-600"
            >
              메일 앱으로
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
