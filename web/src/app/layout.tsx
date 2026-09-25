import type { Metadata, Viewport } from "next";
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

const SITE_URL = "https://ai-agent-patrick-16be.vercel.app";
const DESCRIPTION =
  "학생회 회칙·세칙·감사보고서를 근거로 규정 위반 여부와 감사 처분 가능성을 알려주는 AI예요.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: "학생회 규정 AI 어시스턴트",
  description: DESCRIPTION,
  // 카카오톡·메신저에 링크를 붙였을 때 보이는 미리보기
  openGraph: {
    type: "website",
    url: "/",
    siteName: "학생회 규정 AI",
    title: "학생회 규정 AI 어시스턴트",
    description: DESCRIPTION,
    locale: "ko_KR",
    images: [{ url: "/emblem.png", width: 304, height: 304, alt: "인하대학교 마크" }],
  },
  twitter: { card: "summary", title: "학생회 규정 AI 어시스턴트", description: DESCRIPTION },
};

// 모바일 브라우저 주소창 색을 흰 헤더와 맞춘다
export const viewport: Viewport = {
  themeColor: "#ffffff",
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
