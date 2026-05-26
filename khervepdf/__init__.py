"""KhervePDF — WYSIWYG PDF viewer and annotation editor with Git history."""
from __future__ import annotations

from pathlib import Path

# Bumped on every commit (user request — title bar surfaces the count).
# Patch component (.N) and +sha7 are appended automatically from pygit2.
__version__ = "0.60"


def _git_build_info() -> tuple[int, str, str] | None:
    """Return (commit_count, short_sha, last_subject) for this repo, or
    None if we can't read it (not a git checkout, pygit2 missing, etc.)."""
    repo_root = Path(__file__).resolve().parent.parent
    try:
        import pygit2
        if not (repo_root / ".git").exists():
            return None
        repo = pygit2.Repository(str(repo_root))
        if repo.head_is_unborn:
            return None
        head_oid = repo.head.target
        count = sum(1 for _ in repo.walk(head_oid, pygit2.GIT_SORT_NONE))
        head_commit = repo[head_oid]
        subject = head_commit.message.splitlines()[0] if head_commit.message else ""
        return count, str(head_oid)[:7], subject
    except Exception:
        return None


def version_string() -> str:
    """Format: "v<major>.<minor>.<commit_count>+<sha7>".

    Falls back to "v<major>.<minor>" if git info isn't available.
    """
    info = _git_build_info()
    if info is None:
        return f"v{__version__}"
    count, sha, _ = info
    return f"v{__version__}.{count}+{sha}"


def last_commit_subject() -> str:
    """Subject line of HEAD, or empty string if unavailable."""
    info = _git_build_info()
    return info[2] if info else ""
