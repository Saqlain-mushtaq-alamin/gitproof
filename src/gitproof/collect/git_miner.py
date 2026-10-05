"""Thin wrapper around the `git` binary. Bare clones: no working tree is written to disk."""
from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..util import parse_dt


class GitError(Exception):
    pass


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat", "LC_ALL": "C"})
    return env


def _run(args: list[str], timeout: int | None = 600) -> subprocess.CompletedProcess:
    if shutil.which("git") is None:
        raise GitError("git is not installed or not on PATH")
    return subprocess.run(["git", *args], capture_output=True, env=_env(), timeout=timeout,
                          check=False)


def _text(proc: subprocess.CompletedProcess) -> str:
    return proc.stdout.decode("utf-8", errors="replace")


def _fail(proc: subprocess.CompletedProcess, what: str) -> GitError:
    detail = proc.stderr.decode("utf-8", errors="replace").strip().splitlines()
    return GitError(f"{what} failed: {detail[-1] if detail else 'unknown error'}")


def _auth_args(url: str, token: str | None) -> list[str]:
    if token and url.startswith("https://github.com/"):
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        return ["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {basic}"]
    return []


def ensure_clone(url: str, dest: Path, token: str | None = None) -> Path:
    """Create or update a bare clone. The token is passed per-command and never stored."""
    auth = _auth_args(url, token)
    if (dest / "HEAD").exists():
        proc = _run([*auth, "--git-dir", str(dest), "fetch", "--quiet", "--prune", "--force",
                     "origin", "+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*"],
                    timeout=1800)
        if proc.returncode == 0:
            return dest
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = _run([*auth, "clone", "--bare", "--quiet", url, str(dest)], timeout=1800)
    if proc.returncode != 0:
        raise _fail(proc, f"cloning {url.split('/')[-1]}")
    return dest


def has_commits(git_dir: Path) -> bool:
    proc = _run(["--git-dir", str(git_dir), "for-each-ref", "--count=1", "refs/heads"])
    return proc.returncode == 0 and bool(_text(proc).strip())


def head_ref(git_dir: Path) -> str:
    if _run(["--git-dir", str(git_dir), "rev-parse", "--verify", "-q", "HEAD"]).returncode == 0:
        return "HEAD"
    proc = _run(["--git-dir", str(git_dir), "for-each-ref", "--count=1",
                 "--format=%(refname)", "refs/heads"])
    return _text(proc).strip() or "HEAD"


@dataclass
class RawCommit:
    sha: str
    author_name: str
    author_email: str
    authored_at: datetime
    parents: int
    subject: str
    files: list[tuple[int, int, str]]  # (additions, deletions, path)


_RS, _US = "\x1e", "\x1f"
LOG_FORMAT = "--format=%x1e%H%x1f%an%x1f%ae%x1f%aI%x1f%P%x1f%s"


def parse_log_lines(lines: Iterable[str]) -> Iterator[RawCommit]:
    """Parse `git log --numstat` output produced with LOG_FORMAT."""
    current: RawCommit | None = None
    for raw in lines:
        line = raw.rstrip("\n")
        if line.startswith(_RS):
            if current:
                yield current
            fields = line[1:].split(_US)
            if len(fields) < 6:
                current = None
                continue
            sha, name, email, date, parents, subject = fields[:6]
            current = RawCommit(sha=sha, author_name=name, author_email=email,
                                authored_at=parse_dt(date), parents=len(parents.split()),
                                subject=subject, files=[])
        elif line and current is not None:
            parts = line.split("\t", 2)
            if len(parts) == 3:
                add, dele, path = parts
                current.files.append((int(add) if add.isdigit() else 0,
                                      int(dele) if dele.isdigit() else 0, path))
    if current:
        yield current


def iter_log(git_dir: Path, since: str | None = None,
             max_commits: int | None = None) -> Iterator[RawCommit]:
    args = ["git", "-c", "core.quotepath=false", "--git-dir", str(git_dir), "log", "--all",
            "--no-renames", "--numstat", "--no-color", LOG_FORMAT]
    if since:
        args += ["--since", since]
    if max_commits:
        args += [f"--max-count={max_commits}"]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=_env(),
                            text=True, encoding="utf-8", errors="replace")
    assert proc.stdout is not None
    try:
        yield from parse_log_lines(proc.stdout)
    finally:
        proc.stdout.close()
        proc.wait()


def list_tree(git_dir: Path, rev: str = "HEAD") -> list[tuple[str, int]]:
    proc = _run(["--git-dir", str(git_dir), "-c", "core.quotepath=false", "ls-tree", "-r", "-l",
                 "-z", rev])
    if proc.returncode != 0:
        raise _fail(proc, "listing files")
    out: list[tuple[str, int]] = []
    for entry in _text(proc).split("\0"):
        if "\t" not in entry:
            continue
        meta, path = entry.split("\t", 1)
        parts = meta.split()
        if len(parts) >= 4 and parts[1] == "blob" and parts[3].isdigit():
            out.append((path, int(parts[3])))
    return out


def read_blob(git_dir: Path, path: str, rev: str = "HEAD", limit: int = 200_000) -> str | None:
    proc = _run(["--git-dir", str(git_dir), "show", f"{rev}:{path}"])
    return None if proc.returncode != 0 else proc.stdout[:limit].decode("utf-8", errors="replace")


def list_tags(git_dir: Path) -> list[tuple[str, str]]:
    proc = _run(["--git-dir", str(git_dir), "for-each-ref", "--sort=creatordate",
                 "--format=%(refname:short)\t%(creatordate:iso-strict)", "refs/tags"])
    out = []
    for line in _text(proc).splitlines():
        if "\t" in line:
            tag, date = line.split("\t", 1)
            out.append((tag, date))
    return out


_BLAME_HEADER = re.compile(r"^[0-9a-f]{40} \d+ \d+")


def blame_counts(git_dir: Path, path: str, rev: str = "HEAD") -> Counter[tuple[str, str, str]]:
    """Surviving lines per (author_email, author_name, commit_sha) for one file at `rev`."""
    proc = _run(["--git-dir", str(git_dir), "blame", "--line-porcelain", "-w", rev, "--", path],
                timeout=120)
    counts: Counter[tuple[str, str, str]] = Counter()
    if proc.returncode != 0:
        return counts
    name = sha = ""
    for line in _text(proc).splitlines():
        if _BLAME_HEADER.match(line):
            sha = line[:40]
        elif line.startswith("author "):
            name = line[7:]
        elif line.startswith("author-mail "):
            counts[(line[12:].strip().strip("<>").lower(), name, sha)] += 1
    return counts


def blame_many(git_dir: Path, paths: list[str], rev: str = "HEAD", workers: int = 4,
               on_progress: Callable[[], None] | None = None
               ) -> dict[str, Counter[tuple[str, str, str]]]:
    results: dict[str, Counter[tuple[str, str, str]]] = {}

    def work(p: str) -> tuple[str, Counter[tuple[str, str, str]]]:
        try:
            return p, blame_counts(git_dir, p, rev)
        except subprocess.TimeoutExpired:
            return p, Counter()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for path, counts in pool.map(work, paths):
            results[path] = counts
            if on_progress:
                on_progress()
    return results
