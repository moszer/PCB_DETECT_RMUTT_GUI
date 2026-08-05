#!/bin/bash
# Run this from the project folder on your Mac:
#   cd "/Users/pattaraponprakodchue/Desktop/Desktop Files/defect detection yolo"
#   bash push_to_github.sh
set -e

# 1. Clear any stale git lock files (left over from the sandbox session)
rm -f .git/index.lock .git/HEAD.lock .git/packed-refs.lock .git/refs/heads/*.lock

# 2. Install git-lfs if missing (needs Homebrew: https://brew.sh)
if ! git lfs version >/dev/null 2>&1; then
  brew install git-lfs
fi
git lfs install

# 3. Make sure .pt files are LFS-tracked (.gitattributes already set this)
git lfs track "*.pt"

# 4. Commit current work (new app/ code, .gitignore, .gitattributes)
git add -A
git commit -m "Add modular GUI, .gitignore, LFS attrs" || echo "nothing new to commit"

# 5. Rename branch to main
git branch -M main

# 6. Ensure remote points at your repo
git remote remove origin 2>/dev/null || true
git remote add origin https://github.com/moszer/PCB_DETECT_RMUTT_GUI.git

# 7. Rewrite history so the big .pt files move into LFS (fixes GitHub's 100MB limit)
git lfs migrate import --include="*.pt" --everything

# 8. Push everything
git push -u origin main
