"""Print-friendly HTML version of the report (source for PDF export)."""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from .. import __version__
from ..util import fmt_date, fmt_int, fmt_month, plural
from .data import ReportData
from .report import methodology, professional_summary

FRAMEWORK_CATEGORIES = {"Framework", "ML/AI", "Library", "Platform", "Security", "Testing"}
LAYOUTS = ("full", "summary")


def _pct(value: float, peak: float) -> float:
    return round(100 * value / peak, 1) if peak else 0.0


def build_html_context(data: ReportData, layout: str = "full", top: int | None = None,
                       verification: dict[str, str] | None = None,
                       ai: dict[str, Any] | None = None) -> dict[str, Any]:
    if layout not in LAYOUTS:
        raise ValueError(f"layout must be one of {LAYOUTS}")
    p, t = data.profile, data.profile["totals"]
    login = p["login"]
    q = quote(login)
    limit = top or (5 if layout == "summary" else None)
    repos = data.repos[:limit] if limit else data.repos
    urls = {r["full_name"]: r["url"] for r in data.repos}

    skills = []
    for s in p["skills"][: 10 if layout == "summary" else 25]:
        links = [{"sha": e["sha"][:7], "url": f"{urls.get(e['repo'], 'https://github.com/' + e['repo'])}/commit/{e['sha']}"}
                 for e in s["evidence"][:2]]
        skills.append({**s, "repo_count": len(s["repos"]), "first_label": fmt_month(s["first_seen"]),
                       "links": links})

    projects = []
    for r in repos:
        c, per = r["contribution"], r["period"]
        stack = ([r["primary_language"]] if r["primary_language"] else []) + [
            s["name"] for s in r["skills"] if s["category"] in FRAMEWORK_CATEGORIES][:3]
        lines = c["surviving_lines"] if c["surviving_lines"] is not None else c["additions"]
        pr_sorted = sorted(r["prs"]["items"], key=lambda x: (not x["merged"], x["date"]))[:5]
        projects.append({
            **r,
            "stack": ", ".join(stack) or "n/a",
            "period_short": f"{fmt_month(per['first'])} - {fmt_month(per['last'])}",
            "period_text": f"{fmt_month(per['first'])} to {fmt_month(per['last'])} ({per['months']} months)",
            "lines": fmt_int(lines),
            "commits_fmt": fmt_int(c["commits"]),
            "share_text": f"{c['share'] * 100:.0f}%" if c["total_commits"] else "n/a",
            "surviving_text": (f"{fmt_int(c['surviving_lines'])} of {fmt_int(c['total_lines'])} lines"
                               + (f" ({c['surviving_share'] * 100:.0f}%)" if c["surviving_share"] is not None else "")
                               + (" (sampled)" if c["blame_truncated"] else ""))
            if c["surviving_lines"] is not None else "not measured",
            "languages_text": ", ".join(f"{l['name']} {l['share'] * 100:.0f}%" for l in r["languages"][:5]) or "n/a",
            "tools_text": ", ".join(s["name"] for s in r["skills"] if s["category"] != "Language") or "none detected",
            "types_text": ", ".join(f"{k} {v}" for k, v in sorted(r["commit_types"].items(), key=lambda kv: -kv[1])),
            "areas_fmt": [{"area": a["area"], "pct": round(a["share"] * 100), "width": round(a["share"] * 100, 1),
                           "lines": fmt_int(a["lines"])} for a in r["areas"][:6]],
            "phases_fmt": [{"n": ph["index"], "label": ph["label"], "commits": ph["commits"],
                            "range": f"{fmt_date(ph['start'])} to {fmt_date(ph['end'])}"} for ph in r["phases"]],
            "key_commits_fmt": [{"sha": k["sha"][:7], "url": f"{r['url']}/commit/{k['sha']}",
                                 "date": fmt_date(k["date"]), "reason": k["reason"], "subject": k["subject"]}
                                for k in r["key_commits"]],
            "pr_links": [{"label": f"#{x['number']} {x['title']}", "url": x["url"], "merged": x["merged"]}
                         for x in pr_sorted],
            "release_links": [{"label": x["tag"], "url": x["url"]} for x in r["releases"][-5:]],
            "commits_url": f"{r['url']}/commits?author={q}",
            "evidence_flags": [(label, r["evidence"][key]) for label, key in [
                ("Commits", "commits"), ("Pull requests", "pull_requests"), ("Releases", "releases"),
                ("Issues", "issues"), ("Code changes", "code_changes"), ("History", "history")]],
        })

    lang_peak = max((l["share"] for l in p["languages"]), default=0)
    languages = [{"name": l["name"], "lines": fmt_int(l["lines"]), "pct": f"{l['share'] * 100:.1f}%",
                  "width": _pct(l["share"], lang_peak)} for l in p["languages"][:8]]
    year_peak = max(p["yearly"].values(), default=0)
    yearly = [{"year": y, "commits": fmt_int(n), "width": _pct(n, year_peak)} for y, n in p["yearly"].items()]
    monthly_items = list(p["monthly"].items())[-24:]
    month_peak = max((n for _, n in monthly_items), default=0)
    monthly = [{"month": m, "n": n, "height": _pct(n, month_peak)} for m, n in monthly_items]

    surviving = t["surviving_lines"]
    stats = [
        (fmt_int(t["commits"]), "commit" if t["commits"] == 1 else "commits"),
        (str(t["repos_with_work"]), "project with commits" if t["repos_with_work"] == 1 else "projects with commits"),
        (fmt_int(surviving) if surviving is not None else fmt_int(t["lines_changed"]),
         "lines still in code" if surviving is not None else "lines changed"),
        (str(t["languages_count"]), "language" if t["languages_count"] == 1 else "languages"),
        (str(p["prs"]["merged"]), "merged pull request" if p["prs"]["merged"] == 1 else "merged pull requests"),
        (str(t["years_active"]), "years of activity"),
    ]
    return {
        "layout": layout, "p": p, "t": t, "pr": p["prs"], "iss": p["issues"], "login": login,
        "version": __version__, "generated": fmt_date(p["generated_at"]),
        "summary": professional_summary(data), "stats": stats, "skills": skills,
        "projects": projects, "languages": languages, "yearly": yearly, "monthly": monthly,
        "open_source": [{**o, "date_label": fmt_date(o["date"]),
                         "status": "merged" if o["merged"] else o["state"]} for o in p["open_source"][:30]],
        "milestones": [{"date": fmt_date(m["date"]), "text": m["text"], "url": m["url"]}
                       for m in p["milestones"][-20:]],
        "evidence": [{"name": r["name"], "url": r["url"], "commits_url": f"{r['url']}/commits?author={q}",
                      "flags": [bool(r["evidence"][k]) for k in
                                ("commits", "pull_requests", "releases", "issues", "code_changes", "history")]}
                     for r in data.repos],
        "others": data.others,
        "verification_links": {
            "Profile": p["url"],
            "All pull requests": f"https://github.com/pulls?q=author%3A{q}+type%3Apr",
            "All issues": f"https://github.com/issues?q=author%3A{q}+type%3Aissue",
        },
        "verification": verification,
        "ai_summary": (ai or {}).get("profile"),
        "ai_repos": (ai or {}).get("repos") or {},
        "methodology": methodology(data),
        "plural": plural, "fmt_int": fmt_int, "fmt_date": fmt_date,
    }


def _env() -> Environment:
    return Environment(loader=PackageLoader("gitproof", "templates"), trim_blocks=True,
                       lstrip_blocks=True, undefined=StrictUndefined,
                       autoescape=select_autoescape(["html", "j2"], default=True),
                       keep_trailing_newline=True)


def build_html(data: ReportData, layout: str = "full", top: int | None = None,
               verification: dict[str, str] | None = None, ai: dict[str, Any] | None = None) -> str:
    ctx = build_html_context(data, layout, top, verification, ai)
    return _env().get_template("report.html.j2").render(**ctx)
