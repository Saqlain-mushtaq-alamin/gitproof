"""The `analyze` pipeline: GitHub API -> git mining -> deterministic analysis -> SQLite."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from .analyze import aggregate, repo_analysis
from .analyze.attribution import Identity, build_identity
from .analyze.filters import is_bulk_commit, language_for, noise_reason
from .analyze.skills import is_manifest
from .collect import git_miner
from .collect.github_api import GitHubClient, GitHubError, NotFound, RateLimited
from .config import Config, home_dir
from .db import Store
from .util import iso, mask_email, now

README_PREFERENCE = (".md", ".markdown", ".rst", ".txt")


@dataclass
class AnalyzeOptions:
    token: str | None = None
    include_private: bool = False
    since: str | None = None
    exclude_forks: bool = False
    refresh: bool = False
    repos: list[str] | None = None
    max_repos: int | None = None
    blame: bool = True
    aliases: list[str] = field(default_factory=list)
    clone_base: str = "https://github.com"
    transport: httpx.BaseTransport | None = None


@dataclass
class AnalyzeResult:
    login: str
    analyzed: int = 0
    with_work: int = 0
    skipped: int = 0
    errors: int = 0
    warnings: list[str] = field(default_factory=list)
    api_requests: int = 0
    cache_hits: int = 0


class UserNotFound(Exception):
    pass


def clones_dir() -> Path:
    d = home_dir() / "clones"
    d.mkdir(parents=True, exist_ok=True)
    return d


def repo_row(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "full_name": raw["full_name"], "name": raw["name"], "owner": raw["owner"]["login"],
        "is_fork": int(raw.get("fork", False)), "archived": int(raw.get("archived", False)),
        "private": int(raw.get("private", False)), "size_kb": raw.get("size", 0),
        "default_branch": raw.get("default_branch"), "description": raw.get("description"),
        "stars": raw.get("stargazers_count", 0), "forks": raw.get("forks_count", 0),
        "topics": json.dumps(raw.get("topics", [])), "html_url": raw.get("html_url"),
        "language": raw.get("language"), "created_at": raw.get("created_at"),
        "pushed_at": raw.get("pushed_at"),
    }


def item_row(kind: str, it: dict[str, Any], login: str) -> tuple:
    repo = it["repository_url"].split("/repos/")[-1]
    pr = it.get("pull_request") or {}
    return (kind, repo, it["number"], it["title"], it["state"], int(bool(pr.get("merged_at"))),
            it["created_at"], it.get("closed_at"), it["html_url"],
            int(repo.split("/")[0].lower() != login.lower()))


def pick_readme(files: list[tuple[str, int]]) -> str | None:
    root = [p for p, _ in files if "/" not in p and p.lower().startswith("readme")]

    def rank(p: str) -> int:
        return next((i for i, ext in enumerate(README_PREFERENCE) if p.lower().endswith(ext)), 99)

    root.sort(key=rank)
    return root[0] if root else None


def mined_key(repo: dict[str, Any], opts: AnalyzeOptions, identity: Identity) -> str:
    return f"{repo['pushed_at']}|{opts.since}|{identity.fingerprint()}|{int(opts.blame)}"


def bulk_commit_shas(file_rows: list[tuple]) -> set[str]:
    """Commits that import hundreds of files / tens of thousands of lines at once."""
    by_sha: dict[str, list[tuple[int, int]]] = {}
    for _, sha, path, adds, dels in file_rows:
        if not noise_reason(path):
            by_sha.setdefault(sha, []).append((adds, dels))
    return {sha for sha, fl in by_sha.items()
            if is_bulk_commit(len(fl), sum(a for a, _ in fl), sum(d for _, d in fl))}


def run_blame(dest: Path, tree: list[tuple[str, int]], identity: Identity, allow_name: bool,
              max_files: int, exclude_shas: set[str] | None = None) -> dict[str, Any]:
    candidates = [(p, s) for p, s in tree
                  if language_for(p) and not noise_reason(p) and 0 < s <= 400_000]
    candidates.sort(key=lambda ps: -ps[1])
    chosen = [p for p, _ in candidates[:max_files]]
    results = git_miner.blame_many(dest, chosen, git_miner.head_ref(dest))
    exclude_shas = exclude_shas or set()
    user_lines = total_lines = excluded = 0
    by_lang: Counter[str] = Counter()
    for path, counts in results.items():
        lang = language_for(path) or "Other"
        for (email, name, sha), n in counts.items():
            if sha in exclude_shas:      # bulk imports are not authored work
                excluded += n
                continue
            total_lines += n
            if identity.matches(email, name, allow_name):
                user_lines += n
                by_lang[lang] += n
    return {"user_lines": user_lines, "total_lines": total_lines, "files": len(chosen),
            "truncated": len(candidates) > max_files, "user_by_language": dict(by_lang),
            "excluded_bulk_lines": excluded}


def mine_repo(store: Store, cfg: Config, opts: AnalyzeOptions, token: str | None,
              repo: dict[str, Any], identity: Identity, login: str) -> str:
    """Clone/fetch, parse history, snapshot HEAD, run blame. Returns the final status."""
    full = repo["full_name"]
    if (repo["size_kb"] or 0) > cfg.max_repo_size_mb * 1024:
        store.set_repo_state(full, "skipped", f"repository larger than {cfg.max_repo_size_mb} MB")
        return "skipped"

    dest = clones_dir() / f"{repo['owner']}__{repo['name']}.git"
    git_miner.ensure_clone(f"{opts.clone_base.rstrip('/')}/{full}.git", dest, token)
    if not git_miner.has_commits(dest):
        store.set_repo_state(full, "empty", "repository has no commits")
        return "empty"

    allow_name = (not repo["is_fork"]) and repo["owner"].lower() == login.lower()
    commit_rows: list[tuple] = []
    file_rows: list[tuple] = []
    authors: Counter[tuple[str, str]] = Counter()
    user_authors: set[tuple[str, str]] = set()

    for rc in git_miner.iter_log(dest, opts.since, cfg.max_commits_per_repo):
        is_user = identity.matches(rc.author_email, rc.author_name, allow_name)
        is_merge = rc.parents > 1
        adds = sum(a for a, _, _ in rc.files)
        dels = sum(d for _, d, _ in rc.files)
        commit_rows.append((full, rc.sha, rc.author_name, rc.author_email.lower(),
                            iso(rc.authored_at), int(is_merge), rc.subject, int(is_user),
                            adds, dels, len(rc.files)))
        key = (rc.author_name, rc.author_email.lower())
        if not is_merge:
            authors[key] += 1
        if is_user:
            user_authors.add(key)
            file_rows.extend((full, rc.sha, p, a, d) for a, d, p in rc.files)
    store.replace_commits(full, commit_rows, file_rows)

    ref = git_miner.head_ref(dest)
    tree = git_miner.list_tree(dest, ref)
    readme_path = pick_readme(tree)
    readme = git_miner.read_blob(dest, readme_path, ref, 60_000) if readme_path else None
    manifests: dict[str, str] = {}
    for path, size in tree:
        if is_manifest(path) and size <= 200_000 and len(manifests) < 12:
            text = git_miner.read_blob(dest, path, ref)
            if text:
                manifests[path] = text

    store.put_analysis("snapshot", full, {
        "files": [[p, s] for p, s in tree[:30_000]], "readme": readme, "manifests": manifests,
        "tags": git_miner.list_tags(dest)[-50:],
        "authors": [{"name": n, "email": mask_email(e), "commits": c, "is_user": (n, e) in user_authors}
                    for (n, e), c in authors.most_common(8)],
        "truncated": len(commit_rows) >= cfg.max_commits_per_repo,
    })
    blame_result = None
    if opts.blame and any(r[7] for r in commit_rows):
        blame_result = run_blame(dest, tree, identity, allow_name, cfg.blame_max_files,
                                 bulk_commit_shas(file_rows))
    store.put_analysis("blame", full, blame_result)
    store.set_repo_state(full, "ok", None, mined_key=mined_key(repo, opts, identity))
    return "ok"


def _fetch_releases(client: GitHubClient, store: Store, full: str, warnings: list[str]) -> None:
    """Releases are optional: fall back to git tags when the API quota is low."""
    if not client.budget_ok():
        return
    try:
        rows = [(full, r["tag_name"], r.get("name"), r.get("published_at") or r.get("created_at"),
                 r.get("html_url"), "release")
                for r in client.releases(full) if not r.get("draft")]
        store.replace_releases(full, rows)
    except RateLimited:
        msg = "Rate limit reached while fetching releases; using git tags instead."
        if msg not in warnings:
            warnings.append(msg)
    except GitHubError:
        pass


def analyze_user(login: str, cfg: Config, opts: AnalyzeOptions,
                 console: Console | None = None) -> AnalyzeResult:
    console = console or Console()
    token = opts.token
    result = AnalyzeResult(login=login)
    warnings = result.warnings
    # resolve the canonical login (GitHub is case-insensitive) before opening the store
    probe_store = Store(login)
    client = GitHubClient(probe_store, token, transport=opts.transport)
    try:
        client.refresh_limits()
        try:
            user = client.user(login)
        except NotFound:
            raise UserNotFound(f"GitHub user '{login}' was not found") from None
    except BaseException:
        client.close()
        probe_store.close()
        raise
    login = user["login"]
    result.login = login
    store = probe_store
    store.meta_set("user", user)
    try:
        raw_repos = client.repos(login, opts.include_private)
        for raw in raw_repos:
            store.upsert_repo(repo_row(raw))
        repos = store.get_repos()
        all_repos = list(repos)
        if opts.exclude_forks:
            repos = [r for r in repos if not r["is_fork"]]
        if opts.repos:
            wanted = {w.lower() for w in opts.repos}
            repos = [r for r in repos
                     if r["name"].lower() in wanted or r["full_name"].lower() in wanted]
        if opts.max_repos:
            repos = repos[: opts.max_repos]
        console.print(f"[bold]{user.get('name') or login}[/bold] - {len(all_repos)} repositories "
                      f"({len(repos)} selected)")

        reviews: int | None = None
        try:
            store.replace_items("pr", [item_row("pr", i, login)
                                       for i in client.search_items(login, "pr")])
            store.replace_items("issue", [item_row("issue", i, login)
                                          for i in client.search_items(login, "issue")])
            if client.budget_ok("search", reserve=1):
                reviews = client.search_count(f"reviewed-by:{login} type:pr -author:{login}")
        except RateLimited as exc:
            warnings.append(f"Pull-request/issue data incomplete: {exc.message}")
        except GitHubError as exc:
            warnings.append(f"Could not fetch pull requests/issues: {exc.message}")
        prs, issues = store.items("pr"), store.items("issue")

        learned_e = set(store.meta_get("learned_emails", []))
        learned_n = set(store.meta_get("learned_names", []))
        for r in repos:
            if not client.budget_ok():
                warnings.append("API quota low: skipped identity learning for some repositories "
                                "(use a token for best attribution).")
                break
            try:
                for c in client.author_commits(r["full_name"], login):
                    info = (c.get("commit") or {}).get("author") or {}
                    if info.get("email"):
                        learned_e.add(info["email"].lower())
                    if info.get("name"):
                        learned_n.add(info["name"].lower())
            except RateLimited:
                warnings.append("Rate limit hit while learning identities; using what was found.")
                break
            except GitHubError:
                continue
        store.meta_set("learned_emails", sorted(learned_e))
        store.meta_set("learned_names", sorted(learned_n))
        identity = build_identity(login, user, sorted(set(cfg.aliases) | set(opts.aliases)),
                                  learned_e, learned_n)

        analyses: list[dict[str, Any]] = []
        progress = Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"),
                            BarColumn(), TextColumn("{task.completed}/{task.total}"),
                            TimeElapsedColumn(), console=console, transient=True)
        with progress:
            task = progress.add_task("Analyzing repositories", total=len(repos))
            for r in repos:
                progress.update(task, description=f"Analyzing {r['name']}")
                full = r["full_name"]
                try:
                    fresh = store.get_repo(full) or r
                    snap = store.get_analysis("snapshot", full)
                    cached = (not opts.refresh and fresh.get("mined_key") == mined_key(fresh, opts, identity)
                              and fresh.get("status") == "ok" and snap is not None)
                    status = "ok" if cached else mine_repo(store, cfg, opts, token, fresh, identity, login)
                    if status != "ok":
                        note = (store.get_repo(full) or {}).get("status_note")
                        if status == "skipped":
                            result.skipped += 1
                            warnings.append(f"Skipped {full}: {note}")
                        analyses.append({"full_name": full, "name": r["name"], "status": status,
                                         "status_note": note})
                        progress.advance(task)
                        continue
                    _fetch_releases(client, store, full, warnings)
                    analysis = repo_analysis.assemble_repo(
                        store, store.get_repo(full), store.get_analysis("snapshot", full),
                        store.get_analysis("blame", full), prs, issues, cfg.area_tokens)
                    store.put_analysis("repo", full, analysis)
                    analyses.append(analysis)
                    result.analyzed += 1
                    if analysis["status"] == "ok":
                        result.with_work += 1
                except (git_miner.GitError, GitHubError) as exc:
                    result.errors += 1
                    store.set_repo_state(full, "error", str(exc))
                    warnings.append(f"{full}: {exc}")
                    analyses.append({"full_name": full, "name": r["name"], "status": "error",
                                     "status_note": str(exc)})
                progress.advance(task)

        profile = aggregate.build_profile(login, user, all_repos, analyses, prs, issues, reviews,
                                          warnings, opts.since)
        store.put_analysis("profile", login, profile)
        store.meta_set("last_run", iso(now()))
        result.api_requests, result.cache_hits = client.requests_made, client.cache_hits
        return result
    finally:
        client.close()
        store.close()
