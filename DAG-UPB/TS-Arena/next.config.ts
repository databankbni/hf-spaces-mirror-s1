import type { NextConfig } from "next";

// This repo is built two different ways, and only one of them wants a
// standalone build:
//
//   Dockerfile   the Hugging Face Space (README frontmatter `sdk: docker`,
//                pushed by .github/workflows/main.yml). It runs the slim
//                `.next/standalone` bundle with `node server.js`, so it needs
//                `output: "standalone"` and sets the flag below.
//   Nixpacks     the Coolify apps. Nixpacks never reads the `Dockerfile`; it
//                starts the app with `npm start` -> `next start`, which does
//                not serve a standalone build and warns about it.
//
// Hence the opt-in: the Docker build sets NEXT_OUTPUT_STANDALONE, every other
// build gets a plain `next build` that `next start` can actually serve.
const nextConfig: NextConfig = {
  output: process.env.NEXT_OUTPUT_STANDALONE === "1" ? "standalone" : undefined,
};

export default nextConfig;
