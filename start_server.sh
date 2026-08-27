#!/bin/bash
# Kill anything on port 8000
fuser -k 8000/tcp 2>/dev/null || true
sleep 1

# Start server in background
cd /mnt/d/hanrry-screening-recruiter-agent
source env/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload > server.log 2>&1 &
SERVER_PID=$!

# Wait for startup
sleep 5

# Health check
echo "=== Health Check ==="
curl -s http://localhost:8000/health | python3 -m json.tool

echo ""
echo "=== Registered Routes ==="
curl -s http://localhost:8000/openapi.json | python3 -c "
import json, sys
spec = json.load(sys.stdin)
for path, methods in spec['paths'].items():
    for method in methods:
        print(f'  {method.upper():<8} {path}')
"

echo ""
echo "Server running — PID=$SERVER_PID"
echo "Docs: http://localhost:8000/docs"
