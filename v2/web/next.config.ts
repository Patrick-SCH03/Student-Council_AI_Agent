import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Docker 배포용 self-contained 빌드 (.next/standalone)
  output: "standalone",
  // same-origin(/api) 호출을 백엔드로 프록시 — 터널/단일 오리진 배포용
  async rewrites() {
    const apiUrl = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
};

export default nextConfig;
