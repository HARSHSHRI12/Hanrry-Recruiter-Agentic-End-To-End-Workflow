#!/bin/bash
set -e

# Start the FastAPI web server in the FOREGROUND (this is the main process Render monitors)
# Note: The VideoSDK calling agent is now embedded inside the FastAPI lifespan to save memory!
echo "Starting FastAPI Web Server..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
