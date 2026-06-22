"""Office / OpenDocument → PDF conversion via LibreOffice headless.

`docx/pptx/xlsx/odt/odp/ods/…` can only be rendered faithfully by a real office engine —
the XML libraries (`python-docx`/`python-pptx`) parse content but do not lay out pages,
fonts, charts, or slides. We shell out to LibreOffice (`soffice --headless --convert-to pdf`)
and then hand the PDF to the existing PDF rasterizer.

LibreOffice on untrusted input is a large attack surface (document macros, DDE, remote
template / OLE injection, outbound fetches). This module is hardened accordingly:

- **argv form, never a shell**, and the input is passed as an **absolute path** (always begins
  with ``/``) so a filename beginning with ``-`` can't be reinterpreted as a LibreOffice flag.
- **byte cap** before the file is handed to LibreOffice.
- **isolated, throwaway user profile** (`-env:UserInstallation`) per conversion — no shared
  state, and `--convert-to` does not execute document macros.
- **hard timeout** with **process-group kill** (LibreOffice forks `soffice.bin`; killing only
  the parent would orphan it).
- callers gate on ``settings.allow_office_render`` (off on the untrusted REST service).

Network egress is NOT something this module can fully block (LibreOffice may try to fetch a
remote template/image); the recommended deployment is a network egress-deny around the
renderer, the same backstop documented for the browser. See SECURITY.md.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import uuid
from pathlib import Path

from .config import Settings
from .errors import MissingDependencyError, RenderError, UnsafeSourceError

# Extensions LibreOffice can convert to PDF. MS Office + OpenDocument + RTF.
OFFICE_EXT = {
    ".doc", ".docx", ".odt", ".rtf",          # word processing
    ".ppt", ".pptx", ".odp",                  # presentations
    ".xls", ".xlsx", ".ods",                  # spreadsheets
}


def find_soffice(settings: Settings) -> str | None:
    """Locate the LibreOffice binary (explicit override → PATH)."""
    if settings.soffice_path:
        return settings.soffice_path if Path(settings.soffice_path).exists() else None
    return shutil.which("soffice") or shutil.which("libreoffice")


async def convert_to_pdf(path: Path, out_dir: Path, settings: Settings) -> Path:
    """Convert an Office/OpenDocument file at ``path`` to a PDF inside ``out_dir``.

    Raises ``UnsafeSourceError`` (gate off / too large), ``MissingDependencyError`` (no
    LibreOffice), or ``RenderError`` (conversion failed/timed out).
    """
    if not settings.allow_office_render:
        raise UnsafeSourceError(
            "Office document rendering is disabled (allow_office_render=False). It is off by "
            "default on the REST service because LibreOffice is a large attack surface on "
            "untrusted input."
        )
    soffice = find_soffice(settings)
    if soffice is None:
        raise MissingDependencyError(
            "Office document rendering (LibreOffice)",
            pip_extra=None,
            system="dnf install libreoffice  /  apt-get install libreoffice",
        )
    if not path.exists():
        raise RenderError(f"Office source does not exist: {path}")
    try:
        nbytes = path.stat().st_size
    except OSError as e:
        raise RenderError(f"Cannot stat document: {e}") from e
    if nbytes > settings.max_document_bytes:
        raise RenderError(
            f"Document is {nbytes} bytes, over the {settings.max_document_bytes}-byte cap."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    # Per-conversion throwaway profile dir (isolation; avoids the shared ~/.config lock).
    profile = out_dir / f"lo_profile_{uuid.uuid4().hex[:8]}"
    profile.mkdir(parents=True, exist_ok=True)
    # Absolute path: always begins with '/', so a filename starting with '-' can't be
    # reinterpreted as a flag (LibreOffice has no '--' end-of-options separator).
    abs_path = str(path.resolve())
    argv = [
        soffice,
        "--headless", "--norestore", "--nolockcheck", "--nodefault", "--nologo",
        f"-env:UserInstallation=file://{profile}",
        "--convert-to", "pdf",
        "--outdir", str(out_dir),
        abs_path,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # own process group so we can kill soffice.bin too
        )
    except OSError as e:
        raise RenderError(f"Could not start LibreOffice: {e}") from e
    try:
        _out, err = await asyncio.wait_for(
            proc.communicate(), timeout=settings.document_convert_timeout_s
        )
    except TimeoutError as e:
        _kill_group(proc)
        raise RenderError(
            f"LibreOffice conversion timed out after {settings.document_convert_timeout_s}s."
        ) from e
    if proc.returncode != 0:
        msg = (err or b"").decode("utf-8", "replace").strip()[:300]
        raise RenderError(f"LibreOffice conversion failed (exit {proc.returncode}): {msg}")

    pdf = out_dir / (path.stem + ".pdf")
    if not pdf.exists():
        # LibreOffice names the output after the input stem; fall back to any produced PDF.
        produced = sorted(out_dir.glob("*.pdf"))
        if not produced:
            raise RenderError("LibreOffice produced no PDF.")
        pdf = produced[0]
    return pdf


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
