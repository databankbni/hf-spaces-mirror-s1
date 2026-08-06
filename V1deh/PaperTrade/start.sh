#!/usr/bin/env bash
# start.sh — Kill any process holding port 5000, then start the Flask app fresh.
# Usage: ./start.sh [venv-name]   (default venv name: .venv)

PORT=5000
VENV_NAME="${1:-.venv}"

cd "$(dirname "$0")"

echo ""
echo "  NSE Paper Trading Platform"
echo "  --------------------------"

# Kill anything on port 5000
echo ""
echo "  [1/4] Checking port $PORT..."
PIDS=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
if [ -n "$PIDS" ]; then
  echo "  Killing PID(s) $PIDS on port $PORT"
  echo "$PIDS" | xargs kill -9 2>/dev/null || true
  sleep 0.5
else
  echo "  Port $PORT is free"
fi

# Kill stale python app.py processes
STALE=$(pgrep -f "python.*app.py" 2>/dev/null || true)
if [ -n "$STALE" ]; then
  echo "  Killing stale Flask processes: $STALE"
  echo "$STALE" | xargs kill -9 2>/dev/null || true
  sleep 0.3
fi

# Set up / activate venv
echo ""
echo "  [2/4] Environment (venv: $VENV_NAME)..."

if [ -f "$VENV_NAME/bin/activate" ]; then
  source "$VENV_NAME/bin/activate"
  echo "  Activated existing venv: $VENV_NAME"
else
  echo "  '$VENV_NAME' not found — creating it..."
  python3 -m venv "$VENV_NAME"
  source "$VENV_NAME/bin/activate"
  echo "  Created and activated venv: $VENV_NAME"

  echo ""
  echo "  [3/4] Installing dependencies..."
  if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
    echo "  Dependencies installed from requirements.txt"
  else
    echo "  No requirements.txt found — skipping install"
  fi
fi

# Start Flask
echo ""
echo "  [4/4] Starting Flask on port $PORT..."
echo ""
echo "  Open: http://localhost:$PORT"
echo "  Stop: Ctrl+C"
echo ""

exec python3 app.py
