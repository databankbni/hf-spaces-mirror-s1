# Use the official Ollama image as the base
FROM ollama/ollama:latest

# Expose port 7860 (Hugging Face required port)
EXPOSE 7860

# Set the working directory
WORKDIR /app

# Copy the entrypoint script
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Run entrypoint
ENTRYPOINT ["./entrypoint.sh"]
