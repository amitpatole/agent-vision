# Security

AgentVision renders **untrusted, attacker-controlled** HTML/URLs/images and runs a network
service, so it treats its inputs as hostile. This documents the security model, what's
hardened, the trust boundaries, and how to report issues.

## Reporting a vulnerability

Please report privately to **amit.patole@gmail.com** (don't open a public issue for an
unpatched vuln). Include a PoC if you can; we aim to confirm quickly.

## What's hardened

**SSRF (the headline surface).** Source URLs and every in-page request are checked against one
policy (`agentvision/netguard.py`): private, loopback, link-local, reserved, multicast,
unspecified, CGNAT (100.64/10) and cloud-metadata addresses are blocked; IPv4-mapped IPv6
(`::ffff:…`) is normalized first; unresolvable/unparseable hosts fail closed. The check runs at
**resolve time** and is **re-run at fetch time** inside the renderer's route guard for every
request — navigation, subresource, **and redirect target** — and for **WebSocket** connections
(`route_web_socket`). Non-`http(s)` schemes (gopher/ftp/…) are default-denied; `file://` is
denied for subresources and allowed only for an explicit top-level navigation when
`allow_file_scheme` is set.

**DNS rebinding is closed by a vetting egress proxy** (`agentvision/proxy.py`): Chromium is
launched with `--proxy-server` (and `--proxy-bypass-list=<-loopback>`) pointing at a local
proxy that resolves each host **once**, vets the resolved IP, and connects to **that exact IP**.
Because Chromium never resolves a host itself, there is no second lookup to rebind, and the
`Host` header / TLS SNI are preserved. The proxy runs only when SSRF protection is on (it's
skipped under `--allow-local`).

**Renderer isolation.** Chromium runs with its **OS sandbox enabled by default**
(`chromium_sandbox`); it is only disabled if you explicitly set
`AGENTVISION_CHROMIUM_SANDBOX=false`, and a sandbox launch failure is reported loudly rather
than silently downgraded. Downloads are disabled, pop-ups/extra pages are closed, viewport and
`device_scale` are clamped, and a full-page capture is bounded so attacker-controlled page
height can't OOM the host.

**Untrusted images / PDFs / OCR.** Every decode of attacker bytes goes through
`agentvision/imageguard.py`, which enforces a byte cap and a pixel-dimension cap **before** any
decode (decompression-bomb defense; PIL's own bomb guard is also armed). PDFs are byte-capped,
width-capped, first-page-only, with a poppler timeout; OCR has a subprocess timeout.

**The HTTP service.** Loopback bind is zero-config; binding a routable interface **refuses to
start without `AGENTVISION_API_TOKEN`**. When a token is set it's required on every endpoint
(except `/healthz`) via constant-time comparison. Request bodies are capped (including chunked
streams), concurrent renders are bounded by a semaphore, the service refuses to read local-file
sources, and error responses don't disclose internal detail (resolved IPs, paths).

**Secrets.** No default/hardcoded auth or signing secret exists. Provider API keys and the API
token are read once, never persisted to cache/reports, and registered for value-based redaction
so they're scrubbed from any log line.

## Defense-in-depth deployment (recommended)

The application controls above close the known SSRF vectors (including DNS rebinding, via the
vetting proxy). For production, add a network-level backstop so a future bug or a disabled
control can't reach internal services:

- **Restrict the renderer's egress.** Run AgentVision (or its container) on a network that
  **denies outbound to link-local `169.254.0.0/16`, the metadata IPs, and RFC-1918 / CGNAT
  ranges**, allowing only the public destinations you intend to render. (e.g. a container with
  an egress firewall / NetworkPolicy, or a locked-down VPC egress.)
- **Keep `block_private_networks` on** (the default). Only use `--allow-local` against trusted
  local targets.
- **Containerize** so Chromium's OS sandbox is available (the default) without `--no-sandbox`.
- **Require a token** for any non-loopback REST bind (enforced) and front it with TLS.

## Trust boundaries

- The **`local` backend** sends nothing off-box. Cloud backends send a screenshot to the chosen
  provider.
- `--allow-local` / `block_private_networks=false` intentionally disables SSRF protection for
  local/LAN dev — use only against trusted targets.
- The **MCP server** is a local (stdio) tool; it accepts local file paths by design for the
  developer's own machine. The **REST service** is the network surface and is locked down as
  above.
