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
            <div className="flex items-center gap-2">
              <a
                href="mailto:wwoo5241@inha.edu?subject=%5B%ED%95%99%EC%83%9D%ED%9A%8C%20%EA%B7%9C%EC%A0%95%20AI%5D%20%EC%98%A4%EB%A5%98%20%EC%8B%A0%EA%B3%A0%20%2F%20%EB%AC%B8%EC%9D%98"
                className="flex items-center gap-1.5 rounded-full border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-500 transition hover:border-indigo-300 hover:text-indigo-600"
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={1.6}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="h-3.5 w-3.5"
                  aria-hidden
                >
                  <rect x="3" y="5" width="18" height="14" rx="2" />
                  <path d="m3 7 9 6 9-6" />
                </svg>
                오류 신고·문의
              </a>
              <span className="rounded-full bg-indigo-50 px-3 py-1.5 text-xs font-bold text-indigo-600">
                INHA 학생회
              </span>
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-3xl flex-1 px-4">{children}</main>
      </body>
    </html>
  );
}
