"""HTML -> PDF with a fallback chain: WeasyPrint, then a headless Chromium-family browser."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class PdfError(Exception):
    pass


BROWSER_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                 "chrome", "msedge", "microsoft-edge", "microsoft-edge-stable", "brave-browser")
BROWSER_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


def find_browser() -> str | None:
    override = os.environ.get("GITPROOF_BROWSER")
    if override and Path(override).exists():
        return override
    for name in BROWSER_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for path in BROWSER_PATHS:
        if Path(path).exists():
            return path
    # Playwright's bundled Chromium (also what CI images ship)
    pw = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if pw:
        for candidate in sorted(Path(pw).glob("chromium-*/chrome-linux*/chrome")):
            return str(candidate)
    return None


def weasyprint_available() -> bool:
    try:
        import weasyprint  # noqa: F401
        return True
    except Exception:  # missing package or missing system libraries (pango)
        return False


def _with_weasyprint(html: str, out: Path) -> None:
    import weasyprint
    weasyprint.HTML(string=html, base_url=str(out.parent)).write_pdf(str(out))


def _with_browser(html: str, out: Path, browser: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "report.html"
        src.write_text(html, encoding="utf-8")
        profile = Path(tmp) / "profile"
        cmd = [browser, "--headless=new", "--disable-gpu", "--no-sandbox",
               f"--user-data-dir={profile}", "--no-pdf-header-footer",
               f"--print-to-pdf={out}", src.as_uri()]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    if not out.exists() or out.stat().st_size == 0:
        raise PdfError(f"{Path(browser).name} did not produce a PDF: {proc.stderr.strip()[-300:]}")


def html_to_pdf(html: str, out: Path, engine: str = "auto") -> str:
    """Write a PDF and return the engine used ('weasyprint' or 'browser')."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    if engine in ("auto", "weasyprint"):
        if weasyprint_available():
            try:
                _with_weasyprint(html, out)
                return "weasyprint"
            except Exception as exc:
                errors.append(f"WeasyPrint failed: {exc}")
        else:
            errors.append("WeasyPrint is not available (pip install 'gitproof[pdf]'; on Windows it "
                          "also needs the GTK runtime)")
        if engine == "weasyprint":
            raise PdfError("; ".join(errors))
    if engine in ("auto", "browser"):
        browser = find_browser()
        if browser:
            try:
                _with_browser(html, out, browser)
                return "browser"
            except (subprocess.SubprocessError, OSError, PdfError) as exc:
                errors.append(f"Browser printing failed: {exc}")
        else:
            errors.append("no Chrome, Edge or Chromium found (set GITPROOF_BROWSER to its path)")
    raise PdfError(
        "Could not create a PDF: " + "; ".join(errors) +
        ". Alternative: run 'gitproof export --format html' and use your browser's Print > Save as PDF.")
