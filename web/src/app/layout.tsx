import type { Metadata } from "next";
import localFont from "next/font/local";
import Image from "next/image";
import Link from "next/link";

import ContactButton from "@/components/ContactButton";
import VisitTracker from "@/components/VisitTracker";

import "./globals.css";

// next/font/google은 빌드마다 Google 서버에서 폰트를 받아오므로, 네트워크가
// 막히면 빌드가 통째로 실패한다(CI에서 실제로 겪음). 가변 폰트 파일을 저장소에
// 두고 자체 호스팅해 빌드의 외부 의존을 없앤다.
const jakarta = localFont({
  src: "./fonts/PlusJakartaSans-Variable.woff2",
  variable: "--font-jakarta",
  weight: "400 800",
  display: "swap",
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
            <ContactButton />
          </div>
        </header>
        <main className="mx-auto w-full max-w-3xl flex-1 px-4">{children}</main>
        <VisitTracker />
      </body>
    </html>
  );
}
