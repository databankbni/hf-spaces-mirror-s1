FROM python:3.10-slim

# HuggingFace requires a user with UID 1000
RUN useradd -m -u 1000 user
USER user

ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# Copy the project files
COPY --chown=1000:1000 . $HOME/app

# Install Python requirements
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# HuggingFace strictly requires port 7860
EXPOSE 7860

# Start command
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "7860"]

