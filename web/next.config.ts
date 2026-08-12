import type { NextConfig } from "next";

// API 호출은 NEXT_PUBLIC_API_URL로 지정한 백엔드에 직접 보낸다.
// (스트리밍 응답이 프록시 계층의 타임아웃에 걸리지 않도록 함)
const nextConfig: NextConfig = {};

export default nextConfig;
