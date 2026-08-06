import type { NextConfig } from "next";
import { fileURLToPath } from "node:url";

const nextConfig: NextConfig = {
  // Minimal self-contained server output for the Docker image.
  output: "standalone",
  // Pin the workspace root to this app. The parent repo has its own
  // (unrelated) lockfile, which otherwise triggers a root-detection warning.
  turbopack: {
    root: fileURLToPath(new URL(".", import.meta.url)),
  },
  // /auth was the old Supabase sign-in page, removed when auth moved to
  // Clerk. Old bookmarks/links (and anyone Clerk bounces back to a
  // pre-migration URL) should land on the new sign-in page instead of 404ing.
  async redirects() {
    return [
      {
        source: "/auth",
        has: [{ type: "query", key: "redirect", value: "(?<redirect>.*)" }],
        destination: "/sign-in?redirect_url=:redirect",
        permanent: true,
      },
      {
        source: "/auth",
        destination: "/sign-in",
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
