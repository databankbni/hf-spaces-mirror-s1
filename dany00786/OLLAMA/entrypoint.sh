#!/bin/bash

# 1. Set environment variables for Ollama
# Run on port 7860 (Hugging Face required port)
export OLLAMA_HOST=0.0.0.0:7860
# Persist models in the mounted storage bucket
export OLLAMA_MODELS=/data/ollama

# Create storage directory if it doesn't exist
mkdir -p /data/ollama

# 2. Start Ollama in the background
ollama serve &

# 3. Wait for Ollama to start up
echo "Waiting for Ollama to start..."
while ! curl -s http://localhost:7860/api/tags > /dev/null; do
    sleep 1
done
echo "Ollama started!"

# 4. Pull the local models if they don't exist in persistence
MODELS=("qwen2.5:1.5b" "sadiq-bd/llama3.2-1b-uncensored")
for MODEL_NAME in "${MODELS[@]}"; do
    echo "Checking if model $MODEL_NAME is already pulled..."
    if ! ollama list | grep -F -q "$MODEL_NAME"; then
        echo "Model not found. Pulling $MODEL_NAME..."
        ollama pull "$MODEL_NAME"
        echo "Model $MODEL_NAME pulled successfully!"
    else
        echo "Model $MODEL_NAME is already present in persistent storage."
    fi
done

# 5. Keep the container alive by waiting on the background process
wait -n
