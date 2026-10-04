#!/usr/bin/env bash
# Update the station to the latest code on GitHub, in one command.
#   ./update.sh               pull, update libraries if they changed, restart the station here
#   ./update.sh --background  restart it in the background instead (e.g. over SSH); log in .cache/run_web.log
#   ./update.sh --no-restart  only pull and update libraries
#   ./update.sh --force       update even while a scan is running (it will be stopped)
# Your data (backend/data, backend/.env, models) is not touched: git does not track it.
set -euo pipefail
# Everything runs from main(): bash parses it whole first, so git pull may replace this file safely.
main() {
RESTART="here"; FORCE=0
for arg in "$@"; do
    case "$arg" in
        --background) RESTART="background" ;;
        --no-restart) RESTART="no" ;;
        --force) FORCE=1 ;;
        -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $arg (see ./update.sh --help)" >&2; exit 2 ;;
    esac
done
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
BACKEND_PORT="${PCB_BACKEND_PORT:-8000}"

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then B=$'\e[1m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; C=$'\e[36m'; N=$'\e[0m'; else B=; G=; Y=; R=; C=; N=; fi
step() { echo; echo "${B}${C}▸ $*${N}"; }
ok()   { echo "  ${G}✓${N} $*"; }
warn() { echo "  ${Y}!${N} $*"; }
die()  { echo "  ${R}✗${N} $*" >&2; exit 1; }

# ── safety checks ─────────────────────────────────────────────────────────────
step "Checking"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "Not a git checkout. Clone it with: git clone https://github.com/moszer/PCB_DETECT_RMUTT_GUI.git"
scan="$(curl -s -m 3 "http://127.0.0.1:$BACKEND_PORT/api/aoi/scan/status" 2>/dev/null | grep -o '"status":"[a-z]*"' | head -1 || true)"
if [[ "$scan" == '"status":"running"' && $FORCE -eq 0 ]]; then
    die "A scan is running. Wait for it to finish (or run ./update.sh --force)."
fi
# Only tracked files matter; models, data and .env are untracked/ignored.
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    git status --short --untracked-files=no | sed 's/^/    /'
    die "These files were edited here, so the update could overwrite them. Keep them with 'git stash', or undo with 'git checkout -- <file>', then run ./update.sh again."
fi
ok "No local edits$( [[ -n "$scan" ]] && echo ", no scan running")"

# ── pull ──────────────────────────────────────────────────────────────────────
step "Downloading the latest code"
BEFORE="$(git rev-parse HEAD)"
# Skip Git LFS weights (the web station downloads its model from Hugging Face).
GIT_LFS_SKIP_SMUDGE=1 git pull --ff-only --quiet || die "git pull failed (see above). Check the internet connection."
AFTER="$(git rev-parse HEAD)"
if [[ "$BEFORE" == "$AFTER" ]]; then
    ok "Already up to date ($(git log -1 --format='%h %s'))"
else
    ok "Updated $(git rev-list --count "$BEFORE..$AFTER") commit(s):"
    git log --format='      %h %s' "$BEFORE..$AFTER" | head -15
fi

# ── libraries, only when they changed ─────────────────────────────────────────
CHANGED="$(git diff --name-only "$BEFORE" "$AFTER" -- . 2>/dev/null || true)"
if grep -qE '^(main_program_for_webapp/)?(backend/requirements[^/]*\.txt|frontend/package(-lock)?\.json|install\.sh)$' <<<"$CHANGED"; then
    step "Libraries changed: running ./install.sh"
    ./install.sh --no-system --yes
elif [[ "$BEFORE" != "$AFTER" ]]; then
    ok "Libraries unchanged (no install needed)"
fi

# ── restart ───────────────────────────────────────────────────────────────────
station_pids() {  # run_web.sh processes started from this folder
    local pid
    for pid in $(pgrep -f "run_web.sh" 2>/dev/null || true); do
        [[ "$pid" == "$$" ]] && continue
        local cwd=""
        if [[ -e "/proc/$pid/cwd" ]]; then cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
        else cwd="$(lsof -a -d cwd -p "$pid" -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)"; fi
        if [[ "$cwd" == "$PROJECT_DIR" ]] && ps -o args= -p "$pid" | grep -q "bash .*run_web.sh"; then echo "$pid"; fi
    done
    return 0
}
PIDS="$(station_pids)"
ARGS=""
if [[ -n "$PIDS" ]]; then
    ARGS="$(ps -o args= -p "$(head -1 <<<"$PIDS")" | sed -E 's/.*run_web\.sh ?//')"
fi
# A desktop session started before joining "dialout" can't open the stage port: use sg.
LAUNCH=(./run_web.sh)
if [[ "$(uname)" == "Linux" ]] && id -nG "$(id -un)" | grep -qw dialout && ! id -G | tr ' ' '\n' | grep -qx "$(getent group dialout | cut -d: -f3)"; then
    LAUNCH=(sg dialout -c "./run_web.sh $ARGS")
    ARGS=""
fi

if [[ "$RESTART" == "no" ]]; then
    if [[ -n "$PIDS" ]]; then warn "The station is still running the old code: restart run_web.sh to use the update."; fi
    exit 0
fi
if [[ -z "$PIDS" ]]; then
    step "Done"
    echo "  Start the station with: ${B}./run_web.sh --prod${N}  (or ./run_web.sh for development)"
    exit 0
fi
if [[ "$(cat .cache/station.commit 2>/dev/null)" == "$AFTER" ]]; then
    step "Done"
    ok "The running station already uses this version (no restart needed)"
    exit 0
fi
step "Restarting the station (run_web.sh ${ARGS:-<no options>})"
kill -TERM $PIDS 2>/dev/null || true
for _ in $(seq 1 30); do [[ -z "$(station_pids)" ]] && break; sleep 0.5; done
[[ -n "$(station_pids)" ]] && die "The old station did not stop; stop it with Ctrl+C in its window, then run ./run_web.sh"
ok "Stopped the old station"
# shellcheck disable=SC2086
if [[ "$RESTART" == "background" ]]; then
    mkdir -p .cache
    nohup "${LAUNCH[@]}" $ARGS > .cache/run_web.log 2>&1 < /dev/null &
    disown || true
    ok "Started in the background (pid $!). Log: $PROJECT_DIR/.cache/run_web.log"
    echo "  It is ready in about a minute (longer if --prod rebuilds the web page)."
else
    echo
    exec "${LAUNCH[@]}" $ARGS
fi
}

main "$@"
