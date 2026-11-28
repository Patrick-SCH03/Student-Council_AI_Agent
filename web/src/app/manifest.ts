import type { MetadataRoute } from "next";

// 홈 화면에 추가했을 때의 이름·아이콘 (2026-11-28 열린 P·S 합자 — Patrick의 P 고리가 SON의 S가 되는 한 획, public/icon-*.png)
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "학생회 업무 AI",
    short_name: "학생회 AI",
    description: "인하대학교 학생회 규정 확인·예산 검토·문서 작성",
    start_url: "/",
    display: "standalone",
    background_color: "#f8fafc",
    theme_color: "#ffffff",
    lang: "ko",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
