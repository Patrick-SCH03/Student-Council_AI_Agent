"use client";

// 기획 도우미: 사업 개요 → 총회 양식 초안(사업 계획서·예산운영 계획서) → 계산 점검·규정 메모.
// 예산표를 고치면 서버가 금액·예비비를 다시 계산하고 점검도 다시 한다(무료). 규정 메모(유료)는 다시 받기를 눌러야 갱신된다.

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { LoginCard } from "@/components/auth/Account";
import { useAuth } from "@/components/auth/AuthProvider";
import { Spinner } from "@/components/chat/parts";
import { Area, DateField, FileButton, Form, INPUT, Num, Text } from "@/components/form/Fields";
import { FindingSections, type NotesState } from "@/components/review/Report";
import ContributeCheck from "@/components/contrib/ContributeCheck";
import PageHeader from "@/components/shell/PageHeader";
import SaveButton from "@/components/workspace/SaveButton";
import { word } from "@/lib/office/download";
import { planDocBlocks, planFileName } from "@/lib/office/forms";
import { loadProfile, rememberProfile } from "@/lib/profile";
import {
  type EditLine,
  FUNDS,
  MAX_LINES,
  budgetProblem,
  PHASES,
  type Plan,
  type PlanInput,
  type PlanResult,
  draftPlan,
  draftTotal,
  inputProblem,
  rebuildPlan,
  suggestPlanField,
  toEdit,
} from "@/lib/plan";
import { type Finding, fetchNotes, parseWon, reportText, won } from "@/lib/review";
import { BTN_GHOST, BTN_MD, BTN_PRIMARY, BTN_SECONDARY, BTN_SM, CARD, PAGE, SECTION_TITLE } from "@/lib/ui";
import { useCopy } from "@/lib/useCopy";

const EMPTY: PlanInput = {
  title: "",
  org: "",
  purpose: "",
  target: "",
  headcount: null,
  start: "",
  end: null,
  place: "",
  fund: "학생회비",
  budget_cap: null,
  fee: null,
  activities: "",
  meeting: "",
  meeting_date: null,
  term: "",
};

/** 목적·주요 활동 칸의 AI 초안 버튼 — 사업명만 있어도 쓸 수 있다. 칸에 글이 있으면 다듬는다 */
function SuggestButton({
  field,
  input,
  onText,
}: {
  field: "purpose" | "activities";
  input: PlanInput;
  onText: (text: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const filled = !!input[field].trim();
  const ready = !!input.title.trim();
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      onText(await suggestPlanField(field, input));
    } catch (e) {
      setError(e instanceof Error ? e.message : "AI 초안을 만들지 못했어요.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="flex items-center gap-2">
      {error && (
        <span role="alert" className="text-[12px] font-semibold text-rose-600">
          {error}
        </span>
      )}
      <button
        type="button"
        disabled={!ready || busy}
        onClick={run}
        title={ready ? undefined : "사업명을 먼저 적어 주세요"}
        className="inline-flex h-7 items-center gap-1 rounded-full bg-indigo-50 px-3 text-[12px] font-bold text-indigo-700 ring-1 ring-indigo-100 transition hover:bg-indigo-100 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {busy ? <Spinner /> : <span aria-hidden>✦</span>}
        {busy ? "쓰는 중…" : filled ? "AI로 다듬기" : "AI 초안"}
      </button>
    </span>
  );
}

function PlanForm({
  input,
  onChange,
  onSubmit,
  error,
  contribute,
  onContribute,
}: {
  input: PlanInput;
  onChange: React.Dispatch<React.SetStateAction<PlanInput>>;
  onSubmit: () => void;
  error: string | null;
  contribute: boolean;
  onContribute: (v: boolean) => void;
}) {
  // 함수형 갱신: AI 초안이 도착하는 사이 다른 칸을 고쳐도 덮어쓰지 않는다
  const set = (patch: Partial<PlanInput>) => onChange((prev) => ({ ...prev, ...patch }));
  const problem = inputProblem(input);
  return (
    <>
      <Form title="사업 개요">
        <Text label="사업명" maxLength={60} value={input.title} placeholder="기말고사 간식드리미" onChange={(title) => set({ title })} />
        <Text label="기구" maxLength={40} value={input.org} placeholder="가나다학과 학생회" onChange={(org) => set({ org })} />
        <Area
          label="목적"
          maxLength={400}
          value={input.purpose}
          placeholder="시험 기간 학우를 응원하고 납부자 혜택을 주고자 해요."
          onChange={(purpose) => set({ purpose })}
          action={<SuggestButton field="purpose" input={input} onText={(purpose) => set({ purpose })} />}
        />
        <Text label="대상" maxLength={80} value={input.target} placeholder="학생회비 납부 학우" onChange={(target) => set({ target })} />
        <Num label="예상 인원" value={input.headcount ?? 0} unit="명" onChange={(v) => set({ headcount: v || null })} />
        <DateField label="시작일" value={input.start} onChange={(v) => set({ start: v ?? "" })} />
        <DateField label="끝나는 날 (하루면 비워 두기)" value={input.end} onChange={(end) => set({ end })} />
        <Text label="장소" maxLength={60} value={input.place} placeholder="(선택)" onChange={(place) => set({ place })} />
        <Num label="예산 상한 (선택)" value={input.budget_cap ?? 0} onChange={(v) => set({ budget_cap: v || null })} />
        <Num label="참가비 1인 (선택)" value={input.fee ?? 0} onChange={(v) => set({ fee: v || null })} />
        <div className="sm:col-span-2">
          <span className="text-[12px] font-semibold text-slate-500">재원</span>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {FUNDS.map((fund) => (
              <button
                key={fund}
                type="button"
                aria-pressed={input.fund === fund}
                onClick={() => set({ fund })}
                className={`rounded-full px-3 py-1.5 text-[13px] font-semibold transition ${
                  input.fund === fund ? "bg-slate-950 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200"
                }`}
              >
                {fund}
              </button>
            ))}
          </div>
        </div>
        <Area
          label="주요 활동"
          maxLength={1200}
          value={input.activities}
          placeholder="구글폼 선착순 신청, 기프티콘 지급"
          rows={4}
          onChange={(activities) => set({ activities })}
          action={<SuggestButton field="activities" input={input} onText={(activities) => set({ activities })} />}
        />
        <Text label="인준 회의 (선택)" maxLength={60} value={input.meeting} placeholder="2학기 1차 정기총회" onChange={(meeting) => set({ meeting })} />
        <DateField label="인준 회의일 (선택)" value={input.meeting_date} onChange={(meeting_date) => set({ meeting_date })} />
        <Text label="대수 (선택, 표지 명의)" maxLength={20} value={input.term} placeholder="제43대" onChange={(term) => set({ term })} />
      </Form>
      <div className="mt-3">
        <ContributeCheck checked={contribute} onChange={onContribute} />
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-end gap-3">
        {(error || problem) && (
          <p className={`text-[14px] font-semibold ${error || input.title ? "text-rose-600" : "text-slate-500"}`}>{error || problem}</p>
        )}
        <button type="button" disabled={!!problem} onClick={onSubmit} className={`${BTN_MD} ${BTN_PRIMARY}`}>
          초안 만들기
        </button>
      </div>
    </>
  );
}

const md = (iso: string) => {
  const [, m, d] = iso.split("-").map(Number);
  return `${m}.${d}`;
};

function Schedule({ plan }: { plan: Plan }) {
  return (
    <section className="mt-6">
      <h3 className={SECTION_TITLE}>사업 내용</h3>
      <div className="mt-2 space-y-3">
        {PHASES.map((phase) => {
          const rows = plan.steps.filter((s) => s.phase === phase);
          if (!rows.length) return null;
          return (
            <div key={phase}>
              <p className="text-[12px] font-bold text-slate-500">{phase}</p>
              <ul className="mt-1 space-y-1">
                {rows.map((s, i) => (
                  <li key={i} className="flex gap-3 text-[14px] text-slate-700">
                    <span className="w-10 shrink-0 tabular-nums text-slate-500">{md(s.date)}</span>
                    {s.text}
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/** 숫자 칸 오른쪽에 단위를 늘 보인다 (값을 채우면 placeholder가 사라져 무슨 칸인지 모르게 되지 않게) */
function UnitInput({ label, unit, value, onChange }: { label: string; unit: string; value: number; onChange: (v: number) => void }) {
  return (
    <label className="relative block">
      <span className="sr-only">{label}</span>
      <input
        inputMode="numeric"
        value={value ? value.toLocaleString("ko-KR") : ""}
        placeholder={label}
        onChange={(e) => onChange(Math.max(parseWon(e.target.value) ?? 0, 0))}
        className={`${INPUT} pr-8 text-right tabular-nums`}
      />
      <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-[12px] text-slate-400">{unit}</span>
    </label>
  );
}

function BudgetEditor({
  plan,
  lines,
  reserve,
  onLines,
  onReserve,
  busy,
}: {
  plan: Plan;
  lines: EditLine[];
  reserve: number;
  onLines: (lines: EditLine[]) => void;
  onReserve: (v: number) => void;
  busy: boolean;
}) {
  const set = (i: number, patch: Partial<EditLine>) => onLines(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const total = draftTotal(lines, reserve);
  // 쓸 수 있는 돈 = 예산 상한 + 참가비 × 인원 (서버 PlanIn.spend_limit과 같다)
  const fee = (plan.request.fee ?? 0) * (plan.request.headcount ?? 0);
  const cap = plan.request.budget_cap ? plan.request.budget_cap + fee : null;
  return (
    <section className="mt-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 className={SECTION_TITLE}>예산</h3>
        <span
          className={`flex items-center gap-1.5 whitespace-nowrap text-[13px] font-semibold tabular-nums ${cap && total > cap ? "text-rose-600" : "text-slate-600"}`}
        >
          {busy && <Spinner />}
          합계 {won(total)}
          {cap ? ` / 상한 ${won(cap)}${fee ? " (참가비 포함)" : ""}` : ""}
        </span>
      </div>
      <ul className="mt-2 space-y-2">
        {lines.map((l, i) => {
          const evidence = plan.lines[i]?.item === l.item ? plan.lines[i] : null;
          return (
            <li key={i} className="rounded-2xl bg-slate-50 p-3">
              <div className="grid grid-cols-[1fr_2rem] gap-2 sm:grid-cols-[1fr_8rem_5.5rem_2rem]">
                <input aria-label="항목" value={l.item} onChange={(e) => set(i, { item: e.target.value })} className={INPUT} />
                <button
                  type="button"
                  aria-label="이 줄 지우기"
                  onClick={() => onLines(lines.filter((_, j) => j !== i))}
                  className={`${BTN_SM} ${BTN_GHOST} h-9 w-8 px-0 sm:order-last`}
                >
                  ×
                </button>
                <div className="col-span-2 grid grid-cols-2 gap-2 sm:col-span-2">
                  <UnitInput label="단가" unit="원" value={l.unit_price} onChange={(unit_price) => set(i, { unit_price })} />
                  <UnitInput label="수량" unit={l.unit || "개"} value={l.qty} onChange={(qty) => set(i, { qty })} />
                </div>
              </div>
              <p className="mt-2 flex flex-wrap items-center gap-x-2 text-[12px] text-slate-500">
                <span className="font-semibold tabular-nums text-slate-700">{won(l.unit_price * l.qty)}</span>
                {l.basis && <span>· {l.basis}</span>}
                {evidence && <span>· 증빙: {evidence.evidence.join(", ")}</span>}
                {evidence?.checklist && (
                  <Link
                    href={{ pathname: "/checklist", query: { topic: evidence.checklist } }}
                    className="font-semibold text-indigo-600 hover:underline"
                  >
                    법령 점검표 →
                  </Link>
                )}
              </p>
            </li>
          );
        })}
      </ul>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          disabled={lines.length >= MAX_LINES}
          onClick={() => onLines([...lines, { item: "", unit_price: 0, qty: 1, unit: "개", basis: "" }])}
          className={`${BTN_SM} ${BTN_GHOST}`}
        >
          {lines.length >= MAX_LINES ? `${MAX_LINES}줄까지 적을 수 있어요` : "+ 줄 추가"}
        </button>
        <label className="flex items-center gap-2 text-[13px] text-slate-600">
          예비비
          <input
            aria-label="예비비"
            inputMode="numeric"
            value={reserve ? reserve.toLocaleString("ko-KR") : ""}
            placeholder="0"
            onChange={(e) => onReserve(parseWon(e.target.value) ?? 0)}
            className={`${INPUT} w-32 text-right tabular-nums`}
          />
        </label>
      </div>
    </section>
  );
}

type Notes = { state: NotesState; notes: Finding[] };

function Result({
  result,
  notes,
  onResult,
  onRefreshNotes,
  onReset,
}: {
  result: PlanResult;
  notes: Notes;
  onResult: (r: PlanResult) => void;
  onRefreshNotes: () => void;
  onReset: () => void;
}) {
  const { plan } = result;
  // 처음 받은 초안 — 고친 안을 보낼 때 사업 개요·일정은 이것을 그대로 쓴다 (화면에서는 예산만 고친다)
  const [base] = useState(plan);
  const [lines, setLines] = useState<EditLine[]>(() => toEdit(plan).lines);
  const [reserve, setReserve] = useState(plan.reserve);
  // 고친 횟수 — 0이면 처음 받은 초안 그대로. 다시 계산을 눌러도 1 늘린다
  const [edits, setEdits] = useState(0);
  // 화면의 예산이 서버 계산(result)에 아직 반영되지 않았다 — 이때 복사·저장하면 고치기 전 내용이 나간다
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, copyText] = useCopy();

  const changed = () => {
    setEdits((n) => n + 1);
    setPending(true);
    setError(null);
  };
  const editLines = (next: EditLine[]) => {
    setLines(next);
    changed();
  };
  const editReserve = (next: number) => {
    setReserve(next);
    changed();
  };

  // 예산을 고치면 잠시 뒤 서버가 다시 계산·점검 (무료). 마지막으로 고친 것의 응답만 반영한다
  const problem = budgetProblem(lines);
  useEffect(() => {
    if (!edits || problem) return;
    let alive = true;
    const timer = setTimeout(async () => {
      try {
        const next = await rebuildPlan({ ...toEdit(base), lines: lines.filter((l) => l.item.trim()), reserve });
        if (!alive) return;
        onResult(next);
        setPending(false);
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : "다시 계산하지 못했어요.");
      }
    }, 600);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [edits, lines, reserve, base, onResult, problem]);

  const copy = () => copyText(result.text);

  return (
    <section className={`p-5 sm:p-6 ${CARD}`}>
      <p className="text-[13px] font-semibold text-slate-500">
        {plan.request.org || "사업 계획서 초안"}
        {plan.method === "rule" && " · 기본 틀이에요. 항목을 직접 채워 주세요"}
      </p>
      <h2 className="mt-1 text-[22px] font-extrabold tracking-tight text-slate-950">{plan.request.title}</h2>
      <p className="mt-3 text-[15px] leading-relaxed text-slate-700">{plan.intent}</p>

      <Schedule plan={plan} />
      <BudgetEditor plan={plan} lines={lines} reserve={reserve} onLines={editLines} onReserve={editReserve} busy={pending && !error} />
      {problem && <p className="mt-2 text-[13px] font-semibold text-rose-600">{problem}</p>}
      {!problem && error && (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-[13px] font-semibold text-rose-600">
          {error}
          <button type="button" onClick={changed} className={`${BTN_SM} ${BTN_SECONDARY}`}>
            다시 계산
          </button>
        </p>
      )}

      <FindingSections findings={result.findings} notes={notes.notes} notesState={notes.state} onRefreshNotes={onRefreshNotes} />

      <div className="mt-7 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-5">
        <p className="text-[12px] text-slate-500">단가는 어림값이에요. 견적을 받아 고쳐 주세요.</p>
        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" onClick={onReset} className={`${BTN_MD} ${BTN_SECONDARY}`}>
            새로 쓰기
          </button>
          <SaveButton
            key={result.text}
            kind="plan"
            title={plan.request.title}
            text={[result.text, reportText(plan.request.title, [...result.findings, ...notes.notes])].join("\n\n")}
            disabled={pending || notes.state === "loading"}
          />
          <button type="button" onClick={copy} disabled={pending} className={`${BTN_MD} ${BTN_SECONDARY}`}>
            {copied ? "복사했어요" : "양식 복사"}
          </button>
          <FileButton file={word(planFileName(plan.request), () => planDocBlocks(plan.request, result.blocks))} disabled={pending} />
        </div>
      </div>
    </section>
  );
}

type Step = { name: "form"; error: string | null } | { name: "writing" } | { name: "result"; id: number; result: PlanResult };

export default function PlanPage() {
  const { user } = useAuth();
  const owner = user ? user.email : null;
  const [input, setInput] = useState<PlanInput>(EMPTY);
  const [contribute, setContribute] = useState(true); // 기본 허락(운영자 결정 2026-11-28), 해제 가능
  const [step, setStep] = useState<Step>({ name: "form", error: null });
  const [notes, setNotes] = useState<Notes>({ state: "loading", notes: [] });
  // 이전 초안의 늦게 온 응답이 새 화면을 덮지 않게
  const run = useRef(0);
  // 규정 메모 요청 번호 — 예산을 고치면 늘어나, 고치기 전 내용으로 받은 메모가 늦게 와도 버린다
  const notesSeq = useRef(0);

  // 규정 메모(유료)는 초안을 받았을 때와 '다시 받기'를 눌렀을 때만 부른다
  const loadNotes = (r: PlanResult, id: number) => {
    const seq = ++notesSeq.current;
    const current = () => id === run.current && seq === notesSeq.current;
    setNotes({ state: "loading", notes: [] });
    fetchNotes(r.doc, r.text.split("※ 감사 자료 확보")[0], r.findings).then(
      (n) => current() && setNotes({ state: "done", notes: n }),
      () => current() && setNotes({ state: "error", notes: [] }),
    );
  };

  const submit = async () => {
    const id = ++run.current;
    setStep({ name: "writing" });
    try {
      const result = await draftPlan(input, contribute);
      if (owner) rememberProfile(owner, { org: input.org, term: input.term }); // 다음에 열 때 기구·대수를 미리 채운다
      if (id !== run.current) return;
      setStep({ name: "result", id, result });
      loadNotes(result, id);
    } catch (e) {
      if (id === run.current) setStep({ name: "form", error: e instanceof Error ? e.message : "초안을 만들지 못했어요." });
    }
  };
  const reset = () => {
    run.current += 1;
    setStep({ name: "form", error: null });
  };
  const onResult = useCallback((result: PlanResult) => {
    setStep((s) => (s.name === "result" ? { ...s, result } : s));
    // 고친 내용은 메모에 아직 반영되지 않았다 — 받는 중인 메모도 고치기 전 내용이라 버린다
    notesSeq.current += 1;
    setNotes({ state: "stale", notes: [] });
  }, []);

  // 다른 계정으로 바뀌면 이전 계정의 입력·초안을 지우고, 그 계정이 지난번에 적은 기구·대수를 미리 채운다
  const ownerRef = useRef(owner);
  useEffect(() => {
    const changed = ownerRef.current !== owner;
    ownerRef.current = owner;
    if (changed) {
      run.current += 1;
      setStep({ name: "form", error: null });
    }
    const saved = owner ? loadProfile(owner) : null;
    // 계정이 정해진 뒤(마운트 후) 이 브라우저 저장소에서 복원 — 하이드레이션과 어긋나지 않게 effect에서
    setInput((prev) => {
      const base = changed ? EMPTY : prev;
      return saved ? { ...base, org: base.org || saved.org, term: base.term || saved.term } : base;
    });
  }, [owner]);

  return (
    <div className={PAGE}>
      <PageHeader title="기획 도우미" desc="사업 개요를 적으면 총회 양식 초안을 쓰고, 예산과 규정을 바로 점검해요." />
      <div className="mt-6">
        {user === undefined && <div className="h-48 animate-pulse rounded-3xl bg-slate-100 motion-reduce:animate-none" />}
        {user === null && <LoginCard />}
        {user && step.name === "form" && (
          <PlanForm
            input={input}
            onChange={setInput}
            onSubmit={submit}
            error={step.error}
            contribute={contribute}
            onContribute={setContribute}
          />
        )}
        {user && step.name === "writing" && (
          <div className={`flex flex-col items-center gap-3 px-6 py-12 text-center ${CARD}`} role="status">
            <Spinner className="h-6 w-6" />
            <p className="text-[16px] font-bold text-slate-950">초안을 쓰고 있어요</p>
            <p className="text-[13px] text-slate-500">보통 10~20초, 길면 1분쯤 걸려요</p>
          </div>
        )}
        {user && step.name === "result" && (
          <Result
            key={step.id}
            result={step.result}
            notes={notes}
            onResult={onResult}
            onRefreshNotes={() => loadNotes(step.result, step.id)}
            onReset={reset}
          />
        )}
      </div>
    </div>
  );
}
