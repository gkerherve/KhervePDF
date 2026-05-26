"""Per-document Git backend for KhervePDF.

Each PDF's parent directory becomes a git repo. The PDF file itself is
committed on save, so the user gets local version history and an
optional push to GitHub without leaving the app. The diff is binary —
useful for "which version had the highlights I deleted?", not for line
edits — but lets the user roll back annotations.

Falls back gracefully when pygit2 isn't installed (every function
returns False / empty / None so the app keeps working).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

try:
    import pygit2
    _OK = True
except Exception:
    pygit2 = None  # type: ignore
    _OK = False


def is_available() -> bool:
    return _OK


# ----- low-level repo discovery -----

def _find_enclosing(d: Path) -> Optional[Path]:
    cur = d.resolve()
    while cur != cur.parent:
        if (cur / ".git").exists():
            return cur
        cur = cur.parent
    return None


def init_repo(pdf_path: Path) -> bool:
    """Initialise a git repo in the PDF's parent directory if one
    isn't already in place (or in any ancestor). Returns True on
    success or when a repo already governs the location."""
    if not _OK:
        return False
    repo_dir = pdf_path.parent
    if (repo_dir / ".git").exists():
        return True
    if _find_enclosing(repo_dir) is not None:
        # Already inside someone else's repo — don't nest.
        return True
    try:
        pygit2.init_repository(str(repo_dir), bare=False)
    except Exception:
        return False
    # Match the suite convention: HEAD on refs/heads/dev so the first
    # commit lands on `dev` instead of libgit2's default master.
    try:
        head_file = repo_dir / ".git" / "HEAD"
        head_file.write_text("ref: refs/heads/dev\n", encoding="utf-8")
    except Exception:
        pass
    return True


def _repo_for(pdf_path: Path):
    if not _OK:
        return None
    repo_dir = pdf_path.parent
    try:
        if (repo_dir / ".git").exists():
            return pygit2.Repository(str(repo_dir))
        enc = _find_enclosing(repo_dir)
        return pygit2.Repository(str(enc)) if enc else None
    except Exception:
        return None


def _signature(repo) -> "pygit2.Signature":
    """User's configured git identity if available, else a sane
    fallback so first-time users still get clean commits."""
    try:
        return repo.default_signature
    except Exception:
        pass
    return pygit2.Signature("KhervePDF", "khervepdf@local")


def _rel_path(repo, pdf_path: Path) -> Optional[str]:
    try:
        rel = pdf_path.resolve().relative_to(Path(repo.workdir).resolve())
    except ValueError:
        return None
    return str(rel).replace("\\", "/")


# ----- high-level operations -----

def commit_file(pdf_path: Path, message: Optional[str] = None) -> bool:
    """Stage the PDF (creating a repo first if needed) and create a
    commit. Returns True on success, False otherwise."""
    if not _OK:
        return False
    if not init_repo(pdf_path):
        return False
    repo = _repo_for(pdf_path)
    if repo is None:
        return False
    rel = _rel_path(repo, pdf_path)
    if rel is None:
        return False
    try:
        index = repo.index
        index.read()
        index.add(rel)
        index.write()
        tree = index.write_tree()
        parents: list = []
        if not repo.head_is_unborn:
            parents.append(repo.head.target)
        sig = _signature(repo)
        msg = message or f"Update {pdf_path.name}"
        repo.create_commit("HEAD", sig, sig, msg, tree, parents)
        return True
    except Exception:
        return False


def history(pdf_path: Path, limit: int = 50
            ) -> list[tuple[str, str, int, str]]:
    """Return up to `limit` commits as (sha7, author, unix_time,
    subject) tuples, newest first."""
    if not _OK:
        return []
    repo = _repo_for(pdf_path)
    if repo is None or repo.head_is_unborn:
        return []
    out: list[tuple[str, str, int, str]] = []
    try:
        for commit in repo.walk(repo.head.target, pygit2.GIT_SORT_TIME):
            if len(out) >= limit:
                break
            subject = (commit.message.splitlines()[0]
                       if commit.message else "")
            out.append((str(commit.id)[:7], commit.author.name,
                        int(commit.commit_time), subject))
    except Exception:
        pass
    return out


def restore_to_commit(pdf_path: Path, sha: str) -> bool:
    """Overwrite the working-copy PDF with its version at `sha`."""
    if not _OK:
        return False
    repo = _repo_for(pdf_path)
    if repo is None:
        return False
    rel = _rel_path(repo, pdf_path)
    if rel is None:
        return False
    try:
        commit = repo.revparse_single(sha)
        blob = commit.tree[rel]
        pdf_path.write_bytes(blob.data)
        return True
    except Exception:
        return False


def current_branch(pdf_path: Path) -> Optional[str]:
    if not _OK:
        return None
    repo = _repo_for(pdf_path)
    if repo is None or repo.head_is_unborn:
        return None
    try:
        return repo.head.shorthand
    except Exception:
        return None


def get_remote(pdf_path: Path, name: str = "origin") -> Optional[str]:
    if not _OK:
        return None
    repo = _repo_for(pdf_path)
    if repo is None:
        return None
    try:
        return repo.remotes[name].url
    except KeyError:
        return None
    except Exception:
        return None


def set_remote(pdf_path: Path, url: str,
               name: str = "origin") -> bool:
    if not _OK:
        return False
    repo = _repo_for(pdf_path)
    if repo is None:
        return False
    try:
        existing = {r.name for r in repo.remotes}
        if name in existing:
            repo.remotes.set_url(name, url)
        else:
            repo.remotes.create(name, url)
        return True
    except Exception:
        return False


def push(pdf_path: Path,
         remote_name: str = "origin",
         branch: Optional[str] = None) -> tuple[bool, str]:
    """Push to remote via the system git CLI (pygit2's push needs
    credentials wiring that's painful to get right cross-platform —
    delegating to CLI uses whatever the user already has set up:
    SSH keys, Git Credential Manager, gh, etc.). Returns (ok, msg)."""
    if not _OK:
        return False, "pygit2 not installed"
    repo = _repo_for(pdf_path)
    if repo is None:
        return False, "Not a git repository"
    try:
        branch = branch or repo.head.shorthand
    except Exception:
        return False, "No branch (commit something first)"
    try:
        cmd = ["git", "-C", str(Path(repo.workdir)),
               "push", "-u", remote_name, branch]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=60)
        if r.returncode == 0:
            return True, r.stdout.strip() or "Pushed"
        return False, (r.stderr or r.stdout or "push failed").strip()
    except FileNotFoundError:
        return False, "git CLI not found on PATH"
    except subprocess.TimeoutExpired:
        return False, "push timed out"
    except Exception as e:
        return False, str(e)
