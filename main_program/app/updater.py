"""Explicit, fast-forward-only updates for Git installations of PCB Inspect."""
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess


REPOSITORY_URL = "https://github.com/moszer/PCB_DETECT_RMUTT_GUI"
ALLOWED_REMOTES = {
    REPOSITORY_URL, REPOSITORY_URL + ".git",
    "git@github.com:moszer/PCB_DETECT_RMUTT_GUI.git",
    "ssh://git@github.com/moszer/PCB_DETECT_RMUTT_GUI.git",
}


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateInfo:
    current: str
    target: str
    version: str
    latest_version: str
    commits: str
    changes: tuple[str, ...]
    blocker: str = ""

    @property
    def available(self):
        return self.current != self.target and not self.blocker


class GitUpdater:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def git(self, *args, timeout=20):
        env = os.environ.copy()
        env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
        try:
            result = subprocess.run(
                ["git", "-C", str(self.root), *args], capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env,
            )
        except FileNotFoundError as exc:
            raise UpdateError("Git is not installed. Install Git and reopen the application.") from exc
        except subprocess.TimeoutExpired as exc:
            raise UpdateError("The update request timed out. Check your connection and try again.") from exc
        if result.returncode:
            raise UpdateError((result.stderr or result.stdout).strip() or "Git command failed.")
        return result.stdout.strip()

    def validate_repository(self):
        try:
            top = self.git("rev-parse", "--show-toplevel")
        except UpdateError as exc:
            raise UpdateError("Automatic updates require a Git clone and Git installed. "
                              f"Download or clone from {REPOSITORY_URL}.\n\n{exc}") from exc
        if Path(top).resolve() != self.root:
            raise UpdateError("This application is not at the root of its own Git checkout.")
        if self.git("remote", "get-url", "origin").rstrip("/") not in ALLOWED_REMOTES:
            raise UpdateError("The origin remote does not point to the official PCB Inspect repository.")

    def version(self, revision):
        return self.git("describe", "--tags", "--always", "--abbrev=8", revision)

    def local_blocker(self):
        if self.git("rev-parse", "--abbrev-ref", "HEAD") != "main":
            return "Switch to the main branch before updating."
        dirty = self.git("status", "--porcelain", "--untracked-files=no")
        if dirty:
            return "Local tracked files have changes. Commit or back them up and resolve the changes first.\n" + dirty
        for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
            location = Path(self.git("rev-parse", "--git-path", marker))
            if not location.is_absolute():
                location = self.root / location
            if location.exists():
                return "Finish the current Git merge/rebase operation before updating."
        return ""

    def check(self):
        self.validate_repository()
        # Fetch main explicitly; neither the branch nor working files are changed.
        self.git("fetch", "--no-recurse-submodules", "origin",
                 "refs/heads/main:refs/remotes/origin/main", "--tags", timeout=120)
        current = self.git("rev-parse", "HEAD")
        target = self.git("rev-parse", "refs/remotes/origin/main")
        ahead, behind = map(int, self.git("rev-list", "--left-right", "--count", f"{current}...{target}").split())
        blocker = self.local_blocker()
        if ahead:
            blocker = ("This checkout has local commits ahead of GitHub." if not behind else
                       "Local and GitHub histories have diverged. Resolve them with Git before updating.")
        changes = tuple(filter(None, self.git("diff", "--name-only", current, target).splitlines()))
        return UpdateInfo(current, target, self.version(current), self.version(target),
                          self.git("log", "-20", "--format=%h %s", f"{current}..{target}"), changes, blocker)

    def install(self, info):
        self.validate_repository()
        if not info.available:
            raise UpdateError(info.blocker or "No update is available.")
        if self.git("rev-parse", "HEAD") != info.current:
            raise UpdateError("The local version changed. Check for updates again.")
        if self.git("rev-parse", "refs/remotes/origin/main") != info.target:
            raise UpdateError("The fetched version changed. Check for updates again.")
        blocker = self.local_blocker()
        if blocker:
            raise UpdateError(blocker)
        if self.git("merge-base", "HEAD", info.target) != info.current:
            raise UpdateError("This update cannot be installed with a fast-forward.")
        # Preserve old data/model files if upstream deliberately replaces them.
        # Locally modified tracked files were already blocked above.
        changed = self.git("diff", "--name-only", "-z", info.current, info.target).split("\0")
        backup = None
        for name in filter(None, changed):
            source = self.root / name
            if source.is_file() and (source.suffix.lower() in {".pt", ".onnx", ".engine", ".json", ".csv"}):
                if backup is None:
                    git_dir = Path(self.git("rev-parse", "--absolute-git-dir"))
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                    backup = git_dir / "pcb-update-backups" / stamp
                dest = backup / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
        # Git rejects collisions with both untracked AND ignored files. Never
        # reset, clean, stash or force-overwrite the user's checkout.
        self.git("-c", f"core.hooksPath={os.devnull}", "merge", "--ff-only",
                 "--no-overwrite-ignore", info.target, timeout=120)
        if self.git("rev-parse", "HEAD") != info.target:
            raise UpdateError("The installed revision could not be verified.")
        return str(backup) if backup else ""
