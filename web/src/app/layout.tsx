import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";

import AppShell from "@/components/shell/AppShell";
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

const SITE_URL = "https://app.inhacouncil.com";
const DESCRIPTION =
  "인하대학교 학생회 회칙·세칙·감사 사례를 근거로 규정 질문에 답하고, 예산안·결산서를 점검하는 업무 도우미예요.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: "학생회 업무 AI",
  description: DESCRIPTION,
  // 카카오톡·메신저에 링크를 붙였을 때 보이는 미리보기
  openGraph: {
    type: "website",
    url: "/",
    siteName: "학생회 업무 AI",
    title: "학생회 업무 AI",
    description: DESCRIPTION,
    locale: "ko_KR",
    images: [{ url: "/emblem.png", width: 640, height: 640, alt: "인하대학교 마크" }],
  },
  twitter: { card: "summary", title: "학생회 업무 AI", description: DESCRIPTION },
};

// 모바일 브라우저 주소창 색을 흰 헤더와 맞춘다
export const viewport: Viewport = {
  themeColor: "#ffffff",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko" className={`${jakarta.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-slate-50 text-slate-800">
        <AppShell>{children}</AppShell>
        <VisitTracker />
      </body>
    </html>
  );
}
