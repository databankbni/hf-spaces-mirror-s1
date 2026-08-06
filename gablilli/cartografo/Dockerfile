FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    wget \
    unzip \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fL \
    "https://github.com/maplibre/martin/releases/download/martin-v1.12.0/martin-x86_64-unknown-linux-gnu.tar.gz" \
    -o /tmp/martin.tar.gz \
    && tar -xzf /tmp/martin.tar.gz -C /tmp \
    && mv /tmp/martin /usr/local/bin/ \
    && rm /tmp/martin.tar.gz \
    && martin --version

RUN npm install --prefix /app fontnik

RUN pip install fastapi uvicorn httpx --no-cache-dir

# install go-pmtiles CLI
RUN curl -fL \
    "https://github.com/protomaps/go-pmtiles/releases/download/v1.31.0/go-pmtiles_1.31.0_Linux_x86_64.tar.gz" \
    -o /tmp/go-pmtiles.tar.gz \
    && tar -xzf /tmp/go-pmtiles.tar.gz -C /tmp \
    && mv /tmp/pmtiles /usr/local/bin/ \
    && rm /tmp/go-pmtiles.tar.gz \
    && pmtiles version

# download and convert satoshi
RUN mkdir -p /app/fonts \
    && curl -L "https://api.fontshare.com/v2/fonts/download/satoshi" -o /tmp/satoshi.zip \
    && unzip -q /tmp/satoshi.zip -d /tmp/satoshi \
    && rm /tmp/satoshi.zip \
    && for ttf in $(find /tmp/satoshi -name "*.ttf"); do \
        fontname=$(basename "$ttf" .ttf | sed 's/Satoshi-/Satoshi /'); \
        mkdir -p "/app/fonts/$fontname"; \
        node -e " \
            const fontnik = require('/app/node_modules/fontnik'); \
            const fs = require('fs'); \
            const font = fs.readFileSync('$ttf'); \
            let done = 0; \
            const total = Math.ceil(65536/256); \
            for (let i = 0; i < 65536; i += 256) { \
                const end = Math.min(i+255, 65535); \
                fontnik.range({font, start: i, end}, (err, data) => { \
                    if (!err && data) fs.writeFileSync('/app/fonts/$fontname/' + i + '-' + end + '.pbf', data); \
                    if (++done === total) process.exit(0); \
                }); \
            } \
        "; \
    done \
    && rm -rf /tmp/satoshi

# download and convert noto sans
RUN curl -fL "https://github.com/openmaptiles/fonts/raw/master/noto-sans/NotoSans-Regular.ttf" \
        -o /tmp/NotoSans-Regular.ttf \
    && mkdir -p /app/fonts/noto-sans \
    && node -e " \
        const fontnik = require('/app/node_modules/fontnik'); \
        const fs = require('fs'); \
        const font = fs.readFileSync('/tmp/NotoSans-Regular.ttf'); \
        let done = 0; \
        const total = Math.ceil(65536/256); \
        for (let i = 0; i < 65536; i += 256) { \
            const end = Math.min(i+255, 65535); \
            fontnik.range({font, start: i, end}, (err, data) => { \
                if (!err && data) fs.writeFileSync('/app/fonts/noto-sans/' + i + '-' + end + '.pbf', data); \
                if (++done === total) process.exit(0); \
            }); \
        } \
    " \
    && rm /tmp/NotoSans-Regular.ttf
    
# copy sprite & styles
COPY sprites/ /app/sprites/
COPY style.json /app/style.json
COPY server.py /app/server.py
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 7860

CMD ["/app/start.sh"]
