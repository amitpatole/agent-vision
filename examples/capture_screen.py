"""Sight: grade the LIVE desktop via the screenshot portal.

Run (from a terminal INSIDE a graphical desktop session):

    pip install 'agentvision[desktop]'      # jeepney (D-Bus) + a running xdg-desktop-portal
    python examples/capture_screen.py

No API key needed — this uses the offline 'local' backend, so the captured pixels never leave
the machine (deterministic checks only). The OS portal prompts you for permission on capture;
approve it. For a semantic question ("is a dialog asking about X?") use a cloud backend and pass
allow_screen_capture_egress=True to consent to the upload.
"""

import asyncio

from agentvision import analyze, load_settings
from agentvision.errors import AgentVisionError


async def main() -> None:
    # `local` backend => no egress; --interactive lets you pick the window/area at the prompt.
    settings = load_settings(vision_backend="local", screen_capture_interactive=True)

    try:
        report = await analyze("desktop:", settings=settings, backend="local")
    except AgentVisionError as e:
        # Fails closed: no [desktop] extra, no portal, no graphical session, or you denied the
        # prompt. (On a headless / SSH-only host there is no display to capture.)
        print(f"screen capture unavailable: {e}")
        return

    print(f"verdict: {report.verdict.value.upper()}  ({report.backend})")
    print(report.summary)
    for issue in report.issues:
        print(f"  - [{issue.kind.value}] {issue.message}")

    # To ask a semantic question about the screen, use a cloud backend + explicit egress consent:
    #   settings = load_settings(vision_backend="anthropic", allow_screen_capture_egress=True)
    #   report = await analyze("desktop:", settings=settings, backend="anthropic",
    #                          expected="is an error dialog open?")


if __name__ == "__main__":
    asyncio.run(main())
