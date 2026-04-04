# Harbor Media Server

Harbor Media Server is a Windows-first Docker media platform that turns a single PC into a private streaming service, request portal, download pipeline, photo library, and operations dashboard.

Overseerr handles requests. Prowlarr manages indexers. Radarr, Sonarr, and Lidarr automate movies, television, and music. qBittorrent handles torrents behind Gluetun's VPN kill-switch. SABnzbd adds an optional Usenet path without replacing the torrent workflow. Bazarr manages subtitles. Plex serves the finished library. Immich manages personal photos and videos. Pi-hole provides DNS filtering. Tdarr handles library optimization. Homepage ties everything together, while ClamAV, the scanner, the download orchestrator, the Indexer Guardian, autoheal, and the safe-update flow add safety, repair, and operational resilience.

The goal is simple: request content, let Harbor acquire it safely, organize it into the correct library, recover from common failures automatically, and keep the entire stack visible from one dashboard.

## Why Harbor Media Server

| Capability | Typical media server | Harbor Media Server |
|---|---|---|
| Streaming | Playback only | Plex plus requests, acquisition, organization, recovery, and remote-access options |
| Requests | Manual or missing | Overseerr feeds directly into the automation pipeline |
| Downloads | Unmanaged or exposed directly | qBittorrent behind Gluetun and an optional SABnzbd path |
| Automation | Partial or fragmented | Radarr, Sonarr, Lidarr, Prowlarr, and Bazarr operate as one pipeline |
| Photos and personal media | Separate app or service | Immich is part of the same stack |
| Safety | Basic app defaults | ClamAV, quarantine-first scanning, guarded orchestration, and healthchecks |
| Recovery | Manual queue babysitting | Automated retry, salvage, bounded repair, and backlog sweeping |
| Visibility | Multiple disconnected web interfaces | Homepage, healthchecks, autoheal, and a live update status page |
| Updates | Manual image pulls or blind auto-updates | Guarded safe-update workflow with deferred high-risk bundles |
| Overall experience | A collection of separate containers | One self-hosted media platform with a clear operating model |

## What is in the stack

| Service | Purpose | Port | Notes |
|---|---|---:|---|
| Gluetun | VPN tunnel and kill-switch | - | qBittorrent and SABnzbd share this namespace |
| qBittorrent | Torrent client | 8081 | Routed through Gluetun |
| SABnzbd | Usenet client | 8082 | Optional secondary downloader behind Gluetun |
| port-updater | Syncs qB listen port to the forwarded VPN port | - | Keeps Gluetun and qB aligned |
| gluetun-namespace-guard | Restarts shared-namespace services after a Gluetun restart | - | Protects qB, SAB, and port-updater |
| download-orchestrator | qB workload, speed, backlog, and repair controller | - | Included by default |
| Radarr | Movie automation | 7878 | Uses `/movies` |
| Sonarr | Television automation | 8989 | Uses `/tv` |
| Lidarr | Music automation | 8686 | Uses `/music` |
| Bazarr | Subtitle automation | 6767 | Connected to Radarr and Sonarr |
| Prowlarr | Indexer management | 9696 | Syncs indexers to the Arr apps |
| Indexer Guardian | Public indexer replacement and cleanup | - | Keeps the managed public indexer set healthy |
| FlareSolverr | Proxy for Cloudflare-protected indexers | 8191 | Optional by tag in Prowlarr |
| Plex | Media server | 32400 | GPU-enabled container configuration |
| Overseerr | Request portal | 5055 | Connected to Plex, Radarr, and Sonarr |
| Immich Server | Photo and video management | 2283 | Depends on Redis and Postgres |
| Immich ML | Immich machine learning | - | Face and object recognition |
| Immich Redis | Immich cache | - | Internal only |
| Immich Postgres | Immich database | - | Internal only |
| ClamAV | Antivirus daemon | - | Scanner target |
| scanner | Download safety scanner | - | Quarantine-first workflow |
| Unpackerr | Archive extraction for Arr workflows | - | Optional but recommended |
| Tdarr | Library optimization and transcoding | 8265 / 8266 | CPU and GPU capable |
| Homepage | Dashboard | 3000 | Service widgets and links |
| Pi-hole | DNS ad blocking | 53, 8080, 9080, 8443 | Includes alternate local web origin |
| cloudflared | Cloudflare Tunnel connector | - | Optional remote-access path for Plex |
| update-status | Safe-update report page | 8099 | Shows applied, deferred, and blocked updates |
| Portainer | Docker UI | 9000 | Optional management interface |
| Recyclarr | TRaSH sync helper | - | Optional quality/profile sync |
| Watchtower | Image update monitor | - | Monitor-only by default |
| autoheal | Restarts unhealthy containers | - | Watches `autoheal=true` labels |

## Repository layout

Run Docker Compose from the repository root. The repo contains build contexts such as `./scanner`, `./port-updater`, `./download-orchestrator`, `./indexer-guardian`, and `./gluetun-namespace-guard`, so `docker-compose.yml` should stay here.

```text
repo-root/
|-- .env.example
|-- docker-compose.yml
|-- docs/
|-- download-orchestrator/
|-- indexer-guardian/
|-- gluetun-namespace-guard/
|-- homepage/config/
|-- port-updater/
|-- recyclarr/config/
|-- scanner/
|-- scripts/
`-- setup.ps1
```

## Runtime layout

Harbor uses two top-level roots on the Windows host.

```text
DOCKER_ROOT (example: D:\docker)
|-- gluetun/
|-- qbittorrent/config/
|-- sabnzbd/config/
|-- plex/config/
|-- plex/transcode/
|-- overseerr/config/
|-- homepage/config/
|-- pihole/etc-pihole/
|-- pihole/etc-dnsmasq.d/
|-- scanner/logs/
|-- tdarr/
|   |-- server/
|   |-- configs/
|   |-- logs/
|   `-- transcode_cache/
|-- immich/model-cache/
|-- immich/postgres/
|-- recyclarr/config/
|-- indexer-guardian/
`-- portainer/data/

Named Docker volumes
|-- radarr_config
|-- sonarr_config
|-- lidarr_config
|-- bazarr_config
|-- prowlarr_config
`-- gluetun_port

DATA_ROOT (example: D:\media)
|-- downloads/
|   |-- incomplete/
|   `-- usenet/
|       |-- complete/
|       `-- incomplete/
|-- media/
|   |-- movies/
|   |-- tv/
|   `-- music/
|-- photos/
`-- quarantine/
```

## Host requirements

- Windows 10 or Windows 11
- Docker Desktop running Linux containers
- Git for Windows
- Two storage roots:
  - `DOCKER_ROOT` for app state and runtime config
  - `DATA_ROOT` for downloads, media, photos, and quarantine
- A VPN provider that supports OpenVPN credentials and forwarded ports if the qB port-updater flow is required
- A valid OpenVPN profile file for Gluetun
- An NVIDIA GPU if Plex hardware transcoding or Tdarr GPU work is required
- A Usenet provider account if SABnzbd should handle real jobs

## Environment file

Copy `.env.example` to `.env` and fill in the values before the first launch.

```powershell
Copy-Item .env.example .env
notepad .env
```

Important values:

| Variable | Purpose |
|---|---|
| `DOCKER_ROOT` | Persistent app-state root |
| `DATA_ROOT` | Media, download, and photo root |
| `SERVER_HOST` | Hostname or LAN IP used for generated Homepage links |
| `TIMEZONE` | TZ database name such as `America/Los_Angeles` |
| `VPN_USERNAME` / `VPN_PASSWORD` | OpenVPN credentials for Gluetun |
| `QBIT_USER` / `QBIT_PASS` | qBittorrent WebUI credentials used by Harbor services |
| `PIHOLE_PASSWORD` | Pi-hole web password |
| `IMMICH_DB_PASSWORD` | Immich Postgres password |
| `PLEX_ADVERTISE_IP` | Plex advertise URL such as `http://192.168.1.100:32400/` |
| `CLOUDFLARE_TUNNEL_TOKEN` | Optional Cloudflare Tunnel token |
| `SAB_SERVER_*` | Optional SABnzbd provider settings |
| `PROWLARR_NEWZNAB_*` | Optional Newznab or NZB indexer settings |

## Public documentation

- [docs/SETUP.md](docs/SETUP.md): full Windows-first setup guide
- [docs/SERVICE-SETUP.md](docs/SERVICE-SETUP.md): service-by-service setup reference
- [docs/AI-SETUP.md](docs/AI-SETUP.md): prompts for Codex, Claude, and other autonomous agents

## Quick start

1. Clone the repository.

```powershell
git clone https://github.com/YOUR_GITHUB_USERNAME/harbor-media-server.git
cd harbor-media-server
```

2. Run the setup helper.

```powershell
.\setup.ps1
```

3. Place the OpenVPN profile at:

```text
DOCKER_ROOT\gluetun\custom.ovpn
```

4. Start the stack if `setup.ps1` did not already launch it.

```powershell
docker compose up -d --build
```

5. Run the bootstrap script if `setup.ps1` did not already run it.

```powershell
.\scripts\bootstrap-media-stack.ps1
```

6. Install the safe-update task and seed the status page.

```powershell
.\scripts\install-update-task.ps1
.\scripts\safe-update-media-stack.ps1 -Preview
```

## What the setup flow automates

| Stage | What it configures automatically | What still needs user input |
|---|---|---|
| `setup.ps1` | Preflight checks, port scan, `.env` generation, runtime directories, named volumes, runtime template copies, update-status placeholder files, optional scheduled task, optional first launch | Real `.ovpn` file, external account credentials, browser-only onboarding |
| `docker compose up -d --build` | Builds and launches the containers from the repository root | Nothing by itself |
| `scripts/bootstrap-media-stack.ps1` | qBittorrent defaults, SABnzbd defaults, Arr root folders, qB and SAB clients in Arr and Prowlarr, Prowlarr app links, FlareSolverr proxy, public indexer set, Recyclarr runtime API keys, runtime Homepage services file, update-status Homepage link | Plex claim, Overseerr onboarding, private trackers, premium NZB indexers, Cloudflare hostname work, token-only Homepage widgets |
| `scripts/safe-update-media-stack.ps1` | Registry image pulls, safe bundle decisions, deferred-risk handling, update report generation | Repository-built services still update through git pull plus rebuild |

## What still needs manual setup

These tasks are intentionally left to a human or a browser-capable autonomous agent because they depend on personal accounts, tokens, or operator choices:

1. Plex claim or login and final library confirmation
2. Overseerr first admin setup and Plex connection
3. Private or authenticated tracker setup in Prowlarr
4. SABnzbd provider credentials and any premium NZB indexers
5. Cloudflare Tunnel creation, token generation, and hostname routing
6. Optional token-only Homepage widgets such as Plex, Portainer, Immich, or Overseerr

## Update strategy

Harbor does not rely on blind container auto-updates.

Recommended update flow:

```powershell
.\scripts\install-update-task.ps1
.\scripts\safe-update-media-stack.ps1 -Preview
.\scripts\safe-update-media-stack.ps1
```

Current behavior:

- `watchtower` is monitor-only
- the safe updater writes the status page to `http://localhost:8099`
- registry-backed services update only when the update bundle is classified as safe
- repository-built services update through git pull plus `docker compose up -d --build`
- higher-risk bundles can be deferred instead of being applied automatically

## Core behavior

Harbor includes three operational layers beyond the application containers themselves.

### Download orchestrator

The download orchestrator continuously watches qBittorrent, the Arr apps, and free disk space. It keeps the active download window narrow when space is tight, prefers finishable downloads over dead backlog, rotates away from non-moving swarms, and can trigger bounded repair for broken or missing downloads.

### Indexer Guardian

Indexer Guardian watches the managed public Prowlarr indexer set. When a public indexer repeatedly fails and matches Harbor's replacement rules, it can retire that slot, seed the closest replacement, and clean stale copies out of the Arr apps without touching private trackers.

### Safe-update flow

The safe-update scripts classify container updates into safe, manual, deferred, and blocked decisions. The result is visible on the update-status page so updates remain transparent instead of silently mutating the stack.

## Current integration defaults

| Integration | Default |
|---|---|
| qB WebUI | `http://localhost:8081` |
| SABnzbd | `http://localhost:8082` |
| Homepage | `http://localhost:3000` |
| Radarr | `http://localhost:7878` |
| Sonarr | `http://localhost:8989` |
| Lidarr | `http://localhost:8686` |
| Prowlarr | `http://localhost:9696` |
| Overseerr | `http://localhost:5055` |
| Immich | `http://localhost:2283` |
| Tdarr | `http://localhost:8265` |
| Portainer | `http://localhost:9000` |
| Pi-hole | `http://127.0.0.1:9080/admin/` |
| Safe update status | `http://localhost:8099` |

## Troubleshooting

| Symptom | Likely cause | First checks |
|---|---|---|
| qBittorrent UI loads but downloads never move | VPN path or swarm quality problem | Check Gluetun health, qB bind interface, port-updater logs, and orchestrator snapshot |
| Arr apps show stuck queue items | Broken downloads or missing imports | Check `download-orchestrator` logs and `D:\docker\download-orchestrator\orphan-report.json` |
| Homepage widgets fail | Missing token, stale API key, or app auth issue | Check runtime `D:\docker\homepage\config\services.yaml` and service API health |
| Pi-hole works but login loops | Browser-origin cookie issue | Use `http://127.0.0.1:9080/admin/` and close stale tabs |
| SABnzbd stays idle | No provider or no useful NZB source configured | Fill in `SAB_SERVER_*` and optional `PROWLARR_NEWZNAB_*` values |
| Sonarr or Radarr mention app updates | Container image lag versus upstream app notice | Check `safe-update-media-stack.ps1 -Preview` and the update-status page |

## Known limitations

- Public torrent swarms can still be slow or dead even when Harbor is healthy
- SABnzbd cannot download real jobs without a Usenet provider
- Cloudflare remote access still requires user-owned Cloudflare infrastructure
- Plex hardware transcoding depends on the host GPU, driver stack, and Plex Pass
- Some first-time onboarding steps remain browser-only by design
