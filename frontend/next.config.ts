import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 独立产物（.next/standalone）供容器化生产运行
  output: "standalone",
};

export default nextConfig;
