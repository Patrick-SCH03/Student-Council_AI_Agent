import type { NextConfig } from "next";

// API 호출은 NEXT_PUBLIC_API_URL로 지정한 백엔드에 직접 보낸다.
// (스트리밍 응답이 프록시 계층의 타임아웃에 걸리지 않도록 함)
const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          // 인라인 스크립트를 쓰는 Next 런타임을 깨지 않는 범위의 CSP — 프레이밍·플러그인만 차단
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'; object-src 'none'; base-uri 'self'" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
