import type { Metadata } from "next";

// 관리자 대시보드는 검색에 노출하지 않는다. 숨긴 URL은 검색 제외가 아니다.
export const metadata: Metadata = {
  title: "운영 대시보드 · 학생회 규정 AI",
  robots: { index: false, follow: false },
};

export default function StatsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
