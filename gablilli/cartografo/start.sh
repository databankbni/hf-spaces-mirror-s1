#!/bin/bash
set -e

echo "== Cartografo =="
echo "Scaricando tile Italia da Protomaps..."

LATEST=$(curl -s https://maps.protomaps.com/builds/ | grep -oP '2[0-9]{7}\.pmtiles' | sort -r | head -1 | sed 's/\.pmtiles//')

if [ -z "$LATEST" ]; then
  echo "Impossibile trovare build, uso data odierna..."
  LATEST=$(date +%Y%m%d)
fi

echo "Build: $LATEST"

pmtiles extract \
  "https://build.protomaps.com/${LATEST}.pmtiles" \
  /app/italy.pmtiles \
  --bbox=6.6272658,35.2889616,18.7844746,47.0921462

echo "Tile scaricati: $(du -sh /app/italy.pmtiles | cut -f1)"
echo "Avviando server..."
exec uvicorn server:app --host 0.0.0.0 --port 7860
