"use client";

// 홈 '다가오는 일정': 운영 대시보드에서 넣은 총회·마감 날짜를 가까운 순으로. 없으면 아무것도 보이지 않는다.

import Link from "next/link";
import { useEffect, useState } from "react";

import { fetchEvents } from "@/lib/api";
import { type Event, dateLabel, dday } from "@/lib/events";
import { todayKst } from "@/lib/format";


export default function UpcomingEvents() {
  const [events, setEvents] = useState<Event[]>([]);
  const [today, setToday] = useState("");

  useEffect(() => {
    let alive = true;
    fetchEvents()
      .then((e) => {
        if (!alive) return;
        setToday(todayKst());
        setEvents(e);
      })
      .catch(() => {}); // 일정을 못 불러와도 홈은 그대로
    return () => {
      alive = false;
    };
  }, []);

  if (!events.length) return null;
  return (
    <section aria-label="다가오는 일정" className="mx-auto mt-8 max-w-2xl">
      <h2 className="px-1 text-[13px] font-bold text-slate-500">다가오는 일정</h2>
      <ul className="mt-2 divide-y divide-slate-100 rounded-2xl bg-white shadow-[0_2px_10px_rgba(15,23,42,0.06)] ring-1 ring-slate-200/70">
        {events.map((e) => {
          const left = dday(e.date, today);
          const soon = left === "오늘" || left === "내일" || /^D-[1-7]$/.test(left);
          const body = (
            <>
              <span className={`w-14 shrink-0 text-[13px] font-extrabold tabular-nums ${soon ? "text-rose-600" : "text-indigo-600"}`}>
                {left}
              </span>
              <span className="min-w-0 flex-1 truncate text-[14px] font-semibold text-slate-900">{e.title}</span>
              <span className="shrink-0 text-[12px] text-slate-500">{dateLabel(e.date)}</span>
            </>
          );
          return (
            <li key={`${e.date}-${e.title}`}>
              {e.href ? (
                <Link href={e.href} className="flex items-center gap-3 px-4 py-3 hover:bg-slate-50">
                  {body}
                </Link>
              ) : (
                <div className="flex items-center gap-3 px-4 py-3">{body}</div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
