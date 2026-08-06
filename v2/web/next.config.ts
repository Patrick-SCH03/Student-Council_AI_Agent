import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Docker 배포용 self-contained 빌드 (.next/standalone)
  output: "standalone",
};

export default nextConfig;
