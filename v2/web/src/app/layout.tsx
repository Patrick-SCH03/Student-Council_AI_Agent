import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "학생회 규정 AI 어시스턴트",
  description:
    "학생회 규정·재정·감사 질문을 AI 멀티에이전트가 문서 기반으로 분석합니다.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko" className="h-full antialiased">
      <body className="min-h-full flex flex-col bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
        <header className="sticky top-0 z-10 border-b border-zinc-200 bg-white/80 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/80">
          <div className="mx-auto flex h-14 max-w-3xl items-center justify-between px-4">
            <Link href="/" className="flex items-center gap-2 font-semibold">
              <span aria-hidden>🎓</span>
              <span>학생회 규정 AI 어시스턴트</span>
            </Link>
            <nav className="flex items-center gap-4 text-sm text-zinc-500">
              <Link href="/" className="hover:text-zinc-900 dark:hover:text-zinc-100">
                채팅
              </Link>
              <Link
                href="/admin"
                className="hover:text-zinc-900 dark:hover:text-zinc-100"
              >
                문서 관리
              </Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto w-full max-w-3xl flex-1 px-4">{children}</main>
      </body>
    </html>
  );
}
