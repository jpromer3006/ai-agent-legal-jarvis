#!/bin/bash
# JARVIS Immigration launcher (macOS). Double click to run.
cd "$(dirname "$0")"
source /Users/jpromero/anaconda3/bin/activate
conda activate dev2
pip install -q -r requirements.txt 2>/dev/null

PORT=8503
if ! lsof -i :$PORT >/dev/null 2>&1; then
  streamlit run app.py --server.port $PORT >/tmp/jarvis_immigration.log 2>&1 &
  for i in {1..40}; do curl -s "http://localhost:$PORT" >/dev/null && break; sleep 0.5; done
fi
URL="http://localhost:$PORT"
if [ -d "/Applications/Google Chrome.app" ]; then
  open -na "Google Chrome" --args --app="$URL"
else
  open "$URL"
fi
