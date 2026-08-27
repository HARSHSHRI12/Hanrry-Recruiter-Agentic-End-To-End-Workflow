#!/bin/bash

# Start the calling agent in the background
echo "Starting VideoSDK Calling Agent..."
python -m app.agents.calling_agent &
AGENT_PID=$!

# Start the FastAPI web server
echo "Starting FastAPI Web Server..."
uvicorn main:app --host 0.0.0.0 --port 8000 &
WEB_PID=$!

# Wait for any process to exit
wait -n $AGENT_PID $WEB_PID

# Exit with status of process that exited first
exit $?
