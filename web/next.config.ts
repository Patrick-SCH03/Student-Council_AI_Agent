import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Docker 배포에서만 self-contained 빌드 사용.
  // 로컬 `next start`와 Vercel은 일반 빌드가 맞다.
  output: process.env.BUILD_STANDALONE === "1" ? "standalone" : undefined,
  // same-origin(/api) 호출을 백엔드로 프록시 — 터널/단일 오리진 배포용
  async rewrites() {
    const apiUrl = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
};

export default nextConfig;
