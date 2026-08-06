# ThoxOS Web Edition — HF Docker Space (Vite SPA + Node blob route).
FROM node:22-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build

FROM node:22-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production PORT=7860
# Only what the server needs at runtime: the build, the server, the ThoxRoute serving registry,
# and @vercel/blob. models/ is read at runtime (not bundled) so THOXROUTE_REGISTRY_JSON can
# override it and so a registry edit does not require rebuilding the client bundle.
COPY --from=build /app/dist ./dist
COPY --from=build /app/server.js ./server.js
COPY --from=build /app/models ./models
# The identity guard is imported by server.js at runtime — without it the proxy cannot start.
COPY --from=build /app/shared ./shared
COPY --from=build /app/package.json ./package.json
RUN npm install --no-audit --no-fund --omit=dev @vercel/blob@^0.27.0
EXPOSE 7860
CMD ["node", "server.js"]
