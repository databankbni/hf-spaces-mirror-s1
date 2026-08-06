FROM nikolaik/python-nodejs:python3.11-nodejs20
WORKDIR /app
COPY . .
RUN echo "=== بدء تهيئة السيرفر وتثبيت المكاتب ===" > bot_log.txt
RUN apt-get update && apt-get install -y build-essential ffmpeg libsqlite3-dev libcairo2-dev libpango1.0-dev libjpeg-dev libgif-dev librsvg2-dev >> bot_log.txt 2>&1 || true
RUN pip install --no-cache-dir flask requests flask-cors psutil tls_client discord.py aiohttp colorama python-dotenv pillow pymongo motor beautifulsoup4 websockets cryptography pytz yt-dlp PyNaCl >> bot_log.txt 2>&1 || true
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt >> bot_log.txt 2>&1 || true; fi
RUN npm install discord.js eris axios dotenv chalk fs-extra moment mongoose express ws node-fetch quick.db discord.js-selfbot-v13 pro.db better-sqlite3 wio.db discord-giveaways @discordjs/voice @discordjs/rest mathjs ms table stopwatch-node canvas libsodium-wrappers ytdl-core play-dl >> bot_log.txt 2>&1 || true
RUN if [ -f package.json ]; then npm install --no-cache >> bot_log.txt 2>&1 && npm cache clean --force || true; fi
RUN echo "=== تم بنجاح! جاري تشغيل البوت ===" >> bot_log.txt
CMD ["python", "-u", "hosty_wrapper.py"]