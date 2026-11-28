import type { Metadata } from "next";

// 관리자 대시보드는 검색에 노출하지 않는다. 숨긴 URL은 검색 제외가 아니다.
export const metadata: Metadata = {
  title: "운영 대시보드 · 학생회 업무 AI",
  robots: { index: false, follow: false },
};

export default function StatsLayout({ children }: { children: React.ReactNode }) {
  // 다른 화면처럼 가운데 정렬·좌우 여백을 둔다(사이드바 선에 붙지 않게). 표·그래프가 많아 폭은 넓게
  return <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:px-10 lg:py-10">{children}</div>;
}
