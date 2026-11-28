"use client";

// 운영 대시보드: 홈 '다가오는 일정' 편집. 인하광장 학생자치기구 공고(총회 개회 공고 등)에서 확인한 날짜를 넣는다.

import { useEffect, useState } from "react";

import { AuthError, fetchStoredEvents, saveEvents } from "@/lib/api";
import type { Event } from "@/lib/events";

import { CARD_SHADOW } from "./parts";

const INPUT = "rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-indigo-400";
const BLANK: Event = { date: "", title: "", href: null };

export default function EventsSettings({ onAuthError }: { onAuthError: (e: unknown, fallback: string) => void }) {
  const [rows, setRows] = useState<Event[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchStoredEvents().then(setRows, (e) => onAuthError(e, "일정을 불러오지 못했어요."));
  }, [onAuthError]);

  const set = (i: number, patch: Partial<Event>) => setRows((r) => r.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const filled = rows.filter((r) => r.date || r.title.trim());
  const incomplete = filled.some((r) => !r.date || !r.title.trim());

  const save = async () => {
    setBusy(true);
    setMessage(null);
    try {
      setRows(await saveEvents(filled));
      setMessage("저장했어요. 지난 일정은 홈에 보이지 않아요.");
    } catch (e) {
      if (e instanceof AuthError) onAuthError(e, "");
      else setMessage(e instanceof Error ? e.message : "저장하지 못했어요.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`rounded-2xl border border-slate-200 bg-white p-5 ${CARD_SHADOW}`}>
      <p className="text-sm font-bold text-slate-800">
        홈 &lsquo;다가오는 일정&rsquo;
        <span className="ml-2 text-xs font-medium text-slate-500">가까운 4개가 홈에 보여요</span>
      </p>
      <div className="mt-4 space-y-2">
        {rows.map((r, i) => (
          <div key={i} className="grid gap-2 sm:grid-cols-[150px_1fr_160px_auto]">
            <input type="date" aria-label="날짜" value={r.date} onChange={(e) => set(i, { date: e.target.value })} className={INPUT} />
            <input
              aria-label="일정"
              value={r.title}
              maxLength={80}
              placeholder="총대의원회 5차 정기총회"
              onChange={(e) => set(i, { title: e.target.value })}
              className={INPUT}
            />
            <input
              aria-label="링크"
              value={r.href ?? ""}
              placeholder="링크 (선택, /plan)"
              onChange={(e) => set(i, { href: e.target.value || null })}
              className={INPUT}
            />
            <button
              type="button"
              onClick={() => setRows((x) => x.filter((_, j) => j !== i))}
              className="text-xs font-medium text-slate-500 hover:text-rose-700"
            >
              빼기
            </button>
          </div>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-end gap-2.5">
        {message && <span className="mr-auto text-xs font-medium text-slate-500">{message}</span>}
        <button
          type="button"
          onClick={() => setRows((r) => [...r, BLANK])}
          className="rounded-full border border-slate-200 px-4 py-2 text-xs font-medium text-slate-600 transition hover:border-slate-300"
        >
          일정 추가
        </button>
        <button
          type="button"
          disabled={busy || incomplete}
          onClick={save}
          className="rounded-full bg-indigo-600 px-5 py-2 text-xs font-bold text-white transition hover:bg-indigo-700 disabled:bg-slate-200 disabled:text-slate-500"
        >
          {busy ? "저장 중..." : "저장"}
        </button>
      </div>
    </div>
  );
}
