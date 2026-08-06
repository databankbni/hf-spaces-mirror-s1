FROM node:20-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends git ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ARG PROVIDER_REPO_URL=https://github.com/Zenda-Cross/vega-providers.git
ARG PROVIDER_REPO_REF=main

COPY package*.json ./
RUN npm install

COPY . .
RUN rm -rf vega-providers-main \
  && git clone --depth 1 --branch ${PROVIDER_REPO_REF} ${PROVIDER_REPO_URL} vega-providers-main \
  && cd vega-providers-main \
  && npm ci \
  && npm run build

EXPOSE 7860
CMD ["npm", "start"]
