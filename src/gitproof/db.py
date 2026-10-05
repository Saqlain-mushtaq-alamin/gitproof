from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .config import home_dir
from .util import iso, now

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS http_cache (
    url TEXT PRIMARY KEY, etag TEXT, body TEXT, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS repos (
    full_name TEXT PRIMARY KEY, name TEXT, owner TEXT, is_fork INTEGER, archived INTEGER,
    private INTEGER, size_kb INTEGER, default_branch TEXT, description TEXT, stars INTEGER,
    forks INTEGER, topics TEXT, html_url TEXT, language TEXT, created_at TEXT, pushed_at TEXT,
    mined_key TEXT, status TEXT, status_note TEXT);
CREATE TABLE IF NOT EXISTS commits (
    repo TEXT, sha TEXT, author_name TEXT, author_email TEXT, authored_at TEXT,
    is_merge INTEGER, subject TEXT, is_user INTEGER, additions INTEGER, deletions INTEGER,
    files_changed INTEGER, PRIMARY KEY (repo, sha));
CREATE INDEX IF NOT EXISTS idx_commits_user ON commits (repo, is_user);
CREATE TABLE IF NOT EXISTS commit_files (
    repo TEXT, sha TEXT, path TEXT, additions INTEGER, deletions INTEGER);
CREATE INDEX IF NOT EXISTS idx_cf ON commit_files (repo, sha);
CREATE TABLE IF NOT EXISTS items (
    kind TEXT, repo TEXT, number INTEGER, title TEXT, state TEXT, merged INTEGER,
    created_at TEXT, closed_at TEXT, url TEXT, external INTEGER,
    PRIMARY KEY (kind, repo, number));
CREATE TABLE IF NOT EXISTS releases (
    repo TEXT, tag TEXT, name TEXT, published_at TEXT, url TEXT, source TEXT,
    PRIMARY KEY (repo, tag));
CREATE TABLE IF NOT EXISTS analysis (
    scope TEXT, key TEXT, data TEXT, updated_at TEXT, PRIMARY KEY (scope, key));
"""

REPO_COLS = [
    "full_name", "name", "owner", "is_fork", "archived", "private", "size_kb", "default_branch",
    "description", "stars", "forks", "topics", "html_url", "language", "created_at", "pushed_at",
]


def db_path(login: str) -> Path:
    folder = home_dir() / "data"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{login.lower()}.db"


class Store:
    """SQLite store holding everything gitproof knows about one GitHub user."""

    def __init__(self, login: str, path: Path | None = None):
        self.login = login
        self.path = path or db_path(login)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def get_http(self, url: str) -> tuple[str | None, str] | None:
        row = self.conn.execute("SELECT etag, body FROM http_cache WHERE url=?", (url,)).fetchone()
        return (row["etag"], row["body"]) if row else None

    def put_http(self, url: str, etag: str | None, body: str) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO http_cache VALUES (?,?,?,?)",
                              (url, etag, body, iso(now())))

    def meta_get(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def meta_set(self, key: str, value: Any) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value)))

    def upsert_repo(self, repo: dict[str, Any]) -> None:
        values = [repo.get(c) for c in REPO_COLS]
        updates = ", ".join(f"{c}=excluded.{c}" for c in REPO_COLS[1:])
        marks = ",".join("?" for _ in REPO_COLS)
        with self.conn:
            self.conn.execute(
                f"INSERT INTO repos ({','.join(REPO_COLS)}) VALUES ({marks}) "
                f"ON CONFLICT(full_name) DO UPDATE SET {updates}", values)

    def get_repos(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM repos ORDER BY pushed_at DESC").fetchall()
        return [dict(r) for r in rows]

    def get_repo(self, full_name: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM repos WHERE full_name=?", (full_name,)).fetchone()
        return dict(row) if row else None

    def set_repo_state(self, full_name: str, status: str, note: str | None = None,
                       mined_key: str | None = None) -> None:
        with self.conn:
            if mined_key is None:
                self.conn.execute("UPDATE repos SET status=?, status_note=? WHERE full_name=?",
                                  (status, note, full_name))
            else:
                self.conn.execute(
                    "UPDATE repos SET status=?, status_note=?, mined_key=? WHERE full_name=?",
                    (status, note, mined_key, full_name))

    def replace_commits(self, repo: str, commits: Iterable[tuple], files: Iterable[tuple]) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM commits WHERE repo=?", (repo,))
            self.conn.execute("DELETE FROM commit_files WHERE repo=?", (repo,))
            self.conn.executemany(
                "INSERT OR REPLACE INTO commits VALUES (?,?,?,?,?,?,?,?,?,?,?)", commits)
            self.conn.executemany("INSERT INTO commit_files VALUES (?,?,?,?,?)", files)

    def commits(self, repo: str, user_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM commits WHERE repo=?" + (" AND is_user=1" if user_only else "")
        return [dict(r) for r in self.conn.execute(sql + " ORDER BY authored_at", (repo,))]

    def user_files(self, repo: str) -> dict[str, list[tuple[str, int, int]]]:
        out: dict[str, list[tuple[str, int, int]]] = {}
        for r in self.conn.execute(
                "SELECT sha, path, additions, deletions FROM commit_files WHERE repo=?", (repo,)):
            out.setdefault(r["sha"], []).append((r["path"], r["additions"], r["deletions"]))
        return out

    def replace_items(self, kind: str, rows: Iterable[tuple]) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM items WHERE kind=?", (kind,))
            self.conn.executemany("INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?,?,?,?,?)", rows)

    def items(self, kind: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM items WHERE kind=? ORDER BY created_at DESC", (kind,)).fetchall()
        return [dict(r) for r in rows]

    def replace_releases(self, repo: str, rows: Iterable[tuple]) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM releases WHERE repo=?", (repo,))
            self.conn.executemany("INSERT OR REPLACE INTO releases VALUES (?,?,?,?,?,?)", rows)

    def releases(self, repo: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM releases WHERE repo=? ORDER BY published_at", (repo,)).fetchall()
        return [dict(r) for r in rows]

    def put_analysis(self, scope: str, key: str, data: Any) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO analysis VALUES (?,?,?,?)",
                              (scope, key, json.dumps(data), iso(now())))

    def get_analysis(self, scope: str, key: str) -> Any | None:
        row = self.conn.execute("SELECT data FROM analysis WHERE scope=? AND key=?",
                                (scope, key)).fetchone()
        return json.loads(row["data"]) if row else None

    def all_analysis(self, scope: str) -> dict[str, Any]:
        rows = self.conn.execute("SELECT key, data FROM analysis WHERE scope=?", (scope,))
        return {r["key"]: json.loads(r["data"]) for r in rows}
