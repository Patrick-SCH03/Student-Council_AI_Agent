"use client";

// 내 작업함 아래: 서비스 개선에 허락한 자료 수와 모두 지우기 (동의 철회).

import { useEffect, useState } from "react";

import { fetchMyContributions, withdrawContributions } from "@/lib/contrib";
import { BTN_SM, BTN_SECONDARY } from "@/lib/ui";

export default function MyContributions() {
  const [count, setCount] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchMyContributions().then(
      (r) => setCount(r.count),
      () => setCount(null),
    );
  }, []);

  if (!count) return null;
  return (
    <div className="mt-8 flex flex-wrap items-center gap-3 rounded-2xl border border-slate-200 p-4 text-[14px] text-slate-600">
      <p className="flex-1">서비스 개선에 쓰도록 허락한 자료 {count}건이 가명 처리돼 보관돼 있어요.</p>
      {message && <span className="text-[13px] text-slate-500">{message}</span>}
      <button
        type="button"
        onClick={async () => {
          if (!confirm(`개선 자료 ${count}건을 모두 지울까요? 되돌릴 수 없어요.`)) return;
          try {
            await withdrawContributions();
            setCount(0);
          } catch (e) {
            setMessage(e instanceof Error ? e.message : "지우지 못했어요.");
          }
        }}
        className={`${BTN_SM} ${BTN_SECONDARY}`}
      >
        모두 지우기
      </button>
    </div>
  );
}
