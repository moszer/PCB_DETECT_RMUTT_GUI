#!/usr/bin/env bash
# Start only this station's processes, preserve failures, and stop both on exit.
#   ./run_web.sh          development mode (hot reload)
#   ./run_web.sh --prod   build the frontend once and serve it (faster, lighter: Jetson / daily use)
set -euo pipefail
MODE="dev"
for arg in "$@"; do
    case "$arg" in
        --prod) MODE="prod" ;;
        -h|--help) sed -n '2,4p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${PCB_BACKEND_PORT:-8000}"
FRONTEND_PORT="${PCB_FRONTEND_PORT:-3001}"
BACKEND_PID=""
FRONTEND_PID=""
cleanup() {
    code=$?
    trap - EXIT INT TERM
    for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
        if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; fi
    done
    wait 2>/dev/null || true
    exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [[ ! -x "$PROJECT_DIR/backend/venv/bin/python" || ! -f "$PROJECT_DIR/frontend/node_modules/next/dist/bin/next" ]]; then
    echo "Missing backend virtual environment or frontend dependencies. Run ./install.sh first." >&2
    exit 1
fi
# Refuse occupied ports rather than accidentally connecting to another station.
"$PROJECT_DIR/backend/venv/bin/python" - "$BACKEND_PORT" "$FRONTEND_PORT" <<'PY'
import socket, sys, time
for port in sys.argv[1:]:
    port_int = int(port)
    bound = False
    for _ in range(6):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(('0.0.0.0', port_int))
                bound = True
                break
            except (ValueError, OSError):
                time.sleep(0.5)
    if not bound:
        sys.exit(f'Cannot start station on port {port}: Address already in use by another running process.')
PY
cd "$PROJECT_DIR/backend"
venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" &
BACKEND_PID=$!
wait_ready() {
    local pid="$1" url="$2" service="$3"
    for ((i=0; i<180; i++)); do
        if ! kill -0 "$pid" 2>/dev/null; then
            echo "$service exited before becoming ready." >&2
            return 1
        fi
        if curl --fail --silent --max-time 2 "$url" >/dev/null 2>&1; then return 0; fi
        sleep 1
    done
    echo "$service startup timed out." >&2
    return 1
}
wait_ready "$BACKEND_PID" "http://127.0.0.1:$BACKEND_PORT/api/system/status" Backend
cd "$PROJECT_DIR/frontend"
export BACKEND_URL="http://127.0.0.1:$BACKEND_PORT"
if [[ "$MODE" == "prod" ]]; then
    # Rebuild when the source is newer than the last build (rewrites bake BACKEND_URL in at build time).
    if [[ ! -f .next/BUILD_ID ]] || [[ -n "$(find src public next.config.ts package.json -newer .next/BUILD_ID -print -quit 2>/dev/null)" ]] \
        || [[ "$(cat .next/.backend-url 2>/dev/null)" != "$BACKEND_URL" ]]; then
        echo "Building the frontend (first run or source changed)..."
        node node_modules/next/dist/bin/next build
        echo "$BACKEND_URL" > .next/.backend-url
    fi
    node node_modules/next/dist/bin/next start -p "$FRONTEND_PORT" &
else
    node node_modules/next/dist/bin/next dev -p "$FRONTEND_PORT" &
fi
FRONTEND_PID=$!
wait_ready "$FRONTEND_PID" "http://127.0.0.1:$FRONTEND_PORT" Frontend
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || true)
LAN_IP="${LAN_IP:-127.0.0.1}"
echo "Station ready: http://localhost:$FRONTEND_PORT · LAN: http://$LAN_IP:$FRONTEND_PORT"
echo "Use the configured operator passcode. Press Ctrl+C to stop."
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do sleep 1; done
echo "A station service exited; stopping the other service." >&2
exit 1
