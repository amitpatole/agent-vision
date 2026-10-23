# AgentVision benchmark corpus

A small, labelled, self-contained corpus for measuring what a backend actually catches. It is
themed on media and communications work: player pages, TV schedules, headlines, carousels,
newsletters and social cards. No case touches the network.

```bash
python bench/make_corpus.py                       # regenerate corpus/ + manifest.json
python bench/run.py --backend local               # deterministic checks only
python bench/run.py --backend ollama --model qwen2.5vl:7b \
    --base-url http://localhost:11434/v1          # a self-hosted vision model
python bench/run.py --summarize                   # table over results/*.json
```

`manifest.json` is the ground truth. Each case lists the one defect a correct grader must report,
or `null` for a clean page. Scoring is described at the top of `run.py`. Results and how to read
them are in the [pilot guide](../docs/pilot.md#benchmark).

Extend it with your own artifacts. A pilot is only as convincing as a corpus built from your real
defects.
