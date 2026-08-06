# syntax=docker.io/docker/dockerfile:1

FROM node:20-alpine AS base

# Install dependencies only when needed
FROM base AS deps
# Check https://github.com/nodejs/docker-node/tree/b4117f9333da4138b03a546ec926ef50a31506c3#nodealpine to understand why libc6-compat might be needed.
RUN apk add --no-cache libc6-compat
WORKDIR /app

# Install dependencies based on the preferred package manager
COPY package.json yarn.lock* package-lock.json* pnpm-lock.yaml* .npmrc* ./
RUN \
  if [ -f yarn.lock ]; then yarn --frozen-lockfile; \
  elif [ -f package-lock.json ]; then npm ci; \
  elif [ -f pnpm-lock.yaml ]; then corepack enable pnpm && pnpm i --frozen-lockfile; \
  else echo "Lockfile not found." && exit 1; \
  fi


# Rebuild the source code only when needed
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# News posts (the /news section) are not checked into this repo — they live in
# a separate content repository so that anyone running their own TS-Arena does
# not inherit ours. Set NEWS_CONTENT_REPO to a clone URL to bake that repo's
# `*.md` files into the image; leave it unset and the /news section simply
# does not appear. The clone itself is done by the `prebuild` npm script, so
# that Nixpacks builds (which never read this Dockerfile) behave identically.
# For a private repo the URL carries a token — see the README for what that
# means for the built image.
ARG NEWS_CONTENT_REPO=
ARG NEWS_CONTENT_REF=main
ENV NEWS_CONTENT_REPO=$NEWS_CONTENT_REPO
ENV NEWS_CONTENT_REF=$NEWS_CONTENT_REF
RUN apk add --no-cache git

# The runner stage below serves the slim `.next/standalone` bundle, which only
# exists when next.config.ts switches `output` to "standalone". That is opt-in
# because the other build path (Nixpacks, used by the Coolify apps) starts the
# app with `next start`, which cannot serve a standalone build.
ENV NEXT_OUTPUT_STANDALONE=1

# Next.js collects completely anonymous telemetry data about general usage.
# Learn more here: https://nextjs.org/telemetry
# Uncomment the following line in case you want to disable telemetry during the build.
# ENV NEXT_TELEMETRY_DISABLED=1

RUN \
  if [ -f yarn.lock ]; then yarn run build; \
  elif [ -f package-lock.json ]; then npm run build; \
  elif [ -f pnpm-lock.yaml ]; then corepack enable pnpm && pnpm run build; \
  else echo "Lockfile not found." && exit 1; \
  fi

# Production image, copy all the files and run next
FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production
# Uncomment the following line in case you want to disable telemetry during runtime.
# ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
# The news Markdown is also read at request time (the root layout decides
# whether to show the News tab), so it has to exist in the runtime image too.
COPY --from=builder /app/content ./content

# Automatically leverage output traces to reduce image size
# https://nextjs.org/docs/advanced-features/output-file-tracing
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

ENV PORT=3000

# server.js is created by next build from the standalone output
# https://nextjs.org/docs/pages/api-reference/config/next-config-js/output
ENV HOSTNAME="0.0.0.0"
CMD ["node", "server.js"]