"""Run the labelled corpus through one AgentVision backend and score it.

    python bench/run.py --backend local
    python bench/run.py --backend ollama --model qwen2.5vl:7b --base-url http://HOST:11434/v1
    python bench/run.py --summarize            # table over every bench/results/*.json

Scoring (per case, ground truth in bench/manifest.json):
- defect case: *flagged* when the verdict is not PASS; *kind hit* when the expected IssueKind is
  reported (for ``missing_element``: that kind, ``intent_mismatch``, or a violated brief claim);
  *vision hit* when that kind came from the vision model itself (not the deterministic checks).
- clean case: *clean pass* when the verdict is PASS; *false fail* when it is FAIL.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from agentvision import analyze, check, load_settings
from agentvision.models.intent import Brief

HERE = Path(__file__).parent
RESULTS = HERE / "results"


def _kind_hit(report, defect: str, *, vision_only: bool) -> bool:
    kinds = {defect}
    if defect == "missing_element":
        kinds |= {"intent_mismatch"}
    for i in report.issues:
        if vision_only and str(getattr(i.source, "value", i.source)) != "vision":
            continue
        if str(getattr(i.kind, "value", i.kind)) in kinds:
            return True
    if defect == "missing_element" and report.conformance and not vision_only:
        return bool(report.conformance.violated)
    return False


async def run_case(c: dict, backend: str, settings) -> dict:
    src = str(HERE / "corpus" / c["file"])
    brief = Brief.from_inputs(expect=c["expect"]) if c["expect"] else None
    t0 = time.monotonic()
    try:
        if backend == "local":
            rep = await check(src, settings=settings, brief=brief)
        else:
            rep = await analyze(src, settings=settings, backend=backend, brief=brief)
    except Exception as e:  # noqa: BLE001 — a crash is a scored outcome, not a harness failure
        return {"id": c["id"], "defect": c["defect"], "error": f"{type(e).__name__}: {e}"[:300],
                "elapsed_s": round(time.monotonic() - t0, 2)}
    verdict = str(getattr(rep.verdict, "value", rep.verdict))
    row = {
        "id": c["id"], "defect": c["defect"], "verdict": verdict,
        "kinds": sorted({str(getattr(i.kind, "value", i.kind)) for i in rep.issues}),
        "n_issues": len(rep.issues),
        "unparseable": any("unparseable" in i.message for i in rep.issues),
        "elapsed_s": round(time.monotonic() - t0, 2),
        "summary": (rep.summary or "")[:200],
    }
    if c["defect"]:
        row["flagged"] = verdict != "pass"
        row["kind_hit"] = _kind_hit(rep, c["defect"], vision_only=False)
        row["vision_hit"] = _kind_hit(rep, c["defect"], vision_only=True)
    else:
        row["clean_pass"] = verdict == "pass"
        row["false_fail"] = verdict == "fail"
    return row


def score(rows: list[dict]) -> dict:
    d = [r for r in rows if r["defect"]]
    c = [r for r in rows if not r["defect"]]

    def frac(rs, key):
        return f"{sum(1 for r in rs if r.get(key))}/{len(rs)}"

    lat = sorted(r["elapsed_s"] for r in rows)
    return {
        "defects_flagged": frac(d, "flagged"), "right_kind": frac(d, "kind_hit"),
        "vision_right_kind": frac(d, "vision_hit"), "clean_pass": frac(c, "clean_pass"),
        "false_fail": frac(c, "false_fail"), "unparseable": frac(rows, "unparseable"),
        "errors": sum(1 for r in rows if "error" in r),
        "median_s": lat[len(lat) // 2] if lat else 0, "max_s": lat[-1] if lat else 0,
    }


async def main_run(a) -> None:
    cases = json.loads((HERE / "manifest.json").read_text())
    overrides = {"ephemeral": True}
    if a.backend == "ollama":
        overrides.update(ollama_model=a.model, ollama_base_url=a.base_url)
    elif a.backend in ("openai", "gemini", "anthropic"):
        overrides[f"{a.backend}_model"] = a.model
    settings = load_settings(**overrides)
    rows = []
    for c in cases:
        row = await run_case(c, a.backend, settings)
        rows.append(row)
        print(json.dumps(row), flush=True)
    label = a.backend if a.backend == "local" else f"{a.backend}-{a.model.replace(':', '_')}"
    RESULTS.mkdir(exist_ok=True)
    out = {"label": label, "backend": a.backend, "model": a.model if a.backend != "local" else "",
           "score": score(rows), "rows": rows}
    (RESULTS / f"{label}.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out["score"]))


def summarize() -> None:
    cols = ["defects_flagged", "right_kind", "vision_right_kind", "clean_pass", "false_fail",
            "unparseable", "errors", "median_s", "max_s"]
    print("| run | " + " | ".join(cols) + " |")
    print("|---|" + "---|" * len(cols))
    for f in sorted(RESULTS.glob("*.json")):
        r = json.loads(f.read_text())
        print(f"| {r['label']} | " + " | ".join(str(r["score"][k]) for k in cols) + " |")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--backend", default="local")
    p.add_argument("--model", default="qwen2.5vl:7b")
    p.add_argument("--base-url", default="http://localhost:11434/v1")
    p.add_argument("--summarize", action="store_true")
    a = p.parse_args()
    summarize() if a.summarize else asyncio.run(main_run(a))
