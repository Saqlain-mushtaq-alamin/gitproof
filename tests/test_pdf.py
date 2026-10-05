from __future__ import annotations

import io
import shutil
import subprocess

import pytest
from conftest import make_transport
from rich.console import Console
from typer.testing import CliRunner

from gitproof.cli import app
from gitproof.config import Config
from gitproof.pipeline import AnalyzeOptions, analyze_user
from gitproof.render import html_report, pdf
from gitproof.render.data import load_report

runner = CliRunner()
HAVE_WEASY = pdf.weasyprint_available()
HAVE_BROWSER = pdf.find_browser() is not None


@pytest.fixture()
def data(gp_home, fixture_root):
    opts = AnalyzeOptions(clone_base=f"file://{fixture_root}", transport=make_transport())
    analyze_user("alice", Config(), opts, Console(file=io.StringIO()))
    return load_report("alice")


def pages(path) -> int:
    out = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, check=False).stdout
    return int(next(l for l in out.splitlines() if l.startswith("Pages:")).split()[1])


def test_html_contains_all_sections_and_real_links(data):
    html = html_report.build_html(data)
    for marker in ["Professional summary", "Technical skills", "GitHub activity", "Project portfolio",
                   "Project-by-project analysis", "Contribution timeline", "Technology usage",
                   "Open source contributions", "Major development milestones", "Evidence of work",
                   "GitHub verification links", "Methodology and limitations"]:
        assert marker in html, marker
    assert "https://github.com/alice/demo/commit/" in html
    assert "github.com/demo/" not in html


def test_html_escapes_untrusted_text(data):
    data.profile["bio"] = "<script>alert(1)</script> & co"
    data.repos[0]["purpose"] = "<img src=x onerror=alert(2)>"
    data.repos[0]["key_commits"][0]["subject"] = "</td><b>boom</b>"
    html = html_report.build_html(data)
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html
    assert "<img src=x" not in html
    assert "<b>boom</b>" not in html


def test_summary_layout_is_short_and_singular_wording(data):
    html = html_report.build_html(data, layout="summary")
    assert "Project-by-project analysis" not in html and "Top projects" in html
    assert "project with commits" in html and "projects with commits" not in html
    assert "1 languages" not in html


def test_unknown_layout_rejected(data):
    with pytest.raises(ValueError):
        html_report.build_html(data, layout="poster")


@pytest.mark.skipif(not HAVE_WEASY, reason="weasyprint not installed")
def test_weasyprint_pdf(data, tmp_path):
    out = tmp_path / "r.pdf"
    assert pdf.html_to_pdf(html_report.build_html(data), out, "weasyprint") == "weasyprint"
    assert out.read_bytes().startswith(b"%PDF")
    one = tmp_path / "s.pdf"
    pdf.html_to_pdf(html_report.build_html(data, layout="summary"), one, "weasyprint")
    if shutil.which("pdfinfo"):
        assert pages(one) == 1 and pages(out) >= 3


@pytest.mark.skipif(not HAVE_BROWSER, reason="no Chromium-family browser available")
def test_browser_pdf(data, tmp_path):
    out = tmp_path / "b.pdf"
    assert pdf.html_to_pdf(html_report.build_html(data, layout="summary"), out, "browser") == "browser"
    assert out.read_bytes().startswith(b"%PDF")
    if shutil.which("pdfinfo"):
        assert pages(out) == 1


def test_pdf_fallback_message_when_no_engine(monkeypatch, tmp_path):
    monkeypatch.setattr(pdf, "weasyprint_available", lambda: False)
    monkeypatch.setattr(pdf, "find_browser", lambda: None)
    with pytest.raises(pdf.PdfError) as exc:
        pdf.html_to_pdf("<p>x</p>", tmp_path / "x.pdf")
    msg = str(exc.value)
    assert "gitproof[pdf]" in msg and "GITPROOF_BROWSER" in msg and "--format html" in msg


def test_cli_export_html_pdf(data, tmp_path):
    h = tmp_path / "r.html"
    assert runner.invoke(app, ["export", "alice", "-f", "html", "-o", str(h)]).exit_code == 0
    assert h.read_text().startswith("<!doctype html>")
    if HAVE_WEASY or HAVE_BROWSER:
        p = tmp_path / "r.pdf"
        res = runner.invoke(app, ["export", "alice", "-f", "pdf", "--layout", "summary", "-o", str(p)])
        assert res.exit_code == 0 and p.read_bytes().startswith(b"%PDF")
    bad = runner.invoke(app, ["export", "alice", "-f", "pdf", "--layout", "poster"])
    assert bad.exit_code == 1 and "Unknown layout" in bad.output
    bad = runner.invoke(app, ["export", "alice", "-f", "pdf", "--engine", "magic"])
    assert bad.exit_code == 1
