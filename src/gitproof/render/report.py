"""Build the proof-of-work report (Markdown / JSON) from stored analysis."""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from jinja2 import Environment, PackageLoader, StrictUndefined

from .. import __version__
from ..util import fmt_date, fmt_int, fmt_month, iso, now, plural
from .data import ReportData

FRAMEWORK_CATEGORIES = {"Framework", "ML/AI", "Library", "Platform", "Security", "Testing"}


def md(text: Any) -> str:
    """Make arbitrary text safe inside a Markdown table cell."""
    return " ".join(str(text).replace("|", "\\|").split())


def commit_link(repo_url: str, sha: str) -> str:
    return f"[`{sha[:7]}`]({repo_url}/commit/{sha})"


def block_bar(value: int, peak: int, width: int = 24) -> str:
    return "█" * max(1 if value else 0, round(value / peak * width)) if peak else ""


def professional_summary(data: ReportData) -> str:
    p, t = data.profile, data.profile["totals"]
    if not data.repos:
        return (f"No repositories with attributable commits were found for {p['name']}. "
                "Try adding email aliases with `gitproof config --alias`.")
    first, last = (t["first_activity"] or "")[:4], (t["last_activity"] or "")[:4]
    span = f"{first}-{last}" if first != last else first
    out = [f"{p['name']} has {t['years_active']} years of visible GitHub activity ({span}), with "
           f"{plural(t['commits'], 'attributable commit')} across "
           f"{plural(t['repos_with_work'], 'repository', 'repositories')} and "
           f"{plural(t['active_days'], 'active day')}."]
    langs = [l["name"] for l in p["languages"][:3]]
    if p["focus"]:
        s = f"Work is concentrated in {', '.join(p['focus'])} (inferred from the technologies used)"
        if langs:
            s += f", mainly in {', '.join(langs)}"
        out.append(s + ".")
    if t["surviving_lines"]:
        out.append(f"About {fmt_int(t['surviving_lines'])} lines written by the developer are still "
                   "present in the current state of the analyzed repositories.")
    top = data.repos[0]
    out.append(f"The most substantial project by evidence of work is {top['name']}: {top['purpose']}")
    if p["prs"]["external_merged"]:
        n = p["prs"]["external_merged"]
        out.append(f"{plural(n, 'pull request')} {'has' if n == 1 else 'have'} been merged into "
                   "other people's repositories.")
    if t["active_projects"]:
        n = t["active_projects"]
        out.append(f"{plural(n, 'project')} received commits in the last 180 days.")
    return " ".join(out)


def methodology(data: ReportData) -> list[str]:
    p = data.profile
    notes = [
        "Only commits whose author email or name matches the developer's GitHub identity are "
        "counted. Names are matched only inside repositories the developer owns.",
        "Lock files, vendored or generated code, build output, binary assets and data files are "
        "excluded from line counts. Commits that import 150+ files or 20,000+ lines at once are "
        "treated as bulk imports and excluded from line counts, including surviving lines (they "
        "still count as commits).",
        "Merge commits are not counted as work. Forks appear only when they contain commits "
        "attributed to the developer, and the history shown is the fork's own history.",
        "\"Surviving lines\" come from `git blame` at the default branch and show how much of the "
        "developer's code is still present. For very large repositories only the largest source "
        "files are sampled, and this is flagged per project.",
        "Commit types, development areas and phases are derived from commit messages, file paths "
        "and activity gaps by fixed rules, so the same history always gives the same result. They "
        "are heuristics, not a judgement of quality.",
        "Skills marked 'strong' come from files the developer changed. Skills marked 'inferred' "
        "come from dependency manifests the developer edited, so first-seen dates are approximate.",
        "Technology domains in the summary are inferred from the technologies used and are not a "
        "job title.",
        "Every statistic links to commits, pull requests or releases on GitHub so it can be "
        "verified independently.",
    ]
    if p.get("since_filter"):
        notes.append(f"Only commits since {p['since_filter']} were analyzed.")
    truncated = [r["name"] for r in data.repos if r["contribution"]["blame_truncated"]]
    if truncated:
        notes.append("Surviving-line figures were sampled for: " + ", ".join(truncated) + ".")
    notes += [f"Data note: {w}" for w in p["warnings"]]
    return notes


def ai_block(res: dict[str, Any] | None) -> dict[str, Any] | None:
    """Markdown-ready view of a stored (already verified) AI result."""
    if not res or not res.get("text"):
        return None
    refs = " ".join(f"[`{e['id']}`]({e['url']})" if e.get("url") else f"`{e['id']}`"
                    for e in res.get("evidence", []))
    return {"text": res["text"], "label": f"{res['provider']} / {res['model']}", "refs": refs}


def build_context(data: ReportData, top: int | None = None, skills_limit: int = 25,
                  milestones_limit: int = 20, ai: dict[str, Any] | None = None,
                  verify: dict[str, str] | None = None) -> dict[str, Any]:
    p = data.profile
    login = p["login"]
    repos = data.repos[:top] if top else data.repos
    repo_urls = {r["full_name"]: r["url"] for r in data.repos}

    skills = []
    for s in p["skills"][:skills_limit]:
        links = [commit_link(repo_urls.get(e["repo"], f"https://github.com/{e['repo']}"), e["sha"])
                 for e in s["evidence"][:2]]
        skills.append({**s, "repo_count": len(s["repos"]), "evidence_links": " ".join(links),
                       "first_label": fmt_month(s["first_seen"])})

    portfolio, projects = [], []
    for r in repos:
        c, per = r["contribution"], r["period"]
        stack = ([r["primary_language"]] if r["primary_language"] else []) + [
            s["name"] for s in r["skills"] if s["category"] in FRAMEWORK_CATEGORIES][:3]
        lines = c["surviving_lines"] if c["surviving_lines"] is not None else c["additions"]
        portfolio.append({
            "name": r["name"], "url": r["url"], "purpose": md(r["purpose"]),
            "stack": md(", ".join(stack) or "n/a"),
            "period": f"{fmt_month(per['first'])} - {fmt_month(per['last'])}",
            "commits": fmt_int(c["commits"]), "lines": fmt_int(lines),
            "quality": f"{r['quality']['score']}/100"})
        key_commits = [{"link": commit_link(r["url"], k["sha"]), "date": fmt_date(k["date"]),
                        "reason": k["reason"], "subject": md(k["subject"])}
                       for k in r["key_commits"]]
        pr_sorted = sorted(r["prs"]["items"], key=lambda x: (not x["merged"], x["date"]))[:5]
        projects.append({
            **r,
            "period_text": f"{fmt_month(per['first'])} -> {fmt_month(per['last'])} ({per['months']} months)",
            "languages_text": ", ".join(f"{l['name']} {l['share'] * 100:.0f}%"
                                        for l in r["languages"][:5]) or "n/a",
            "tools_text": ", ".join(s["name"] for s in r["skills"]
                                    if s["category"] != "Language") or "none detected",
            "share_text": f"{c['share'] * 100:.0f}%" if c["total_commits"] else "n/a",
            "surviving_text": (
                f"{fmt_int(c['surviving_lines'])} of {fmt_int(c['total_lines'])} lines"
                + (f" ({c['surviving_share'] * 100:.0f}%)" if c["surviving_share"] is not None else "")
                + (" - sampled" if c["blame_truncated"] else "")
            ) if c["surviving_lines"] is not None else "not measured",
            "key_commits": key_commits,
            "phases_fmt": [{"n": ph["index"], "label": ph["label"],
                            "range": f"{fmt_date(ph['start'])} -> {fmt_date(ph['end'])}",
                            "commits": ph["commits"]} for ph in r["phases"]],
            "areas_fmt": [{"area": a["area"], "pct": f"{a['share'] * 100:.0f}%",
                           "lines": fmt_int(a["lines"])} for a in r["areas"][:7]],
            "types_text": ", ".join(f"{k} {v}" for k, v in
                                    sorted(r["commit_types"].items(), key=lambda kv: -kv[1])),
            "release_links": [f"[{md(x['tag'])}]({x['url']})" for x in r["releases"][-5:]],
            "pr_links": [f"[#{x['number']} {md(x['title'])}]({x['url']})"
                         + (" (merged)" if x["merged"] else "") for x in pr_sorted],
            "commits_url": f"{r['url']}/commits?author={quote(login)}",
            "ai": ai_block(((ai or {}).get("repos") or {}).get(r["full_name"])),
        })

    peak = max(p["monthly"].values()) if p["monthly"] else 0
    monthly_bars = [f"{m}  {block_bar(n, peak):<24} {n}" for m, n in list(p["monthly"].items())[-24:]]
    yearly_peak = max(p["yearly"].values()) if p["yearly"] else 0
    yearly = [{"year": y, "commits": fmt_int(n), "bar": block_bar(n, yearly_peak, 30)}
              for y, n in p["yearly"].items()]
    evidence = [{
        "name": r["name"], "url": r["url"],
        "flags": ["✓" if r["evidence"][k] else "✗" for k in
                  ("commits", "pull_requests", "releases", "issues", "code_changes", "history")],
        "commits_url": f"{r['url']}/commits?author={quote(login)}"} for r in data.repos]
    open_source = [{**o, "label": md(o["title"]), "date_label": fmt_date(o["date"]),
                    "status": "merged" if o["merged"] else o["state"]} for o in p["open_source"][:30]]
    milestones = [{"date": fmt_date(m["date"]), "text": md(m["text"]), "url": m["url"]}
                  for m in p["milestones"][-milestones_limit:]]
    q = quote(login)
    return {
        "p": p, "t": p["totals"], "pr": p["prs"], "iss": p["issues"], "login": login,
        "generated": fmt_date(p["generated_at"]), "version": __version__,
        "summary": professional_summary(data),
        "ai_summary": ai_block((ai or {}).get("profile")),
        "skills": skills, "portfolio": portfolio, "projects": projects,
        "monthly_bars": monthly_bars, "yearly": yearly,
        "languages": [{"name": l["name"], "lines": fmt_int(l["lines"]), "pct": f"{l['share'] * 100:.1f}%"}
                      for l in p["languages"][:12]],
        "languages_basis": {"surviving": "lines still present in the code",
                            "added": "lines added",
                            "mixed": "surviving lines where available, otherwise lines added"
                            }[p["languages_basis"]],
        "evidence": evidence, "open_source": open_source, "milestones": milestones,
        "others": data.others,
        "verification": {
            "profile": p["url"],
            "prs": f"https://github.com/pulls?q=author%3A{q}+type%3Apr",
            "issues": f"https://github.com/issues?q=author%3A{q}+type%3Aissue",
            "merged_external": f"https://github.com/search?q=author%3A{q}+type%3Apr+is%3Amerged&type=pullrequests",
        },
        "methodology": methodology(data),
        "fingerprint": verify,
        "fmt_month": fmt_month, "fmt_date": fmt_date, "fmt_int": fmt_int, "plural": plural,
    }


def _env() -> Environment:
    return Environment(loader=PackageLoader("gitproof", "templates"), trim_blocks=True,
                       lstrip_blocks=True, undefined=StrictUndefined, keep_trailing_newline=True)


def build_markdown(data: ReportData, top: int | None = None, ai: dict[str, Any] | None = None,
                   verification: dict[str, str] | None = None) -> str:
    return _env().get_template("report.md.j2").render(
        **build_context(data, top=top, ai=ai, verify=verification))


def build_json(data: ReportData, ai: dict[str, Any] | None = None,
               verification: dict[str, str] | None = None) -> str:
    payload: dict[str, Any] = {"schema_version": 1, "generated_at": iso(now()), "profile": data.profile,
                               "repositories": data.repos, "not_analyzed": data.others}
    if verification:
        payload["fingerprint"] = verification["digest"]
    if ai and (ai.get("profile") or ai.get("repos")):
        payload["ai"] = {"profile": ai.get("profile"), "repositories": ai.get("repos")}
    return json.dumps(payload, indent=2, ensure_ascii=False)
