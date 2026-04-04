# Harbor Media Server Setup Guide

This guide covers the standard Windows-first install path for Harbor Media Server on a single PC.

The goal is to get a new machine from a fresh clone to a working Harbor stack with as little manual rework as possible. The setup flow handles folders, volumes, initial configuration, service wiring, and guarded update automation. The remaining manual steps are limited to account-linked tasks such as Plex onboarding, private trackers, Cloudflare, and Usenet providers.

## What the setup is trying to achieve

The default Harbor install flow is built to:

- create the correct Windows folder layout
- create the named Docker volumes used by the SQLite-heavy services
- generate `.env`
- launch the stack from the repository root
- wire qBittorrent, SABnzbd, Prowlarr, Radarr, Sonarr, Lidarr, Recyclarr, Homepage, and the safety layers together
- leave only the account-linked and browser-only tasks for the operator

For a service-by-service view, use [SERVICE-SETUP.md](SERVICE-SETUP.md).

For autonomous-agent prompts, use [AI-SETUP.md](AI-SETUP.md).

## Recommended install flow

1. Clone the repository.
2. Run [`setup.ps1`](../setup.ps1).
3. Place the OpenVPN profile at `DOCKER_ROOT\gluetun\custom.ovpn`.
4. Start the stack if `setup.ps1` did not already do it.
5. Run [`scripts/bootstrap-media-stack.ps1`](../scripts/bootstrap-media-stack.ps1) if `setup.ps1` did not already do it.
6. Install the safe-update task.
7. Seed the safe-update status page.
8. Complete the small set of remaining browser-only tasks.
9. Run the verification checklist.

## Quick start commands

```powershell
git clone https://github.com/YOUR_GITHUB_USERNAME/harbor-media-server.git
cd harbor-media-server
.\setup.ps1
docker compose up -d --build
.\scripts\bootstrap-media-stack.ps1
.\scripts\install-update-task.ps1
.\scripts\safe-update-media-stack.ps1 -Preview
```

## What each stage does

| Stage | What it does | What it leaves to the operator |
|---|---|---|
| [`setup.ps1`](../setup.ps1) | Checks prerequisites, scans ports, prompts for values, creates directories, creates named volumes, seeds runtime templates, writes `.env`, optionally installs the update task, optionally launches the stack | Real VPN profile file, provider credentials, browser-only onboarding |
| `docker compose up -d --build` | Builds and launches the stack from the repository root | Nothing by itself |
| [`scripts/bootstrap-media-stack.ps1`](../scripts/bootstrap-media-stack.ps1) | Configures qBittorrent, SABnzbd, Radarr, Sonarr, Lidarr, Prowlarr, Recyclarr, Homepage, and the public indexer baseline | Plex claim, Overseerr first admin, private trackers, Usenet providers, premium NZB indexers, Cloudflare |
| [`scripts/safe-update-media-stack.ps1`](../scripts/safe-update-media-stack.ps1) | Pulls registry images, classifies updates, applies only safe bundles when not in preview mode, writes the update-status page | Repository-built services still update through git pull plus rebuild |

## What the bootstrap script configures

`bootstrap-media-stack.ps1` is the piece that turns Harbor from a pile of containers into a linked system.

It currently:

- logs into qBittorrent using the configured credentials or the bootstrap password from the container logs
- sets qBittorrent paths to `/downloads` and `/downloads/incomplete`
- binds qBittorrent to `tun0`
- disables qB random-port startup behavior and UPnP
- creates the expected qB categories:
  - `radarr`
  - `sonarr`
  - `lidarr`
  - `prowlarr`
  - `manual`
- configures SABnzbd paths, categories, host whitelist, and direct-unpack defaults
- configures a SAB provider automatically if the `SAB_SERVER_*` values are present in `.env`
- creates Radarr, Sonarr, and Lidarr root folders if needed
- adds qBittorrent and provider-gated SABnzbd as download clients in Radarr, Sonarr, and Lidarr
- adds Radarr, Sonarr, and Lidarr into Prowlarr
- adds qBittorrent and SABnzbd into Prowlarr
- adds a FlareSolverr proxy in Prowlarr
- seeds the default managed public torrent indexer set unless explicitly skipped
- adds a primary Newznab source automatically if `PROWLARR_NEWZNAB_*` is present
- seeds `AnimeTosho (Usenet)` automatically as a limited fallback when SAB provider values exist but no primary Newznab source is configured
- patches the runtime Recyclarr config with the real Radarr and Sonarr API keys
- generates the runtime Homepage services file using the current host and the stack values Harbor can discover safely
- adds the update-status page to Homepage

## Service automation matrix

| Service | Automated by `setup.ps1` | Automated by bootstrap | Still manual or account-linked |
|---|---|---|---|
| Gluetun | Folders, env placeholders, Compose wiring | No | Real `.ovpn` file and valid VPN credentials |
| qBittorrent | Folders and env placeholders | Login, paths, categories, `tun0` binding, safe defaults | None if bootstrap succeeds |
| SABnzbd | Folders and env placeholders | Paths, categories, provider bootstrap, Arr and Prowlarr links | Real provider and any premium NZB sources |
| Prowlarr | Container launch | App links, download clients, FlareSolverr, public indexer set, optional Newznab source | Private trackers and authenticated sources |
| Indexer Guardian | Container launch | Watches and repairs the managed public Prowlarr indexer set | Private trackers and any unmanaged public sources |
| Radarr | Container launch and named volume | Root folder and download clients | Custom movie policy beyond repo defaults |
| Sonarr | Container launch and named volume | Root folder and download clients | Custom television or anime policy beyond repo defaults |
| Lidarr | Container launch and named volume | Root folder and download clients | Music policy beyond repo defaults |
| Bazarr | Container launch and named volume | No | Subtitle providers and language strategy |
| FlareSolverr | Container launch | Prowlarr proxy object | Optional tag strategy changes |
| Plex | Container launch and mounts | No | Claim, login, libraries, remote-access decisions |
| Overseerr | Container launch | No | First admin setup and Plex connection |
| Immich | Container launch and database wiring | No | First admin login and client onboarding |
| Homepage | Runtime template seed | Runtime services file and safe widgets | Token-only widgets if desired |
| Pi-hole | Container launch | Homepage-ready route | Whether the wider network should use Pi-hole as DNS |
| Tdarr | Container launch and mounts | No | Libraries, workers, transcode workflow |
| Recyclarr | Template seed | Runtime API key patching | Optional release-profile changes |
| Safe update status | Placeholder files | Live report generation | Nothing if the default route is fine |
| download-orchestrator | Container launch | No | None |

## Safe update automation

Harbor's intended update path is:

```powershell
.\scripts\install-update-task.ps1
.\scripts\safe-update-media-stack.ps1 -Preview
.\scripts\safe-update-media-stack.ps1
```

Current behavior:

- `watchtower` monitors only
- the safe updater writes the status page to `http://localhost:8099`
- registry-backed containers update only when Harbor classifies the bundle as safe
- repository-built services update through git pull plus `docker compose up -d --build`
- protected or risky bundles can be deferred instead of applied automatically

## What remains manual

These tasks depend on user-owned accounts, tokens, or operator intent:

- Plex claim or login and final library confirmation
- Overseerr first admin onboarding
- private trackers and authenticated indexers in Prowlarr
- SAB provider details and premium NZB sources
- Cloudflare Tunnel creation, token issuance, and hostname routing
- token-only Homepage widgets such as Plex, Portainer, Immich, or Overseerr

## Optional bootstrap switches

Skip the default public indexer set:

```powershell
.\scripts\bootstrap-media-stack.ps1 -SkipProwlarrIndexers
```

Skip generated Homepage runtime config:

```powershell
.\scripts\bootstrap-media-stack.ps1 -SkipHomepageRuntime
```

## Recommended verification after bootstrap

Run:

```powershell
docker compose ps
docker logs qbittorrent --tail 50
docker logs sabnzbd --tail 50
docker logs prowlarr --tail 50
docker logs radarr --tail 50
docker logs sonarr --tail 50
docker logs lidarr --tail 50
docker logs homepage --tail 50
docker logs download-orchestrator --tail 50
docker logs indexer-guardian --tail 50
```

Then verify these endpoints:

- `http://localhost:3000`
- `http://localhost:8081`
- `http://localhost:8082`
- `http://localhost:9696`
- `http://localhost:7878`
- `http://localhost:8989`
- `http://localhost:8686`
- `http://localhost:5055`
- `http://localhost:32400/web`
- `http://localhost:8099`
- `http://127.0.0.1:9080/admin/`

## Common first-run blockers

| Symptom | Likely cause |
|---|---|
| Gluetun will not go healthy | Missing or invalid OpenVPN file or VPN credentials |
| qBittorrent is up but cannot download | VPN path issue, poor swarm quality, or no forwarded port |
| SABnzbd never receives jobs | No provider configured, or no useful NZB source configured |
| Arr apps show no releases | Prowlarr not seeded yet, or no working indexers available |
| Homepage cards load but widgets fail | Token- or API-key-dependent widgets still need manual setup |
| Plex remote access is not public | Cloudflare or router path has not been completed yet |
