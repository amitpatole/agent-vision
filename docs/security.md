# Security

AgentVision renders **untrusted, attacker-controlled** HTML / URLs / images and ships a
network service, so it treats its inputs as hostile and is hardened by default. This is the
overview; the full policy + reporting is in
[SECURITY.md](https://github.com/amitpatole/agent-vision/blob/main/SECURITY.md).

## What's protected

- **SSRF** — one policy (`netguard`) blocks private / loopback / link-local / reserved /
  multicast / CGNAT (100.64/10) / cloud-metadata; IPv4-mapped IPv6 is normalized; unresolvable
  hosts fail closed. Checked at resolve time **and** re-checked at fetch time for every request,
  redirect, and WebSocket. Non-`http(s)` schemes are default-denied; `file://` only for an
  explicit top-level navigation.
- **DNS rebinding — closed by a vetting egress proxy.** Chromium routes all egress through a
  local proxy that resolves each host **once**, vets the IP, and connects to **that exact IP**
  (HTTP, HTTPS/WSS via CONNECT, WS). Chromium never resolves a host itself, so there's no second
  lookup to rebind; `Host` / TLS SNI are preserved. The proxy caps concurrent connections and
  times out idle ones.
- **Renderer isolation** — Chromium OS sandbox **on by default**; downloads disabled, popups
  closed; viewport / `device_scale` / full-page capture clamped (OOM bound).
- **Untrusted bytes** — byte + pixel caps before any image decode (decompression-bomb guard);
  PDF byte/size/timeout bounds; OCR timeout.
- **Office documents (LibreOffice)** — `.docx/.pptx/.xlsx/…` are converted to PDF via
  LibreOffice headless, which is hardened: argv form (no shell), the input passed as an
  **absolute path** so a `-`-leading filename can't become a flag, a byte cap, an isolated
  throwaway user profile per conversion (and `--convert-to` does not execute document macros),
  and a hard timeout with **process-group kill**. Gated **off by default on the REST service**
  (`allow_office_render=False`) — LibreOffice is a large attack surface on untrusted input.
- **HTTP service** — loopback is zero-config; a non-loopback bind **refuses to start without a
  token**; token auth is constant-time; request bodies are capped (incl. chunked); renders are
  bounded by a semaphore; errors don't leak internals; local-file sources are refused.
- **Path confinement** — every local-file read is normalized and confined with a
  resolve-then-`commonpath` barrier, so `..` traversal, symlink escapes, and poisoned artifact
  ids can't reach a file outside the allowed area. The REST service refuses bare-path / `file://`
  reads outright; set `file_root` to additionally pin all reads beneath one directory (see below).
- **Secrets** — no default/hardcoded secret; API keys/token are value-scrubbed from logs.

## Confidential inputs (no on-disk cache)

For a confidential artifact, run in **ephemeral mode** so renders and session state never land in
the persistent cache — a `0700` temp dir is used and wiped at the end of the run (even on error):

```bash
agentvision check confidential.pptx --no-cache --backend local   # nothing leaves the box, nothing cached
```

Equivalent to `AGENTVISION_EPHEMERAL=true`, or `ephemeral_cache()` in the
[Python API](api.md#confidential-inputs-ephemeral-cache). Note ephemeral mode only controls
**disk persistence** — a cloud vision backend still sends the render to its provider, so pair
`--no-cache` with `--backend local` (or `check`) for fully on-box handling. The offline
PowerPoint inspector (`agentvision check deck.pptx`) is key-free and no-egress, so it's safe for
confidential decks. See [Configuration → Confidential inputs](configuration.md#confidential-inputs-ephemeral-cache).

## Path confinement for file sources (`file_root`)

By default the CLI/library trust the local user and read any path you point them at. When a
service reads paths chosen by an **untrusted caller**, set `file_root` to confine every local
read beneath one directory — anything that resolves outside it (via `..`, symlink, or absolute
path) is refused:

```bash
export AGENTVISION_FILE_ROOT=/srv/agentvision/inbox
export AGENTVISION_API_TOKEN=$(openssl rand -hex 32)
agentvision serve --host 0.0.0.0 --port 8000
```

The REST service additionally refuses bare-path and `file://` sources by default, so this is a
second layer for deployments that intentionally serve files from a directory.

## Authenticated rendering

`--storage-state PATH` renders an app while logged in (see
[Configuration](configuration.md#authenticated-interactive-rendering)). The security model:

- **Credentials by reference, never inline.** The CLI accepts only a *path* to a Playwright
  `storage_state` JSON (or the `AGENTVISION_STORAGE_STATE` env var) — never a password or token
  on the command line (which would land in shell history and `ps`).
- **Read-only consumption.** AgentVision loads the session into memory and never re-serializes
  it, so no fresh credential file is written as a side effect. Tracing/HAR are never enabled, so
  session cookies can't leak into a trace artifact.
- **Secrets are redaction-registered.** Every cookie / localStorage value in the state file is
  registered with the log scrubber on load, so it can never appear in a log line; only
  non-sensitive counts (`N cookies, M origins`) are logged.
- **Forced ephemeral.** Supplying a session **forces `--no-cache`**, so authenticated captures
  (which contain real user data) are never written to the shared on-disk cache.
- **Fail-closed on expiry.** If the session is expired/invalid and the page lands on a login
  wall, AgentVision errors (`AuthExpiredError`) instead of silently grading the login page.

**The state file is a live credential** — anyone with it can impersonate the account. Keep it out
of version control (`echo 'state.json' >> .gitignore`; verify with `git check-ignore -v
state.json`). An authenticated screenshot also contains real user data; treat the output the same
way (the analyze/check path keeps it in the ephemeral temp dir and wipes it).

## Pre-capture interactions

`--interactions` drives the page (click/hover/fill/…) before grading, so it can act inside a live
authenticated app. Guardrails:

- **Closed vocabulary, no code execution.** Steps are a fixed enum mapped one-to-one to Playwright
  calls; there is **no `eval`/raw-JS step**, so a steps file can't run arbitrary code in the page.
- **Read-only by default.** While steps run, non-GET HTTP requests (POST/PUT/PATCH/DELETE) are
  aborted, so a click can't submit/delete/send. Opt in per run with `--allow-mutations` when a
  step legitimately needs a write.
- **Fail-closed.** A missing selector or timeout aborts the render rather than grading the wrong
  state; a runaway is bounded by `max_interactions`, a per-step timeout, and the overall render
  timeout.
- **Secrets by reference.** Use `fill_env` (types the value of a named env var, redaction-
  registered) rather than `fill` for a password, so no secret is written into the steps JSON.
- **Local-only surface.** Interactions and `storage_state` are **not** settable by a remote
  REST/MCP caller — both resolve from server-side config only.

**Residual limits (stated honestly).** The read-only guard covers **HTTP non-GET** requests; it
does **not** block a write sent over a WebSocket, nor a side-effecting `GET` (an app that mutates
on a GET is its own bug). Login-wall detection is a heuristic (login-ish URL or a visible password
field) and is best-effort. Treat `--allow-mutations` against a production app the way you'd treat
any write — it is not a sandbox.

## Deploy securely (recommended backstops)

```bash
export AGENTVISION_API_TOKEN=$(openssl rand -hex 32)   # required for any non-loopback bind
```

- **Restrict the renderer's egress** at the network layer (deny outbound to `169.254.0.0/16`,
  RFC-1918, CGNAT) — defense in depth around the app controls. This also backstops LibreOffice,
  which can attempt to fetch remote templates/images that the conversion step can't fully block.
- **Containerize** so the Chromium sandbox is available without `--no-sandbox`.
- Keep `block_private_networks` on (default); only use `--allow-local` against trusted targets.

## Reporting

Report privately to **amit.patole@gmail.com** — please don't open a public issue for an
unpatched vulnerability.
