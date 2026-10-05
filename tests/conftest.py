from __future__ import annotations

import os
import subprocess
from pathlib import Path

import httpx
import pytest


def git(cwd: Path, *args: str, env: dict | None = None) -> str:
    full_env = dict(os.environ)
    full_env.update({"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"})
    full_env.update(env or {})
    out = subprocess.run(["git", *args], cwd=cwd, env=full_env, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr}")
    return out.stdout


def commit(repo: Path, message: str, name: str, email: str, date: str, files: dict[str, str | None]):
    """Create/modify/delete files and commit with a fixed author and date."""
    for rel, content in files.items():
        path = repo / rel
        if content is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(repo, "add", "-A")
    env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": date,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_DATE": date}
    git(repo, "commit", "-q", "-m", message, env=env)


README = """# Demo

Demo is a small peer-to-peer file transfer tool that discovers nearby devices on the local
network and sends files between them.

## Installation

```bash
pip install demo
```

## Usage

Run `demo send file.txt`.

![screenshot](shot.png)
"""


@pytest.fixture()
def fixture_root(tmp_path: Path) -> Path:
    """A directory acting as 'https://github.com': <root>/alice/demo.git is a real repository."""
    root = tmp_path / "remote"
    repo = root / "alice" / "demo.git"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    A = ("Alice Dev", "alice@example.com")
    B = ("Bob Other", "bob@example.com")
    N = ("alice", "123+alice@users.noreply.github.com")

    commit(repo, "Initial commit", *A, "2025-01-10T10:00:00+00:00", {
        "README.md": README,
        "pyproject.toml": '[project]\nname = "demo"\ndependencies = ["fastapi>=0.100", "torch"]\n',
        "src/demo/__init__.py": "",
        "src/demo/app.py": "def main():\n    return 1\n",
    })
    commit(repo, "feat: add device discovery over mdns", *A, "2025-01-20T10:00:00+00:00", {
        "src/demo/network/discovery.py": "\n".join(f"def d{i}(): return {i}" for i in range(60)),
    })
    commit(repo, "feat: implement file transfer protocol", *A, "2025-02-02T10:00:00+00:00", {
        "src/demo/network/transfer.py": "\n".join(f"def t{i}(): return {i}" for i in range(120)),
    })
    commit(repo, "Fix crash when peer disconnects", *A, "2025-02-10T10:00:00+00:00", {
        "src/demo/network/transfer.py": "\n".join(f"def t{i}(): return {i}" for i in range(125)),
    })
    commit(repo, "Add dependency lock", *A, "2025-02-11T10:00:00+00:00", {
        "package-lock.json": "{" + "x" * 5000 + "}\n" * 3000,
    })
    commit(repo, "Bob adds a ui screen", *B, "2025-02-15T10:00:00+00:00", {
        "src/demo/ui/screen.py": "\n".join(f"def s{i}(): pass" for i in range(40)),
    })
    commit(repo, "Import legacy data tools", *A, "2025-03-01T10:00:00+00:00", {
        f"legacy/mod{i}.py": "\n".join(f"x{j} = {j}" for j in range(30)) for i in range(160)
    })
    commit(repo, "test: add transfer tests", *N, "2025-03-05T10:00:00+00:00", {
        "tests/test_transfer.py": "def test_a():\n    assert True\n",
        "tests/test_discovery.py": "def test_b():\n    assert True\n",
    })
    commit(repo, "ci: add workflow and docker", *N, "2025-03-06T10:00:00+00:00", {
        ".github/workflows/ci.yml": "name: ci\non: [push]\n",
        "Dockerfile": "FROM python:3.12\n",
        "LICENSE": "MIT License\n",
    })
    # a side branch merged back (creates a merge commit)
    git(repo, "checkout", "-q", "-b", "feature/ui")
    commit(repo, "Add settings screen", *A, "2025-03-10T10:00:00+00:00", {
        "src/demo/ui/settings.py": "\n".join(f"def z{i}(): pass" for i in range(25)),
    })
    git(repo, "checkout", "-q", "main")
    env = {"GIT_AUTHOR_NAME": A[0], "GIT_AUTHOR_EMAIL": A[1], "GIT_AUTHOR_DATE": "2025-03-12T10:00:00+00:00",
           "GIT_COMMITTER_NAME": A[0], "GIT_COMMITTER_EMAIL": A[1],
           "GIT_COMMITTER_DATE": "2025-03-12T10:00:00+00:00"}
    git(repo, "merge", "--no-ff", "-q", "-m", "Merge branch 'feature/ui'", "feature/ui", env=env)
    git(repo, "tag", "-a", "v1.0", "-m", "v1.0", env=env)
    return root


def make_transport(requests_log: list[str] | None = None, rate_limit_search: bool = False):
    profile = {"login": "alice", "name": "Alice Dev", "bio": "Builds things", "email": None,
               "html_url": "https://github.com/alice", "followers": 3,
               "created_at": "2020-01-01T00:00:00Z", "company": None, "location": None, "blog": ""}
    repo = {"full_name": "alice/demo", "name": "demo", "owner": {"login": "alice"}, "fork": False,
            "archived": False, "private": False, "size": 100, "default_branch": "main",
            "description": "Demo project", "stargazers_count": 4, "forks_count": 1,
            "topics": ["p2p"], "html_url": "https://github.com/alice/demo", "language": "Python",
            "created_at": "2025-01-10T10:00:00Z", "pushed_at": "2025-03-12T10:00:00Z"}

    def pr(n, repo_full, merged):
        return {"number": n, "title": f"PR {n}", "state": "closed", "created_at": "2025-02-01T00:00:00Z",
                "closed_at": "2025-02-02T00:00:00Z", "html_url": f"https://github.com/{repo_full}/pull/{n}",
                "repository_url": f"https://api.github.com/repos/{repo_full}",
                "pull_request": {"merged_at": "2025-02-02T00:00:00Z" if merged else None}}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if requests_log is not None:
            requests_log.append(f"{request.method} {path}?{request.url.query.decode()}")
        hdr = {"x-ratelimit-remaining": "4000", "x-ratelimit-resource": "core"}
        if path == "/rate_limit":
            return httpx.Response(200, json={"resources": {"core": {"remaining": 4000, "reset": 0},
                                                           "search": {"remaining": 25, "reset": 0}}})
        if path == "/users/alice":
            return httpx.Response(200, json=profile, headers=hdr)
        if path == "/users/ghost":
            return httpx.Response(404, json={"message": "Not Found"})
        if path == "/users/alice/repos":
            return httpx.Response(200, json=[repo], headers=hdr)
        if path == "/search/issues":
            if rate_limit_search:
                return httpx.Response(403, json={"message": "API rate limit exceeded"},
                                      headers={"x-ratelimit-remaining": "0", "x-ratelimit-resource": "search"})
            q = request.url.params.get("q", "")
            if "reviewed-by" in q:
                return httpx.Response(200, json={"total_count": 7, "items": []}, headers=hdr)
            if "type:pr" in q:
                items = [pr(1, "alice/demo", True), pr(5, "someone/else", True), pr(6, "someone/else", False)]
            else:
                items = [{"number": 2, "title": "Bug", "state": "open", "created_at": "2025-02-03T00:00:00Z",
                          "closed_at": None, "html_url": "https://github.com/alice/demo/issues/2",
                          "repository_url": "https://api.github.com/repos/alice/demo"}]
            return httpx.Response(200, json={"total_count": len(items), "items": items}, headers=hdr)
        if path == "/repos/alice/demo/commits":
            return httpx.Response(200, json=[{"commit": {"author": {"name": "Alice Dev", "email": "alice@example.com"}}}], headers=hdr)
        if path == "/repos/alice/demo/releases":
            return httpx.Response(200, json=[], headers=hdr)
        return httpx.Response(404, json={"message": f"unhandled {path}"})

    return httpx.MockTransport(handler)


@pytest.fixture()
def gp_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "gphome"
    monkeypatch.setenv("GITPROOF_HOME", str(home))
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    return home
