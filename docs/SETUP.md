# Harbor Media Server Setup Guide

This is the recommended install path when you want Harbor to do as much of the heavy lifting as possible without committing personal credentials or forcing unsafe defaults into the repository.

## Setup goals

The setup flow is designed to get a new machine as close as possible to the current live Harbor stack with minimal manual interaction:

- create the correct folder layout
- create the named Docker volumes used by the SQLite-heavy services
- generate `.env`
- launch the stack from the repository root
- wire qBittorrent, SABnzbd, Radarr, Sonarr, Lidarr, Prowlarr, the Indexer Guardian, Recyclarr, and Homepage together
- leave only account-linked or browser-only tasks for the operator or an autonomous browser agent

If you want the version tailored for autonomous agents, see [AI-SETUP.md](AI-SETUP.md).

If you want the service-by-service reference, see [SERVICE-SETUP.md](SERVICE-SETUP.md).

## Recommended install flow

1. Clone the repository.
2. Run [`setup.ps1`](../setup.ps1).
3. Place your OpenVPN profile at `DOCKER_ROOT\gluetun\custom.ovpn`.
4. Start the stack if `setup.ps1` did not already do it for you.
5. Run [`scripts/bootstrap-media-stack.ps1`](../scripts/bootstrap-media-stack.ps1) if `setup.ps1` did not already do it for you.
6. Install the daily safe-update task and seed the update status page.
7. Finish the small set of account-linked tasks that cannot be safely automated without your credentials or your browser session.

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

## What each stage configures

| Stage | What it does | What it leaves for you |
|---|---|---|
| [`setup.ps1`](../setup.ps1) | Checks prerequisites, scans ports, prompts for values, creates directories, creates named volumes, seeds Homepage/Recyclarr runtime templates, seeds update-status placeholders, writes `.env`, optionally installs the safe-update task, optionally launches the stack, optionally launches the bootstrap | Real `.ovpn` file, external account credentials you do not want in `.env`, browser-only onboarding |
| `docker compose up -d --build` | Builds and launches the stack from the repository root | None by itself; this is the runtime start step |
| [`scripts/bootstrap-media-stack.ps1`](../scripts/bootstrap-media-stack.ps1) | Configures qBittorrent, SABnzbd, Radarr, Sonarr, Lidarr, Prowlarr, Recyclarr, and the runtime Homepage config | Plex claim/onboarding, Overseerr first admin, private trackers, Usenet providers, Cloudflare domain routing, token-only Homepage widgets |
| [`scripts/safe-update-media-stack.ps1`](../scripts/safe-update-media-stack.ps1) | Pulls registry images, evaluates Harbor update safety rules, applies only the safe bundle updates in non-preview mode, and writes the live update report page | Repository-built services still update by git pull plus rebuild, and protected bundles may still require review |

## What the bootstrap script configures

The bootstrap phase is where Harbor becomes a linked stack instead of a pile of containers.

It currently:

- logs into qBittorrent using the `.env` credentials or the one-time temporary qB bootstrap password from container logs
- sets qBittorrent paths to `/downloads` and `/downloads/incomplete`
- forces qBittorrent to bind to `tun0`
- disables qB random-port startup behavior and UPnP
- creates the expected qB categories:
  - `radarr`
  - `sonarr`
  - `lidarr`
  - `prowlarr`
  - `manual`
- configures SABnzbd paths, categories, direct-unpack defaults, and host whitelist
- configures a SABnzbd server automatically if you provide `SAB_SERVER_*` values in `.env`
- creates Radarr, Sonarr, and Lidarr root folders if they do not already exist
- adds qBittorrent and staged-disabled SABnzbd download clients to Radarr, Sonarr, and Lidarr
- adds Radarr, Sonarr, and Lidarr into Prowlarr
- adds qBittorrent and staged-disabled SABnzbd into Prowlarr
- adds a FlareSolverr proxy in Prowlarr
- adds a primary Newznab indexer automatically if you provide `PROWLARR_NEWZNAB_*` values in `.env`
- seeds a curated public torrent indexer pack in Prowlarr unless you skip it
- seeds that public pack as Harbor-managed slots so the Indexer Guardian can replace broken public indexers automatically
- updates the runtime Recyclarr config with the real Radarr and Sonarr API keys
- generates a working runtime Homepage services file using the current host, API keys, and passwords the stack can safely discover
- adds the safe-update status page link to Homepage

## Service setup matrix

| Service | Automated by `setup.ps1` | Automated by bootstrap | Still manual or account-linked |
|---|---|---|---|
| Gluetun | Folders, env placeholders, Compose service | No | Provide the real `.ovpn` file and valid VPN credentials |
| qBittorrent | Folders, env placeholders | Login, WebUI credentials, safe defaults, categories, `tun0` binding, runtime config patch | None if bootstrap succeeds |
| SABnzbd | Folders, env placeholders | Runtime config, paths, categories, staged Arr and Prowlarr integration | Add a real Usenet provider and at least one NZB indexer if you want real Usenet jobs |
| Prowlarr | Container launch | App links, download clients, FlareSolverr proxy, default public torrent indexers | Private trackers, authenticated indexers, any provider-specific tuning |
| Indexer Guardian | State directory and container launch | Monitors Harbor-managed public Prowlarr slots, replaces broken public indexers with validated alternatives, and cleans stale Arr-side copies | Private trackers and any indexers you do not want Harbor to manage |
| Radarr | Container launch, named volume | qB and SAB clients, root folder | Quality/profile tuning beyond the included baseline |
| Sonarr | Container launch, named volume | qB and SAB clients, root folder | Anime strategy, quality/profile tuning beyond the included baseline |
| Lidarr | Container launch, named volume | qB and SAB clients, root folder | Music-specific profile strategy |
| Bazarr | Container launch, named volume | No | Subtitle providers and any custom language scoring |
| FlareSolverr | Container launch | Prowlarr proxy object | None if you keep the default tag strategy |
| Plex | Container launch, media mounts, GPU wiring | No | First login or claim, library confirmation, optional remote-access polish |
| Overseerr | Container launch | No | First admin login, Plex authentication, optional request defaults |
| Immich | Container launch, folders, database | No | First admin login, API key creation, mobile app onboarding |
| Homepage | Template seed | Runtime service links and safe widgets | Token-only widgets such as Plex, Portainer, Immich, or Overseerr if you want them |
| Safe update status | Placeholder status files | Live report generation through `safe-update-media-stack.ps1` | None if you keep the default `http://localhost:8099` path |
| Pi-hole | Container launch | Homepage widget-ready runtime config | Decide whether only the server or your wider network should actually use Pi-hole as DNS |
| Tdarr | Container launch, WSL GPU path | No | Custom libraries, worker counts, and transcode workflow decisions |
| Recyclarr | Template seed | Runtime Radarr and Sonarr API keys | Any profile or release-preference tuning beyond the included baseline |
| cloudflared | Container launch if token is present | No | Cloudflare tunnel creation, domain routing, and hostname publication |
| Portainer | Container launch | No | First admin login |
| autoheal | Container launch | No | None |
| Watchtower | Container launch | No | Monitor-only by default; Harbor safe-update scripts decide when updates are applied |
| download-orchestrator | Optional container launch behind the experimental profile | No | Choose whether to run the orchestrator profile at all |

## Safe update automation

Harbor's recommended update flow is:

1. install the scheduled task
2. run a preview pass to see what Harbor would update
3. let the task or a manual non-preview run apply only the safe bundle updates

```powershell
.\scripts\install-update-task.ps1
.\scripts\safe-update-media-stack.ps1 -Preview
.\scripts\safe-update-media-stack.ps1
```

Current behavior:

- `watchtower` is monitor-only
- the safe updater writes the report page to `http://localhost:8099`
- registry-backed services update only when Harbor decides the bundle is safe
- repository-built services still update through git pull plus `docker compose up -d --build`
- protected bundles such as Pi-hole or complex stacks such as Immich are intentionally deferred for review

## What is still intentionally manual

These pieces either require your personal accounts or are safer to confirm in a browser:

- Plex first-time claim/login and library confirmation
- Overseerr first admin onboarding and Plex connection
- Cloudflare Tunnel domain routing and token creation
- private tracker setup in Prowlarr
- Usenet provider details and premium NZB indexers
- token-only Homepage widgets
- any custom quality-profile or release-profile tuning beyond the included defaults
- any public-indexer strategy changes beyond the default Harbor-managed pack

## Optional bootstrap switches

Skip the default Prowlarr public indexer pack:

```powershell
.\scripts\bootstrap-media-stack.ps1 -SkipProwlarrIndexers
```

Skip generated Homepage runtime config:

```powershell
.\scripts\bootstrap-media-stack.ps1 -SkipHomepageRuntime
```

## Recommended verification after bootstrap

Run these checks after the bootstrap completes:

```powershell
docker compose ps
docker logs qbittorrent --tail 50
docker logs sabnzbd --tail 50
docker logs prowlarr --tail 50
docker logs radarr --tail 50
docker logs sonarr --tail 50
docker logs lidarr --tail 50
docker logs homepage --tail 50
```

Then open:

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

## When to use the AI-assisted setup flow

Use the AI-assisted setup flow when you want an autonomous agent to:

- run the scripts for you
- finish the remaining browser-only setup in Plex or Overseerr
- add authenticated indexers or providers
- perform a final top-to-bottom verification pass

See [AI-SETUP.md](AI-SETUP.md) for ready-to-paste prompts.
