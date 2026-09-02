FROM python:3.10-slim

# התקנת כלי מערכת בסיסיים ו-ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# הגדרת תיקיית העבודה בשרת
WORKDIR /app

# העתקת קבצי הפרויקט
COPY . /app

# התקנת חבילות הפייתון הבסיסיות מראש
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    SpeechRecognition \
    gtts \
    edge-tts \
    miniaudio \
    certifi \
    pytubefix \
    bgutil-ytdlp-pot-provider \
    yt-dlp-ejs \
    https://github.com/yt-dlp/yt-dlp/archive/master.zip

# חשיפת הפורט הפנימי של השרת
EXPOSE 5060

# פקודת ההרצה של הבוט במצב Unbuffered (כמו ה-u-) כדי שהלוגים יזרמו בזמן אמת
CMD ["python", "-u", "bot.py"]