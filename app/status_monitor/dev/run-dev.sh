#!/usr/bin/env bash
#
# Starts the status page development environment:
#   1. Mock data server (port 3001)
#   2. Mock data control panel (port 3002)
#   3. Vite dev server with hot reload (port 3000)
#
# Prerequisites:
#   - npm dependencies installed (cd ../frontend && npm install)
#
# Usage:
#   ./run-dev.sh          # start all servers
#   Ctrl-C                # stop all servers

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/../frontend"

cleanup() {
    echo ""
    echo "Shutting down..."
    kill $MOCK_PID $CONTROL_PID $VITE_PID 2>/dev/null
    wait $MOCK_PID $CONTROL_PID $VITE_PID 2>/dev/null
    echo "Done."
}
trap cleanup EXIT

python3 "$SCRIPT_DIR/mock_server.py" &
MOCK_PID=$!

python3 "$SCRIPT_DIR/mock_control.py" &
CONTROL_PID=$!

cd "$FRONTEND_DIR"
MOCK=1 npx vite --host &
VITE_PID=$!

sleep 3

echo ""
echo "========================================"
echo "  Status page dev environment is running"
echo "========================================"
echo ""
echo "  Status page:     http://localhost:3000/status/"
echo "  Mock control:    http://localhost:3002"
echo ""
echo "  Press Ctrl-C to stop all servers."
echo "========================================"
echo ""

wait
