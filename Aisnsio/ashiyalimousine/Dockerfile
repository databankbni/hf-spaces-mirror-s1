FROM node:22-slim

WORKDIR /app

# Install production deps first for better layer caching (no lockfile present)
COPY --chown=node:node package.json ./
RUN npm install --omit=dev

# Copy the rest of the app, owned by the non-root node user
COPY --chown=node:node . .

# Run as the built-in non-root user (uid 1000)
USER node

ENV PORT=7860
EXPOSE 7860

CMD ["node", "--experimental-sqlite", "server.js"]
