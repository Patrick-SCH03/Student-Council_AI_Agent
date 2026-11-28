"use client";

// 읽어 온 예산표 확인: 숫자가 원문과 다르면 여기서 고친 뒤 점검한다 (추출 실수가 점검 결과로 번지지 않게).

import { type BudgetDoc, type Headcount, type Line, parseWon, won } from "@/lib/review";
import { BTN_GHOST, BTN_MD, BTN_PRIMARY, BTN_SECONDARY, BTN_SM, CARD, INPUT, SECTION_TITLE } from "@/lib/ui";


function AmountInput({ value, onChange, label }: { value: number | null; onChange: (v: number | null) => void; label: string }) {
  return (
    <input
      inputMode="numeric"
      aria-label={label}
      value={value == null ? "" : value.toLocaleString("ko-KR")}
      onChange={(e) => onChange(parseWon(e.target.value))}
      placeholder="0"
      className={`${INPUT} text-right tabular-nums`}
    />
  );
}

function LinesEditor({
  name,
  lines,
  total,
  onLines,
  onTotal,
}: {
  name: string;
  lines: Line[];
  total: number | null;
  onLines: (lines: Line[]) => void;
  onTotal: (v: number | null) => void;
}) {
  const update = (i: number, patch: Partial<Line>) => onLines(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const sum = lines.every((l) => l.amount != null) ? lines.reduce((a, l) => a + (l.amount ?? 0), 0) : null;
  return (
    <section>
      <div className="flex items-baseline justify-between">
        <h3 className={SECTION_TITLE}>{name}</h3>
        <span className="text-[12px] text-slate-500">항목 합 {won(sum)}</span>
      </div>
      <ul className="mt-2 space-y-2">
        {lines.map((line, i) => (
          <li key={i} className="grid grid-cols-[1fr_8.5rem_2rem] items-center gap-2">
            <input aria-label={`${name} 항목`} value={line.item} onChange={(e) => update(i, { item: e.target.value })} className={INPUT} />
            <AmountInput label={`${name} 금액`} value={line.amount} onChange={(v) => update(i, { amount: v })} />
            <button
              type="button"
              aria-label="이 줄 지우기"
              onClick={() => onLines(lines.filter((_, j) => j !== i))}
              className={`${BTN_SM} ${BTN_GHOST} h-8 w-8 px-0`}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      <div className="mt-2 grid grid-cols-[1fr_8.5rem_2rem] items-center gap-2">
        <button
          type="button"
          onClick={() => onLines([...lines, { item: "", amount: null, note: "" }])}
          className={`${BTN_SM} ${BTN_GHOST} justify-self-start`}
        >
          + 줄 추가
        </button>
        <AmountInput label={`${name} 합계`} value={total} onChange={onTotal} />
        <span className="text-[12px] font-semibold text-slate-500">합계</span>
      </div>
    </section>
  );
}

/** 인원 × 단가 계산: 무리(신입생·재학생)마다 인원·단가, 그리고 문서에 적힌 금액 */
function HeadcountsEditor({ headcounts, onChange }: { headcounts: Headcount[]; onChange: (h: Headcount[]) => void }) {
  const update = (i: number, patch: Partial<Headcount>) => onChange(headcounts.map((h, j) => (j === i ? { ...h, ...patch } : h)));
  const setPart = (i: number, k: number, key: "counts" | "unit_prices", v: number | null) => {
    const list = [...headcounts[i][key]];
    list[k] = v ?? 0;
    update(i, { [key]: list });
  };
  return (
    <section>
      <h3 className={SECTION_TITLE}>인원 × 단가</h3>
      <ul className="mt-2 space-y-3">
        {headcounts.map((h, i) => (
          <li key={i} className="rounded-2xl bg-slate-50 p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[14px] font-semibold text-slate-800">{h.label}</span>
              <button type="button" onClick={() => onChange(headcounts.filter((_, j) => j !== i))} className={`${BTN_SM} ${BTN_GHOST}`}>
                빼기
              </button>
            </div>
            {h.counts.map((count, k) => (
              <div key={k} className="mt-2 grid grid-cols-[1fr_auto_1fr] items-center gap-2">
                <input
                  inputMode="numeric"
                  aria-label="인원"
                  value={count.toLocaleString("ko-KR")}
                  onChange={(e) => setPart(i, k, "counts", parseWon(e.target.value))}
                  className={`${INPUT} text-right tabular-nums`}
                />
                <span className="text-[13px] text-slate-500">명 ×</span>
                <AmountInput label="단가" value={h.unit_prices[k] ?? null} onChange={(v) => setPart(i, k, "unit_prices", v)} />
              </div>
            ))}
            <div className="mt-2 grid grid-cols-[1fr_auto] items-center gap-2">
              <AmountInput label="문서에 적힌 금액" value={h.stated_amount} onChange={(stated_amount) => update(i, { stated_amount })} />
              <span className="text-[12px] font-semibold text-slate-500">문서 금액</span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[12px] font-semibold text-slate-500">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

export default function ConfirmTable({
  doc,
  onChange,
  onConfirm,
  onReset,
  method,
  busy,
}: {
  doc: BudgetDoc;
  onChange: (doc: BudgetDoc) => void;
  onConfirm: () => void;
  onReset: () => void;
  method: "ai" | "rule";
  busy: boolean;
}) {
  const set = (patch: Partial<BudgetDoc>) => onChange({ ...doc, ...patch });
  const event = doc.event_dates[0];
  return (
    <section className={`p-5 sm:p-6 ${CARD}`}>
      <h2 className="text-[18px] font-extrabold tracking-tight text-slate-950">읽어 온 예산표를 확인해 주세요</h2>
      <p className="mt-1 text-[14px] text-slate-500">
        {method === "rule" ? "표 모양을 일부만 읽었어요. " : ""}원문과 다른 숫자가 있으면 고친 뒤 점검해요.
      </p>

      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        <Field label="인준 회의일">
          <input type="date" value={doc.meeting_date ?? ""} onChange={(e) => set({ meeting_date: e.target.value || null })} className={INPUT} />
        </Field>
        <Field label={`사업 시작일${event ? ` · ${event.label}` : ""}`}>
          <input
            type="date"
            value={event?.start ?? ""}
            onChange={(e) =>
              set({
                event_dates: [
                  { label: event?.label ?? "사업", start: e.target.value || null, end: event?.end ?? null, text: event?.text ?? "" },
                  ...doc.event_dates.slice(1),
                ],
              })
            }
            className={INPUT}
          />
        </Field>
      </div>

      <div className="mt-6 space-y-6">
        <LinesEditor name="수입" lines={doc.income} total={doc.income_total} onLines={(income) => set({ income })} onTotal={(income_total) => set({ income_total })} />
        <LinesEditor name="지출" lines={doc.expense} total={doc.expense_total} onLines={(expense) => set({ expense })} onTotal={(expense_total) => set({ expense_total })} />
        <section>
          <h3 className={SECTION_TITLE}>수입/지출 총계</h3>
          <div className="mt-2 grid grid-cols-3 gap-2">
            <Field label="수입금">
              <AmountInput label="총계 수입금" value={doc.summary_income} onChange={(summary_income) => set({ summary_income })} />
            </Field>
            <Field label="지출금">
              <AmountInput label="총계 지출금" value={doc.summary_expense} onChange={(summary_expense) => set({ summary_expense })} />
            </Field>
            <Field label="차액">
              <AmountInput label="총계 차액" value={doc.balance} onChange={(balance) => set({ balance })} />
            </Field>
          </div>
        </section>
        {doc.headcounts.length > 0 && (
          <HeadcountsEditor headcounts={doc.headcounts} onChange={(headcounts) => set({ headcounts })} />
        )}
      </div>

      <div className="mt-7 flex flex-wrap items-center justify-end gap-2 border-t border-slate-100 pt-5">
        <button type="button" onClick={onReset} disabled={busy} className={`${BTN_MD} ${BTN_SECONDARY}`}>
          다른 문서
        </button>
        <button type="button" onClick={onConfirm} disabled={busy} className={`${BTN_MD} ${BTN_PRIMARY}`}>
          {busy ? "점검하고 있어요…" : "이대로 점검하기"}
        </button>
      </div>
    </section>
  );
}
