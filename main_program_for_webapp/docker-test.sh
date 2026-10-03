#!/usr/bin/env bash
# Build the Docker images, run the backend tests, start the station and smoke-test it.
#   ./docker-test.sh          test, then stop and remove the test containers
#   ./docker-test.sh --keep   leave the stack running afterwards (http://localhost:3101)
# Uses ports 3101/8101 so it never collides with a station already running on 3001/8000.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
KEEP=0; [[ "${1:-}" == "--keep" ]] && KEEP=1
export PCB_BACKEND_PORT="${PCB_BACKEND_PORT:-8101}" PCB_FRONTEND_PORT="${PCB_FRONTEND_PORT:-3101}"
PROJECT="rmutt-aoi-test"
DC=(docker compose -p "$PROJECT")
pass() { echo "  ✓ $*"; }
fail() { echo "  ✗ $*" >&2; "${DC[@]}" logs --tail 40 >&2 || true; exit 1; }
cleanup() { [[ $KEEP -eq 1 ]] || "${DC[@]}" down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

command -v docker >/dev/null || { echo "Docker is not installed." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker is not running (start Docker Desktop / the docker service)." >&2; exit 1; }

echo "==> Build images"
"${DC[@]}" build

echo "==> Backend tests (in the container)"
"${DC[@]}" run --rm -e PCB_CAMERA_SIMULATION= backend python -m pytest -q -p no:cacheprovider

echo "==> Start the station"
"${DC[@]}" up -d
for _ in $(seq 1 90); do
  [[ "$("${DC[@]}" ps --format '{{.Service}}={{.Health}}' | tr '\n' ' ')" == *"frontend=healthy"* ]] && break
  sleep 2
done
FRONT="http://localhost:$PCB_FRONTEND_PORT"

echo "==> Smoke tests"
curl -fs "http://localhost:$PCB_BACKEND_PORT/api/health" | grep -q '"status":"ok"' && pass "backend health" || fail "backend health"
[[ "$(curl -s -o /dev/null -w '%{http_code}' "$FRONT/")" == "200" ]] && pass "web page" || fail "web page"
curl -fs "$FRONT/api/camera/status" >/dev/null && pass "frontend → backend proxy" || fail "proxy"
IMG="../test/pass.jpg"
if [[ -f "$IMG" ]]; then
  out="$(curl -fs -m 180 -F "file=@$IMG" "$FRONT/api/inspection/inspect-upload")" || fail "inspection"
  n="$(echo "$out" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["detections"]))')"
  [[ "$n" -gt 0 ]] && pass "YOLO inspection: $n parts on test/pass.jpg" || fail "YOLO found nothing"
fi
bytes="$(curl -s -m 4 -o /dev/null -w '%{size_download}' "$FRONT/api/camera/stream" || true)"
[[ "${bytes:-0}" -gt 10000 ]] && pass "live camera stream (test camera)" || fail "camera stream"

echo
echo "All Docker checks passed."
[[ $KEEP -eq 1 ]] && echo "Still running: $FRONT   (stop: docker compose -p $PROJECT down -v)"
