FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends     ca-certificates     curl     wget     tar     tzdata     && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Shanghai

WORKDIR /app

RUN wget https://github.com/router-for-me/CLIProxyAPI/releases/download/v7.2.137/CLIProxyAPI_7.2.137_linux_amd64.tar.gz     && tar -zxvf CLIProxyAPI_7.2.137_linux_amd64.tar.gz     && chmod +x cli-proxy-api     && rm -f CLIProxyAPI_7.2.137_linux_amd64.tar.gz

RUN mkdir -p /app/auth /app/logs

COPY config.yaml /app/config.yaml
COPY auth/ /app/auth/
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 7860

ENTRYPOINT ["/app/entrypoint.sh"]
