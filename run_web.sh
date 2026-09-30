#!/usr/bin/env bash
# ==============================================================================
# PCB AOI Web Station - Launcher Script
# Starts FastAPI Backend (Port 8000) and Next.js Frontend (Port 3000)
# ==============================================================================

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$PROJECT_DIR/main_program_for_webapp/run_web.sh" ]; then
    echo "🔄 Redirecting to main_program_for_webapp/run_web.sh..."
    cd "$PROJECT_DIR/main_program_for_webapp"
    exec ./run_web.sh "$@"
elif [ -f "$PROJECT_DIR/../main_program_for_webapp/run_web.sh" ]; then
    echo "🔄 Redirecting to main_program_for_webapp/run_web.sh..."
    cd "$PROJECT_DIR/../main_program_for_webapp"
    exec ./run_web.sh "$@"
fi

BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

echo "=========================================================="
echo "  🚀 Starting PCB AOI Inspection Station (Web Edition)"
echo "=========================================================="

# Find LAN IP address for iPad access
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1")

# Clean up background jobs on exit
cleanup() {
    echo ""
    echo "🛑 Shutting down PCB AOI Web Station..."
    if [ -n "$BACKEND_PID" ]; then
        kill "$BACKEND_PID" 2>/dev/null || true
    fi
    if [ -n "$FRONTEND_PID" ]; then
        kill "$FRONTEND_PID" 2>/dev/null || true
    fi
    wait 2>/dev/null || true
    echo "👋 All services stopped cleanly."
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# 1. Start Backend (FastAPI)
echo "📦 [1/2] Starting FastAPI Backend on port 8000..."
cd "$BACKEND_DIR"
if [ ! -d "venv" ]; then
    echo "❌ Error: Virtual environment 'backend/venv' not found."
    exit 1
fi

venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Wait for backend to respond
echo "⏳ Waiting for backend to initialize..."
until curl -s http://127.0.0.1:8000/api/system/status > /dev/null 2>&1; do
    sleep 0.5
done
echo "✅ Backend is READY on http://0.0.0.0:8000"

# 2. Start Frontend (Next.js)
echo "🌐 [2/2] Starting Next.js Frontend on port 3001..."
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "=========================================================="
echo "  ✨ PCB AOI Station is RUNNING!"
echo "=========================================================="
echo "  🖥️  Local Machine:  http://localhost:3001"
echo "  📱  iPad / LAN:      http://$LAN_IP:3001"
echo "  ⚙️  Backend API:     http://localhost:8000/docs"
echo "  🔑  Default Passcode: 1234"
echo "=========================================================="
echo "Press Ctrl+C to stop all services."

# Keep script running to monitor children
wait
