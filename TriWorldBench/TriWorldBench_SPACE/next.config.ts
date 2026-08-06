import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // An optional isolated directory supports parallel local builds.
  distDir: process.env.TRIWORLDBENCH_NEXT_DIST_DIR || ".next",
  outputFileTracingRoot: __dirname,
  // Public styles and static assets are imported directly by the site layout.
  images: {
    remotePatterns: [],
  },
};

export default nextConfig;
