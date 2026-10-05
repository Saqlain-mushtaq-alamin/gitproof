"""Decide which git commits belong to the GitHub user.

Match order: exact email (profile, aliases, emails GitHub attributed to the login), the user's
GitHub noreply address, then exact author name - names only inside repos the user owns,
because names collide across the wider world.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

NOREPLY_RE = re.compile(r"^(?:\d+\+)?(?P<login>[^@]+)@users\.noreply\.github\.com$", re.IGNORECASE)
GENERIC_NAMES = {"github", "unknown", "root", "admin", "user", "ubuntu", "dev", "me"}


@dataclass
class Identity:
    login: str
    emails: set[str] = field(default_factory=set)
    names: set[str] = field(default_factory=set)

    def add(self, value: str | None) -> None:
        if not value:
            return
        value = value.strip().lower()
        if not value:
            return
        if "@" in value:
            if value != "noreply@github.com":
                self.emails.add(value)
        elif value not in GENERIC_NAMES:
            self.names.add(value)

    def matches(self, email: str, name: str, allow_name: bool = False) -> bool:
        e = (email or "").strip().lower()
        if e in self.emails:
            return True
        m = NOREPLY_RE.match(e)
        if m and m.group("login").lower() == self.login.lower():
            return True
        return allow_name and (name or "").strip().lower() in self.names

    def fingerprint(self) -> str:
        blob = "|".join(sorted(self.emails)) + "#" + "|".join(sorted(self.names))
        return hashlib.sha1(blob.encode()).hexdigest()[:12]


def build_identity(login: str, profile: dict[str, Any], aliases: list[str],
                   learned_emails: set[str], learned_names: set[str]) -> Identity:
    ident = Identity(login=login)
    for v in [login, profile.get("name"), profile.get("email"), *aliases,
              *learned_emails, *learned_names]:
        ident.add(v)
    return ident
