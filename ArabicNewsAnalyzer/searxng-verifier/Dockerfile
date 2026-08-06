FROM searxng/searxng:latest

# Hugging Face Docker Spaces expect the app to listen on port 7860
ENV SEARXNG_BIND_ADDRESS=0.0.0.0:7860

# Copy our custom settings (enables JSON output format)
COPY settings.yml /etc/searxng/settings.yml

EXPOSE 7860
