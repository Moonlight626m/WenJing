import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 独立产物（.next/standalone）供容器化生产运行
  output: "standalone",
  // 允许 dev 时通过 127.0.0.1 访问（默认仅 localhost，HMR/静态资源会被拦）
  allowedDevOrigins: ["127.0.0.1"],
};

export default nextConfig;
