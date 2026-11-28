"use client";

// 화면 맨 위 공지 한 줄: 방침·약관 변경 예고, 점검·장애 안내. 닫으면 같은 공지는 이 브라우저에서 다시 보이지 않는다.

import Link from "next/link";
import { useEffect, useState } from "react";

import { fetchNotice } from "@/lib/api";
import { type Notice, dismissNotice, visibleNotice } from "@/lib/notice";

export default function NoticeBar() {
  const [notice, setNotice] = useState<Notice | null>(null);

  useEffect(() => {
    let alive = true;
    fetchNotice()
      .then((n) => alive && setNotice(visibleNotice(n)))
      .catch(() => {}); // 공지를 못 불러와도 화면은 그대로 쓴다
    return () => {
      alive = false;
    };
  }, []);

  if (!notice) return null;
  return (
    <div role="status" className="border-b border-indigo-100 bg-indigo-50 print:hidden">
      <div className="mx-auto flex max-w-3xl items-start gap-3 px-4 py-2.5 text-[13px] leading-relaxed text-indigo-950">
        <p className="flex-1">
          {notice.text}
          {notice.href && (
            <>
              {" "}
              <Link href={notice.href} className="whitespace-nowrap font-semibold text-indigo-700 underline">
                자세히 보기
              </Link>
            </>
          )}
        </p>
        <button
          type="button"
          onClick={() => {
            dismissNotice(notice);
            setNotice(null);
          }}
          aria-label="공지 닫기"
          className="-my-1 shrink-0 rounded-full p-1 text-indigo-400 hover:bg-indigo-100 hover:text-indigo-900"
        >
          <svg aria-hidden viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M5 5l10 10M15 5L5 15" strokeLinecap="round" />
          </svg>
        </button>
      </div>
    </div>
  );
}
