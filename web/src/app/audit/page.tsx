"use client";

// 정기감사 대비 (오픈 예정 — 관리자 계정만 미리 쓴다): 질문에 답하고 감사자료 폴더를 고르면, 위험 항목·빠진 제출자료·파일명 문제를 보여 준다.
// 답과 파일 이름은 브라우저 안에서만 쓴다. 금액 문서의 내용 점검만 로그인 후 문서 검토와 같은 방식으로 서버를 거친다.

import Link from "next/link";
import { useMemo, useState } from "react";

import AuditFiles, { type Picked } from "@/components/audit/AuditFiles";
import RequireLogin from "@/components/auth/RequireLogin";
import PageHeader from "@/components/shell/PageHeader";
import { useCanPreview } from "@/components/shell/SoonBadge";
import { type Answer, QUESTIONS, SUBMISSIONS, matchSubmissions, nameWarnings, riskyQuestions } from "@/lib/audit";
import { CARD, PAGE, SECTION_TITLE } from "@/lib/ui";

const CHOICES: [Answer, string][] = [
  ["yes", "예"],
  ["no", "아니요"],
  ["na", "해당 없음"],
];

function Choice({ value, onChange }: { value: Answer | undefined; onChange: (v: Answer) => void }) {
  return (
    <div className="flex shrink-0 gap-1">
      {CHOICES.map(([v, label]) => (
        <button
          key={v}
          type="button"
          aria-pressed={value === v}
          onClick={() => onChange(v)}
          className={`h-8 rounded-full px-3 text-[13px] font-semibold transition ${
            value === v ? "bg-slate-950 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200 hover:text-slate-950"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

export default function AuditPage() {
  const admin = useCanPreview();
  return (
    <div className={PAGE}>
      <PageHeader
        title="정기감사 대비"
        desc={admin ? "지난 감사에서 반복된 처분 유형으로 미리 점검해요. 답과 파일 이름은 이 브라우저 밖으로 나가지 않아요." : undefined}
      />
      {admin === undefined ? (
        <div className="mt-6 h-48 animate-pulse rounded-3xl bg-slate-100 motion-reduce:animate-none" />
      ) : admin ? (
        // 관리자 계정(파일럿 테스트)만 실제 화면을 쓴다
        <RequireLogin>
          <AuditContent />
        </RequireLogin>
      ) : (
        <section className={`mt-6 flex flex-col items-center gap-3 px-6 py-14 text-center ${CARD}`}>
          <span className="rounded-full bg-slate-200 px-3 py-1 text-[12px] font-bold text-slate-600">오픈 예정</span>
          <h2 className="text-[18px] font-extrabold tracking-tight text-slate-950">오픈 준비 중이에요</h2>
        </section>
      )}
    </div>
  );
}

/** 로그인 뒤 화면 — 입력 상태를 여기 두어 계정이 바뀌면 RequireLogin이 통째로 새로 만든다 */
function AuditContent() {
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  const [picked, setPicked] = useState<Picked[]>([]);

  const files = useMemo(() => picked.map((p) => p.path), [picked]);
  const matched = useMemo(() => matchSubmissions(files), [files]);
  const warnings = useMemo(() => nameWarnings(files), [files]);
  const risky = riskyQuestions(answers);
  const answered = Object.keys(answers).length;

  return (
    <>
      <section className={`mt-6 p-5 sm:p-6 ${CARD}`}>
        <div className="flex items-baseline justify-between">
          <h2 className={SECTION_TITLE}>1. 질문에 답해 주세요</h2>
          <span className="text-[12px] font-semibold text-slate-500">
            {answered}/{QUESTIONS.length}
          </span>
        </div>
        <ul className="mt-3 divide-y divide-slate-100">
          {QUESTIONS.map((q) => (
            <li key={q.id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
              <span className="text-[15px] font-medium leading-snug text-slate-900">{q.text}</span>
              <Choice value={answers[q.id]} onChange={(v) => setAnswers({ ...answers, [q.id]: v })} />
            </li>
          ))}
        </ul>
      </section>

      <section className={`mt-4 p-5 sm:p-6 ${CARD}`}>
        <h2 className={SECTION_TITLE}>2. 감사자료를 첨부해 주세요</h2>
        <p className="mt-1 text-[14px] text-slate-500">폴더째 고르면 13종 제출자료와 파일 이름을 바로 점검해요.</p>
        <AuditFiles files={picked} onFiles={setPicked} />
      </section>

      <section className={`mt-4 p-5 sm:p-6 ${CARD}`}>
        <h2 className="text-[18px] font-extrabold tracking-tight text-slate-950">점검 결과</h2>

        <h3 className={`mt-4 ${SECTION_TITLE}`}>처분 위험 {risky.length}건</h3>
        {risky.length === 0 ? (
          <p className="mt-1 text-[14px] text-slate-500">
            {answered ? "답한 범위에서는 위험 항목이 없어요." : "질문에 답하면 여기에 보여요."}
          </p>
        ) : (
          <ul className="mt-2 space-y-2.5">
            {risky.map((q) => (
              <li key={q.id} className="rounded-2xl border border-rose-200 bg-rose-50/50 p-4">
                <p className="text-[15px] font-bold text-slate-950">{q.text}</p>
                <p className="mt-1.5 text-[14px] leading-relaxed text-slate-700">{q.todo}</p>
                <p className="mt-1.5 text-[12px] text-slate-500">{q.why}</p>
                <Link
                  href={{ pathname: "/ask", query: { q: q.ask } }}
                  className="mt-2 inline-block text-[13px] font-semibold text-indigo-600 hover:underline"
                >
                  규정으로 확인하기 →
                </Link>
              </li>
            ))}
          </ul>
        )}

        <h3 className={`mt-6 ${SECTION_TITLE}`}>제출자료 13종</h3>
        {files.length === 0 ? (
          <p className="mt-1 text-[14px] text-slate-500">감사자료를 첨부하면 빠진 자료를 찾아요.</p>
        ) : (
          <ul className="mt-2 grid gap-1.5 sm:grid-cols-2">
            {SUBMISSIONS.map((s) => {
              const hit = matched[s.id];
              return (
                <li key={s.id} className="flex items-center justify-between gap-2 rounded-xl bg-slate-50 px-3 py-2 text-[14px]">
                  <span className="text-slate-800">{s.name}</span>
                  <span className={`shrink-0 text-[12px] font-bold ${hit.length ? "text-emerald-600" : "text-rose-600"}`}>
                    {hit.length ? `있음 ${hit.length}` : "없음"}
                  </span>
                </li>
              );
            })}
          </ul>
        )}

        {warnings.length > 0 && (
          <>
            <h3 className={`mt-6 ${SECTION_TITLE}`}>파일 이름 고칠 것 {warnings.length}건</h3>
            <ul className="mt-2 space-y-1.5">
              {warnings.map((w, i) => (
                <li key={`${w.file}-${i}`} className="rounded-xl border border-amber-200 bg-amber-50/50 px-3 py-2 text-[13px]">
                  <span className="font-semibold text-slate-900">{w.file}</span>
                  <span className="text-slate-600"> — {w.reason}</span>
                </li>
              ))}
            </ul>
          </>
        )}

        <p className="mt-6 text-[12px] text-slate-500">자가점검이에요. 감사 결과를 예측하거나 보장하지 않아요.</p>
      </section>
    </>
  );
}
