"""`agentvision doctor` — diagnose rendering + backend readiness.

Attempts a real Chromium launch and, on failure, runs ``ldd`` on the browser binary to
enumerate *all* missing system libraries at once (a launch exception only names the
first). Prints the right install command for the detected distro.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys

from ..backends.registry import ALL_BACKENDS, build_backend
from ..config import load_settings

_OK = "\033[32m✓\033[0m"
_BAD = "\033[31m✗\033[0m"
_WARN = "\033[33m!\033[0m"

_DNF_LIBS = ("nss nspr atk at-spi2-atk at-spi2-core cups-libs libdrm libxkbcommon "
             "libXcomposite libXdamage libXrandr libXfixes libXrender mesa-libgbm "
             "pango cairo alsa-lib gtk3")
_APT_HINT = "playwright install --with-deps chromium   (Debian/Ubuntu)"


def _distro_install_hint(missing: list[str]) -> str:
    if shutil.which("dnf"):
        return f"sudo dnf install -y {_DNF_LIBS}"
    if shutil.which("apt-get"):
        return f"sudo {_APT_HINT}"
    return f"Install the equivalent of: {_DNF_LIBS}"


async def _check_chromium() -> tuple[bool, str]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return False, "playwright not installed — pip install 'agentvision[render]'"
    try:
        async with async_playwright() as pw:
            exe = pw.chromium.executable_path
            try:
                browser = await pw.chromium.launch(
                    headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
                )
                await browser.close()
                return True, "Chromium launches"
            except Exception as e:  # noqa: BLE001
                missing = _ldd_missing(exe)
                hint = _distro_install_hint(missing)
                detail = (f"missing libs: {', '.join(missing)}" if missing else str(e))
                return False, f"Chromium will not launch ({detail}). Fix: {hint}"
    except Exception as e:  # noqa: BLE001
        return False, f"Chromium not installed. Run: agentvision doctor --fix  ({e})"


def _ldd_missing(exe: str | None) -> list[str]:
    if not exe or platform.system() != "Linux" or not shutil.which("ldd"):
        return []
    try:
        out = subprocess.run(["ldd", exe], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return []
    missing = []
    for line in (out.stdout + out.stderr).splitlines():
        if "not found" in line:
            missing.append(line.strip().split()[0])
    return sorted(set(missing))


async def run_doctor(fix: bool = False) -> bool:
    settings = load_settings()
    print("AgentVision doctor\n" + "=" * 40)

    if fix:
        print("Installing Chromium browser …")
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])
        print()

    ok = True

    chromium_ok, msg = await _check_chromium()
    print(f"  {_OK if chromium_ok else _BAD} Rendering (Chromium): {msg}")
    ok = ok and chromium_ok

    # OCR
    tess = shutil.which("tesseract")
    print(f"  {_OK if tess else _WARN} OCR (tesseract): "
          + (tess or "not found — install tesseract-ocr + tesseract-ocr-eng (optional)"))

    # PDF
    poppler = shutil.which("pdftoppm")
    print(f"  {_OK if poppler else _WARN} PDF (poppler): "
          + (poppler or "not found — install poppler-utils (optional)"))

    # Office documents (docx/pptx/xlsx/odf via LibreOffice)
    from ..office import find_soffice
    soffice = find_soffice(settings)
    print(f"  {_OK if soffice else _WARN} Office docs (LibreOffice): "
          + (soffice or "not found — install libreoffice (optional, for docx/pptx/xlsx)"))

    # Backends
    print("\n  Vision backends:")
    any_cloud = False
    for name in ALL_BACKENDS:
        try:
            available = build_backend(name, settings).available()
        except Exception:  # noqa: BLE001
            available = False
        if name == "local":
            print(f"    {_OK} local (offline, always available)")
            continue
        if available:
            any_cloud = True
            print(f"    {_OK} {name} (key present)")
        else:
            key_env = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
                       "gemini": "GOOGLE_API_KEY"}.get(name, "")
            print(f"    {_WARN} {name} (set {key_env} to enable)")

    print("\n" + "=" * 40)
    if chromium_ok:
        print("Ready. Try: agentvision demo"
              + ("" if any_cloud else "   (set an API key for semantic analysis)"))
    else:
        print("Rendering is not ready — fix the Chromium item above, or use the Dockerfile.")
    return ok
