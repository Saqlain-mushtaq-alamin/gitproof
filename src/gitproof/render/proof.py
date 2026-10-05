"""Report fingerprint and resume bullets (deterministic, no AI)."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..util import fmt_int, plural
from .data import ReportData


def _canon(profile: dict[str, Any], repos: list[dict[str, Any]]) -> bytes:
    p = {k: v for k, v in profile.items() if k != "generated_at"}
    return json.dumps({"profile": p, "repositories": repos}, sort_keys=True,
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def fingerprint(data: ReportData) -> str:
    """SHA-256 over the analysis data (not the generation time), so equal data gives an equal digest."""
    return hashlib.sha256(_canon(data.profile, data.repos)).hexdigest()


def fingerprint_json(text: str) -> str:
    """Recompute the digest from an exported JSON report."""
    doc = json.loads(text)
    return hashlib.sha256(_canon(doc["profile"], doc["repositories"])).hexdigest()


def verification(data: ReportData) -> dict[str, str]:
    return {"digest": fingerprint(data),
            "command": f"gitproof verify {data.profile['login']}-proof-of-work.json"}


def resume_bullets(data: ReportData, limit: int = 6) -> list[str]:
    """Factual bullets built only from measured numbers."""
    t = data.profile["totals"]
    out = []
    for r in data.repos[:limit]:
        c = r["contribution"]
        langs = ", ".join(l["name"] for l in r["languages"][:2]) or "multiple languages"
        lines = c["surviving_lines"] if c["surviving_lines"] is not None else c["additions"]
        kind = "lines still in production code" if c["surviving_lines"] is not None else "lines added"
        out.append(f"{r['name']}: {plural(c['commits'], 'commit')} in {langs}; "
                   f"{fmt_int(lines)} {kind}; {r['period']['months']} months of history. {r['purpose']}")
    pr = data.profile["prs"]
    if pr["external_merged"]:
        out.append(f"Open source: {plural(pr['external_merged'], 'pull request')} merged into other "
                   "people's repositories.")
    out.append(f"Overall: {plural(t['commits'], 'commit')} across "
               f"{plural(t['repos_with_work'], 'repository', 'repositories')} over "
               f"{t['years_active']} years.")
    return out


def linkedin_summary(data: ReportData) -> str:
    p, t = data.profile, data.profile["totals"]
    langs = ", ".join(l["name"] for l in p["languages"][:4])
    s = (f"{p['name']} - {plural(t['commits'], 'commit')} across "
         f"{plural(t['repos_with_work'], 'repository', 'repositories')} on GitHub over "
         f"{t['years_active']} years")
    if langs:
        s += f", mostly {langs}"
    if p["focus"]:
        s += f". Focus: {', '.join(p['focus'])}"
    return s + f". Evidence: {p['url']}"
