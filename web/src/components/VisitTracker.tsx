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
      const todayKey = `visited-${new Date().toISOString().slice(0, 10)}`;
      if (localStorage.getItem(todayKey)) return;
      fetch(`${API_BASE}/api/track`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ visitor_id: visitorId }),
      })
        .then(() => localStorage.setItem(todayKey, "1"))
        .catch(() => {});
    } catch {
      // localStorage 접근 불가 환경은 무시
    }
  }, [pathname]);

  return null;
}
