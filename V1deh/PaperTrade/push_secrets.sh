#!/bin/bash
# Push .env secrets to HF Spaces using the HF API

set -e

# Parse .env file
HF_TOKEN=$(grep "^HF_TOKEN=" .env | cut -d'=' -f2)
OLLAMA_ENDPOINT=$(grep "^OLLAMA_ENDPOINT=" .env | cut -d'=' -f2)
OLLAMA_MODEL=$(grep "^OLLAMA_MODEL=" .env | cut -d'=' -f2)
REPO_ID="V1deh/PaperTrade"

echo "📝 Pushing secrets to HF Spaces..."
echo "  OLLAMA_ENDPOINT: $OLLAMA_ENDPOINT"
echo "  OLLAMA_MODEL: $OLLAMA_MODEL"
echo ""

# Push OLLAMA_ENDPOINT
echo "Pushing OLLAMA_ENDPOINT..."
curl -X POST \
  "https://huggingface.co/api/spaces/$REPO_ID/secrets" \
  -H "Authorization: Bearer $HF_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"key\": \"OLLAMA_ENDPOINT\", \"value\": \"$OLLAMA_ENDPOINT\"}" \
  -s -o /dev/null && echo "  ✓ OLLAMA_ENDPOINT" || echo "  ✗ OLLAMA_ENDPOINT failed"

# Push OLLAMA_MODEL
echo "Pushing OLLAMA_MODEL..."
curl -X POST \
  "https://huggingface.co/api/spaces/$REPO_ID/secrets" \
  -H "Authorization: Bearer $HF_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"key\": \"OLLAMA_MODEL\", \"value\": \"$OLLAMA_MODEL\"}" \
  -s -o /dev/null && echo "  ✓ OLLAMA_MODEL" || echo "  ✗ OLLAMA_MODEL failed"

echo ""
echo "✓ Secrets pushed! Restart your Space to apply."
