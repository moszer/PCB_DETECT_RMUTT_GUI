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
BUILD_PID=""
UPDATES_FILE=""
UPDATES_PID=""

if [[ -t 1 && -z "${NO_COLOR:-}" ]] || [[ "${PCB_FORCE_COLOR:-}" == "1" ]]; then
    B=$'\e[1m'; D=$'\e[2m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; C=$'\e[36m'; N=$'\e[0m'
else B=; D=; G=; Y=; R=; C=; N=; fi
section() { echo; echo "${B}${C}▸ $*${N}"; }
# Spinners only on a real terminal (not in .cache/run_web.log); PCB_NO_ANIM=1 turns them off.
ANIM=0
if [[ -t 1 && -z "${NO_COLOR:-}" && -z "${PCB_NO_ANIM:-}" ]]; then ANIM=1; fi
SPIN=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏)
spin_frame() {  # tick, label, [detail]
    [[ $ANIM -eq 1 ]] || return 0
    local cols detail="${3:-}"
    cols=$(tput cols 2>/dev/null || echo 100)
    if [[ -n "$detail" ]]; then
        detail="${detail//$'\r'/}"
        local room=$(( cols - ${#2} - 16 ))
        (( room > 8 )) && detail=" ${D}${detail:0:$room}${N}" || detail=""
    fi
    printf '\r\033[K  %s%s%s %s %s%ss%s%s' "$C" "${SPIN[$(( $1 % 10 ))]}" "$N" "$2" "$D" "$(( $1 / 10 ))" "$N" "$detail"
}
spin_clear() { [[ $ANIM -eq 1 ]] && printf '\r\033[K' || true; }
# Background service output: clear the spinner line first so both stay readable.
tidy() { if [[ $ANIM -eq 1 ]]; then while IFS= read -r line; do printf '\r\033[K%s\n' "$line"; done; else cat; fi; }
ok()   { echo "  ${G}✓${N} $*"; }
warn() { echo "  ${Y}!${N} $*"; }
fail() { echo "  ${R}✗${N} $*" >&2; }

cleanup() {
    code=$?
    trap - EXIT INT TERM
    spin_clear
    for pid in "$BUILD_PID" "$FRONTEND_PID" "$BACKEND_PID"; do
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

READY_SECS=0
wait_ready() {  # pid, url, service name, spinner label
    local pid="$1" url="$2" service="$3" label="${4:-$3 starting}"
    for ((i=0; i<1800; i++)); do  # 0.1 s ticks, 3 min
        if ! kill -0 "$pid" 2>/dev/null; then
            spin_clear; fail "$service exited before becoming ready."
            return 1
        fi
        if (( i % 10 == 0 )) && curl --fail --silent --max-time 2 "$url" >/dev/null 2>&1; then
            spin_clear; READY_SECS=$(( i / 10 )); return 0
        fi
        spin_frame "$i" "$label"
        sleep 0.1
    done
    spin_clear; fail "$service startup timed out."
    return 1
}
took() { (( $1 > 0 )) && echo " ${D}· ${1}s${N}" || true; }

# ── start ─────────────────────────────────────────────────────────────────────
section "Starting"
[[ $ANIM -eq 1 ]] || echo "  ${D}…${N} backend  (FastAPI + YOLO) on port $BACKEND_PORT"
cd "$PROJECT_DIR/backend"
# Keep-alive longer than the web server's proxy reuses idle connections: at uvicorn's default
# 5 s, Next sometimes reused a socket uvicorn had just closed (ECONNRESET → HTTP 500 on /api).
# Live streams end on the stop signal (app/core/shutdown.py); anything still open after 5 s is
# cut instead of holding the stop forever.
venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --log-level warning --timeout-keep-alive 75 --timeout-graceful-shutdown 5 > >(tidy) 2>&1 &
BACKEND_PID=$!
wait_ready "$BACKEND_PID" "http://127.0.0.1:$BACKEND_PORT/api/system/status" Backend "backend (FastAPI + YOLO) starting on port $BACKEND_PORT"
ok "backend ready (pid $BACKEND_PID)$(took $READY_SECS)"

cd "$PROJECT_DIR/frontend"
export BACKEND_URL="http://127.0.0.1:$BACKEND_PORT"
if [[ "$MODE" == "prod" ]]; then
    # Rebuild when the source is newer than the last build (rewrites bake BACKEND_URL in at build time).
    if [[ ! -f .next/BUILD_ID ]] || [[ -n "$(find src public next.config.ts package.json -newer .next/BUILD_ID -print -quit 2>/dev/null)" ]] \
        || [[ "$(cat .next/.backend-url 2>/dev/null)" != "$BACKEND_URL" ]]; then
        BUILD_LOG="$PROJECT_DIR/.cache/frontend-build.log"
        [[ $ANIM -eq 1 ]] || echo "  ${D}…${N} building the frontend (first run or source changed)"
        node node_modules/next/dist/bin/next build > "$BUILD_LOG" 2>&1 &
        BUILD_PID=$!
        tick=0
        while kill -0 "$BUILD_PID" 2>/dev/null; do
            # The build's latest step, without its colours.
            spin_frame "$tick" "building the frontend" "$(tail -n 1 "$BUILD_LOG" 2>/dev/null | sed -E 's/\x1b\[[0-9;]*[A-Za-z]//g')"
            sleep 0.1; tick=$(( tick + 1 ))
        done
        spin_clear
        if ! wait "$BUILD_PID"; then
            BUILD_PID=""
            fail "frontend build failed — last lines of $BUILD_LOG:"
            tail -n 25 "$BUILD_LOG" | sed 's/^/    /' >&2
            exit 1
        fi
        BUILD_PID=""
        echo "$BACKEND_URL" > .next/.backend-url
        ok "frontend built$(took $(( tick / 10 )))"
    fi
    [[ $ANIM -eq 1 ]] || echo "  ${D}…${N} frontend (Next.js production) on port $FRONTEND_PORT"
    node node_modules/next/dist/bin/next start -p "$FRONTEND_PORT" > >(tidy) 2>&1 &
    FRONTEND_LABEL="frontend (Next.js production) starting on port $FRONTEND_PORT"
else
    [[ $ANIM -eq 1 ]] || echo "  ${D}…${N} frontend (Next.js dev server) on port $FRONTEND_PORT"
    node node_modules/next/dist/bin/next dev -p "$FRONTEND_PORT" > >(tidy) 2>&1 &
    FRONTEND_LABEL="frontend (Next.js dev server) starting on port $FRONTEND_PORT"
fi
FRONTEND_PID=$!
wait_ready "$FRONTEND_PID" "http://127.0.0.1:$FRONTEND_PORT" Frontend "$FRONTEND_LABEL"
ok "frontend ready (pid $FRONTEND_PID)$(took $READY_SECS)"

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
