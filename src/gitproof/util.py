from __future__ import annotations

from datetime import UTC, datetime


def parse_dt(value: str) -> datetime:
    """Parse an ISO-8601 timestamp into an aware UTC datetime."""
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def now() -> datetime:
    return datetime.now(UTC)


def month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def fmt_month(value: str | None) -> str:
    return "n/a" if not value else parse_dt(value).strftime("%b %Y")


def fmt_date(value: str | None) -> str:
    return "n/a" if not value else parse_dt(value).strftime("%Y-%m-%d")


def fmt_int(n: float | None) -> str:
    return "n/a" if n is None else f"{int(n):,}"


def months_between(a: datetime, b: datetime) -> float:
    return max(0.0, (b - a).total_seconds() / (86400 * 30.4375))


def plural(n: int, singular: str, plural_form: str | None = None) -> str:
    """'1 repository', '2 repositories'."""
    return f"{n:,} {singular if n == 1 else (plural_form or singular + 's')}"


def clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 3].rstrip() + "..."


def mask_email(email: str) -> str:
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    return (local[:1] + "***@" + domain) if local else "***@" + domain
