import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async redirects() {
    return [
      { source: "/enquire", destination: "/contact", permanent: true },
      { source: "/models", destination: "/digital-twins", permanent: false },
    ];
  },
};

export default nextConfig;
