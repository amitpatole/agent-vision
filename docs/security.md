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
- **Secrets** — no default/hardcoded secret; API keys/token are value-scrubbed from logs.

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
