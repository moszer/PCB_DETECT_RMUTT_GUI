#!/usr/bin/env bash
# Start only this station's processes, preserve failures, and stop both on exit.
#   ./run_web.sh            development mode (hot reload), or the mode in .station-mode
#   ./run_web.sh --prod     build the frontend once and serve it (faster, lighter: Jetson / daily use)
#   ./run_web.sh --dev      development mode even where .station-mode says prod
#   ./run_web.sh --update   upgrade the Python/JS libraries first (not PyTorch), then start
#   ./run_web.sh --no-check skip the library check at start-up
# A station that must always run one mode keeps it in .station-mode (not in git):
#   echo prod > .station-mode
set -euo pipefail
MODE="dev"; UPDATE=0; CHECK=1
MODE_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.station-mode"
if [[ -f "$MODE_FILE" ]]; then
    case "$(tr -d '[:space:]' < "$MODE_FILE")" in
        prod) MODE="prod" ;;
        dev|"") ;;
        *) echo "Unknown mode in $MODE_FILE (use prod or dev)" >&2; exit 2 ;;
    esac
fi
for arg in "$@"; do
    case "$arg" in
        --prod) MODE="prod" ;;
        --dev) MODE="dev" ;;
        --update) UPDATE=1 ;;
        --no-check) CHECK=0 ;;
        -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Which code version is running, so ./update.sh knows whether a restart is needed.
mkdir -p "$PROJECT_DIR/.cache" && git -C "$PROJECT_DIR" rev-parse HEAD > "$PROJECT_DIR/.cache/station.commit" 2>/dev/null || true
echo "$$" > "$PROJECT_DIR/.cache/station.pid" 2>/dev/null || true
BACKEND_PORT="${PCB_BACKEND_PORT:-8000}"
FRONTEND_PORT="${PCB_FRONTEND_PORT:-3001}"
PY="$PROJECT_DIR/backend/venv/bin/python"
CONSOLE="$PROJECT_DIR/scripts/console.py"
BACKEND_PID=""
FRONTEND_PID=""
UPDATES_FILE=""
UPDATES_PID=""

if [[ -t 1 && -z "${NO_COLOR:-}" ]] || [[ "${PCB_FORCE_COLOR:-}" == "1" ]]; then
    B=$'\e[1m'; D=$'\e[2m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; C=$'\e[36m'; N=$'\e[0m'
else B=; D=; G=; Y=; R=; C=; N=; fi
section() { echo; echo "${B}${C}▸ $*${N}"; }
ok()   { echo "  ${G}✓${N} $*"; }
warn() { echo "  ${Y}!${N} $*"; }
fail() { echo "  ${R}✗${N} $*" >&2; }

cleanup() {
    code=$?
    trap - EXIT INT TERM
    for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
        if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; fi
    done
    [[ -n "$UPDATES_FILE" ]] && rm -f "$UPDATES_FILE"
    wait 2>/dev/null || true
    exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# ── banner ────────────────────────────────────────────────────────────────────
VERSION="$(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null || echo n/a)"
BANNER=$(cat <<TXT
${B}RMUTT AOI · PCB Inspection Station${N}
มหาวิทยาลัยเทคโนโลยีราชมงคลธัญบุรี
${D}Rajamangala University of Technology Thanyaburi${N}

${D}version${N} $VERSION   ${D}mode${N} $MODE   ${D}host${N} $(uname -s) $(uname -m)
${D}AI vision inspection for printed circuit boards${N}
TXT
)
echo
if [[ -x "$PY" && -f "$CONSOLE" ]]; then printf '%s\n' "$BANNER" | "$PY" "$CONSOLE" banner || printf '%s\n' "$BANNER"
else printf '%s\n' "$BANNER"; fi

# ── environment ───────────────────────────────────────────────────────────────
section "Checking environment"
if [[ ! -x "$PY" || ! -f "$PROJECT_DIR/frontend/node_modules/next/dist/bin/next" ]]; then
    fail "Missing backend virtual environment or frontend dependencies. Run ./install.sh first."
    exit 1
fi
ok "Python $("$PY" -c 'import platform; print(platform.python_version())') · Node $(node --version | sed 's/^v//') · npm $(npm --version)"
if [[ -f "$PROJECT_DIR/best.pt" ]] && ! head -c 40 "$PROJECT_DIR/best.pt" | grep -q "git-lfs"; then
    ok "YOLO model best.pt ($(du -h "$PROJECT_DIR/best.pt" | cut -f1))"
else warn "No usable best.pt next to run_web.sh — run ./install.sh to download it from Hugging Face, or pick a model in Settings"; fi
if [[ -f "$PROJECT_DIR/backend/.env" ]]; then ok "backend/.env found"; else warn "backend/.env missing (copy backend/.env.example) — AI assistant and passcode use defaults"; fi

if [[ $UPDATE -eq 1 ]]; then
    section "Updating libraries (PyTorch is left as installed)"
    REQ_TMP="$(mktemp)"
    grep -vE '^\s*(#|$)|^\s*(torch|torchvision)\b' "$PROJECT_DIR/backend/requirements.txt" > "$REQ_TMP"
    "$PY" -m pip install --upgrade --quiet -r "$REQ_TMP" && ok "Python packages upgraded" || warn "Python upgrade had errors (see above)"
    rm -f "$REQ_TMP"
    (cd "$PROJECT_DIR/frontend" && npm update --no-audit --no-fund --loglevel=error) && ok "Frontend packages upgraded" || warn "npm update had errors"
    rm -f "$PROJECT_DIR/.cache/library-updates.json"
    warn "Libraries changed — if something misbehaves: ./install.sh --test"
fi

if [[ $CHECK -eq 1 ]]; then
    section "Checking libraries"
    "$PY" "$CONSOLE" deps || true
    # Newer-release lookup uses the network and can take a few seconds: do it while the station starts.
    UPDATES_FILE="$(mktemp)"
    ( "$PY" "$CONSOLE" deps --updates 2>/dev/null | sed -n -E '/(newer library|up to date)/,$p' > "$UPDATES_FILE" ) &
    UPDATES_PID=$!
fi

# Refuse occupied ports rather than accidentally connecting to another station.
"$PY" - "$BACKEND_PORT" "$FRONTEND_PORT" <<'PY'
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
ok "Ports $BACKEND_PORT (backend) and $FRONTEND_PORT (frontend) are free"

wait_ready() {
    local pid="$1" url="$2" service="$3"
    for ((i=0; i<180; i++)); do
        if ! kill -0 "$pid" 2>/dev/null; then
            fail "$service exited before becoming ready."
            return 1
        fi
        if curl --fail --silent --max-time 2 "$url" >/dev/null 2>&1; then return 0; fi
        sleep 1
    done
    fail "$service startup timed out."
    return 1
}

# ── start ─────────────────────────────────────────────────────────────────────
section "Starting"
echo "  ${D}…${N} backend  (FastAPI + YOLO) on port $BACKEND_PORT"
cd "$PROJECT_DIR/backend"
venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --log-level warning &
BACKEND_PID=$!
wait_ready "$BACKEND_PID" "http://127.0.0.1:$BACKEND_PORT/api/system/status" Backend
ok "backend ready (pid $BACKEND_PID)"

cd "$PROJECT_DIR/frontend"
export BACKEND_URL="http://127.0.0.1:$BACKEND_PORT"
if [[ "$MODE" == "prod" ]]; then
    # Rebuild when the source is newer than the last build (rewrites bake BACKEND_URL in at build time).
    if [[ ! -f .next/BUILD_ID ]] || [[ -n "$(find src public next.config.ts package.json -newer .next/BUILD_ID -print -quit 2>/dev/null)" ]] \
        || [[ "$(cat .next/.backend-url 2>/dev/null)" != "$BACKEND_URL" ]]; then
        echo "  ${D}…${N} building the frontend (first run or source changed)"
        node node_modules/next/dist/bin/next build >/dev/null
        echo "$BACKEND_URL" > .next/.backend-url
        ok "frontend built"
    fi
    echo "  ${D}…${N} frontend (Next.js production) on port $FRONTEND_PORT"
    node node_modules/next/dist/bin/next start -p "$FRONTEND_PORT" &
else
    echo "  ${D}…${N} frontend (Next.js dev server) on port $FRONTEND_PORT"
    node node_modules/next/dist/bin/next dev -p "$FRONTEND_PORT" &
fi
FRONTEND_PID=$!
wait_ready "$FRONTEND_PID" "http://127.0.0.1:$FRONTEND_PORT" Frontend
ok "frontend ready (pid $FRONTEND_PID)"

# ── what is running ───────────────────────────────────────────────────────────
"$PY" "$CONSOLE" status --backend-port "$BACKEND_PORT" --frontend-port "$FRONTEND_PORT" --mode "$MODE" \
    --backend-pid "$BACKEND_PID" --frontend-pid "$FRONTEND_PID" || true
if [[ -n "$UPDATES_FILE" ]]; then
    # The lookup runs in the background; give it a few more seconds, but never block the station on it.
    for ((i=0; i<20; i++)); do kill -0 "$UPDATES_PID" 2>/dev/null || break; sleep 1; done
    if kill -0 "$UPDATES_PID" 2>/dev/null; then kill "$UPDATES_PID" 2>/dev/null || true; warn "Library update lookup timed out (offline?) — skipped"
    elif [[ -s "$UPDATES_FILE" ]]; then section "Library updates"; cat "$UPDATES_FILE"; echo; fi
fi
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do sleep 1; done
echo "A station service exited; stopping the other service." >&2
exit 1
