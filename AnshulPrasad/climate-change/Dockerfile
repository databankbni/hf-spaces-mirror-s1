# Base image
FROM python:3.13-slim

# System environment variables
ENV PYTHONUBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7860 \
    TZ="America/Los_Angeles"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libeccodes-dev \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Install Python depedencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn whitenoise

# Copy application source code
COPY . .

# Create target static files directory and create non-root user (UID 1000 required by Hugging Face)
RUN mkdir -p /app/staticfiles && \
    useradd -m -u 1000 user && \
    chown -R user:user /app

USER user

# Collect static files during build
RUN python django_app/manage.py collectstatic --noinput

# Expose port 7860
EXPOSE 7860

# Shift the execution context strictly into the nested application directory
WORKDIR /app/django_app

# Explicitly define the fully qualified namespace for the settings module
ENV DJANGO_SETTINGS_MODULE="config.settings"

# Execute the WSGI application with the extended timeout threshold
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:7860", "--workers", "2", "--timeout", "300"]