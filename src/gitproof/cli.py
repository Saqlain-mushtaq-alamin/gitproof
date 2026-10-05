import json
import shutil
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from . import __version__
from .ai import service as ai_service
from .ai.base import AIError, estimate_tokens
from .ai.providers import make_provider
from .collect.github_api import GitHubError
from .config import Config, home_dir, resolve_token
from .db import Store, db_path
from .pipeline import AnalyzeOptions, UserNotFound, analyze_user
from .render import dashboard, html_report, pdf, proof, report
from .render.data import NoDataError, load_report

app = typer.Typer(
    add_completion=False, no_args_is_help=True,
    help="gitproof - turn a GitHub username into an evidence-backed proof-of-work report.",
)
cache_app = typer.Typer(help="Manage cached data.", no_args_is_help=True)
app.add_typer(cache_app, name="cache")


def _fail(console: Console, message: str, code: int = 1) -> "typer.Exit":
    console.print(f"[bold red]Error:[/bold red] {message}")
    return typer.Exit(code)


def _resolve_user(console: Console, username: str | None) -> str:
    cfg = Config.load()
    login = username or cfg.last_user
    if not login:
        raise _fail(console, "No username given and nothing analyzed yet. "
                             "Run: gitproof analyze <username>")
    return login


def _console(no_color: bool = False, width: int | None = None) -> Console:
    # Legacy consoles (cp1252, ascii) cannot encode every character found in repo names,
    # commit messages or READMEs; replace instead of crashing mid-render.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    return Console(no_color=no_color, width=width, highlight=False)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"gitproof {__version__}")
        raise typer.Exit()



def _load_ai(login: str, data) -> dict:
    """Stored AI output that is still valid for the current analysis."""
    store = Store(login)
    try:
        return ai_service.load_ai(store, data)
    finally:
        store.close()


def _provider(console: Console, cfg: Config, name: str | None, model: str | None):
    name = (name or cfg.ai_provider or "ollama").lower()
    if name == "claude":
        model = model or cfg.claude_model
    else:
        model = model or cfg.ai_model
    try:
        return make_provider(name, model=model, host=cfg.ollama_host)
    except AIError as exc:
        raise _fail(console, str(exc))


def _confirm_cloud(console: Console, cfg: Config, provider, yes: bool, what: str, tokens: int) -> None:
    """Claude is opt-in: explain exactly what leaves the machine and ask once."""
    if not provider.is_cloud:
        return
    console.print(Panel(
        f"[bold]This sends data to Anthropic's API[/bold] (model {provider.model}).\n"
        f"What is sent: {what}\n"
        "It is built from derived metadata only: repository names and descriptions, one-sentence "
        "purposes, technology names, commit subjects, pull-request titles, release tags and counts. "
        "Source code, file contents and email addresses are never sent.\n"
        f"Estimated size: about {tokens:,} input tokens. API usage is billed separately from any "
        "claude.ai subscription.", title="Cloud AI", border_style="yellow"))
    if cfg.claude_consent or yes:
        return
    try:
        ok = typer.confirm("Send this to Anthropic?", default=False)
    except typer.Abort:
        ok = False
    if not ok:
        raise _fail(console, "Cancelled. Nothing was sent. (Use --provider ollama to stay fully local.)")
    cfg.claude_consent = True
    cfg.save()
    console.print("[dim]Consent saved; reset it with: gitproof config --reset-ai-consent[/dim]")


def _print_ai(console: Console, title: str, res: dict) -> None:
    from rich.console import Group
    from rich.text import Text
    if not res.get("text"):
        console.print(Panel(Text("No statement survived evidence checking.", style="yellow"), title=title))
        return
    ids = "  ".join(e["id"] for e in res.get("evidence", []))
    note = f"{res['provider']} / {res['model']}" + (" (cached)" if res.get("cached") else "")
    body = Group(Text(res["text"]), Text(f"\nEvidence: {ids}", style="dim"),
                 Text(f"{note}; {len(res.get('dropped', []))} of {res.get('proposed', 0)} proposed "
                      "statements were dropped by the evidence check.", style="dim italic"))
    console.print(Panel(body, title=title, border_style="magenta"))


@app.callback()
def main(version: bool = typer.Option(False, "--version", callback=_version, is_eager=True,
                                      help="Show version and exit.")) -> None:
    pass


@app.command()
def analyze(
    username: str = typer.Argument(..., help="GitHub username to analyze."),
    token: str | None = typer.Option(None, "--token", help="GitHub token (or set GITHUB_TOKEN)."),
    include_private: bool = typer.Option(False, "--include-private",
                                         help="Include your private repos (needs a token for that user)."),
    since: str | None = typer.Option(None, "--since", help="Only analyze commits since YYYY-MM-DD."),
    exclude_forks: bool = typer.Option(False, "--exclude-forks", help="Skip forked repositories."),
    refresh: bool = typer.Option(False, "--refresh", help="Re-mine every repository."),
    repos: str | None = typer.Option(None, "--repos", help="Comma-separated repository names."),
    max_repos: int | None = typer.Option(None, "--max-repos", help="Analyze at most N repositories."),
    no_blame: bool = typer.Option(False, "--no-blame", help="Skip surviving-line measurement (faster)."),
    alias: list[str] | None = typer.Option(None, "--alias", help="Extra git email/name that is you."),
    no_dashboard: bool = typer.Option(False, "--no-dashboard", help="Do not print the dashboard afterwards."),
) -> None:
    """Collect GitHub data, mine git history and analyze it. Results are cached locally."""
    console = _console()
    cfg = Config.load()
    opts = AnalyzeOptions(
        token=resolve_token(token, cfg), include_private=include_private, since=since,
        exclude_forks=exclude_forks, refresh=refresh,
        repos=[r.strip() for r in repos.split(",") if r.strip()] if repos else None,
        max_repos=max_repos, blame=not no_blame, aliases=list(alias or []),
    )
    if not opts.token:
        console.print("[yellow]No GitHub token found.[/yellow] Unauthenticated requests are limited to "
                      "60/hour; set GITHUB_TOKEN or run [bold]gitproof config --token ...[/bold] "
                      "for best results.\n")
    try:
        result = analyze_user(username, cfg, opts, console)
    except UserNotFound as exc:
        raise _fail(console, str(exc))
    except GitHubError as exc:
        raise _fail(console, str(exc))
    except KeyboardInterrupt:
        raise _fail(console, "Interrupted. Progress is cached; run the command again to resume.", 130)

    cfg = Config.load()
    cfg.last_user = result.login
    cfg.save()
    console.print(f"[green]Done.[/green] {result.with_work} repositories with your commits, "
                  f"{result.skipped} skipped, {result.errors} errors "
                  f"({result.api_requests} API requests, {result.cache_hits} served from cache).")
    for w in result.warnings:
        console.print(f"[yellow]•[/yellow] {w}")
    if not no_dashboard:
        console.print()
        try:
            dashboard.render_overview(console, load_report(result.login))
        except NoDataError as exc:
            raise _fail(console, str(exc))


@app.command()
def show(
    username: str | None = typer.Argument(None, help="GitHub username (default: last analyzed)."),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Show one repository in detail."),
    all_repos: bool = typer.Option(False, "--all", help="List every repository."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colors."),
    width: int | None = typer.Option(None, "--width", help="Force terminal width."),
) -> None:
    """Show the terminal dashboard for an analyzed user."""
    console = _console(no_color, width)
    login = _resolve_user(console, username)
    try:
        data = load_report(login)
    except NoDataError as exc:
        raise _fail(console, str(exc))
    ai = _load_ai(data.profile["login"], data)
    if ai.get("stale"):
        console.print(f"[yellow]AI summaries are out of date for: {', '.join(ai['stale'])}. "
                      "Run gitproof summarize to refresh.[/yellow]")
    if repo:
        found = data.find_repo(repo)
        if not found:
            names = ", ".join(r["name"] for r in data.repos[:15])
            raise _fail(console, f"'{repo}' is not in the analysis. Available: {names}")
        dashboard.render_repo(console, found, data.profile["login"], ai)
    else:
        dashboard.render_overview(console, data, show_all=all_repos, ai=ai)


@app.command()
def export(
    username: str | None = typer.Argument(None, help="GitHub username (default: last analyzed)."),
    fmt: str = typer.Option("md", "--format", "-f", help="md, json, html or pdf."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Output file path."),
    top: int | None = typer.Option(None, "--top", help="Detail only the top N projects."),
    layout: str = typer.Option("full", "--layout", help="PDF/HTML layout: full or summary (one page)."),
    engine: str = typer.Option("auto", "--engine", help="PDF engine: auto, weasyprint or browser."),
    with_ai: bool = typer.Option(True, "--ai/--no-ai", help="Include stored AI summaries (default)."),
    with_verify: bool = typer.Option(True, "--verify/--no-verify", help="Add a SHA-256 data fingerprint."),
) -> None:
    """Export the proof-of-work report to Markdown, JSON, HTML or PDF."""
    console = _console()
    fmt = fmt.lower()
    if fmt not in {"md", "json", "html", "pdf"}:
        raise _fail(console, f"Unknown format '{fmt}'. Use md, json, html or pdf.")
    if layout not in html_report.LAYOUTS:
        raise _fail(console, f"Unknown layout '{layout}'. Use full or summary.")
    if engine not in {"auto", "weasyprint", "browser"}:
        raise _fail(console, f"Unknown engine '{engine}'. Use auto, weasyprint or browser.")
    login = _resolve_user(console, username)
    try:
        data = load_report(login)
    except NoDataError as exc:
        raise _fail(console, str(exc))
    ai = _load_ai(data.profile["login"], data) if with_ai else None
    ver = proof.verification(data) if with_verify else None
    suffix = "" if layout == "full" else "-summary"
    target = out or Path(f"{data.profile['login']}-proof-of-work{suffix}.{fmt}")
    if fmt == "md":
        target.write_text(report.build_markdown(data, top=top, ai=ai, verification=ver), encoding="utf-8")
    elif fmt == "json":
        target.write_text(report.build_json(data, ai=ai, verification=ver), encoding="utf-8")
    else:
        html = html_report.build_html(data, layout=layout, top=top, verification=ver, ai=ai)
        if fmt == "html":
            target.write_text(html, encoding="utf-8")
        else:
            try:
                used = pdf.html_to_pdf(html, target, engine)
            except pdf.PdfError as exc:
                raise _fail(console, str(exc))
            console.print(f"[dim]PDF rendered with {used}[/dim]")
    console.print(f"[green]Wrote[/green] {target}")


@app.command()
def config(
    token: str | None = typer.Option(None, "--token", help="Save a GitHub token."),
    alias: list[str] | None = typer.Option(None, "--alias", help="Add a git email/name that is you."),
    clear_aliases: bool = typer.Option(False, "--clear-aliases", help="Remove saved aliases."),
    show_config: bool = typer.Option(False, "--show", help="Print current settings."),
    ai_provider: str | None = typer.Option(None, "--ai-provider", help="Default AI provider: ollama or claude."),
    ai_model: str | None = typer.Option(None, "--ai-model", help="Default Ollama model."),
    claude_model: str | None = typer.Option(None, "--claude-model", help="Default Claude model."),
    ollama_host: str | None = typer.Option(None, "--ollama-host", help="Ollama URL (default localhost:11434)."),
    reset_ai_consent: bool = typer.Option(False, "--reset-ai-consent", help="Ask again before using Claude."),
) -> None:
    """View or change settings stored in ~/.gitproof/config.toml."""
    console = _console()
    cfg = Config.load()
    changed = False
    if token:
        cfg.token, changed = token, True
    if ai_provider:
        if ai_provider.lower() not in {"ollama", "claude"}:
            raise _fail(console, "AI provider must be ollama or claude.")
        cfg.ai_provider, changed = ai_provider.lower(), True
    for attr, val in (("ai_model", ai_model), ("claude_model", claude_model), ("ollama_host", ollama_host)):
        if val:
            setattr(cfg, attr, val)
            changed = True
    if reset_ai_consent:
        cfg.claude_consent, changed = False, True
    if clear_aliases:
        cfg.aliases, changed = [], True
    for a in alias or []:
        if a not in cfg.aliases:
            cfg.aliases.append(a)
            changed = True
    if changed:
        cfg.save()
        console.print("[green]Saved.[/green] Re-run 'gitproof analyze' to apply new aliases.")
    if show_config or not changed:
        shown_token = "set" if cfg.token else "not set"
        console.print(Panel(
            f"token: {shown_token}\naliases: {', '.join(cfg.aliases) or 'none'}\n"
            f"last user: {cfg.last_user or 'none'}\nmax repo size: {cfg.max_repo_size_mb} MB\n"
            f"AI provider: {cfg.ai_provider} (ollama model: {cfg.ai_model or 'auto'}, "
            f"claude model: {cfg.claude_model or 'default'}); cloud consent given: {cfg.claude_consent}\n"
            f"data folder: {home_dir()}", title="gitproof settings"))


@cache_app.command("clear")
def cache_clear(
    username: str | None = typer.Argument(None, help="Only clear this user (default: everything)."),
    keep_clones: bool = typer.Option(False, "--keep-clones", help="Keep cloned repositories."),
) -> None:
    """Delete cached analysis data and cloned repositories."""
    console = _console()
    if username:
        path = db_path(username)
        for p in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
            p.unlink(missing_ok=True)
    else:
        shutil.rmtree(home_dir() / "data", ignore_errors=True)
    if not keep_clones:
        shutil.rmtree(home_dir() / "clones", ignore_errors=True)
    console.print("[green]Cache cleared.[/green]")


@app.command()
def summarize(
    username: str | None = typer.Argument(None, help="GitHub username (default: last analyzed)."),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Summarize one repository only."),
    provider: str | None = typer.Option(None, "--provider", "-p", help="ollama (local) or claude (cloud)."),
    model: str | None = typer.Option(None, "--model", "-m", help="Model name."),
    top: int = typer.Option(8, "--top", help="How many top repositories to summarize."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the cloud confirmation prompt."),
    refresh: bool = typer.Option(False, "--refresh", help="Ignore cached summaries."),
) -> None:
    """Optional: write evidence-checked AI summaries (local Ollama by default, Claude opt-in)."""
    console = _console()
    cfg = Config.load()
    login = _resolve_user(console, username)
    try:
        data = load_report(login)
    except NoDataError as exc:
        raise _fail(console, str(exc))
    if repo:
        found = data.find_repo(repo)
        if not found:
            raise _fail(console, f"'{repo}' is not in the analysis.")
        repos = [found]
    else:
        repos = data.repos[:top]
    if not repos:
        raise _fail(console, "No repositories with attributable commits to summarize.")
    prov = _provider(console, cfg, provider, model)
    est = ai_service.estimate_summary_tokens(data, repos, include_profile=not repo)
    _confirm_cloud(console, cfg, prov, yes, f"{len(repos)} repository digest(s)"
                   + ("" if repo else " and a profile digest"), est)
    console.print(f"Using [bold]{prov.name}[/bold] / {prov.model}")
    store = Store(data.profile["login"])
    try:
        results: dict[str, dict] = {}
        try:
            for r in repos:
                with console.status(f"Summarizing {r['name']}..."):
                    res = ai_service.summarize_repo(store, r, prov, refresh)
                results[r["full_name"]] = res
                _print_ai(console, f"{r['name']}", res)
            if not repo:
                existing = ai_service.load_ai(store, data)
                merged = {**existing["repos"], **results}
                with console.status("Summarizing profile..."):
                    res = ai_service.summarize_profile(store, data, prov, merged, refresh)
                _print_ai(console, f"{data.profile['name']} (profile)", res)
        except AIError as exc:
            raise _fail(console, str(exc))
    finally:
        store.close()
    console.print("[green]Saved.[/green] Summaries appear in 'gitproof show' and in exports "
                  "(use --no-ai to leave them out).")


@app.command()
def ask(
    question: str = typer.Argument(..., help="A question about the analyzed GitHub account."),
    username: str | None = typer.Option(None, "--user", "-u", help="GitHub username (default: last analyzed)."),
    provider: str | None = typer.Option(None, "--provider", "-p", help="ollama (local) or claude (cloud)."),
    model: str | None = typer.Option(None, "--model", "-m", help="Model name."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the cloud confirmation prompt."),
) -> None:
    """Optional: ask a question; answers cite commits/PRs and say so when there is no evidence."""
    console = _console()
    cfg = Config.load()
    login = _resolve_user(console, username)
    try:
        data = load_report(login)
    except NoDataError as exc:
        raise _fail(console, str(exc))
    store = Store(data.profile["login"])
    try:
        corpus = ai_service.build_corpus(data, store)
        prompt, hits = ai_service.ask_payload_preview(question, corpus, data)
        prov = None
        if hits:
            prov = _provider(console, cfg, provider, model)
            _confirm_cloud(console, cfg, prov, yes, f"your question plus {hits} matching facts",
                           estimate_tokens(prompt) + 150)
        try:
            res = ai_service.answer_question(store, data, prov, question, corpus)
        except AIError as exc:
            raise _fail(console, str(exc))
    finally:
        store.close()
    if not res["grounded"]:
        console.print(Panel(res["answer"], title="Answer", border_style="yellow"))
        if res["asked_model"] and res.get("dropped"):
            console.print(f"[dim]{len(res['dropped'])} statement(s) from the model were rejected "
                          "because they were not supported by the data.[/dim]")
        return
    _print_ai(console, "Answer", {**res, "text": res["answer"], "proposed": len(res["claims"]) + len(res["dropped"])})
    for e in res["evidence"]:
        console.print(f"  [yellow]{e['id']}[/yellow] {e['label']}" + (f"  [blue]{e['url']}[/blue]" if e.get("url") else ""))


if __name__ == "__main__":
    sys.exit(app())


@app.command()
def verify(
    file: Path = typer.Argument(..., help="A JSON report exported by gitproof."),
) -> None:
    """Check that an exported JSON report's data still matches its SHA-256 fingerprint.

    This detects edits to the data after export. It does not prove who made the report;
    for that, re-run `gitproof analyze` yourself and compare the numbers.
    """
    console = _console()
    try:
        text = file.read_text(encoding="utf-8")
        stored = json.loads(text).get("fingerprint")
        actual = proof.fingerprint_json(text)
    except (OSError, ValueError, KeyError) as exc:
        raise _fail(console, f"Cannot read report: {exc}")
    if not stored:
        raise _fail(console, "This report has no fingerprint (exported with --no-verify).")
    if stored == actual:
        console.print(f"[green]OK[/green] data matches fingerprint {actual[:16]}...")
    else:
        console.print("[red]MISMATCH[/red] the report data was changed after export.")
        raise typer.Exit(1)


@app.command()
def bullets(
    username: str | None = typer.Argument(None, help="GitHub username (default: last analyzed)."),
    count: int = typer.Option(6, "--count", "-n", help="Number of project bullets."),
    linkedin: bool = typer.Option(False, "--linkedin", help="Print a short profile summary instead."),
) -> None:
    """Print resume bullets built only from measured numbers (no AI)."""
    console = _console()
    login = _resolve_user(console, username)
    try:
        data = load_report(login)
    except NoDataError as exc:
        raise _fail(console, str(exc))
    if linkedin:
        console.print(proof.linkedin_summary(data), markup=False, highlight=False)
        return
    for line in proof.resume_bullets(data, count):
        console.print(f"- {line}", markup=False, highlight=False)
