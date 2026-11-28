"use client";

// 공문 번호 대장: 다음 번호 받기·등록·목록. 로그인하지 않았으면 안내만 보여 준다.

import Link from "next/link";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { type Ledger, addEntry, deleteEntry, entryNumber, fetchLedger, nextNumber } from "@/lib/ledger";
import { localToday } from "@/lib/writer";
import { BTN_GHOST, BTN_MD, BTN_PRIMARY, BTN_SECONDARY, BTN_SM, CARD, INPUT, SECTION_TITLE } from "@/lib/ui";


export default function LedgerPanel({
  date,
  title,
  recipient,
  onNumber,
}: {
  date: string;
  title: string;
  recipient: string;
  onNumber: (number: string) => void;
}) {
  const { user } = useAuth();
  const [prefix, setPrefix] = useState("");
  const [ledger, setLedger] = useState<Ledger | null>(null);
  // 받은 번호는 그때의 약칭·연도와 함께 둔다 — 약칭을 바꾼 뒤 등록하면 옛 번호를 쓰지 않는다
  const [reserved, setReserved] = useState<{ prefix: string; year: number; seq: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const owner = user ? user.email : null;
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 계정이 바뀌면 이전 계정의 대장을 바로 지운다
    setLedger(null);
    setReserved(null);
    if (!owner) return;
    let alive = true;
    fetchLedger().then(
      (l) => alive && setLedger(l),
      (e) => alive && setError(e.message),
    );
    return () => {
      alive = false;
    };
  }, [owner]);

  if (!user) {
    return (
      <section className={`mt-4 p-5 print:hidden ${CARD}`}>
        <h2 className={SECTION_TITLE}>공문 번호 대장</h2>
        <p className="mt-1 text-[14px] text-slate-500">
          <Link href="/login?next=/write" className="font-semibold text-indigo-600 hover:underline">
            로그인
          </Link>
          하면 다음 번호를 자동으로 받고, 빠진 번호·겹친 번호를 찾아 줘요.
        </p>
      </section>
    );
  }

  const year = Number((date || localToday()).slice(0, 4));
  const run = async (fn: () => Promise<void>) => {
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "처리하지 못했어요.");
    }
  };

  return (
    <section className={`mt-4 p-5 sm:p-6 print:hidden ${CARD}`}>
      <h2 className={SECTION_TITLE}>공문 번호 대장</h2>
      <p className="mt-1 text-[14px] text-slate-500">번호·날짜·제목·수신만 저장해요. 본문은 저장하지 않아요.</p>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="min-w-0 flex-1">
          <span className="text-[12px] font-semibold text-slate-500">기구 약칭</span>
          <input value={prefix} placeholder="가나다학과" onChange={(e) => setPrefix(e.target.value)} className={`mt-1 ${INPUT}`} />
        </label>
        <button
          type="button"
          disabled={!prefix.trim()}
          onClick={() =>
            run(async () => {
              const next = await nextNumber(prefix.trim(), year);
              setReserved({ prefix: prefix.trim(), year, seq: next.seq });
              onNumber(next.number);
            })
          }
          className={`${BTN_MD} ${BTN_SECONDARY}`}
        >
          다음 번호 받기
        </button>
        <button
          type="button"
          disabled={!prefix.trim() || !title.trim() || !date}
          onClick={() =>
            run(async () => {
              const same = reserved && reserved.prefix === prefix.trim() && reserved.year === year;
              setLedger(await addEntry({ prefix: prefix.trim(), issued_on: date, title, recipient, ...(same ? { seq: reserved.seq } : {}) }));
              setReserved(null);
            })
          }
          className={`${BTN_MD} ${BTN_PRIMARY}`}
        >
          대장에 등록
        </button>
      </div>
      {error && (
        <p role="alert" className="mt-2 text-[13px] font-medium text-rose-600">
          {error}
        </p>
      )}
      {ledger && ledger.problems.length > 0 && (
        <ul className="mt-3 space-y-1">
          {ledger.problems.map((p) => (
            <li key={p} className="rounded-xl bg-amber-50 px-3 py-2 text-[13px] font-medium text-amber-800">
              {p}
            </li>
          ))}
        </ul>
      )}
      {ledger && ledger.entries.length > 0 && (
        <ul className="mt-3 divide-y divide-slate-100 text-[14px]">
          {ledger.entries.map((e) => (
            <li key={e.id} className="flex items-center gap-3 py-2">
              <span className="shrink-0 font-semibold tabular-nums text-slate-900">{entryNumber(e)}</span>
              <span className="min-w-0 flex-1 truncate text-slate-600">
                {e.issued_on} · {e.title}
                {e.recipient ? ` → ${e.recipient}` : ""}
              </span>
              <button type="button" onClick={() => run(async () => setLedger(await deleteEntry(e.id)))} className={`${BTN_SM} ${BTN_GHOST}`}>
                지우기
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
