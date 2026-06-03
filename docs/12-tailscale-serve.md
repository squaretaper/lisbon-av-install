# Tailscale Serve — Remote Access to the Install

The Lisbon mini exposes its bridges over Tailscale HTTPS so the install team can monitor the camera, the audio bridge status, and the heuristic profile from any tailnet device — bento, your laptop, Pablo's MacBook, anywhere. Tailnet-only by design; nothing is public.

## Endpoints

Base URL: `https://ganchi.tail6dbafa.ts.net/camera/`

| Path | What it is |
|---|---|
| `/camera/` | Minimal browser viewer (live MJPEG) |
| `/camera/frame.jpg` | Latest JPEG, single frame |
| `/camera/stream.mjpeg` | Continuous multipart MJPEG (for browsers, OBS, ffmpeg `-i`) |
| `/camera/status` | Camera probe status JSON (device, frame rate, ok flag) |
| `/camera/health` | Process health |

The base hostname `ganchi.tail6dbafa.ts.net` is the mini's Tailscale MagicDNS name. From any tailnet device, just paste the URL into a browser — Tailscale issues a real TLS cert and your device authenticates by being on the tailnet. No password, no port forward, no exposure to the public internet.

## Operating the serve config

```bash
# Bring serve up (idempotent — resets then re-adds the camera route)
scripts/tailscale-serve.sh up

# Tear it down
scripts/tailscale-serve.sh down

# Inspect current routes
scripts/tailscale-serve.sh status
```

The script is short, dependency-free, and safe to re-run.

## Why path-scoped under `/camera/`

We may add more services later (`/swn/` for audio bridge status, `/hermes/` for the gateway, `/lights/` for the ESP32 sync). Putting each one under its own path keeps the config clean and avoids root-route collisions when a new bridge ships.

To add another route after the camera, edit `scripts/tailscale-serve.sh` and append another `tailscale serve` call inside the `up` case.

## Survival semantics

Tailscale's serve config is stored in the daemon and survives reboots. The script doesn't need to run on every boot — once it's been applied, the routes stay until something explicitly resets them. Re-running `up` is idempotent.

## Not in the public internet

This is **not** `tailscale funnel`. Funnel would expose the endpoints to the public internet. We are deliberately not doing that for the install:

- Bandwidth on the venue network is finite; we don't want anyone on the open internet pulling the camera stream.
- The whole point of the tailnet is the install team only — no random visitor or scraper.
- If the show ever needs a public preview, that's a separate decision and a separate, well-monitored route.

## Permissions on Tailscale's side

The mini's Tailscale account owns the node and the certificate. HTTPS-on-443 is enabled in the admin console by default for ts.net hostnames. No extra setup required.

If a future redeploy moves the mini to a new tailnet account, run `scripts/tailscale-serve.sh up` once after sign-in; the cert is auto-provisioned on first request.
