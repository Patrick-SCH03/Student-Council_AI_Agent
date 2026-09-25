"use client";

// 익명 방문자 추적 (트래픽 지표용): 방문자 ID를 하루 1회만 서버에 기록한다.
// 관리자 페이지(/stats)는 집계에서 제외.

import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { API_BASE, getVisitorId } from "@/lib/api";

export default function VisitTracker() {
  const pathname = usePathname();

  useEffect(() => {
    if (pathname.startsWith("/stats")) return;
    const visitorId = getVisitorId();
    if (!visitorId) return;
    try {
      // 서버의 '오늘'과 같은 한국 날짜 기준 (UTC면 한국 오전 9시 전 방문이 전날로 잡힌다)
      const kst = new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
      const todayKey = `visited-${kst}`;
      if (localStorage.getItem(todayKey)) return;
      fetch(`${API_BASE}/api/track`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ visitor_id: visitorId }),
      })
        // 실제로 기록된 때만 표시한다 — 실패 응답 뒤 표시하면 그날 방문이 영영 안 잡힌다
        .then((res) => {
          if (res.ok) localStorage.setItem(todayKey, "1");
        })
        .catch(() => {});
    } catch {
      // localStorage 접근 불가 환경은 무시
    }
  }, [pathname]);

  return null;
}
