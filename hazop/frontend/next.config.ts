import type { NextConfig } from "next";

const apiUrl = (process.env.HAZOP_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  basePath: "/hazop",
  output: "standalone",
  poweredByHeader: false,
  cacheComponents: true,
  partialPrefetching: true,
  experimental: {
    proxyTimeout: 180_000,
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
  async headers() {
    return [{ source: "/:path*", headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }] }];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
