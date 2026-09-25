import type { NextConfig } from "next";

// API 호출은 NEXT_PUBLIC_API_URL로 지정한 백엔드에 직접 보낸다.
// (스트리밍 응답이 프록시 계층의 타임아웃에 걸리지 않도록 함)
const API_ORIGIN = new URL(process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").origin;
const isDev = process.env.NODE_ENV === "development";

// Next 16 문서의 'Without Nonces' 형태. 페이지가 정적 생성이라 요청마다 nonce를 넣으려면
// 모든 페이지를 동적 렌더링으로 바꿔야 해서(문서가 성능 비용을 명시) 인라인 스크립트는
// 허용하되, 외부 스크립트 로드와 백엔드 외 주소로의 통신(유출 경로)은 막는다.
const CSP = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' blob: data:",
  "font-src 'self'",
  `connect-src 'self' ${API_ORIGIN}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  ...(API_ORIGIN.startsWith("https:") ? ["upgrade-insecure-requests"] : []),
].join("; ");

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "Content-Security-Policy", value: CSP },
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
