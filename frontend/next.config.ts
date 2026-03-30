import type { NextConfig } from "next";

const BACKEND_URL =
  process.env.BACKEND_INTERNAL_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  allowedDevOrigins: ["127.0.0.1"],

  async rewrites() {
    return [
      {
        // Proxy all /api/* calls to the FastAPI backend so that
        // window.location.origin-based URLs work in the browser
        // without needing NEXT_PUBLIC_API_BASE_URL to be set.
        source: "/api/:path*",
        destination: `${BACKEND_URL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
