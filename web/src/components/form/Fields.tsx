"use client";

// 양식 화면 공통 입력 칸과 결과 카드 (문서 작성·기획 도우미)

import { useId, useState } from "react";

import { parseWon } from "@/lib/review-model";
import { BTN_MD, BTN_PRIMARY, BTN_SECONDARY, CARD, INPUT, SECTION_TITLE } from "@/lib/ui";
import { useCopy } from "@/lib/useCopy";
import { type FileSpec, saveBlob } from "@/lib/office/download";
import type { Check } from "@/lib/writer";

export { INPUT };

export function Text({
  label,
  value,
  onChange,
  placeholder,
  wide,
  maxLength,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  wide?: boolean;
  maxLength?: number;
}) {
  return (
    <label className={wide ? "sm:col-span-2" : ""}>
      <span className="text-[12px] font-semibold text-slate-500">{label}</span>
      <input
        value={value}
        placeholder={placeholder}
        maxLength={maxLength}
        onChange={(e) => onChange(e.target.value)}
        className={`mt-1 ${INPUT}`}
      />
    </label>
  );
}

export function Area({
  label,
  value,
  onChange,
  placeholder,
  rows = 3,
  maxLength,
  action,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  rows?: number;
  maxLength?: number;
  /** 이름 오른쪽 버튼 (예: AI 초안). label 밖에 두어 이름을 눌러도 버튼이 아니라 입력 칸으로 간다 */
  action?: React.ReactNode;
}) {
  const id = useId();
  return (
    <div className="sm:col-span-2">
      <div className="flex min-h-7 items-center justify-between gap-2">
        <label htmlFor={id} className="text-[12px] font-semibold text-slate-500">
          {label}
        </label>
        {action}
      </div>
      <textarea
        id={id}
        rows={rows}
        value={value}
        placeholder={placeholder}
        maxLength={maxLength}
        onChange={(e) => onChange(e.target.value)}
        className={`mt-1 ${INPUT}`}
      />
    </div>
  );
}

export function Num({
  label,
  value,
  onChange,
  unit = "원",
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  unit?: string;
}) {
  return (
    <label>
      <span className="text-[12px] font-semibold text-slate-500">{label}</span>
      <div className="mt-1 flex items-center gap-2">
        <input
          inputMode="numeric"
          value={value ? value.toLocaleString("ko-KR") : ""}
          placeholder="0"
          onChange={(e) => onChange(parseWon(e.target.value) ?? 0)}
          className={`${INPUT} text-right tabular-nums`}
        />
        <span className="shrink-0 text-[13px] text-slate-500">{unit}</span>
      </div>
    </label>
  );
}

/** 날짜 칸. 비우면 null */
export function DateField({ label, value, onChange }: { label: string; value: string | null; onChange: (v: string | null) => void }) {
  return (
    <label>
      <span className="text-[12px] font-semibold text-slate-500">{label}</span>
      <input type="date" value={value ?? ""} onChange={(e) => onChange(e.target.value || null)} className={`mt-1 ${INPUT}`} />
    </label>
  );
}

/** Word·엑셀 받기 버튼. 만드는 동안은 눌리지 않고, 실패하면 이유를 옆에 보인다 */
export function FileButton({ file, disabled }: { file: FileSpec; disabled?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <>
      {error && <span className="self-center text-[13px] font-semibold text-rose-600">{error}</span>}
      <button
        type="button"
        disabled={busy || disabled}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            saveBlob(await file.make(), file.name);
          } catch {
            setError("파일을 만들지 못했어요. 다시 눌러 주세요.");
          } finally {
            setBusy(false);
          }
        }}
        className={`${BTN_MD} ${BTN_PRIMARY}`}
      >
        {busy ? "만드는 중…" : file.label}
      </button>
    </>
  );
}

/** preview가 있으면 화면에는 그것을, 복사에는 text를 쓴다. file이 있으면 Word·엑셀 받기가 주 버튼이다 */
/** actions: 복사 앞에 붙일 버튼 (예: 작업함에 저장) */
export function Output({
  text,
  checks,
  preview,
  actions,
  file,
}: {
  text: string;
  checks: Check[];
  preview?: React.ReactNode;
  actions?: React.ReactNode;
  file: FileSpec;
}) {
  const [copied, copy] = useCopy();
  return (
    <section className={`mt-4 p-5 sm:p-6 print:border-0 print:p-0 print:shadow-none ${CARD}`}>
      <ul className="space-y-1.5 print:hidden">
        {checks.map((c) => (
          <li key={c.text} className={`flex gap-2 text-[14px] ${c.ok ? "text-slate-600" : "font-semibold text-rose-600"}`}>
            <span aria-hidden>{c.ok ? "✓" : "!"}</span>
            {c.text}
          </li>
        ))}
      </ul>
      {preview ?? (
        <pre className="mt-4 whitespace-pre-wrap rounded-2xl bg-slate-50 p-4 font-sans text-[14px] leading-relaxed text-slate-800 print:bg-white print:p-0 print:text-[12pt]">
          {text}
        </pre>
      )}
      <div className="mt-4 flex flex-wrap justify-end gap-2 print:hidden">
        {actions}
        <button type="button" onClick={() => copy(text)} className={`${BTN_MD} ${BTN_SECONDARY}`}>
          {copied ? "복사했어요" : "복사"}
        </button>
        <FileButton file={file} />
      </div>
    </section>
  );
}

export function Form({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className={`mt-4 p-5 sm:p-6 print:hidden ${CARD}`}>
      <h2 className={SECTION_TITLE}>{title}</h2>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">{children}</div>
    </section>
  );
}
