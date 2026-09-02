# Stage 1: Build Astro static site
FROM node:18-slim AS build

WORKDIR /app
COPY app/package*.json ./
RUN npm install

COPY app/ .

# Ensure public/data is a real directory (not symlink)
RUN set -e; \
    rm -rf public/data; \
    mkdir -p public/data; \
    cp -a src/content/assets/data/. public/data/

RUN npm run build

# Stage 2: Python backend + nginx + static site
FROM python:3.10-slim

RUN apt-get update && apt-get install -y nginx && rm -rf /var/lib/apt/lists/*

# Install Python backend dependencies
WORKDIR /backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ /backend/

# Copy built Astro site
COPY --from=build /app/dist /app/dist

# Copy nginx config + entrypoint
COPY nginx.conf /etc/nginx/nginx.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Permissions
RUN mkdir -p /var/cache/nginx /var/run /var/log/nginx /var/lib/nginx/body /tmp && \
    chmod -R 777 /var/cache/nginx /var/run /var/log/nginx /var/lib/nginx /tmp /app /backend

EXPOSE 7860

ENTRYPOINT ["/entrypoint.sh"]
