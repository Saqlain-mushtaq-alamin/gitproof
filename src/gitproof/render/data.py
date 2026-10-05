from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..db import Store, db_path


class NoDataError(Exception):
    pass


@dataclass
class ReportData:
    profile: dict[str, Any]
    repos: list[dict[str, Any]]
    others: list[dict[str, Any]] = field(default_factory=list)

    def find_repo(self, name: str) -> dict[str, Any] | None:
        low = name.lower()
        for r in self.repos:
            if r["name"].lower() == low or r["full_name"].lower() == low:
                return r
        return None


def load_report(login: str) -> ReportData:
    if not db_path(login).exists():
        raise NoDataError(f"No analysis found for '{login}'. Run: gitproof analyze {login}")
    store = Store(login)
    try:
        profiles = store.all_analysis("profile")
        profile = profiles.get(login) or next(iter(profiles.values()), None)
        if not profile:
            raise NoDataError(f"No analysis found for '{login}'. Run: gitproof analyze {login}")
        analyses = store.all_analysis("repo")
        order = {name: i for i, name in enumerate(profile.get("top_repos", []))}
        ranked = sorted((a for a in analyses.values()
                         if a.get("status") == "ok" and a["full_name"] in order),
                        key=lambda a: order[a["full_name"]])
        others = [a for a in analyses.values() if a.get("status") != "ok"]
        for r in store.get_repos():
            if r["full_name"] not in analyses and r.get("status") in {"skipped", "empty", "error"}:
                others.append({"full_name": r["full_name"], "name": r["name"],
                               "status": r["status"], "status_note": r.get("status_note")})
        return ReportData(profile=profile, repos=ranked, others=others)
    finally:
        store.close()
