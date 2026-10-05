from __future__ import annotations

import io

import pytest
from conftest import make_transport
from rich.console import Console

from gitproof.config import Config
from gitproof.pipeline import AnalyzeOptions, UserNotFound, analyze_user
from gitproof.render import dashboard, report
from gitproof.render.data import load_report


def run(fixture_root, **kw):
    opts = AnalyzeOptions(clone_base=f"file://{fixture_root}", transport=make_transport(), **kw)
    return analyze_user("alice", Config(), opts, Console(file=io.StringIO()))


def test_full_pipeline(gp_home, fixture_root):
    result = run(fixture_root)
    assert result.with_work == 1 and result.errors == 0
    data = load_report("alice")
    repo = data.repos[0]
    c = repo["contribution"]

    # attribution: Alice's commits across 2 identities (email + noreply); Bob's excluded;
    # the merge commit is not counted as work
    assert c["commits"] == 9
    assert c["total_commits"] == 10  # 9 by Alice + 1 by Bob, merge excluded
    assert c["merge_commits"] == 1
    authors = {a["name"]: a["is_user"] for a in repo["authors"]}
    assert authors["Bob Other"] is False
    assert authors["Alice Dev"] is True and authors["alice"] is True

    # noise: lockfile excluded from lines, legacy import treated as a bulk commit
    assert c["bulk_commits"] == 1
    assert c["ignored_files"] >= 1
    assert c["additions"] < 1000  # would be ~5000+ if the lock file / bulk import counted

    # surviving lines measured with blame
    assert c["surviving_lines"] and c["surviving_lines"] > 0
    assert c["surviving_lines"] <= c["total_lines"]

    # purpose from README, quality signals, release from tag
    assert "peer-to-peer file transfer" in repo["purpose"]
    q = repo["quality"]
    assert q["has_tests"] and q["has_ci"] and q["has_license"] and q["has_docker"]
    assert q["readme_score"] == 4  # README is under 300 chars, so no "substantial text" point
    assert any(r["tag"] == "v1.0" for r in repo["releases"])

    # skills: language strong, FastAPI/PyTorch inferred from pyproject edited by Alice
    names = {s["name"]: s for s in repo["skills"]}
    assert names["Python"]["confidence"] == "strong"
    assert names["FastAPI"]["confidence"] == "inferred"
    assert "PyTorch" in names and "Docker" in names and "GitHub Actions" in names

    # development areas include networking and testing
    areas = {a["area"] for a in repo["areas"]}
    assert {"Networking", "Testing", "CI/DevOps"} <= areas

    # commit types come from conventional prefixes and keywords
    assert repo["commit_types"]["feature"] >= 2
    assert repo["commit_types"]["fix"] >= 1
    assert repo["commit_types"]["test"] >= 1

    # phases cover all commits
    assert sum(p["commits"] for p in repo["phases"]) == c["commits"]

    # PRs: only the PR in this repo is attached to the repo; external PRs feed open source
    assert repo["prs"]["authored"] == 1 and repo["prs"]["merged"] == 1
    prof = data.profile
    assert prof["prs"]["external_merged"] == 1 and prof["prs"]["reviews"] == 7
    assert len(prof["open_source"]) == 2 and prof["open_source"][0]["merged"] is True


def test_second_run_is_consistent_and_cached(gp_home, fixture_root):
    run(fixture_root)
    first = load_report("alice").profile["totals"]
    r2 = run(fixture_root)
    second = load_report("alice").profile["totals"]
    assert r2.with_work == 1 and r2.errors == 0
    for key in ("commits", "additions", "deletions", "surviving_lines", "repos_with_work"):
        assert first[key] == second[key]


def test_unknown_user(gp_home, fixture_root):
    opts = AnalyzeOptions(clone_base=f"file://{fixture_root}", transport=make_transport())
    with pytest.raises(UserNotFound):
        analyze_user("ghost", Config(), opts, Console(file=io.StringIO()))


class AsciiIO(io.StringIO):
    encoding = "ascii"


def test_dashboard_renders(gp_home, fixture_root):
    run(fixture_root)
    data = load_report("alice")
    for width in (60, 120):
        buf = io.StringIO()
        con = Console(file=buf, width=width, force_terminal=True, color_system=None)
        dashboard.render_overview(con, data)
        dashboard.render_repo(con, data.repos[0], "alice")
        out = buf.getvalue()
        assert "ALICE DEV" in out and "Development timeline" in out and "Skills with evidence" in out
        assert "█" in out  # unicode bars on utf-8 terminals


def test_dashboard_ascii_fallback(gp_home, fixture_root):
    run(fixture_root)
    data = load_report("alice")
    buf = AsciiIO()
    con = Console(file=buf, width=100, force_terminal=True, color_system=None)
    dashboard.render_overview(con, data)
    dashboard.render_repo(con, data.repos[0], "alice")
    out = buf.getvalue()
    out.encode("ascii")  # must not contain any non-ASCII character
    assert "ALICE DEV" in out


def test_markdown_and_json(gp_home, fixture_root):
    run(fixture_root)
    data = load_report("alice")
    md = report.build_markdown(data)
    for heading in ["## 1. Professional Summary", "## 2. Technical Skills", "## 3. GitHub Activity",
                    "## 4. Project Portfolio", "## 5. Project-by-Project Analysis",
                    "## 6. Contribution Timeline", "## 7. Technology Usage",
                    "## 8. Open Source Contributions", "## 9. Major Development Milestones",
                    "## 10. Evidence of Work", "## 11. GitHub Verification Links",
                    "## 12. Methodology and Limitations"]:
        assert heading in md, heading
    assert "https://github.com/alice/demo/commit/" in md
    assert "someone/else" in md
    assert "{{" not in md and "{%" not in md
    import json
    payload = json.loads(report.build_json(data))
    assert payload["profile"]["login"] == "alice" and payload["repositories"]


# ---- regressions found while reading real output --------------------------------------------
def test_evidence_links_point_at_the_real_repository(gp_home, fixture_root):
    run(fixture_root)
    data = load_report("alice")
    md = report.build_markdown(data)
    skills_section = md.split("## 2. Technical Skills")[1].split("## 3.")[0]
    assert "https://github.com/alice/demo/commit/" in skills_section
    assert "github.com/demo/" not in md          # owner was missing before the fix
    for skill in data.profile["skills"]:
        assert all("/" in r for r in skill["repos"])   # keyed by owner/name


def test_activity_tree_lines_are_well_formed(gp_home, fixture_root):
    run(fixture_root)
    md = report.build_markdown(load_report("alice"))
    block = md.split("## 3. GitHub Activity")[1].split("```text")[1].split("```")[0]
    for line in block.strip().splitlines()[2:]:
        assert line.startswith(("├── ", "└── ")), line
        assert line.count("├──") + line.count("└──") == 1, line   # no joined lines


def test_bulk_import_is_excluded_from_surviving_lines(gp_home, fixture_root):
    run(fixture_root)
    c = load_report("alice").repos[0]["contribution"]
    # the 160-file legacy import adds 4,800 lines; they must not inflate the headline number
    assert 0 < c["surviving_lines"] < 1000
    assert c["bulk_lines_excluded"] >= 4800
    # Bob wrote 40 of the remaining lines, so Alice owns most but not all of what is left
    assert c["total_lines"] - c["surviving_lines"] == 40
    assert 0.8 < c["surviving_share"] < 0.9


def test_singular_wording_and_weak_focus(gp_home, fixture_root):
    run(fixture_root)
    data = load_report("alice")
    md = report.build_markdown(data)
    assert "1 repository (" in md and "1 repositories" not in md
    assert "1 issue opened" in md and "1 issues" not in md
    assert "1 programming language" in md and "1 programming languages" not in md
    # one Dockerfile commit must not turn into a "DevOps" primary focus
    assert data.profile["focus"] == []
    assert "Primary focus" not in md
