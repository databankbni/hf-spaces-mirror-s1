FROM node:18-slim

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install ALL dependencies (need devDeps for build)
RUN npm install

# Copy source code
COPY . .

# Build client + server
RUN npm run build

# Create data directory for SQLite
RUN mkdir -p /data

# Environment
ENV NODE_ENV=production
ENV PORT=7860
ENV DB_PATH=/data/teamtracker.db
# JWT_SECRET is set via HF Space Secrets (Settings → Variables and secrets)

# HF Spaces uses port 7860
EXPOSE 7860

CMD ["node", "dist/server/server.js"]
