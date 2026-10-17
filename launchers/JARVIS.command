#!/bin/bash
# JARVIS Legal OS launcher for macOS. Double click this file, or use the
# desktop icon created by make_mac_app.sh.
cd "$(dirname "$0")/.."

# Activate conda env
source /Users/jpromero/anaconda3/bin/activate
conda activate dev2

# Install deps if needed (first run)
pip install -q -r requirements.txt 2>/dev/null

PORT=8502
# Start the server if it is not already running
if ! lsof -i :$PORT >/dev/null 2>&1; then
  streamlit run app.py --server.port $PORT >/tmp/jarvis_legal.log 2>&1 &
  for i in {1..30}; do curl -s "http://localhost:$PORT" >/dev/null && break; sleep 0.5; done
fi

# Open full screen, chrome free, like a dedicated console
URL="http://localhost:$PORT"
if [ -d "/Applications/Google Chrome.app" ]; then
  open -na "Google Chrome" --args --app="$URL" --start-fullscreen
else
  open "$URL"
fi
