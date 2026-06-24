# Swarms & scaling — eyes as a service

A single agent with eyes is useful. A **swarm** of agents that all share one set of eyes is the
real prize: dozens of workers each producing UIs, charts, decks or PDFs, every one of them
graded against the same contract before it counts as done. This page is how you run AgentVision
that way — the topologies, what scales freely, and the one piece of state you have to think
about.

## Two topologies

=== "Embedded (library) — co-located per agent"

    Each worker `pip install`s AgentVision and calls it in-process:

    ```python
    from agentvision import analyze, load_settings
    report = await analyze(artifact, settings=load_settings(vision_backend="local"))
    ```

    No shared service, no network hop, no distributed state — the loop session lives with the
    worker that owns it. **This is the simplest swarm model** and the right default when each
    agent already runs its own process. Scaling is just "more workers."

=== "Eyes as a service (REST) — one fleet, many callers"

    Run `agentvision serve` (FastAPI) and point N agents at it.

    **First, the auth token.** It's a **shared secret you choose** — AgentVision doesn't issue
    one, and there's no default (the server refuses to bind a non-loopback host without it). Any
    high-entropy string works; generate one and export it on the server:

    ```bash
    export TOKEN=$(openssl rand -hex 32)        # or: python -c "import secrets; print(secrets.token_urlsafe(32))"
    AGENTVISION_API_TOKEN=$TOKEN agentvision serve --host 0.0.0.0 --port 8000
    ```

    Give the **same** value to each client; it's sent as a bearer token (compared in constant
    time server-side):

    ```bash
    curl -s localhost:8000/check -H "Authorization: Bearer $TOKEN" \
      -H 'content-type: application/json' -d '{"source":"<html>…</html>"}'
    ```

    Loopback (`127.0.0.1`) needs no token — zero-config for local dev. Keep the token in your
    secret manager / env, never in the repo. See [Security](security.md#deploy-securely-recommended-backstops)
    for the full model.

    Central upgrades, one place to put GPUs/keys, language-agnostic clients. This is where the
    **stateless/stateful split** below matters.

## What scales freely vs. what needs affinity

Every endpoint except the loop is **stateless** — it renders, grades, returns, and forgets.
Stateless endpoints scale horizontally with zero coordination: put R replicas behind a load
balancer and you have R× the throughput.

| Endpoint | State | Scaling |
|---|---|---|
| `/check` `/analyze` `/conform` `/handoff` `/watch` `/sheet` `/baseline` | none | **free** — any replica, round-robin |
| `/loop` + `/loop/{id}/iterate` | **in-process session** | needs affinity (see below) |
| `/artifacts/{id}` | in-process id→path map | fetch promptly, or use shared `cache_dir` + affinity |

!!! warning "The multi-worker loop caveat"
    Loop sessions are kept **in the worker process that created them**. Behind multiple workers
    (`uvicorn …:app --workers N`) or multiple replicas, a loop started on worker A and continued
    on worker B returns `404 unknown session_id`. Single-shot `analyze`/`check`/`conform` have
    no such constraint. The service **fails loud** here — the 404 names the cause and the fixes
    rather than leaving you to guess.

### Three ways to handle loop state

1. **Keep the loop client-side (recommended for swarms).** Each agent owns its `LoopSession`
   via the library and calls only the *stateless* service endpoints (`/analyze`, `/check`,
   `/conform`) once per iteration. The iteration logic lives with the agent; the service stays
   a pure, infinitely-scalable grader. No distributed session, no affinity.
2. **Sticky-route by `session_id`.** Configure the load balancer to send every
   `/loop/{session_id}/iterate` to the replica that created the session. Simple, but a replica
   restart drops its live sessions.
3. **Pin loops to a single replica.** Run the stateless grading fleet wide and a single
   dedicated replica for `/loop`. Fine when loop traffic is light relative to single-shot.

!!! info "Roadmap: a pluggable session store"
    `LoopSession` already takes a `session_id` and persists each iteration's images and metadata
    to the workspace (`cache_dir`); only the live progress counters are in memory. That's the
    seam for an externalized session store (e.g. Redis), mirroring how the brain
    ([Verel](handoff.md)) externalizes its memory backend. Until then, prefer option 1.

## Concurrency, limits, and auth

These are **per process**, so the unit of horizontal scaling is the replica:

- **`max_concurrent_renders`** (default `4`) — a semaphore bounds simultaneous renders per
  replica (each render is a browser/heavy decode). Want more parallel renders? Add replicas, or
  raise this if the box has the RAM/CPU. A swarm of 50 agents against one default replica queues
  behind 4 renders — size the fleet to your render concurrency, not your agent count.
- **`max_request_bytes`** (default 8 MB) — request bodies are capped (header *and* stream, so a
  chunked body can't bypass it).
- **`request_timeout_s`** (default 120) — bound per-request work.
- **Auth is mandatory off loopback.** Binding a routable host without `AGENTVISION_API_TOKEN` is
  refused at startup; clients send `Authorization: Bearer <token>` (compared in constant time).
  `/healthz` stays open for load-balancer checks.
- **Hardened for untrusted input by default** — SSRF blocked (incl. DNS-rebinding via a vetting
  egress proxy), Chromium sandbox on, image-bomb caps, and bare-path/local-file + Office
  conversion **off** on the service. See [Security](security.md).

## The contract is the swarm's lingua franca

The reason a swarm of eyes composes at all: every worker returns the **same**
[`agentsensory`](https://pypi.org/project/agentsensory/) `Report`/`Handoff` — `{verdict,
issues[], next_action, todo}` — regardless of which replica graded it or whether it ran embedded
or over REST. An orchestrator (or a brain like [Verel](handoff.md)) can fan out work to the
swarm and aggregate verdicts on **one bus**, vision graded alongside tests, lint, and types. No
per-worker translation, no verdict dialects.

## Fan-out example (one service, many agents)

A coordinator grades a batch of artifacts concurrently against a shared eyes service, then keeps
only the ones that pass:

```python
import asyncio, httpx

EYES = "http://eyes.internal:8000"
TOKEN = "…"

async def grade(client, artifact: str) -> dict:
    r = await client.post(f"{EYES}/check",
                          headers={"Authorization": f"Bearer {TOKEN}"},
                          json={"source": artifact})
    r.raise_for_status()
    return r.json()

async def main(artifacts: list[str]):
    async with httpx.AsyncClient(timeout=120) as client:
        reports = await asyncio.gather(*(grade(client, a) for a in artifacts))
    passed = [a for a, rep in zip(artifacts, reports) if rep["verdict"] != "fail"]
    print(f"{len(passed)}/{len(artifacts)} artifacts cleared the eyes")

asyncio.run(main([...]))
```

`gather` fans out across the fleet; the service's per-replica render semaphore protects each box
from overload while the load balancer spreads the work. Because `/check` is stateless, this
scales by adding replicas — no session coordination involved.

## See also

- **[Adapters](adapters.md)** — the full REST/MCP/CLI/Skill surface.
- **[Configuration](configuration.md)** — every concurrency/limit/auth knob.
- **[Eyes → brain (handoff)](handoff.md)** — how verdicts flow to an orchestrator.
- **[Security](security.md)** — running the service against untrusted input.
