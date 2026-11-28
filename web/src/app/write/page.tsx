"use client";

// 문서 작성: 양식을 고르고 칸을 채우면 미리보기·검산·복사·인쇄. 이름·학번·서명 칸은 비워 두고 손으로 채운다.

import { Fragment, useEffect, useState } from "react";

import { Area, Form, INPUT, Num, Output, Text } from "@/components/form/Fields";
import { blocksText } from "@/lib/office/blocks";
import { excelBlob, fileName, word } from "@/lib/office/download";
import { appointBlocks, changeBlocks, incidentBlocks, letterBlocks, paymentBlocks } from "@/lib/office/forms";
import RequireLogin from "@/components/auth/RequireLogin";
import PageHeader from "@/components/shell/PageHeader";
import LedgerPanel from "@/components/write/LedgerPanel";
import MinutesForm from "@/components/write/MinutesForm";
import { parseWon } from "@/lib/review-model";
import { type ProjectSummary, parseBudgets, parseSpends, settle, settleIssues, settleTsv } from "@/lib/settle";
import { BTN_GHOST, BTN_SM, PAGE } from "@/lib/ui";
import {
  type AppointInput,
  CAUSES,
  appointChecks,
  appointText,
  type ChangeInput,
  type Check,
  type IncidentInput,
  type ItemRow,
  type LetterInput,
  type PaymentInput,
  changeChecks,
  changeText,
  incidentChecks,
  incidentText,
  letterChecks,
  localToday,
  paymentChecks,
  paymentText,
} from "@/lib/writer";

function PaymentSheet({ p }: { p: PaymentInput }) {
  const per = p.unit * p.times;
  const cell = "border border-slate-300 px-2 py-2 print:border-black";
  return (
    <div className="mt-4 rounded-2xl bg-white p-4 text-[14px] text-slate-800 ring-1 ring-slate-200 print:p-0 print:ring-0">
      <h3 className="text-center text-[20px] font-extrabold tracking-[0.3em]">지급 확인서</h3>
      <dl className="mt-4 grid grid-cols-[6rem_1fr] gap-y-1">
        <dt className="text-slate-500">행사명</dt>
        <dd>{p.event || "○○ 행사"}</dd>
        <dt className="text-slate-500">지급 사유</dt>
        <dd>
          {p.reason || "○○"} (1인 {per.toLocaleString("ko-KR")}원)
        </dd>
        <dt className="text-slate-500">지급 방법</dt>
        <dd>{p.method}</dd>
        <dt className="text-slate-500">합계</dt>
        <dd className="font-bold">
          {(per * p.people).toLocaleString("ko-KR")}원 ({p.people}명)
        </dd>
      </dl>
      <table className="mt-4 w-full border-collapse text-center text-[13px]">
        <thead>
          <tr>
            {["번호", "성명", "학과(소속)", "연락처", "금액", "서명"].map((h) => (
              <th key={h} className={`${cell} bg-slate-50 font-semibold`}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: Math.max(p.people, 1) }, (_, i) => (
            <tr key={i}>
              <td className={cell}>{i + 1}</td>
              <td className={cell} />
              <td className={cell} />
              <td className={cell} />
              <td className={`${cell} text-right tabular-nums`}>{per.toLocaleString("ko-KR")}원</td>
              <td className={cell} />
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-4 text-center">위 금액을 정히 수령하였음을 확인합니다.</p>
      <p className="mt-2 text-center tracking-[0.4em]">20　.　.　.</p>
    </div>
  );
}

type OrgProps = { org: string };

function PaymentForm({ org }: OrgProps) {
  const [p, setP] = useState<PaymentInput>({ event: "", reason: "심판 수당", method: "계좌이체", people: 5, unit: 20_000, times: 1 });
  return (
    <>
      <Form title="지급 확인서">
        <Text label="행사명" value={p.event} placeholder="학과 체육대회" onChange={(event) => setP({ ...p, event })} />
        <Text label="지급 사유" value={p.reason} placeholder="심판 수당·상금·강사 사례금" onChange={(reason) => setP({ ...p, reason })} />
        <Num label="1회 단가" value={p.unit} onChange={(unit) => setP({ ...p, unit })} />
        <Num label="횟수(경기 수 등)" value={p.times} unit="회" onChange={(times) => setP({ ...p, times })} />
        <Num label="받는 사람 수" value={p.people} unit="명" onChange={(people) => setP({ ...p, people })} />
        <label>
          <span className="text-[12px] font-semibold text-slate-500">지급 방법</span>
          <select
            value={p.method}
            onChange={(e) => setP({ ...p, method: e.target.value as PaymentInput["method"] })}
            className={`mt-1 ${INPUT}`}
          >
            {["계좌이체", "상품권", "현금"].map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </label>
      </Form>
      <Output
        text={paymentText(p)}
        checks={paymentChecks(p)}
        preview={<PaymentSheet p={p} />}
        file={word(`${p.event || "행사"} 지급 확인서`, () => paymentBlocks(p, org))}
      />
    </>
  );
}

function IncidentForm({ org }: OrgProps) {
  const [c, setC] = useState<IncidentInput>({
    date: "",
    what: "",
    causes: [],
    rows: [{ name: "", qty: 1, unit: 0 }],
    stated: null,
    followUp: "",
  });
  const setRow = (i: number, patch: Partial<ItemRow>) => setC({ ...c, rows: c.rows.map((r, j) => (j === i ? { ...r, ...patch } : r)) });
  return (
    <>
      <Form title="경위서">
        <Text label="발생일" value={c.date} placeholder="2026. 3. 7." onChange={(date) => setC({ ...c, date })} />
        <Num label="문서에 적을 금액(검산용)" value={c.stated ?? 0} onChange={(v) => setC({ ...c, stated: v || null })} />
        <Area
          label="무엇이 있었나요"
          value={c.what}
          placeholder="온라인 주문 물품 일부를 환불받았어요."
          onChange={(what) => setC({ ...c, what })}
        />
        <div className="sm:col-span-2">
          <span className="text-[12px] font-semibold text-slate-500">원인</span>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {CAUSES.map((cause) => {
              const on = c.causes.includes(cause);
              return (
                <button
                  key={cause}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setC({ ...c, causes: on ? c.causes.filter((x) => x !== cause) : [...c.causes, cause] })}
                  className={`rounded-full px-3 py-1.5 text-[13px] font-semibold transition ${on ? "bg-slate-950 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200"}`}
                >
                  {cause}
                </button>
              );
            })}
          </div>
        </div>
        <div className="sm:col-span-2">
          <span className="text-[12px] font-semibold text-slate-500">금액표</span>
          {c.rows.map((r, i) => (
            <div key={i} className="mt-2 grid grid-cols-[1fr_5rem_7rem] gap-2">
              <input
                aria-label="품목"
                value={r.name}
                placeholder="품목"
                onChange={(e) => setRow(i, { name: e.target.value })}
                className={INPUT}
              />
              <input
                aria-label="수량"
                inputMode="numeric"
                value={r.qty || ""}
                placeholder="수량"
                onChange={(e) => setRow(i, { qty: parseWon(e.target.value) ?? 0 })}
                className={`${INPUT} text-right`}
              />
              <input
                aria-label="단가"
                inputMode="numeric"
                value={r.unit ? r.unit.toLocaleString("ko-KR") : ""}
                placeholder="단가"
                onChange={(e) => setRow(i, { unit: parseWon(e.target.value) ?? 0 })}
                className={`${INPUT} text-right`}
              />
            </div>
          ))}
          <button
            type="button"
            onClick={() => setC({ ...c, rows: [...c.rows, { name: "", qty: 1, unit: 0 }] })}
            className={`mt-2 ${BTN_SM} ${BTN_GHOST}`}
          >
            + 줄 추가
          </button>
        </div>
        <Area
          label="후속 조치"
          value={c.followUp}
          placeholder="주문 전 수량을 두 사람이 확인해요."
          onChange={(followUp) => setC({ ...c, followUp })}
        />
      </Form>
      <Output text={incidentText(c)} checks={incidentChecks(c)} file={word("경위서", () => incidentBlocks(c, org))} />
    </>
  );
}

function ChangeForm({ org }: OrgProps) {
  const [c, setC] = useState<ChangeInput>({ item: "", approved: 0, spent: 0, reserve: 0, budgetTotal: 0, reason: "" });
  return (
    <>
      <Form title="예산 변경 사유서">
        <Text label="항목" value={c.item} placeholder="숙박비" wide onChange={(item) => setC({ ...c, item })} />
        <Num label="인준 금액" value={c.approved} onChange={(approved) => setC({ ...c, approved })} />
        <Num label="실제 집행 금액" value={c.spent} onChange={(spent) => setC({ ...c, spent })} />
        <Num label="예비비 편성액" value={c.reserve} onChange={(reserve) => setC({ ...c, reserve })} />
        <Num label="사업 예산 총액(10% 확인용)" value={c.budgetTotal} onChange={(budgetTotal) => setC({ ...c, budgetTotal })} />
        <Area
          label="변경 사유"
          value={c.reason}
          placeholder="참가 인원이 늘어 숙박비가 올랐어요."
          onChange={(reason) => setC({ ...c, reason })}
        />
      </Form>
      <Output
        text={changeText(c)}
        checks={changeChecks(c)}
        file={word(`${c.item || "예산"} 변경 사유서`, () => changeBlocks(c, org))}
      />
    </>
  );
}

function LetterForm() {
  const today = localToday();
  const [l, setL] = useState<LetterInput>({ number: "", date: today, to: "", cc: "", title: "", body: "", attachments: "", from: "" });
  return (
    <>
      <Form title="공문">
        <Text
          label="문서번호"
          value={l.number}
          placeholder={`가나다학과-${today.slice(0, 4)}-0001`}
          onChange={(number) => setL({ ...l, number })}
        />
        <label>
          <span className="text-[12px] font-semibold text-slate-500">시행일자</span>
          <input type="date" value={l.date} onChange={(e) => setL({ ...l, date: e.target.value })} className={`mt-1 ${INPUT}`} />
        </label>
        <Text label="수신" value={l.to} placeholder="총대의원회" onChange={(to) => setL({ ...l, to })} />
        <Text label="참조" value={l.cc} placeholder="(선택)" onChange={(cc) => setL({ ...l, cc })} />
        <Text label="제목" value={l.title} placeholder="1학기 사업 자료 제출" wide onChange={(title) => setL({ ...l, title })} />
        <Area
          label="본문"
          value={l.body}
          placeholder="2026학년도 1학기 사업계획서와 예산안을 붙임과 같이 제출합니다."
          onChange={(body) => setL({ ...l, body })}
        />
        <Area
          label="붙임 (한 줄에 하나)"
          value={l.attachments}
          placeholder={"사업계획서 1부\n예산안 1부"}
          onChange={(attachments) => setL({ ...l, attachments })}
        />
        <Text label="발신 명의" value={l.from} placeholder="가나다학과 학생회장" onChange={(from) => setL({ ...l, from })} />
        <Text
          label="기안자 (선택)"
          value={l.drafter ?? ""}
          placeholder="수석집행국장 홍길동"
          onChange={(drafter) => setL({ ...l, drafter })}
        />
        <Text
          label="연락처 줄 (선택)"
          value={l.contact ?? ""}
          placeholder="우편 22212 주소 인천광역시 미추홀구 인하로 100 / 전화 032-000-0000 / 이메일"
          wide
          onChange={(contact) => setL({ ...l, contact })}
        />
      </Form>
      <Output
        text={blocksText(letterBlocks(l))}
        checks={letterChecks(l)}
        file={word(`공문 ${l.title || ""}`, () => letterBlocks(l))}
      />
      <LedgerPanel date={l.date} title={l.title} recipient={l.to} onNumber={(number) => setL((prev) => ({ ...prev, number }))} />
    </>
  );
}

function AppointForm({ org }: OrgProps) {
  const [a, setA] = useState<AppointInput>({ org: "", date: "", head: "", rows: [{ kind: "임명", role: "", name: "" }] });
  const setRow = (i: number, patch: Partial<AppointInput["rows"][number]>) =>
    setA({ ...a, rows: a.rows.map((r, j) => (j === i ? { ...r, ...patch } : r)) });
  return (
    <>
      <Form title="사령 공고">
        <Text label="기구 이름" value={a.org} placeholder={org || "가나다학과 학생회"} onChange={(o) => setA({ ...a, org: o })} />
        <label>
          <span className="text-[12px] font-semibold text-slate-500">효력 발생일</span>
          <input type="date" value={a.date} onChange={(e) => setA({ ...a, date: e.target.value })} className={`mt-1 ${INPUT}`} />
        </label>
        <div className="sm:col-span-2">
          <span className="text-[12px] font-semibold text-slate-500">임면 사항</span>
          {a.rows.map((r, i) => (
            <div key={i} className="mt-2 grid grid-cols-[6.5rem_1fr_1fr] gap-2">
              <select
                aria-label="임면 구분"
                value={r.kind}
                onChange={(e) => setRow(i, { kind: e.target.value as "임명" | "사의수리" })}
                className={INPUT}
              >
                <option>임명</option>
                <option>사의수리</option>
              </select>
              <input
                aria-label="직책"
                value={r.role}
                placeholder="직책 (예: 재무국장)"
                onChange={(e) => setRow(i, { role: e.target.value })}
                className={INPUT}
              />
              <input
                aria-label="이름"
                value={r.name}
                placeholder="이름"
                onChange={(e) => setRow(i, { name: e.target.value })}
                className={INPUT}
              />
            </div>
          ))}
          <button
            type="button"
            onClick={() => setA({ ...a, rows: [...a.rows, { kind: "임명", role: "", name: "" }] })}
            className={`mt-2 ${BTN_SM} ${BTN_GHOST}`}
          >
            + 사람 추가
          </button>
        </div>
        <Text label="공고하는 사람" value={a.head} placeholder="가나다학과 학생회장" wide onChange={(head) => setA({ ...a, head })} />
      </Form>
      <Output text={appointText(a)} checks={appointChecks(a, org)} file={word("사령 공고", () => appointBlocks(a, org))} />
    </>
  );
}

function SettleSheet({ summary }: { summary: ProjectSummary[] }) {
  const cell = "border border-slate-300 px-2 py-1.5 print:border-black";
  return (
    <div className="mt-4 overflow-x-auto rounded-2xl bg-white ring-1 ring-slate-200 print:ring-0">
      <table className="w-full min-w-[560px] border-collapse text-[13px] text-slate-800">
        <thead>
          <tr>
            {["월", "일", "사업명", "상세내용", "금액", "영수증번호"].map((h) => (
              <th key={h} className={`${cell} bg-slate-50 font-semibold`}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {summary.map((p) => (
            <Fragment key={p.project}>
              {p.rows.map((r) => (
                <tr key={r.receipt}>
                  <td className={`${cell} text-center tabular-nums`}>{r.month}</td>
                  <td className={`${cell} text-center tabular-nums`}>{r.day}</td>
                  <td className={cell}>{p.project}</td>
                  <td className={cell}>{r.detail}</td>
                  <td className={`${cell} text-right tabular-nums`}>{r.amount.toLocaleString("ko-KR")}</td>
                  <td className={`${cell} text-center tabular-nums`}>{r.receipt}</td>
                </tr>
              ))}
              <tr className="bg-slate-50 font-semibold">
                <td className={cell} colSpan={4}>
                  {p.project} 합계{p.budget != null && ` (예산 ${p.budget.toLocaleString("ko-KR")})`}
                </td>
                <td className={`${cell} text-right tabular-nums`}>{p.spent.toLocaleString("ko-KR")}</td>
                <td className={`${cell} text-center tabular-nums ${p.diff != null && p.diff < 0 ? "text-rose-600" : ""}`}>
                  {p.diff == null
                    ? "예산 없음"
                    : p.diff === 0
                      ? "일치"
                      : `${p.diff > 0 ? "잔액" : "초과"} ${Math.abs(p.diff).toLocaleString("ko-KR")}`}
                </td>
              </tr>
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SettleForm() {
  const [unit, setUnit] = useState("");
  const [budgetText, setBudgetText] = useState("");
  const [spendText, setSpendText] = useState("");
  const { spends, bad } = parseSpends(spendText);
  const { budgets, bad: badBudgets } = parseBudgets(budgetText);
  const summary = settle(unit, spends, budgets);
  const checks: Check[] = [
    ...(badBudgets.length ? [{ ok: false, text: `인준 예산 ${badBudgets.join(", ")}번째 줄을 읽지 못했어요 (사업명·금액 확인)` }] : []),
    ...(bad.length ? [{ ok: false, text: `지출 내역 ${bad.join(", ")}번째 줄을 읽지 못했어요 (날짜·사업명·금액 확인)` }] : []),
    ...settleIssues(summary, spends).map((i) => ({ ok: false, text: i.text })),
  ];
  if (spends.length && !checks.length) checks.push({ ok: true, text: "사업별 결산이 인준 예산과 맞아요" });
  return (
    <>
      <Form title="정산표">
        <Text label="단위 약칭 (영수증 번호 앞자리)" value={unit} placeholder="가나다" onChange={setUnit} />
        <div className="hidden sm:block" />
        <Area
          label="인준 예산 — 엑셀에서 '사업명 · 금액' 두 열을 복사해 붙여 넣기"
          value={budgetText}
          placeholder={"간식드리미\t385,000\n체육대회\t1,500,000"}
          onChange={setBudgetText}
        />
        <Area
          label="지출 내역 — '날짜 · 사업명 · 상세내용 · 금액 · (계정)' 열을 붙여 넣기"
          rows={6}
          value={spendText}
          placeholder={"5/28\t간식드리미\t싸이버거 50개\t385,000"}
          onChange={setSpendText}
        />
      </Form>
      {spends.length > 0 && (
        <Output
          text={settleTsv(summary)}
          checks={checks}
          preview={<SettleSheet summary={summary} />}
          file={{
            label: "엑셀로 받기",
            name: fileName(`${unit || "학생회"} 사업별 정산서`, "xlsx"),
            make: () => excelBlob(unit, summary, settleIssues(summary, spends)),
          }}
        />
      )}
    </>
  );
}

const KINDS: { id: string; label: string; Form: (props: OrgProps) => React.ReactNode }[] = [
  { id: "payment", label: "지급 확인서", Form: PaymentForm },
  { id: "incident", label: "경위서", Form: IncidentForm },
  { id: "change", label: "예산 변경 사유서", Form: ChangeForm },
  { id: "letter", label: "공문", Form: LetterForm },
  { id: "appoint", label: "사령 공고", Form: AppointForm },
  { id: "settle", label: "정산표", Form: SettleForm },
  { id: "minutes", label: "회의록 정리", Form: MinutesForm },
];

const ORG_KEY = "write-org";

export default function WritePage() {
  const [kind, setKind] = useState(KINDS[0].id);
  const [org, setOrg] = useState("");
  const Active = (KINDS.find((k) => k.id === kind) ?? KINDS[0]).Form;
  // 기구 이름은 이 브라우저에만 기억한다 (Word 문서 머리에 들어감). 하이드레이션이 어긋나지 않게 마운트 후 읽는다
  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- 하이드레이션 안전을 위한 마운트 후 복원
      setOrg(localStorage.getItem(ORG_KEY) ?? "");
    } catch {
      // 저장소 차단 환경은 무시
    }
  }, []);
  const saveOrg = (value: string) => {
    setOrg(value);
    try {
      localStorage.setItem(ORG_KEY, value.trim());
    } catch {
      // 저장소 차단 환경은 무시
    }
  };
  return (
    <div className={PAGE}>
      <div className="print:hidden">
        <PageHeader title="문서 작성" desc="양식을 채우면 숫자를 검산하고 Word·엑셀 파일로 만들어요." />
      </div>
      <RequireLogin>
        <div
          role="tablist"
          className="-mx-4 mt-5 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:px-0 print:hidden"
        >
          {KINDS.map((k) => (
            <button
              key={k.id}
              role="tab"
              aria-selected={k.id === kind}
              onClick={() => setKind(k.id)}
              className={`shrink-0 whitespace-nowrap rounded-full px-4 py-2 text-[14px] font-semibold transition ${
                k.id === kind ? "bg-slate-950 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200 hover:text-slate-950"
              }`}
            >
              {k.label}
            </button>
          ))}
        </div>
        <label className="mt-4 flex max-w-md items-center gap-3 print:hidden">
          <span className="shrink-0 text-[13px] font-semibold text-slate-500">우리 기구</span>
          <input
            value={org}
            onChange={(e) => saveOrg(e.target.value)}
            placeholder="가나다학과 학생회 — Word 문서 머리에 들어가요"
            maxLength={40}
            className={INPUT}
          />
        </label>
        <Active key={kind} org={org} />
      </RequireLogin>
    </div>
  );
}
