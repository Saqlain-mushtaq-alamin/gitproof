from __future__ import annotations

import io

from conftest import make_transport
from rich.console import Console
from typer.testing import CliRunner

from gitproof.cli import app
from gitproof.config import Config
from gitproof.pipeline import AnalyzeOptions, analyze_user

runner = CliRunner()


def seed(fixture_root):
    opts = AnalyzeOptions(clone_base=f"file://{fixture_root}", transport=make_transport())
    analyze_user("alice", Config(), opts, Console(file=io.StringIO()))


def test_show_export_roundtrip(gp_home, fixture_root, tmp_path):
    seed(fixture_root)
    res = runner.invoke(app, ["show", "alice", "--width", "110"])
    assert res.exit_code == 0 and "Developer Proof of Work" in res.output

    res = runner.invoke(app, ["show", "alice", "--repo", "demo", "--width", "110"])
    assert res.exit_code == 0 and "Development timeline" in res.output

    res = runner.invoke(app, ["show", "alice", "--repo", "nope"])
    assert res.exit_code == 1 and "not in the analysis" in res.output

    out = tmp_path / "r.md"
    res = runner.invoke(app, ["export", "alice", "--format", "md", "--out", str(out)])
    assert res.exit_code == 0 and out.read_text().startswith("# Developer Proof of Work: Alice Dev")

    js = tmp_path / "r.json"
    assert runner.invoke(app, ["export", "alice", "-f", "json", "-o", str(js)]).exit_code == 0
    assert '"login": "alice"' in js.read_text()

    assert runner.invoke(app, ["export", "alice", "-f", "docx"]).exit_code == 1


def test_show_without_data(gp_home):
    res = runner.invoke(app, ["show", "nobody"])
    assert res.exit_code == 1 and "gitproof analyze nobody" in res.output
    res = runner.invoke(app, ["show"])
    assert res.exit_code == 1 and "No username" in res.output


def test_config_and_cache(gp_home, fixture_root):
    res = runner.invoke(app, ["config", "--alias", "me@x.org", "--token", "secret"])
    assert res.exit_code == 0
    cfg = Config.load()
    assert cfg.aliases == ["me@x.org"] and cfg.token == "secret"
    res = runner.invoke(app, ["config", "--show"])
    assert "secret" not in res.output and "me@x.org" in res.output   # token is never printed
    seed(fixture_root)
    assert runner.invoke(app, ["cache", "clear", "alice"]).exit_code == 0
    assert runner.invoke(app, ["show", "alice"]).exit_code == 1


def test_ai_commands_need_an_analysis_first(gp_home):
    res = runner.invoke(app, ["summarize", "nobody"])
    assert res.exit_code == 1 and "gitproof analyze nobody" in res.output
    res = runner.invoke(app, ["ask", "anything?", "-u", "nobody"])
    assert res.exit_code == 1 and "gitproof analyze nobody" in res.output


def test_fingerprint_verify_and_bullets(gp_home, fixture_root, tmp_path):
    seed(fixture_root)
    analyzed_home = tmp_path
    r = runner
    out = analyzed_home / "r.json"
    assert r.invoke(app, ["export", "alice", "-f", "json", "-o", str(out)]).exit_code == 0
    assert "OK" in r.invoke(app, ["verify", str(out)]).output
    out.write_text(out.read_text().replace('"commits":', '"commitz":', 1))
    assert r.invoke(app, ["verify", str(out)]).exit_code != 0
    md = analyzed_home / "r.md"
    r.invoke(app, ["export", "alice", "-f", "md", "-o", str(md)])
    assert "Data fingerprint (SHA-256)" in md.read_text()
    b = r.invoke(app, ["bullets", "alice"])
    assert b.exit_code == 0 and b.output.startswith("- ")
    assert "Evidence:" in r.invoke(app, ["bullets", "alice", "--linkedin"]).output
