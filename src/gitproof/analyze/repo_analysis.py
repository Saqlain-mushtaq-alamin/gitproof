"""Turn raw mined data (commits, files, snapshot, blame) into a structured repo analysis.

Pure computation over SQLite contents - no network, no git - so heuristics can be changed and
re-applied without re-cloning anything.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from ..db import Store
from ..util import iso, month_key, months_between, parse_dt
from . import quality, skills
from .classify import area_weights, classify_commit, primary_area
from .filters import is_bulk_commit, language_for, noise_reason
from .phases import build_phases


def _languages_from_tree(files: list[Any]) -> list[dict[str, Any]]:
    sizes: Counter[str] = Counter()
    for path, size in files:
        lang = language_for(path)
        if lang and not noise_reason(path):
            sizes[lang] += int(size)
    total = sum(sizes.values()) or 1
    return [{"name": n, "bytes": b, "share": b / total} for n, b in sizes.most_common(8)]


def _releases(store: Store, full: str, url: str, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows = store.releases(full)
    if rows:
        return [{"tag": r["tag"], "name": r["name"] or r["tag"], "date": r["published_at"],
                 "url": r["url"], "source": r["source"]} for r in rows]
    return [{"tag": t, "name": t, "date": d, "url": f"{url}/releases/tag/{t}", "source": "tag"}
            for t, d in snapshot.get("tags", [])]


def assemble_repo(store: Store, repo: dict[str, Any], snapshot: dict[str, Any],
                  blame: dict[str, Any] | None, prs: list[dict[str, Any]],
                  issues: list[dict[str, Any]],
                  extra_areas: dict[str, list[str]] | None = None) -> dict[str, Any]:
    full = repo["full_name"]
    url = repo.get("html_url") or f"https://github.com/{full}"
    base = {
        "full_name": full, "name": repo["name"], "url": url, "is_fork": bool(repo["is_fork"]),
        "archived": bool(repo["archived"]), "private": bool(repo["private"]),
        "stars": repo.get("stars") or 0, "forks": repo.get("forks") or 0,
        "topics": json.loads(repo["topics"]) if repo.get("topics") else [],
        "created_at": repo.get("created_at"), "pushed_at": repo.get("pushed_at"),
        "description": repo.get("description"),
    }

    all_commits = store.commits(full)
    user_all = [c for c in all_commits if c["is_user"]]
    merge_commits = sum(1 for c in user_all if c["is_merge"])
    user_commits = [c for c in user_all if not c["is_merge"]]
    total_commits = sum(1 for c in all_commits if not c["is_merge"])
    if not user_commits:
        return {**base, "status": "no_user_commits",
                "status_note": "no commits attributed to this user"}

    files_by_sha = store.user_files(full)
    types: Counter[str] = Counter()
    area_lines: Counter[str] = Counter()
    area_commits: Counter[str] = Counter()
    monthly: Counter[str] = Counter()
    daily: Counter[str] = Counter()
    lang_added: Counter[str] = Counter()
    files_modified: set[str] = set()
    additions = deletions = ignored = bulk_count = 0
    phase_input: list[dict[str, Any]] = []
    scored: list[dict[str, Any]] = []
    touches: list[tuple[str, Any, str, int]] = []

    for c in user_commits:
        date = parse_dt(c["authored_at"])
        files = files_by_sha.get(c["sha"], [])
        counted = [(p, a, d) for p, a, d in files if not noise_reason(p)]
        ignored += len(files) - len(counted)
        adds, dels = sum(a for _, a, _ in counted), sum(d for _, _, d in counted)
        bulk = is_bulk_commit(len(counted), adds, dels)
        ctype = classify_commit(c["subject"], False, counted, extra_areas)
        weights = area_weights(counted, extra_areas)
        area = primary_area(weights)

        types[ctype] += 1
        monthly[month_key(date)] += 1
        daily[date.strftime("%Y-%m-%d")] += 1
        touches.extend((c["sha"], date, p, a) for p, a, _ in files)
        if bulk:
            bulk_count += 1
        else:
            additions += adds
            deletions += dels
            files_modified.update(p for p, _, _ in counted)
            for p, a, _ in counted:
                lang = language_for(p)
                if lang:
                    lang_added[lang] += a
            for a_name, w in weights.items():
                area_lines[a_name] += w
                area_commits[a_name] += 1
            scored.append({"sha": c["sha"], "subject": c["subject"], "date": iso(date),
                           "lines": adds + dels, "type": ctype})
        phase_input.append({"date": date, "type": ctype, "area": area,
                            "lines": 0 if bulk else adds + dels, "sha": c["sha"],
                            "subject": c["subject"]})

    n_commits = len(user_commits)
    first = parse_dt(user_commits[0]["authored_at"])
    last = parse_dt(user_commits[-1]["authored_at"])

    first_c, last_c = user_commits[0], user_commits[-1]
    key: dict[str, dict[str, Any]] = {
        first_c["sha"]: {"sha": first_c["sha"], "subject": first_c["subject"], "date": iso(first),
                         "lines": 0, "type": "init", "reason": "First commit"}}
    for s in sorted((s for s in scored if s["type"] in {"feature", "refactor", "perf", "fix"}),
                    key=lambda s: -s["lines"])[:4]:
        key.setdefault(s["sha"], {**s, "reason": "Large change"})
    key.setdefault(last_c["sha"], {"sha": last_c["sha"], "subject": last_c["subject"],
                                   "date": iso(last), "lines": 0, "type": "latest",
                                   "reason": "Latest commit"})
    key_commits = sorted(key.values(), key=lambda k: k["date"])

    releases = _releases(store, full, url, snapshot)
    prs_here = [p for p in prs if p["repo"] == full]
    issues_here = [i for i in issues if i["repo"] == full]
    frameworks = skills.detect_frameworks(snapshot.get("manifests", {}))
    repo_skill_list = skills.repo_skills(touches, frameworks)
    q = quality.assess([(p, s) for p, s in snapshot.get("files", [])],
                       snapshot.get("readme"), len(releases))
    langs = _languages_from_tree(snapshot.get("files", []))

    surviving = blame["user_lines"] if blame else None
    total_lines = blame["total_lines"] if blame else None
    base_size = surviving if surviving is not None else int(additions * 0.5)
    weight = (base_size + 5 * n_commits + 20 * sum(1 for p in prs_here if p["merged"])
              + 10 * len(releases))

    area_total = sum(area_lines.values()) or 1
    areas = [{"area": a, "commits": area_commits[a], "lines": n, "share": n / area_total}
             for a, n in area_lines.most_common()]
    by_lang = (blame or {}).get("user_by_language")

    return {
        **base,
        "status": "ok",
        "purpose": quality.extract_purpose(snapshot.get("readme"), repo.get("description")),
        "primary_language": langs[0]["name"] if langs else repo.get("language"),
        "languages": langs,
        "period": {"first": iso(first), "last": iso(last),
                   "months": round(months_between(first, last), 1)},
        "contribution": {
            "commits": n_commits, "merge_commits": merge_commits, "total_commits": total_commits,
            "share": n_commits / total_commits if total_commits else 0.0,
            "files_modified": len(files_modified), "additions": additions, "deletions": deletions,
            "bulk_commits": bulk_count, "ignored_files": ignored,
            "surviving_lines": surviving, "total_lines": total_lines,
            "surviving_share": (surviving / total_lines)
            if surviving is not None and total_lines else None,
            "blame_truncated": bool(blame and blame.get("truncated")),
            "blame_files": blame["files"] if blame else 0,
            "bulk_lines_excluded": (blame or {}).get("excluded_bulk_lines", 0),
        },
        "commit_types": dict(types),
        "areas": areas,
        "phases": build_phases(phase_input),
        "skills": repo_skill_list,
        "quality": q,
        "releases": releases,
        "prs": {"authored": len(prs_here), "merged": sum(1 for p in prs_here if p["merged"]),
                "items": [{"number": p["number"], "title": p["title"], "url": p["url"],
                           "merged": bool(p["merged"]), "date": p["created_at"]}
                          for p in prs_here[:50]]},
        "issues": len(issues_here),
        "evidence": {
            "commits": n_commits > 0, "pull_requests": bool(prs_here), "releases": bool(releases),
            "issues": bool(issues_here), "code_changes": (additions + deletions) > 0,
            "history": n_commits >= 2 and (last - first).days >= 1,
        },
        "key_commits": key_commits,
        "monthly": dict(sorted(monthly.items())),
        "daily": dict(sorted(daily.items())),
        "authors": snapshot.get("authors", []),
        "user_languages": by_lang or dict(lang_added),
        "languages_basis": "surviving" if by_lang else "added",
        "weight": weight,
    }
