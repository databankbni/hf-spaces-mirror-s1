FROM node:18.19.0-bullseye-slim
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY start.sh .
RUN chmod +x start.sh
EXPOSE 7860
CMD ["./start.sh"]