# Base image: SAME Python version as the container where the model was trained
# (3.10). Avoid python:3.13 (the Space template) because a .joblib serialized
# on 3.10 may fail to load on a different Python version.
FROM python:3.10-slim

# Minimal system dependencies to compile pip wheels if needed
RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

# Working directory inside the container
WORKDIR /app

# Install dependencies first (takes advantage of Docker layer caching:
# if only app.py changes, packages are not reinstalled)
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy the remaining files (app.py, SuperKartModel.joblib, etc.)
COPY . .

# Hugging Face Docker Spaces expect the app on port 7860
EXPOSE 7860

# gunicorn serves the Flask object named "superkart_api" defined in app.py
CMD ["gunicorn", "-b", "0.0.0.0:7860", "app:superkart_api"]
