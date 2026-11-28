"use client";

import Link from "next/link";

import { useCopy } from "@/lib/useCopy";
import { Spinner } from "@/components/chat/parts";
import SaveButton from "@/components/workspace/SaveButton";
import { type Finding, LEVELS, type Level, checklistTopic, reportText } from "@/lib/review";
import { BTN_MD, BTN_PRIMARY, BTN_SECONDARY, BTN_SM, CARD, SECTION_TITLE } from "@/lib/ui";

const TONE: Record<Level, { card: string; badge: string }> = {
  "위반 소지": { card: "border-rose-200 bg-rose-50/50", badge: "bg-rose-600" },
  "보완 필요": {
    card: "border-amber-200 bg-amber-50/50",
    badge: "bg-amber-500",
  },
  "확인 필요": { card: "border-slate-200 bg-slate-50", badge: "bg-slate-500" },
};

function FindingItem({ f }: { f: Finding }) {
  const topic = checklistTopic(f);
  return (
    <li className={`rounded-2xl border p-4 ${TONE[f.level].card}`}>
      <p className="text-[15px] font-bold leading-snug text-slate-950">
        <span className={`mr-2 inline-block rounded-md px-1.5 py-0.5 align-[2px] text-[11px] font-bold text-white ${TONE[f.level].badge}`}>
          {f.level}
        </span>
        {f.title}
      </p>
      {f.detail && <p className="mt-1.5 text-[14px] leading-relaxed text-slate-700">{f.detail}</p>}
      {(f.basis || f.where) && (
        <p className="mt-2 text-[12px] leading-relaxed text-slate-500">
          {f.basis}
          {f.basis && f.where ? " · " : ""}
          {f.where}
        </p>
      )}
      {topic && (
        <Link
          href={{ pathname: "/checklist", query: { topic } }}
          className="mt-2 inline-block text-[13px] font-semibold text-indigo-600 hover:underline"
        >
          법령 점검표 보기 →
        </Link>
      )}
    </li>
  );
}

export type NotesState = "loading" | "done" | "error" | "stale";

/** 계산 점검 + 규정 메모 (문서 검토·기획 도우미 공통). stale은 고친 뒤 아직 메모를 다시 받지 않은 상태 */
export function FindingSections({
  findings,
  notes,
  notesState,
  onRefreshNotes,
}: {
  findings: Finding[];
  notes: Finding[];
  notesState: NotesState;
  onRefreshNotes?: () => void;
}) {
  return (
    <>
      {findings.length > 0 && (
        <>
          <h3 className={`mt-6 ${SECTION_TITLE}`}>계산 점검</h3>
          <ul className="mt-2 space-y-2.5">
            {findings.map((f) => (
              <FindingItem key={`${f.code}-${f.title}`} f={f} />
            ))}
          </ul>
        </>
      )}

      <h3 className={`mt-6 ${SECTION_TITLE}`}>규정 메모</h3>
      {notesState === "loading" && (
        <p className="mt-2 flex items-center gap-2 text-[14px] text-slate-500">
          <Spinner /> 관련 조항을 찾아 보고 있어요
        </p>
      )}
      {notesState === "error" && (
        <p className="mt-2 text-[14px] text-slate-500">규정 메모를 만들지 못했어요. 계산 점검 결과는 그대로 볼 수 있어요.</p>
      )}
      {notesState === "done" &&
        (notes.length > 0 ? (
          <ul className="mt-2 space-y-2.5">
            {notes.map((f) => (
              <FindingItem key={`${f.code}-${f.title}`} f={f} />
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-[14px] text-slate-500">덧붙일 규정 메모가 없어요.</p>
        ))}

      {notesState === "stale" && (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-[14px] text-slate-500">
          내용을 고쳐서 규정 메모를 다시 받아야 해요.
          {onRefreshNotes && (
            <button type="button" onClick={onRefreshNotes} className={`${BTN_SM} ${BTN_SECONDARY}`}>
              다시 받기
            </button>
          )}
        </p>
      )}
    </>
  );
}

export default function Report({
  title,
  findings,
  notes,
  notesState,
  onEdit,
  onReset,
}: {
  title: string;
  findings: Finding[];
  notes: Finding[];
  notesState: NotesState;
  onEdit: () => void;
  onReset: () => void;
}) {
  const [copied, copyText] = useCopy();
  const all = [...findings, ...notes];
  const counts = LEVELS.map((level) => [level, all.filter((f) => f.level === level).length] as const).filter(([, n]) => n > 0);

  const copy = () => copyText(reportText(title, all));

  return (
    <section className={`p-5 sm:p-6 ${CARD}`}>
      <p className="truncate text-[13px] font-semibold text-slate-500">{title}</p>
      <h2 className="mt-1 text-[22px] font-extrabold tracking-tight text-slate-950">
        {all.length > 0 ? `점검 사항 ${all.length}건` : "계산으로 확인한 범위에서 점검 사항이 없어요"}
      </h2>
      {counts.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {counts.map(([level, n]) => (
            <span key={level} className={`rounded-full px-2.5 py-1 text-[12px] font-bold text-white ${TONE[level].badge}`}>
              {level} {n}
            </span>
          ))}
        </div>
      )}

      <FindingSections findings={findings} notes={notes} notesState={notesState} />

      <div className="mt-7 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-5">
        <p className="text-[12px] text-slate-500">AI 점검은 참고용이에요. 인준·감사 판단을 대신하지 않아요.</p>
        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" onClick={onEdit} className={`${BTN_MD} ${BTN_SECONDARY}`}>
            표 고치기
          </button>
          <SaveButton key={`${all.length}-${notesState}`} kind="review" title={title} text={reportText(title, all)} disabled={notesState === "loading"} />
          <button type="button" onClick={copy} className={`${BTN_MD} ${BTN_SECONDARY}`}>
            {copied ? "복사했어요" : "결과 복사"}
          </button>
          <button type="button" onClick={onReset} className={`${BTN_MD} ${BTN_PRIMARY}`}>
            다른 문서
          </button>
        </div>
      </div>
    </section>
  );
}
