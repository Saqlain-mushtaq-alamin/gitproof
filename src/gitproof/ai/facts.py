"""Evidence facts: every statement the AI may use is a Fact with a stable id and a URL.

Only compact, derived metadata is turned into facts - commit subjects, PR titles, release
tags, counts, technology names, the one-sentence project purpose. Source code, file
contents and author email addresses never appear here.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from ..util import fmt_date, fmt_month

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def clean(text: Any, limit: int = 200) -> str:
    """Neutralise untrusted text before it goes into a prompt (control chars, length, fences)."""
    s = _CONTROL.sub(" ", str(text or ""))
    s = s.replace("```", "'''").replace("<<<", "<").replace(">>>", ">")
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 3].rstrip() + "..."


@dataclass
class Fact:
    id: str
    kind: str          # commit | pr | release | repo | skill | area | phase | profile
    text: str
    url: str | None = None
    repo: str | None = None


@dataclass
class Digest:
    """A prompt-ready block of facts plus the index used to verify the model's citations."""
    text: str
    facts: dict[str, Fact] = field(default_factory=dict)

    def add(self, fact: Fact) -> Fact:
        self.facts[fact.id] = fact
        return fact

    def fingerprint(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()[:16]


def numbers_in(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def _short_sha(sha: str, taken: dict[str, Fact]) -> str:
    for n in (7, 9, 12, 40):
        cid = f"c:{sha[:n]}"
        if cid not in taken or taken[cid].url and taken[cid].url.endswith(sha):
            return cid
    return f"c:{sha}"


def _sample_commits(repo: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    """Key commits plus an even spread across the phases, so the model sees the whole story."""
    chosen: dict[str, dict[str, Any]] = {k["sha"]: k for k in repo["key_commits"]}
    return sorted(chosen.values(), key=lambda k: k["date"])[:limit]


def repo_digest(repo: dict[str, Any], extra_commit_subjects: list[dict[str, Any]] | None = None
                ) -> Digest:
    full, url = repo["full_name"], repo["url"]
    c, per, q = repo["contribution"], repo["period"], repo["quality"]
    d = Digest(text="")
    lines: list[str] = []

    def emit(fact: Fact, line: str | None = None) -> None:
        d.add(fact)
        lines.append(f"[{fact.id}] {line or fact.text}")

    stack = [s["name"] for s in repo["skills"]][:10]
    emit(Fact(f"repo:{full}", "repo",
              f"{repo['name']}: {clean(repo['purpose'], 280)} Languages: "
              f"{', '.join(l['name'] for l in repo['languages'][:4]) or 'n/a'}. Stack: "
              f"{', '.join(stack) or 'n/a'}. Active {fmt_month(per['first'])} to {fmt_month(per['last'])} "
              f"({per['months']} months). Developer made {c['commits']} of {c['total_commits']} commits "
              f"(+{c['additions']} / -{c['deletions']} lines excluding noise)"
              + (f", {c['surviving_lines']} lines still in the code" if c["surviving_lines"] is not None else "")
              + f". Quality signals: {', '.join(q['badges'])}.", url, full))
    for a in repo["areas"][:6]:
        emit(Fact(f"area:{full}:{a['area']}", "area",
                  f"{a['area']} work: {a['share'] * 100:.0f}% of changed lines ({a['lines']} lines, "
                  f"{a['commits']} commits)", url, full))
    for ph in repo["phases"]:
        emit(Fact(f"phase:{full}#{ph['index']}", "phase",
                  f"Phase {ph['index']} ({fmt_date(ph['start'])} to {fmt_date(ph['end'])}, "
                  f"{ph['commits']} commits): {ph['label']}", f"{url}/commit/{ph['first_sha']}", full))
    taken: dict[str, Fact] = {}
    for k in _sample_commits(repo):
        cid = _short_sha(k["sha"], taken)
        f = Fact(cid, "commit", f"{fmt_date(k['date'])} {k['reason']}: {clean(k['subject'], 120)}",
                 f"{url}/commit/{k['sha']}", full)
        taken[cid] = f
        emit(f)
    for extra in extra_commit_subjects or []:
        cid = _short_sha(extra["sha"], taken)
        if cid in taken:
            continue
        f = Fact(cid, "commit", f"{fmt_date(extra['date'])}: {clean(extra['subject'], 120)}",
                 f"{url}/commit/{extra['sha']}", full)
        taken[cid] = f
        emit(f)
    for p in repo["prs"]["items"][:6]:
        emit(Fact(f"pr:{full}#{p['number']}", "pr",
                  f"Pull request #{p['number']} {clean(p['title'], 120)}"
                  + (" (merged)" if p["merged"] else ""), p["url"], full))
    for r in repo["releases"][-4:]:
        emit(Fact(f"rel:{full}@{r['tag']}", "release",
                  f"Release {clean(r['tag'], 40)} on {fmt_date(r['date'])}", r["url"], full))
    d.text = "\n".join(lines)
    return d


def profile_facts(profile: dict[str, Any]) -> Digest:
    t, pr = profile["totals"], profile["prs"]
    d = Digest(text="")
    lines: list[str] = []

    def emit(fact: Fact) -> None:
        d.add(fact)
        lines.append(f"[{fact.id}] {fact.text}")

    emit(Fact("profile:totals", "profile",
              f"{profile['name']}: {t['commits']} attributable commits in {t['repos_with_work']} "
              f"repositories over {t['years_active']} years ({fmt_date(t['first_activity'])} to "
              f"{fmt_date(t['last_activity'])}); {t['active_days']} active days; "
              f"{t['lines_changed']} lines changed (noise filtered)"
              + (f", {t['surviving_lines']} still in the code" if t["surviving_lines"] is not None else "")
              + f"; {pr['authored']} pull requests ({pr['merged']} merged, {pr['external_merged']} "
              f"merged into other people's repositories); {t['languages_count']} languages.",
              profile["url"]))
    for s in profile["skills"][:15]:
        emit(Fact(f"skill:{s['name']}", "skill",
                  f"{s['name']} ({s['category']}, {s['confidence']} evidence): first seen "
                  f"{fmt_month(s['first_seen'])}, {s['commits']} commits in {len(s['repos'])} "
                  f"repositories", profile["url"]))
    d.text = "\n".join(lines)
    return d
