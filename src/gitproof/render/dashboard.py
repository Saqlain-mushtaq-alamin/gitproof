"""Terminal dashboard rendered with Rich."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from rich import box
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..util import clip, fmt_date, fmt_int, fmt_month, now, plural
from .data import ReportData

FRAMEWORK_CATEGORIES = {"Framework", "ML/AI", "Library", "Platform", "Security"}


@dataclass
class Glyphs:
    full: str
    empty: str
    spark: str
    heat: list[str]
    ok: str
    no: str
    strong: str
    inferred: str
    arrow: str
    tee: str
    elbow: str
    qfull: str
    qempty: str
    dot: str
    ell: str


def glyphs(console: Console) -> Glyphs:
    if "utf" in (console.encoding or "").lower():
        return Glyphs("█", "░", "▁▂▃▄▅▆▇█", ["·", "░", "▒", "▓", "█"], "✓", "✗", "●", "◐", "→",
                      "├── ", "└── ", "▰", "▱", "·", "…")
    return Glyphs("#", ".", " .:-=+*#", [".", ":", "*", "#", "@"], "[x]", "[ ]", "*", "o", "->",
                  "|-- ", "`-- ", "#", ".", "|", "...")


def bar(share: float, width: int, g: Glyphs) -> str:
    n = max(0, min(width, round(share * width)))
    return g.full * n + g.empty * (width - n)


def _stack(repo: dict[str, Any], g: Glyphs, limit: int = 3) -> str:
    parts = [repo["primary_language"]] if repo.get("primary_language") else []
    parts += [s["name"] for s in repo["skills"]
              if s["category"] in FRAMEWORK_CATEGORIES][: limit - len(parts)]
    return f" {g.dot} ".join(parts) or "n/a"


def _lines(repo: dict[str, Any]) -> int:
    c = repo["contribution"]
    return c["surviving_lines"] if c["surviving_lines"] is not None else c["additions"]


def _two_col(console: Console, left: RenderableType, right: RenderableType) -> RenderableType:
    if console.width < 100:
        return Group(left, right)
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)
    grid.add_row(left, right)
    return grid


def _header(p: dict[str, Any], g: Glyphs) -> Panel:
    body = Text(p["name"].upper(), style="bold bright_white")
    body.append("\n")
    if p["focus"]:
        body.append("Primary focus (inferred): ", style="dim")
        body.append(f" {g.dot} ".join(p["focus"]), style="bold cyan")
        body.append("\n")
    body.append(p["url"].replace("https://", ""), style="underline blue")
    if p.get("bio"):
        body.append("\n" + clip(p["bio"], 110), style="italic dim")
    return Panel(body, title=f"[bold]GITPROOF {g.dot} Developer Proof of Work[/bold]", box=box.DOUBLE,
                 border_style="cyan", padding=(1, 2))


def _counters(p: dict[str, Any], g: Glyphs) -> Panel:
    t, pr, iss = p["totals"], p["prs"], p["issues"]
    lines_txt = f"{fmt_int(t['lines_changed'])} lines changed (noise-filtered)"
    if t["surviving_lines"] is not None:
        lines_txt += f", {fmt_int(t['surviving_lines'])} still in code"
    rows = [
        (plural(t["repos_total"], "repository", "repositories"), f"{t['repos_with_work']} with your commits"),
        (plural(t["commits"], "commit"), plural(t["active_days"], "active day")),
        (lines_txt, ""),
        (plural(t["active_projects"], "active project"), "commits in last 180 days"),
        (plural(t["languages_count"], "programming language"), ""),
        (plural(pr["authored"], "pull request"),
         f"{pr['merged']} merged, {pr['external_merged']} to others' repos"),
        (plural(iss["authored"], "issue"), plural(pr["reviews"], "review") if pr["reviews"] is not None else ""),
        (f"{t['years_active']} years of activity", f"longest streak {plural(t['longest_streak'], 'day')}"),
    ]
    text = Text()
    text.append("GitHub\n", style="bold")
    for i, (main, note) in enumerate(rows):
        text.append(g.elbow if i == len(rows) - 1 else g.tee, style="dim")
        text.append(main, style="bold green")
        if note:
            text.append(f"  {note}", style="dim")
        text.append("\n")
    return Panel(text, title="Overview", border_style="green", box=box.ROUNDED)


def _languages(p: dict[str, Any], g: Glyphs) -> Panel:
    table = Table.grid(padding=(0, 1))
    table.add_column(width=14)
    table.add_column()
    table.add_column(justify="right")
    for lang in p["languages"][:8]:
        table.add_row(lang["name"], Text(bar(lang["share"], 22, g), style="magenta"),
                      f"{lang['share'] * 100:4.1f}%")
    if not p["languages"]:
        table.add_row("n/a", "", "")
    basis = {"surviving": "lines still present in the code", "added": "lines added",
             "mixed": "surviving lines where available, else lines added"}[p["languages_basis"]]
    return Panel(Group(table, Text(f"\nby {basis}", style="dim")), title="Languages",
                 border_style="magenta", box=box.ROUNDED)


def _spark(values: list[int], g: Glyphs) -> str:
    peak = max(values) if values and max(values) else 1
    top = len(g.spark) - 1
    return "".join(g.spark[0] if v == 0 else g.spark[max(1, round(v / peak * top))] for v in values)


def _month_keys(end, count: int) -> list[str]:
    keys, y, m = [], end.year, end.month
    for _ in range(count):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(keys))


def _heatmap(p: dict[str, Any], g: Glyphs, weeks: int = 26) -> Text:
    daily = p["daily"]
    today = now().date()
    start = today - timedelta(days=today.weekday() + 7 * (weeks - 1))
    styles = ["dim", "green4", "green3", "green", "bold bright_green"]
    cells: dict[tuple[int, int], int] = {}
    for offset in range((today - start).days + 1):
        day = start + timedelta(days=offset)
        n = daily.get(day.isoformat(), 0)
        cells[(day.weekday(), offset // 7)] = 0 if n == 0 else 1 if n < 2 else 2 if n < 4 else 3 if n < 7 else 4
    labels = {0: "Mon", 2: "Wed", 4: "Fri"}
    months = [" "] * (weeks * 2 + 4)
    last_month = None
    for col in range(weeks):
        d = start + timedelta(days=col * 7)
        if d.month != last_month:
            if all(c == " " for c in months[col * 2: col * 2 + 4]):
                for i, ch in enumerate(d.strftime("%b")):
                    months[col * 2 + i] = ch
            last_month = d.month
    text = Text("    " + "".join(months).rstrip() + "\n", style="dim")
    for row in range(7):
        text.append(f"{labels.get(row, ''):<4}", style="dim")
        for col in range(weeks):
            level = cells.get((row, col))
            if level is None:
                text.append("  ")
            else:
                text.append(g.heat[level] * 2 if level else g.heat[0] + " ", style=styles[level])
        text.append("\n")
    return text


def _activity(p: dict[str, Any], g: Glyphs) -> Panel:
    monthly = p["monthly"]
    keys = _month_keys(now(), 36)
    spark = Text(_spark([monthly.get(k, 0) for k in keys], g), style="cyan")
    caption = Text(f"{keys[0]} {g.arrow} {keys[-1]}", style="dim")
    if monthly:
        peak_key = max(monthly, key=monthly.get)
        caption.append(f"   peak: {monthly[peak_key]} commits in {peak_key}", style="dim")
    yearly = "  ".join(f"{y}: {fmt_int(n)}" for y, n in p["yearly"].items())
    body = Group(Text("Commits per month (last 36 months)", style="bold"), spark, caption,
                 Text(""), Text("Daily activity (last 26 weeks)", style="bold"), _heatmap(p, g),
                 Text(f"Commits per year  {yearly}", style="dim"))
    return Panel(body, title="Activity", border_style="cyan", box=box.ROUNDED)


def _skills(p: dict[str, Any], g: Glyphs, limit: int = 12) -> Panel:
    table = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False)
    for col, kw in [("Skill", {}), ("Category", {}), ("First seen", {}),
                    ("Repos", {"justify": "right"}), ("Commits", {"justify": "right"}),
                    ("Evidence", {})]:
        table.add_column(col, header_style="bold cyan", **kw)
    for s in p["skills"][:limit]:
        strong = s["confidence"] == "strong"
        mark = Text(f"{g.strong} strong" if strong else f"{g.inferred} inferred",
                    style="green" if strong else "yellow")
        table.add_row(s["name"], s["category"], fmt_month(s["first_seen"]), str(len(s["repos"])),
                      fmt_int(s["commits"]), mark)
    note = Text(f"{g.strong} strong = you changed files of this kind    "
                f"{g.inferred} inferred = in a dependency manifest you edited", style="dim")
    return Panel(Group(table, note), title="Skills with evidence", border_style="yellow",
                 box=box.ROUNDED)


def _projects(data: ReportData, g: Glyphs, show_all: bool, top: int) -> Panel:
    table = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Repository", style="bold")
    table.add_column("Period")
    table.add_column("Commits", justify="right")
    table.add_column("Lines", justify="right")
    table.add_column("Stack")
    table.add_column("Quality")
    repos = data.repos if show_all else data.repos[:top]
    for i, r in enumerate(repos, 1):
        q = r["quality"]["score"]
        filled = round(q / 20)
        quality = Text(g.qfull * filled + g.qempty * (5 - filled) + f" {q}",
                       style="green" if q >= 60 else "yellow" if q >= 35 else "red")
        period = f"{fmt_month(r['period']['first'])} {g.arrow} {fmt_month(r['period']['last'])}"
        table.add_row(str(i), r["name"] + (" (fork)" if r["is_fork"] else ""), period,
                      fmt_int(r["contribution"]["commits"]), fmt_int(_lines(r)), _stack(r, g), quality)
    foot = []
    if len(data.repos) > len(repos):
        foot.append(f"{g.ell} and {len(data.repos) - len(repos)} more (use --all)")
    if data.others:
        foot.append(f"{len(data.others)} repositories had no attributable commits or were skipped")
    parts: list[RenderableType] = [table]
    if foot:
        parts.append(Text("  ".join(foot), style="dim"))
    return Panel(Group(*parts), title="Projects (ranked by evidence of work)",
                 border_style="blue", box=box.ROUNDED)


def _ai_panel(res: dict[str, Any] | None, g: Glyphs, title: str) -> Panel | None:
    if not res or not res.get("text"):
        return None
    ids = "  ".join(e["id"] for e in res.get("evidence", []))
    body = Group(Text(res["text"]), Text(f"\nEvidence: {ids}", style="dim"),
                 Text(f"AI-generated by {res['provider']} / {res['model']}; unsupported statements "
                      f"were removed ({len(res.get('dropped', []))} dropped).", style="dim italic"))
    return Panel(body, title=title, border_style="magenta", box=box.ROUNDED)


def render_overview(console: Console, data: ReportData, show_all: bool = False,
                    top: int = 15, ai: dict[str, Any] | None = None) -> None:
    g = glyphs(console)
    p = data.profile
    console.print(_header(p, g))
    panel = _ai_panel((ai or {}).get("profile"), g, "AI summary (evidence-checked)")
    if panel:
        console.print(panel)
    console.print(_two_col(console, _counters(p, g), _languages(p, g)))
    console.print(_activity(p, g))
    console.print(_skills(p, g))
    console.print(_projects(data, g, show_all, top))
    if p["warnings"]:
        console.print(Panel("\n".join(f"{g.dot} {w}" for w in p["warnings"]), title="Notes",
                            border_style="yellow", box=box.ROUNDED))
    sep = f"  {g.dot}  "
    console.print(Text(f"Generated {fmt_date(p['generated_at'])}{sep}gitproof show --repo <name> "
                       f"for project details{sep}gitproof export --format md for the full report",
                       style="dim"))


def _kv_grid(rows: list[tuple[str, str]]) -> Table:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", no_wrap=True)
    grid.add_column()
    for k, v in rows:
        grid.add_row(k, v)
    return grid


def render_repo(console: Console, repo: dict[str, Any], login: str,
                ai: dict[str, Any] | None = None) -> None:
    g = glyphs(console)
    c, q, per = repo["contribution"], repo["quality"], repo["period"]

    head = Text(repo["name"], style="bold bright_white")
    if repo["is_fork"]:
        head.append("  (fork)", style="yellow")
    head.append("\n" + repo["url"].replace("https://", ""), style="underline blue")
    head.append("\n\n" + repo["purpose"], style="italic")
    console.print(Panel(head, title="[bold]Project[/bold]", box=box.DOUBLE, border_style="cyan",
                        padding=(1, 2)))

    panel = _ai_panel(((ai or {}).get("repos") or {}).get(repo["full_name"]), g,
                      "AI summary (evidence-checked)")
    if panel:
        console.print(panel)
    langs = ", ".join(f"{l['name']} {l['share'] * 100:.0f}%" for l in repo["languages"][:5]) or "n/a"
    stack = [s["name"] for s in repo["skills"] if s["category"] != "Language"][:8]
    tech = _kv_grid([
        ("Languages", langs), ("Frameworks/tools", ", ".join(stack) or "none detected"),
        ("Period", f"{fmt_month(per['first'])} {g.arrow} {fmt_month(per['last'])} ({per['months']} months)"),
        ("Last pushed", fmt_date(repo["pushed_at"])),
        ("Stars / forks", f"{repo['stars']} / {repo['forks']}"),
    ])
    share = f"{c['share'] * 100:.0f}%" if c["total_commits"] else "n/a"
    surv = "n/a (blame disabled)"
    if c["surviving_lines"] is not None:
        surv = f"{fmt_int(c['surviving_lines'])} of {fmt_int(c['total_lines'])} lines"
        if c["surviving_share"] is not None:
            surv += f" ({c['surviving_share'] * 100:.0f}%)"
        if c["blame_truncated"]:
            surv += f"  [sampled {c['blame_files']} largest files]"
    contrib = _kv_grid([
        ("Your commits", f"{fmt_int(c['commits'])} of {fmt_int(c['total_commits'])} ({share})"),
        ("Files modified", fmt_int(c["files_modified"])),
        ("Additions", f"+{fmt_int(c['additions'])}"), ("Deletions", f"-{fmt_int(c['deletions'])}"),
        ("Surviving lines", surv),
        ("Excluded as noise",
         f"{plural(c['ignored_files'], 'file change')}, {plural(c['bulk_commits'], 'bulk import commit')}"),
    ])
    console.print(_two_col(
        console, Panel(tech, title="Technology", border_style="magenta", box=box.ROUNDED),
        Panel(contrib, title="Your contribution", border_style="green", box=box.ROUNDED)))

    areas = Table.grid(padding=(0, 1))
    areas.add_column(width=22)
    areas.add_column()
    areas.add_column(justify="right")
    for a in repo["areas"][:8]:
        areas.add_row(a["area"], Text(bar(a["share"], 24, g), style="cyan"),
                      f"{a['share'] * 100:4.1f}%  {fmt_int(a['lines'])} lines")
    types = "  ".join(f"{k} {v}" for k, v in sorted(repo["commit_types"].items(), key=lambda kv: -kv[1]))
    console.print(Panel(Group(areas, Text(f"\nCommit types: {types}", style="dim")),
                        title="Major development areas", border_style="cyan", box=box.ROUNDED))

    phases = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False)
    phases.add_column("Phase", style="bold")
    phases.add_column("Period")
    phases.add_column("Commits", justify="right")
    phases.add_column("What happened")
    for ph in repo["phases"]:
        phases.add_row(f"Phase {ph['index']}",
                       f"{fmt_date(ph['start'])} {g.arrow} {fmt_date(ph['end'])}",
                       str(ph["commits"]), ph["label"])
    console.print(Panel(phases, title="Development timeline", border_style="blue", box=box.ROUNDED))

    ev = repo["evidence"]
    evidence = Text()
    for label, key in [("Commits", "commits"), ("Pull requests", "pull_requests"),
                       ("Releases", "releases"), ("Issues", "issues"),
                       ("Code changes", "code_changes"), ("Repository history", "history")]:
        evidence.append(f"{g.ok if ev[key] else g.no} {label}\n",
                        style="green" if ev[key] else "dim")
    qline = Text(bar(q["score"] / 100, 20, g) + f" {q['score']}/100\n", style="green")
    qline.append("  ".join(q["badges"]), style="dim")
    console.print(_two_col(
        console, Panel(evidence, title="Evidence", border_style="green", box=box.ROUNDED),
        Panel(qline, title="Project quality signals", border_style="yellow", box=box.ROUNDED)))

    keys = Table.grid(padding=(0, 2))
    keys.add_column(style="yellow", no_wrap=True)
    keys.add_column(style="dim", no_wrap=True)
    keys.add_column()
    for k in repo["key_commits"]:
        keys.add_row(k["sha"][:7], fmt_date(k["date"]), f"{k['reason']}: {clip(k['subject'], 70)}")
    console.print(Panel(keys, title="Key commits (evidence)", border_style="yellow", box=box.ROUNDED))

    if repo["authors"]:
        who = Table.grid(padding=(0, 2))
        who.add_column()
        who.add_column(justify="right")
        who.add_column()
        for a in repo["authors"][:6]:
            who.add_row(a["name"], str(a["commits"]),
                        Text("matched to you" if a["is_user"] else "other author",
                             style="green" if a["is_user"] else "dim"))
        console.print(Panel(
            Group(who, Text("\nWrong match? Add an alias: gitproof config --alias <email>", style="dim")),
            title="Commit attribution check", border_style="dim", box=box.ROUNDED))
