"""Combine per-repository analyses into the developer-level profile."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from ..util import iso, now, parse_dt
from .skills import merge_skills

ACTIVE_WINDOW_DAYS = 180
MIN_FOCUS_COMMITS = 3

DOMAINS: dict[str, set[str]] = {
    "AI/ML": {"PyTorch", "TensorFlow", "Keras", "Hugging Face Transformers", "scikit-learn",
              "NumPy", "pandas", "LangChain", "OpenAI API", "Anthropic API", "Ollama",
              "llama.cpp", "Jupyter Notebook", "FAISS", "ChromaDB", "Gymnasium",
              "Stable-Baselines3", "OpenCV", "XGBoost", "LightGBM", "PEFT", "vLLM",
              "Sentence Transformers", "SHAP", "ONNX Runtime", "CUDA", "Candle"},
    "Mobile": {"Flutter", "React Native", "Expo", "Kotlin", "Swift", "Dart", "Objective-C"},
    "Web": {"React", "Vue", "Svelte", "Next.js", "Angular", "Django", "Flask", "FastAPI",
            "Express", "TypeScript", "JavaScript", "HTML", "CSS", "SCSS", "Tailwind CSS"},
    "Systems": {"Rust", "C", "C++", "Go", "Zig", "Tokio", "Axum"},
    "Security": {"Scapy"},
    "DevOps": {"Docker", "GitHub Actions", "Terraform", "Kubernetes/Helm", "GitLab CI"},
    "Desktop": {"Electron", "Tauri"},
}


def infer_focus(skills: list[dict[str, Any]]) -> list[str]:
    scores: Counter[str] = Counter()
    for s in skills:
        for domain, names in DOMAINS.items():
            if s["name"] in names:
                scores[domain] += s["commits"]
    # a domain needs real volume behind it, otherwise one Dockerfile commit becomes "DevOps"
    return [d for d, n in scores.most_common(3) if n >= MIN_FOCUS_COMMITS]


def _streaks(days: set[str]) -> tuple[int, int]:
    if not days:
        return 0, 0
    dates = sorted(datetime.strptime(d, "%Y-%m-%d").date() for d in days)
    longest = run = 1
    for prev, cur in zip(dates, dates[1:], strict=False):
        run = run + 1 if (cur - prev).days == 1 else 1
        longest = max(longest, run)
    current = 0
    cursor = dates[-1]
    if (now().date() - cursor).days <= 1:
        s = set(dates)
        while cursor in s:
            current += 1
            cursor -= timedelta(days=1)
    return longest, current


def _thin(events: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    priority = {"start": 0, "release": 1, "pr": 1, "phase": 2}
    kept = sorted(events, key=lambda e: (priority[e["kind"]], e["date"]))[:limit]
    return sorted(kept, key=lambda e: e["date"])


def build_milestones(repos: list[dict[str, Any]], limit: int = 40) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for r in repos:
        name, base = r["name"], r["url"]
        events.append({"date": r["period"]["first"], "repo": name, "kind": "start",
                       "text": f"Started {name}",
                       "url": f"{base}/commit/{r['key_commits'][0]['sha']}"})
        for ph in r["phases"][1:]:
            events.append({"date": ph["start"], "repo": name, "kind": "phase",
                           "text": f"{name}: {ph['label']}", "url": f"{base}/commit/{ph['first_sha']}"})
        for rel in r["releases"][:3]:
            if rel.get("date"):
                events.append({"date": rel["date"], "repo": name, "kind": "release",
                               "text": f"{name} release {rel['tag']}", "url": rel["url"]})
        merged = [p for p in r["prs"]["items"] if p["merged"]]
        if merged:
            p = min(merged, key=lambda x: x["date"])
            events.append({"date": p["date"], "repo": name, "kind": "pr",
                           "text": f"{name}: first merged PR - {p['title']}", "url": p["url"]})
    events.sort(key=lambda e: e["date"])
    return events if len(events) <= limit else _thin(events, limit)


def build_profile(login: str, user: dict[str, Any], all_repos: list[dict[str, Any]],
                  analyses: list[dict[str, Any]], prs: list[dict[str, Any]],
                  issues: list[dict[str, Any]], reviews: int | None, warnings: list[str],
                  since: str | None) -> dict[str, Any]:
    ok = sorted((a for a in analyses if a["status"] == "ok"), key=lambda a: -a["weight"])
    commits = sum(a["contribution"]["commits"] for a in ok)
    additions = sum(a["contribution"]["additions"] for a in ok)
    deletions = sum(a["contribution"]["deletions"] for a in ok)
    blamed = [a for a in ok if a["contribution"]["surviving_lines"] is not None]
    surviving = sum(a["contribution"]["surviving_lines"] for a in blamed) if blamed else None

    monthly: Counter[str] = Counter()
    daily: Counter[str] = Counter()
    for a in ok:
        monthly.update(a["monthly"])
        daily.update(a["daily"])
    yearly: Counter[str] = Counter()
    for month, n in monthly.items():
        yearly[month[:4]] += n

    firsts = [parse_dt(a["period"]["first"]) for a in ok]
    lasts = [parse_dt(a["period"]["last"]) for a in ok]
    first, last = (min(firsts), max(lasts)) if ok else (None, None)
    years = round((last - first).days / 365.25, 1) if first and last else 0.0
    cutoff = now() - timedelta(days=ACTIVE_WINDOW_DAYS)
    active_projects = sum(1 for l in lasts if l >= cutoff)
    longest, current = _streaks(set(daily))

    skills = merge_skills({a["full_name"]: a["skills"] for a in ok})
    langs: Counter[str] = Counter()
    bases = {a["languages_basis"] for a in ok}
    for a in ok:
        langs.update(a["user_languages"])
    total_lang = sum(langs.values()) or 1
    languages = [{"name": n, "lines": l, "share": l / total_lang} for n, l in langs.most_common()]
    basis = "surviving" if bases == {"surviving"} else "added" if bases == {"added"} else "mixed"

    cutoff_day = (now() - timedelta(days=400)).strftime("%Y-%m-%d")
    external_prs = [p for p in prs if p["external"]]
    open_source = sorted(
        ({"repo": p["repo"], "title": p["title"], "number": p["number"], "url": p["url"],
          "merged": bool(p["merged"]), "state": p["state"], "date": p["created_at"]}
         for p in external_prs),
        key=lambda p: (not p["merged"], -parse_dt(p["date"]).timestamp()))

    repos_owned = [r for r in all_repos if not r["is_fork"]]
    return {
        "login": login, "name": user.get("name") or login, "bio": user.get("bio"),
        "url": user.get("html_url") or f"https://github.com/{login}",
        "company": user.get("company"), "location": user.get("location"),
        "blog": user.get("blog"), "followers": user.get("followers", 0),
        "account_created": user.get("created_at"), "generated_at": iso(now()),
        "since_filter": since, "warnings": warnings, "focus": infer_focus(skills),
        "totals": {
            "repos_total": len(all_repos), "repos_owned": len(repos_owned),
            "repos_forked": len(all_repos) - len(repos_owned), "repos_with_work": len(ok),
            "commits": commits, "additions": additions, "deletions": deletions,
            "lines_changed": additions + deletions, "surviving_lines": surviving,
            "languages_count": len([l for l in languages if l["share"] >= 0.005]),
            "active_projects": active_projects, "years_active": years,
            "first_activity": iso(first) if first else None,
            "last_activity": iso(last) if last else None,
            "longest_streak": longest, "current_streak": current, "active_days": len(daily),
        },
        "prs": {"authored": len(prs), "merged": sum(1 for p in prs if p["merged"]),
                "external_authored": len(external_prs),
                "external_merged": sum(1 for p in external_prs if p["merged"]),
                "reviews": reviews},
        "issues": {"authored": len(issues), "external": sum(1 for i in issues if i["external"])},
        "languages": languages, "languages_basis": basis, "skills": skills,
        "monthly": dict(sorted(monthly.items())), "yearly": dict(sorted(yearly.items())),
        "daily": {d: n for d, n in sorted(daily.items()) if d >= cutoff_day},
        "open_source": open_source, "milestones": build_milestones(ok),
        "top_repos": [a["full_name"] for a in ok],
    }
