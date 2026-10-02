import type { NextConfig } from "next";

const backendUrl = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR || ".next",
  experimental: {
    // /api is proxied to FastAPI; the default 10 MB request-body cap made every
    // YOLO weights upload (50-110 MB) fail with HTTP 500. Backend caps uploads at 1 GB.
    proxyClientMaxBodySize: "1gb",
  },
  async rewrites() {
    return [
      { source: "/ws/:path*", destination: `${backendUrl}/ws/:path*` },
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
