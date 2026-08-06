import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import Image from "next/image";
import Link from "next/link";
import "./globals.css";

const jakarta = Plus_Jakarta_Sans({
  variable: "--font-jakarta",
  subsets: ["latin"],
  weight: ["400", "500", "700", "800"],
});

export const metadata: Metadata = {
  title: "학생회 규정 AI 어시스턴트",
  description:
    "학생회 규정·재정·감사 질문을 AI 멀티에이전트가 문서 기반으로 분석합니다.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko" className={`${jakarta.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-slate-50 text-slate-800">
        <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur">
          <div className="mx-auto flex h-16 max-w-3xl items-center justify-between px-4">
            <Link href="/" className="flex items-center gap-2.5">
              <Image
                src="/emblem.png"
                alt="인하대학교 마크"
                width={36}
                height={36}
                priority
              />
              <span className="text-lg font-extrabold tracking-tight text-slate-800">
                학생회 규정 AI
              </span>
            </Link>
            <nav className="flex items-center gap-1.5 text-sm font-medium">
              <Link
                href="/"
                className="rounded-full px-4 py-2 text-slate-500 transition hover:bg-indigo-50 hover:text-indigo-600"
              >
                채팅
              </Link>
              <Link
                href="/admin"
                className="rounded-full px-4 py-2 text-slate-500 transition hover:bg-indigo-50 hover:text-indigo-600"
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
