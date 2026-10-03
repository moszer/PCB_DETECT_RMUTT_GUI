#!/usr/bin/env bash
# ==============================================================================
# RMUTT PCB AOI Station — one-command installer
#
#   ./install.sh            install everything for this machine
#   ./install.sh --cpu      Linux PC: CPU-only PyTorch (smaller download, no NVIDIA GPU)
#   ./install.sh --test     also run the backend test suite at the end
#   ./install.sh --no-system  skip OS packages (apt / Homebrew), e.g. without sudo
#   ./install.sh --yes      don't ask before installing OS packages
#
# Detects macOS (Apple Silicon / Intel), Linux PC (x86_64 / arm64) and NVIDIA Jetson
# (Orin Nano etc.), then installs: OS packages, Node.js 20+, a Python venv with the right
# PyTorch build, the frontend packages and backend/.env. Safe to run again (updates).
# ==============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$PROJECT_DIR/backend"
FRONTEND="$PROJECT_DIR/frontend"
VENV="$BACKEND/venv"
NODE_MIN_MAJOR=20
PY_MIN_MINOR=10

CPU_ONLY=0; RUN_TESTS=0; SYSTEM=1; ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --cpu) CPU_ONLY=1 ;;
    --test) RUN_TESTS=1 ;;
    --no-system) SYSTEM=0 ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help) sed -n '3,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done

# ── output helpers ────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then B=$'\e[1m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; C=$'\e[36m'; N=$'\e[0m'; else B=; G=; Y=; R=; C=; N=; fi
step() { echo; echo "${B}${C}==> $*${N}"; }
ok()   { echo "  ${G}✓${N} $*"; }
warn() { echo "  ${Y}!${N} $*"; }
die()  { echo "${R}✗ $*${N}" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
confirm() {
  [[ $ASSUME_YES -eq 1 || ! -t 0 ]] && return 0
  read -r -p "  $1 [Y/n] " reply; [[ -z "$reply" || "$reply" =~ ^[Yy] ]]
}

SUDO=""
if [[ $(id -u) -ne 0 ]]; then have sudo && SUDO="sudo"; fi

# ── detect the platform ───────────────────────────────────────────────────────
OS="$(uname -s)"; ARCH="$(uname -m)"; PLATFORM=""; L4T=""
if [[ "$OS" == "Darwin" ]]; then
  PLATFORM="macos"
elif [[ "$OS" == "Linux" ]]; then
  if [[ -f /etc/nv_tegra_release ]] || [[ -d /usr/local/cuda && "$ARCH" == "aarch64" && -e /dev/nvhost-ctrl ]] || dpkg -l nvidia-l4t-core >/dev/null 2>&1; then
    PLATFORM="jetson"
    # e.g. "# R36 (release), REVISION: 4.3" -> 36 ; dpkg version "39.2.1-..." -> 39
    L4T="$(sed -n 's/^# R\([0-9]*\).*/\1/p' /etc/nv_tegra_release 2>/dev/null || true)"
    [[ -z "$L4T" ]] && L4T="$(dpkg-query -W -f='${Version}' nvidia-l4t-core 2>/dev/null | cut -d. -f1 || true)"
  else
    PLATFORM="linux"
  fi
else
  die "Unsupported OS: $OS (use macOS, Linux or Windows WSL2)"
fi

step "Platform"
case "$PLATFORM" in
  macos)  ok "macOS $(sw_vers -productVersion 2>/dev/null) · $ARCH" ;;
  jetson) ok "NVIDIA Jetson · L4T R${L4T:-?} · $ARCH" ;;
  linux)  ok "Linux $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME") · $ARCH" ;;
esac

# ── OS packages ───────────────────────────────────────────────────────────────
node_major() { have node && node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0; }

install_system_macos() {
  if ! have brew; then
    warn "Homebrew is not installed."
    if confirm "Install Homebrew now (needed for Python/Node)?"; then
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
      [[ -x /opt/homebrew/bin/brew ]] && eval "$(/opt/homebrew/bin/brew shellenv)"
      [[ -x /usr/local/bin/brew ]] && eval "$(/usr/local/bin/brew shellenv)"
    else
      warn "Skipping Homebrew: install Python ≥3.$PY_MIN_MINOR and Node ≥$NODE_MIN_MAJOR yourself."; return
    fi
  fi
  local pkgs=()
  python_ok || pkgs+=(python@3.12)
  [[ $(node_major) -ge $NODE_MIN_MAJOR ]] || pkgs+=(node)
  if [[ ${#pkgs[@]} -gt 0 ]]; then
    confirm "brew install ${pkgs[*]}?" && brew install "${pkgs[@]}"
  fi
  ok "Homebrew packages ready"
}

install_system_linux() {
  if ! have apt-get; then
    warn "No apt-get (not Debian/Ubuntu): install python3-venv, python3-dev, build tools, libgl1, tesseract and Node ≥$NODE_MIN_MAJOR yourself."
    return
  fi
  if [[ -z "$SUDO" && $(id -u) -ne 0 ]]; then
    warn "No sudo: skipping OS packages (re-run with sudo rights, or use --no-system)."; return
  fi
  local pkgs=(python3 python3-venv python3-pip python3-dev build-essential curl ca-certificates git
              libgl1 libglib2.0-0 tesseract-ocr v4l-utils)
  if confirm "apt-get install ${pkgs[*]}?"; then
    $SUDO apt-get update -y
    DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y --no-install-recommends "${pkgs[@]}"
  fi
  if [[ $(node_major) -lt $NODE_MIN_MAJOR ]]; then
    if confirm "Install Node.js 22 LTS (NodeSource)?"; then
      if [[ -n "$SUDO" ]]; then curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
      else curl -fsSL https://deb.nodesource.com/setup_22.x | bash -; fi
      DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y nodejs
    fi
  fi
  # Serial (XY stage) and camera access without root; takes effect after re-login.
  local user="${SUDO_USER:-${USER:-$(id -un)}}"
  if [[ -n "$user" && "$user" != "root" ]] && have usermod; then
    local missing=()
    for g in dialout video; do getent group "$g" >/dev/null && ! id -nG "$user" | grep -qw "$g" && missing+=("$g"); done
    if [[ ${#missing[@]} -gt 0 ]]; then
      $SUDO usermod -aG "$(IFS=,; echo "${missing[*]}")" "$user" && warn "Added $user to ${missing[*]} — log out and back in for camera/serial access."
    fi
  fi
  ok "System packages ready"
}

# ── Python ────────────────────────────────────────────────────────────────────
PYTHON=""
python_ok() {
  local cands=(python3.12 python3.13 python3.14 python3.11 python3.10 python3)
  # NVIDIA's JetPack 6 PyTorch wheels are built for its stock Python 3.10 only.
  [[ "$PLATFORM" == "jetson" && "${L4T:-0}" -eq 36 ]] && cands=(python3.10 "${cands[@]}")
  for cand in "${cands[@]}"; do
    if have "$cand" && "$cand" -c "import sys; sys.exit(0 if sys.version_info >= (3, $PY_MIN_MINOR) else 1)" 2>/dev/null; then
      PYTHON="$(command -v "$cand")"; return 0
    fi
  done
  return 1
}

if [[ $SYSTEM -eq 1 ]]; then
  step "OS packages"
  if [[ "$PLATFORM" == "macos" ]]; then install_system_macos; else install_system_linux; fi
else
  step "OS packages (skipped: --no-system)"
fi

step "Python environment"
python_ok || die "Python ≥3.$PY_MIN_MINOR not found. Install it (macOS: brew install python@3.12 · Ubuntu: sudo apt install python3 python3-venv)."
ok "Using $("$PYTHON" --version) ($PYTHON)"
if [[ -x "$VENV/bin/python" ]] && ! "$VENV/bin/python" -c "import sys" 2>/dev/null; then
  warn "Existing venv is broken; recreating"; rm -rf "$VENV"
fi
if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON" -m venv "$VENV"
  ok "Created backend/venv"
else
  ok "Reusing backend/venv"
fi
PIP=("$VENV/bin/python" -m pip)
"${PIP[@]}" install --upgrade --quiet pip wheel setuptools

# ── PyTorch: the build depends on the machine ────────────────────────────────
torch_ok() { "$VENV/bin/python" -c "import torch, torchvision" 2>/dev/null; }
step "PyTorch"
case "$PLATFORM" in
  macos)
    torch_ok || "${PIP[@]}" install torch torchvision
    ;;
  linux)
    if [[ $CPU_ONLY -eq 0 ]] && have nvidia-smi && nvidia-smi -L >/dev/null 2>&1; then
      ok "NVIDIA GPU found: installing the CUDA build (large download)"
      torch_ok || "${PIP[@]}" install torch torchvision
    else
      [[ $CPU_ONLY -eq 1 ]] && ok "--cpu: CPU-only build" || ok "No NVIDIA GPU: CPU-only build"
      torch_ok || "${PIP[@]}" install --index-url https://download.pytorch.org/whl/cpu torch torchvision
    fi
    ;;
  jetson)
    if torch_ok && "$VENV/bin/python" -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)" 2>/dev/null; then
      ok "CUDA PyTorch already installed"
    elif [[ -n "${PCB_TORCH_INDEX:-}" ]]; then
      "${PIP[@]}" install --index-url "$PCB_TORCH_INDEX" torch torchvision
    elif [[ "${L4T:-0}" -ge 39 ]]; then
      ok "JetPack 7 (L4T R$L4T): CUDA 13 build (tested on Orin Nano Super)"
      "${PIP[@]}" install -r "$BACKEND/requirements-jetson-cu130.txt"
    elif [[ "${L4T:-0}" -eq 36 ]]; then
      ok "JetPack 6 (L4T R36): NVIDIA Jetson AI Lab wheels"
      "${PIP[@]}" install --index-url https://pypi.jetson-ai-lab.io/jp6/cu126 torch torchvision \
        || die "Could not install PyTorch for JetPack 6. Find the wheel for your JetPack at https://forums.developer.nvidia.com/t/pytorch-for-jetson/72048 and re-run with PCB_TORCH_INDEX=<index-url> ./install.sh"
    else
      die "JetPack with L4T R${L4T:-?} is not handled automatically. Install NVIDIA's PyTorch for it (https://forums.developer.nvidia.com/t/pytorch-for-jetson/72048), then re-run ./install.sh — or pass PCB_TORCH_INDEX=<index-url>."
    fi
    ;;
esac
torch_ok || die "PyTorch did not install"
ok "$("$VENV/bin/python" -c 'import torch; print("torch", torch.__version__)')"

step "Backend packages"
"${PIP[@]}" install -r "$BACKEND/requirements.txt"
ok "Backend packages installed"

# ── Frontend ──────────────────────────────────────────────────────────────────
step "Frontend packages"
[[ $(node_major) -ge $NODE_MIN_MAJOR ]] || die "Node.js ≥$NODE_MIN_MAJOR is required (found: $(node --version 2>/dev/null || echo none)). Install Node 22 LTS and re-run."
ok "Node $(node --version) · npm $(npm --version)"
( cd "$FRONTEND" && npm ci --no-audit --no-fund --loglevel=error )
ok "Frontend packages installed"

# ── Configuration ─────────────────────────────────────────────────────────────
step "Configuration"
if [[ ! -f "$BACKEND/.env" ]]; then
  cp "$BACKEND/.env.example" "$BACKEND/.env"; chmod 600 "$BACKEND/.env"
  ok "Created backend/.env from .env.example (add your AI key / operator passcode there)"
else
  ok "Keeping existing backend/.env"
fi
MODEL="$PROJECT_DIR/best.pt"
if [[ -f "$MODEL" ]] && head -c 40 "$MODEL" | grep -q "git-lfs"; then
  warn "best.pt is a Git LFS pointer, not the model. Run: git lfs install && git lfs pull"
elif [[ -f "$MODEL" ]]; then
  ok "YOLO model: best.pt ($(du -h "$MODEL" | cut -f1))"
else
  warn "No best.pt next to run_web.sh — pick a model later in Settings"
fi

# ── Verify ────────────────────────────────────────────────────────────────────
step "Check"
"$VENV/bin/python" - <<'PY'
import platform, shutil, torch, cv2, ultralytics
dev = "cuda (" + torch.cuda.get_device_name(0) + ")" if torch.cuda.is_available() else \
      "mps (Apple GPU)" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu"
print(f"  ✓ Python {platform.python_version()} · torch {torch.__version__} · OpenCV {cv2.__version__} · ultralytics {ultralytics.__version__}")
print(f"  ✓ AI device: {dev}")
try:
    import Vision  # noqa: F401
    print("  ✓ OCR: Apple Vision")
except Exception:
    print("  ✓ OCR: tesseract" if shutil.which("tesseract") else "  ! OCR: no engine (install tesseract-ocr) — reading part markings is disabled")
PY

if [[ $RUN_TESTS -eq 1 ]]; then
  step "Backend tests"
  ( cd "$BACKEND" && venv/bin/python -m pytest -q )
fi

echo
echo "${B}${G}Installed.${N} Start the station with:"
echo "    ${B}cd \"$PROJECT_DIR\" && ./run_web.sh${N}"
echo "  then open http://localhost:${PCB_FRONTEND_PORT:-3001}  (default operator passcode: rmutt-aoi — change it in backend/.env)"
