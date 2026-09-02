FROM python:3.9-slim

WORKDIR /app

# System packages update (SQLite aur baaki tools ke liye)
RUN apt-get update && apt-get install -y sqlite3 && rm -rf /var/lib/apt/lists/*

# Requirements copy aur install karein
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Non-root user setup (For security, just like your screenshot)
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app
COPY --chown=user . $HOME/app

# Flask port expose karein
EXPOSE 5000

# App run command
CMD ["python", "app.py"]