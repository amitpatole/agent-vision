"""Render a responsive contact sheet across breakpoints.

Run:  python examples/contact_sheet.py
"""

import asyncio
from pathlib import Path

from agentvision.config import load_settings
from agentvision.core.capture import contact_sheet

HERE = Path(__file__).parent


async def main() -> None:
    settings = load_settings()
    out, _ = await contact_sheet(
        str(HERE / "broken_layout.fixed.html"),
        settings=settings,
        breakpoints=[375, 768, 1280, 1920],
        out_path=str(HERE / "contact_sheet.png"),
    )
    print(f"Contact sheet written to {out}")


if __name__ == "__main__":
    asyncio.run(main())
