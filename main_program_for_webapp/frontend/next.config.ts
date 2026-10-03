import type { NextConfig } from "next";

const backendUrl = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // The floating dev "N" badge sat on the sidebar footer; build/runtime errors still show.
  devIndicators: false,
  distDir: process.env.NEXT_DIST_DIR || ".next",
  experimental: {
    // /api is proxied to FastAPI; the default 10 MB request-body cap made every
    // YOLO weights upload (50-110 MB) fail with HTTP 500. Backend caps uploads at 1 GB.
    proxyClientMaxBodySize: "1gb",
    // The proxy drops a response that stays silent for proxyTimeout (default 30 s). AI replies
    // wait on busy models and 3D captures move the stage, so allow up to 5 minutes.
    proxyTimeout: 300_000,
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
