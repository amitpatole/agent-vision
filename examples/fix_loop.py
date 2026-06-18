"""Programmatic visual feedback loop.

Run:  python examples/fix_loop.py
(no API key needed — uses the offline 'local' backend)
"""

import asyncio
from pathlib import Path

from agentvision.config import load_settings
from agentvision.core.loop import LoopSession

HERE = Path(__file__).parent


async def main() -> None:
    settings = load_settings(vision_backend="local", full_page=True)
    session = LoopSession(str(HERE / "broken_layout.html"), settings=settings, backend="local")

    # 1) The agent looks at its (broken) page.
    first = await session.iterate()
    print(f"iter 0 → {first.verdict.value.upper()} with {len(first.report.issues)} issue(s):")
    for issue in first.report.issues:
        print(f"   - [{issue.kind.value}] {issue.message}")

    # 2) The agent fixes the source and looks again.
    second = await session.iterate(str(HERE / "broken_layout.fixed.html"))
    print(f"\niter 1 → {second.verdict.value.upper()} with {len(second.report.issues)} issue(s)")
    if second.diff:
        print(f"what changed: {second.diff.narrative}")

    if first.verdict.value == "fail" and second.verdict.value == "pass":
        print("\n✓ FAIL → PASS: the agent saw the problems and fixed them.")


if __name__ == "__main__":
    asyncio.run(main())
