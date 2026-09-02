FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC
WORKDIR /

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      git curl ca-certificates libatomic1 bash build-essential tzdata && \
    ln -fs /usr/share/zoneinfo/${TZ} /etc/localtime && \
    dpkg-reconfigure --frontend noninteractive tzdata && \
    rm -rf /var/lib/apt/lists/*

# Ubuntu 22.04's apt nodejs is v12, too old for lean4game's tooling (Cypress
# postinstall requires the `node:` core-module prefix, added in Node 14.18+).
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

ENV CYPRESS_INSTALL_BINARY=0

# elan (Lean toolchain manager)
RUN curl -sSfL https://github.com/leanprover/elan/releases/download/v1.4.2/elan-x86_64-unknown-linux-gnu.tar.gz | tar xz \
    && ./elan-init -y --default-toolchain none
ENV PATH="${PATH}:/root/.elan/bin"

# --- Build nng4 ---
COPY nng4 /games-src/leanprover-community/nng4
WORKDIR /games-src/leanprover-community/nng4
RUN lake update && lake exe cache get && lake build
WORKDIR /games-src/leanprover-community/nng4/.lake/packages/GameServer/server
RUN lake build

# --- Build STG4 ---
COPY STG4 /games-src/djvelleman/stg4
WORKDIR /games-src/djvelleman/stg4
RUN lake update && lake exe cache get && lake build
WORKDIR /games-src/djvelleman/stg4/.lake/packages/GameServer/server
RUN lake build

# --- Build lean4game (client + relay) ---
COPY lean4game /lean4game
WORKDIR /lean4game
RUN npm install
RUN npm run build:relay
RUN npm run build:client

# --- Import both games into lean4game/games/<owner>/<repo> ---
RUN mkdir -p /lean4game/games/leanprover-community /lean4game/games/djvelleman
RUN cp -r /games-src/leanprover-community/nng4 /lean4game/games/leanprover-community/nng4
RUN cp -r /games-src/djvelleman/stg4 /lean4game/games/djvelleman/stg4

# Remove build caches to keep the image smaller
RUN rm -rf /root/.cache

ENV NODE_ENV=production
ENV NO_BWRAP=true
ENV PORT=7860
ENV API_PORT=7861
EXPOSE 7860

WORKDIR /lean4game
CMD ["node", "relay/dist/src/index.js"]
