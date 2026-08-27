#!/bin/bash
set -e

# Start the calling agent in the BACKGROUND (non-critical, can crash and restart)
echo "Starting VideoSDK Calling Agent..."
python -m app.agents.calling_agent &
AGENT_PID=$!

# Give agent a moment to initialize
sleep 2

# Start the FastAPI web server in the FOREGROUND (this is the main process Render monitors)
echo "Starting FastAPI Web Server..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
