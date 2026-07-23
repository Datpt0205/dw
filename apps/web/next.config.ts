import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  transpilePackages: [
    "@dw/ui",
    "@dw/contracts",
    "@dw/api-client",
    "@dw/agent-ui",
  ],
};

export default nextConfig;
