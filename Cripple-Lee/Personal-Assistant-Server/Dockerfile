# Use an official Python runtime as the base image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

# Copy the project files
COPY . .

# Install the project dependencies
RUN pip install --no-cache-dir -e .

# Expose the port the app runs on
EXPOSE 2026

# Create a non-root user and switch to it
RUN adduser --disabled-password --gecos '' appuser
RUN chown -R appuser:appuser /app
USER appuser

# Health check using the /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:2026/health || exit 1

# Run the application using aegra serve (PaaS mode)
# PostgreSQL and Redis are provided externally via DATABASE_URL and REDIS_URL
CMD ["aegra", "serve", "--host", "0.0.0.0", "--port", "2026"]