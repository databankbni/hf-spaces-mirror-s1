FROM node:24-bookworm-slim

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=7860

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

ENV NODE_ENV=production
ENV TRIWORLDBENCH_VIDEO_ROOT=/tmp/triworldbench/video-cases

EXPOSE 7860

CMD ["sh", "-c", "npm run hf:download-dataset && npm run hf:download-video-cases && npm run hf:restore-space-assets && npx next start -H 0.0.0.0 -p ${PORT:-7860}"]
