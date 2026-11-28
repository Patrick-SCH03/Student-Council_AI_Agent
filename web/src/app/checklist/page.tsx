"use client";

// 법령 점검표: 주제를 고르고 항목을 하나씩 확인한다. 판정은 하지 않고, 확인할 점과 근거 조문을 보여 준다.

import Link from "next/link";
import { useEffect, useState } from "react";

import RequireLogin from "@/components/auth/RequireLogin";
import LawChat from "@/components/checklist/LawChat";
import PageHeader from "@/components/shell/PageHeader";
import { type Basis, CHECKLISTS, type CheckItem, type ConsentInput, consentText } from "@/lib/checklists";
import { josa } from "@/lib/format";
import { BTN_MD, BTN_SECONDARY, CARD, INPUT, PAGE, SECTION_TITLE } from "@/lib/ui";
import { useCopy } from "@/lib/useCopy";


function BasisChip({ b }: { b: Basis }) {
  const label = `${b.law === "재정·회계 세칙" ? "「재정·회계 세칙」" : `「${b.law}」`} ${b.article}`;
  const cls =
    "rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[12px] font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-950";
  // 학생회 세칙은 법제처에 없다 — 규정 질문으로 원문을 찾아 준다
  return b.url ? (
    <a href={b.url} target="_blank" rel="noreferrer" className={cls}>
      {label} ↗
    </a>
  ) : (
    <Link href={{ pathname: "/ask", query: { q: `${josa(label, "은", "는")} 무슨 내용인가요?` } }} className={cls}>
      {label}
    </Link>
  );
}

function Item({ item, done, onToggle }: { item: CheckItem; done: boolean; onToggle: () => void }) {
  return (
    <li className={`rounded-2xl border p-4 transition ${done ? "border-emerald-200 bg-emerald-50/50" : "border-slate-200 bg-white"}`}>
      <label className="flex cursor-pointer gap-3">
        <input type="checkbox" checked={done} onChange={onToggle} className="mt-1 h-4 w-4 shrink-0 accent-slate-900" />
        <span className="text-[15px] font-bold leading-snug text-slate-950">{item.question}</span>
      </label>
      <p className="mt-2 pl-7 text-[14px] leading-relaxed text-slate-600">{item.guide}</p>
      {item.basis && (
        <div className="mt-3 flex flex-wrap gap-1.5 pl-7">
          {item.basis.map((b) => (
            <BasisChip key={`${b.law}-${b.article}`} b={b} />
          ))}
        </div>
      )}
    </li>
  );
}

function ConsentMaker() {
  const [c, setC] = useState<ConsentInput>({ org: "", purpose: "", items: "", keep: "", refuse: "" });
  const [copied, copy] = useCopy();
  const text = consentText(c);
  const fields: [keyof ConsentInput, string, string][] = [
    ["org", "기구 이름", "가나다학과 학생회"],
    ["purpose", "목적", "새내기 새로배움터 참가 신청 확인과 안전 관리"],
    ["items", "항목", "이름, 학과, 연락처"],
    ["keep", "보관 기간", "행사 종료 후 1개월까지 보관한 뒤 파기"],
    ["refuse", "거부할 때", "행사 참가 신청이 제한될 수 있습니다"],
  ];
  return (
    <section className={`mt-4 p-5 sm:p-6 ${CARD}`}>
      <h2 className={SECTION_TITLE}>동의 문구 만들기</h2>
      <p className="mt-1 text-[14px] text-slate-500">신청서·구글폼 맨 앞에 붙여 넣어요.</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {fields.map(([key, label, placeholder]) => (
          <label key={key} className={key === "purpose" ? "sm:col-span-2" : ""}>
            <span className="text-[12px] font-semibold text-slate-500">{label}</span>
            <input
              value={c[key]}
              placeholder={placeholder}
              onChange={(e) => setC({ ...c, [key]: e.target.value })}
              className={`mt-1 ${INPUT}`}
            />
          </label>
        ))}
      </div>
      <pre className="mt-4 whitespace-pre-wrap rounded-2xl bg-slate-50 p-4 font-sans text-[13px] leading-relaxed text-slate-700">
        {text}
      </pre>
      <div className="mt-3 flex justify-end">
        <button
          type="button"
          onClick={() => copy(text)}
          className={`${BTN_MD} ${BTN_SECONDARY}`}
        >
          {copied ? "복사했어요" : "문구 복사"}
        </button>
      </div>
    </section>
  );
}

export default function ChecklistPage() {
  return (
    <div className={PAGE}>
      <PageHeader title="법령 점검표" desc="학생회 사업에서 자주 걸리는 법령을 주제별로 확인해요." />
      <RequireLogin>
        <ChecklistContent />
      </RequireLogin>
    </div>
  );
}

/** 로그인 뒤 화면 — 입력 상태를 여기 두어 계정이 바뀌면 RequireLogin이 통째로 새로 만든다 */
function ChecklistContent() {
  const [active, setActive] = useState(CHECKLISTS[0].id);
  // 문서 검토 결과에서 /checklist?topic=privacy 처럼 바로 열 수 있게 (useSearchParams는 정적 렌더에 Suspense가 필요해 마운트 후 읽는다)
  useEffect(() => {
    const topic = new URLSearchParams(window.location.search).get("topic");
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 주소의 주제를 마운트 후 한 번 반영
    if (topic && CHECKLISTS.some((c) => c.id === topic)) setActive(topic);
  }, []);
  const [done, setDone] = useState<Record<string, boolean>>({});
  const list = CHECKLISTS.find((c) => c.id === active) ?? CHECKLISTS[0];
  const count = list.items.filter((i) => done[i.id]).length;

  return (
    <>
      <div role="tablist" className="-mx-4 mt-5 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:px-0">
        {CHECKLISTS.map((c) => (
          <button
            key={c.id}
            role="tab"
            aria-selected={c.id === active}
            onClick={() => setActive(c.id)}
            className={`shrink-0 whitespace-nowrap rounded-full px-4 py-2 text-[14px] font-semibold transition ${
              c.id === active ? "bg-slate-950 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200 hover:text-slate-950"
            }`}
          >
            {c.title}
          </button>
        ))}
      </div>

      <section className={`mt-4 p-5 sm:p-6 ${CARD}`}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[18px] font-extrabold tracking-tight text-slate-950">{list.title}</h2>
            <p className="mt-1 text-[14px] text-slate-500">{list.when}</p>
          </div>
          <span className="shrink-0 rounded-full bg-slate-100 px-3 py-1 text-[12px] font-bold text-slate-600">
            {count}/{list.items.length} 확인
          </span>
        </div>
        <ul className="mt-5 space-y-2.5">
          {list.items.map((item) => (
            <Item key={item.id} item={item} done={!!done[item.id]} onToggle={() => setDone({ ...done, [item.id]: !done[item.id] })} />
          ))}
        </ul>
        <p className="mt-5 text-[12px] text-slate-500">조문 기준: {list.checkedAt}. 일반 안내이며 세무·법률 자문이 아니에요.</p>
      </section>

      <LawChat topic={list.id} />

      {list.id === "privacy" && <ConsentMaker />}
    </>
  );
}
