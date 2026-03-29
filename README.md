# Harbor Media Server

A Windows-first, Docker Compose media stack for movies, TV, music, photos, subtitles, requests, ad blocking, AV scanning, transcoding, and dashboarding.

The stack is designed around four goals:
- keep torrent traffic pinned behind a VPN kill-switch
- keep the Arr/Plex stack interoperating cleanly
- self-heal common runtime failures
- keep all public repo files free of credentials and identity-specific values

This repository reflects the current structure of the live stack as of March 28, 2026.

## What is in the stack

| Service | Purpose | Port | Notes |
|---|---|---:|---|
| Gluetun | VPN tunnel and kill-switch | - | qBittorrent lives behind this namespace |
| qBittorrent | Torrent client | 8081 | Routed through Gluetun |
| port-updater | Syncs qB listen port to Gluetun forwarded port | - | Self-heals Proton port changes |
| Radarr | Movie automation | 7878 | Uses `/movies` |
| Sonarr | TV automation | 8989 | Uses `/tv` |
| Lidarr | Music automation | 8686 | Uses `/music` |
| Bazarr | Subtitle automation | 6767 | Connected to Radarr/Sonarr |
| Prowlarr | Indexer management | 9696 | Syncs indexers to Arr apps |
| FlareSolverr | Proxy for Cloudflare-protected indexers | 8191 | Optional per-indexer via tags |
| Plex | Media server | 32400 | GPU-enabled container configuration |
| Overseerr | Request portal | 5055 | Connected to Plex/Radarr/Sonarr |
| Immich Server | Photo/video management | 2283 | Depends on Redis/Postgres |
| Immich ML | Immich machine learning | - | Face/object search |
| Immich Redis | Immich cache | - | Internal only |
| Immich Postgres | Immich database | - | Internal only |
| ClamAV | Antivirus daemon | - | Scanner targets this daemon |
| scanner | Download safety scanner | - | Extension, header, and ClamAV checks |
| Unpackerr | Archive extraction for Arr | - | Optional but recommended |
| Tdarr | Library optimization and transcoding | 8265/8266 | CPU and GPU capable when NVENC is available |
| Homepage | Dashboard | 3000 | Service widgets and links |
| Pi-hole | DNS ad blocking | 53, 8080, 9080, 8443 | Uses Pi-hole v6 env keys and an alternate web UI origin |
| cloudflared | Cloudflare Tunnel connector | - | Optional public remote access path for Plex |
| Portainer | Docker UI | 9000 | Optional management UI |
| Recyclarr | TRaSH sync helper | - | Optional profile sync |
| Watchtower | Container updates | - | Automatic image updates |
| autoheal | Restarts unhealthy containers | - | Watches `autoheal=true` labels |

## Repository layout

Run Docker Compose from the repository root. Do not copy `docker-compose.yml` into `DOCKER_ROOT`; the repo contains build contexts such as `./scanner` and `./port-updater` that Compose needs locally.

```text
repo-root/
|-- .env.example
|-- docker-compose.yml
|-- download-orchestrator/
|-- setup.ps1
|-- scanner/
|-- port-updater/
|-- scripts/
|-- homepage/config/
`-- recyclarr/config/
```

## Runtime layout

The live stack is organized around two top-level roots.

```text
DOCKER_ROOT (example: D:\docker)
|-- gluetun/
|-- qbittorrent/config/
|-- sonarr/config/
|-- lidarr/config/
|-- bazarr/config/
|-- prowlarr/config/
|-- plex/config/
|-- plex/transcode/
|-- overseerr/config/
|-- immich/model-cache/
|-- immich/postgres/
|-- homepage/config/
|-- portainer/data/
|-- recyclarr/config/
|-- pihole/etc-pihole/
|-- pihole/etc-dnsmasq.d/
|-- scanner/logs/
`-- tdarr/
    |-- server/
    |-- configs/
    |-- logs/
    `-- transcode_cache/

Docker named volumes
|-- gluetun_port
|-- radarr_config
|-- sonarr_config
|-- lidarr_config
|-- bazarr_config
`-- prowlarr_config

DATA_ROOT (example: D:\NAS)
|-- downloads/
|   `-- incomplete/
|-- quarantine/
|-- photos/
`-- media/
    |-- movies/
    |-- tv/
    `-- music/
```

## Prerequisites

- Windows 10 or 11
- Docker Desktop running with Linux containers
- Git for Windows
- A VPN provider that supports OpenVPN credentials and port forwarding if you want the qB port-updater flow
- An NVIDIA GPU if you want Plex hardware transcoding or future Tdarr GPU work
- Two storage locations:
  - `DOCKER_ROOT` for configs and app state
  - `DATA_ROOT` for downloads, media, and photos

## Environment file

Copy `.env.example` to `.env` in the repository root and fill in the values.

```powershell
Copy-Item .env.example .env
notepad .env
```

Important values:

| Variable | Purpose |
|---|---|
| `DOCKER_ROOT` | Persistent app config root |
| `DATA_ROOT` | Media, downloads, and photos root |
| `TIMEZONE` | TZ database name such as `America/Los_Angeles` |
| `VPN_USERNAME` | VPN manual/OpenVPN username |
| `VPN_PASSWORD` | VPN manual/OpenVPN password |
| `QBIT_USER` | qBittorrent username used by the port-updater |
| `QBIT_PASS` | qBittorrent password used by the port-updater |
| `PIHOLE_PASSWORD` | Pi-hole web password |
| `IMMICH_DB_PASSWORD` | Immich Postgres password |
| `PLEX_ADVERTISE_IP` | Plex LAN advertise URL such as `http://192.168.1.100:32400/` |
| `CLOUDFLARE_TUNNEL_TOKEN` | Optional Cloudflare Tunnel run token for public Plex remote access |
| `RADARR_API_KEY` | Optional for Unpackerr/Recyclarr after first launch |
| `SONARR_API_KEY` | Optional for Unpackerr/Recyclarr after first launch |
| `LIDARR_API_KEY` | Optional for Unpackerr after first launch |

## Quick start

1. Clone the repo.

```powershell
git clone https://github.com/YOUR_GITHUB_USERNAME/harbor-media-server.git
cd harbor-media-server
```

2. Run the setup helper.

```powershell
.\setup.ps1
```

3. Put your OpenVPN config at:

```text
DOCKER_ROOT\gluetun\custom.ovpn
```

4. Start the stack from the repository root.

```powershell
docker compose up -d --build
```

The setup helper also creates the named Docker volumes used by the SQLite-heavy services before first launch:

- `radarr_config`
- `sonarr_config`
- `lidarr_config`
- `bazarr_config`
- `prowlarr_config`

## First launch checklist

After the containers are up, use this order so the integrations line up with the current stack.

1. Log into qBittorrent and set your permanent WebUI username/password.
2. In qBittorrent, set:
   - save path: `/downloads`
   - incomplete path: `/downloads/incomplete`
   - network interface: `tun0`
   - disable random port on startup
   - disable UPnP / NAT-PMP
3. In Prowlarr, add:
   - qBittorrent download client at `http://gluetun:8081`
   - Radarr app at `http://radarr:7878`
   - Sonarr app at `http://sonarr:8989`
   - Lidarr app at `http://lidarr:8686`
   - FlareSolverr proxy at `http://flaresolverr:8191`
4. In Radarr, Sonarr, and Lidarr, add qBittorrent using host `gluetun` and port `8081`.
5. In Overseerr, connect:
   - Plex at `http://plex:32400`
   - Radarr at `http://radarr:7878`
   - Sonarr at `http://sonarr:8989`
6. In Plex, create libraries from:
   - `/media/movies`
   - `/media/tv`
   - `/media/music`
   - `/media/photos`

## Current integration defaults

These are the intended defaults for the public stack today.

### qBittorrent categories

Use category names that match the Arr apps exactly:

- `radarr`
- `sonarr`
- `lidarr`
- optional fallback/manual category for Prowlarr manual grabs

### Arr root folders

- Radarr: `/movies`
- Sonarr: `/tv`
- Lidarr: `/music`

### Arr import behavior

Enable these in Radarr and Sonarr:

- Completed Download Handling
- rename imported files
- hardlinks instead of copy
- recycle bin path under `/downloads/.arr-recycle/...`

### Request / quality strategy

The current intended strategy is:

- prefer 1080p
- allow 720p only as fallback
- do not default the stack to 4K
- reject obvious theater releases

The live stack also uses reject terms such as:

- `CAM`
- `TS`
- `TC`
- `HDTS`
- `HDCAM`
- `TELESYNC`
- `TELECINE`

## What setup.ps1 does

The setup helper now assumes this repository is the Compose project root.

It will:
- check Docker/Git prerequisites
- scan the required ports
- collect `DOCKER_ROOT`, `DATA_ROOT`, timezone, qB, Pi-hole, Immich, and Plex advertise values
- create runtime directories under `DOCKER_ROOT` and `DATA_ROOT`
- create the named Docker volumes used by the SQLite-heavy media apps
- seed Homepage and Recyclarr template files into `DOCKER_ROOT`
- generate `.env` in the repository root
- optionally start the stack from the repository root

## Core architecture notes

### qBittorrent behind Gluetun

- `qbittorrent` uses `network_mode: "service:gluetun"`
- qB traffic is forced through the Gluetun namespace
- the Gluetun firewall acts as the kill-switch layer
- qB is expected to bind to `tun0` inside qB settings
- qB should not rely on UPnP or a random listen port

### Port-forward self-healing

The `port-updater` service watches Gluetun's forwarded port file and rewrites qB's saved port if they drift.

This protects the stack from a common Proton/Gluetun failure mode where the forwarded port changes but qB keeps listening on the old one.

The updater expects valid qB WebUI credentials in:

- `QBIT_USER`
- `QBIT_PASS`

### Download orchestrator

The repo now includes an optional `download-orchestrator` service behind the `experimental` profile.

Its job is to:
- keep qB focused on the healthiest and most finishable torrents for the current free-space budget
- dynamically narrow or widen qB's active queue window
- apply a reviewed safe set of qB speed/performance preferences
- detect broken `missingFiles` cases and prefer qB salvage before any replacement search
- issue tightly bounded Arr retry/search commands for high-confidence queue/import failures
- surface older backlog drift separately from the live repair lane

Its job is not to:
- change VPN provider settings
- change Gluetun killswitch or forwarded-port ownership logic
- rewrite Arr quality/import/profile settings
- change qB save paths, categories, auth, bind interface, or listen port
- take ownership of Plex, Tdarr, Pi-hole, Homepage, or unrelated services

Current control boundaries:
- tunnel/port-forward guard must be healthy before workload control is allowed
- protected qB settings and category-path baselines are checked every cycle
- torrent start/stop actions are stability-gated and cooldown-gated
- qB preference writes are stability-gated and cooldown-gated
- qB recovery actions and Arr repair actions have their own retry limits and cooldowns

Current live write tiers:
- queue window:
  - `max_active_downloads`
  - `max_active_torrents`
  - `max_active_uploads`
- network-lite speed tier:
  - `max_connec`
  - `max_connec_per_torrent`
  - `max_uploads_per_torrent`
  - `connection_speed`
  - `max_concurrent_http_announces`
- advanced reviewed tier:
  - `async_io_threads`
  - `disk_cache`
  - `disk_cache_ttl`
  - `disk_queue_size`
  - `request_queue_size`
  - `enable_piece_extent_affinity`
  - `enable_coalesce_read_write`
  - `send_buffer_*`
  - `socket_backlog_size`
  - `peer_turnover*`
  - `file_pool_size`
  - `checking_memory_use`

Unknown or newly introduced qB settings remain observation-only until explicitly reviewed.

Runtime state files written by the orchestrator:
- `/state/snapshot.json`
- `/state/orphan-report.json`
- `/state/qbit-preferences.json`
- `/state/runtime-state.json`

To run the experimental orchestrator profile:

```powershell
docker compose --profile experimental up -d --build download-orchestrator
```

### Autoheal

The stack includes explicit healthchecks for core services and an `autoheal` container that watches services labeled with `autoheal=true`.

This currently covers the core runtime stack such as:
- `gluetun`
- `qbittorrent`
- `port-updater`
- `radarr`
- `sonarr`
- `lidarr`
- `bazarr`
- `prowlarr`
- `plex`
- `overseerr`
- `homepage`
- `pihole`
- `immich-server`
- `clamav`
- `scanner`
- `tdarr`
- `cloudflared`

### Antivirus and quarantine flow

The `scanner` sidecar now runs in a conservative safe mode. It watches the downloads tree and checks files using three layers:

1. dangerous extension blocking
2. optional media header validation
3. ClamAV scanning after the file is old and stable

Important current behavior:
- suspicious files are quarantined instead of deleted
- incomplete files and Arr recycle bins are skipped
- files must be stable before they are scanned
- ClamAV transport/runtime errors do not mark a file as clean
- a periodic full-library ClamAV pass is available through `scanner/retro-media-clamscan.sh`

### SQLite-heavy service storage

Radarr, Sonarr, Lidarr, Bazarr, and Prowlarr use named Docker volumes for `/config` instead of writing their live SQLite databases directly to the Windows bind-mounted config folders.

That change exists to reduce recurring SQLite lock/corruption issues under sustained Arr/Prowlarr activity on the Windows filesystem path.

The old bind-mounted config folders can still exist on disk as migration/backup safety copies, but the live containers read and write through the named volumes listed in the runtime layout above.

## Service-specific setup notes

### qBittorrent

Recommended qB settings after first login:
- default save path: `/downloads`
- incomplete path: `/downloads/incomplete`
- network interface: `tun0`
- disable random port on startup
- disable UPnP/NAT-PMP
- use categories that match Arr apps: `radarr`, `sonarr`, `lidarr`
- use the same username/password in your local `.env` for `QBIT_USER` and `QBIT_PASS`

### Prowlarr

- add qBittorrent as an explicit download client
- add Radarr, Sonarr, and Lidarr as apps
- add FlareSolverr at `http://flaresolverr:8191`
- tags are optional for FlareSolverr
- only use tags if you want to scope the proxy to specific indexers
- leave app sync enabled so indexers propagate from Prowlarr into the Arr apps

### Radarr and Sonarr

Recommended interoperability settings:
- qB host: `gluetun`
- qB port: `8081`
- completed download handling: enabled
- hardlinks instead of copy: enabled
- rename imports: enabled
- recycle bins configured under `/downloads/.arr-recycle/...`

Recommended release preference scoring:

- Remux preferred over everything else
- BluRay preferred over WEB
- WEB-DL preferred over WEBRip
- HEVC preferred when available and device support is acceptable

Quality strategy used in the live stack:
- 1080p first
- 720p allowed only as fallback
- no 4K target profile in the default request flow
- reject obvious theater sources such as `CAM`, `TS`, `TC`, `HDTS`, `HDCAM`, `TELESYNC`, `TELECINE`

### Plex

Plex container paths are:
- movies: `/media/movies`
- TV: `/media/tv`
- music: `/media/music`
- photos: `/media/photos`
- transcode temp: `/transcode`

Recommended Plex settings:
- hardware acceleration enabled if NVIDIA runtime is available
- partial library scans enabled
- automatic trash emptying disabled
- transcode temp directory on `/transcode`
- advertise your LAN URL through `PLEX_ADVERTISE_IP`

Remote access options supported by this repo:
- Cloudflare Tunnel via `cloudflared` and `CLOUDFLARE_TUNNEL_TOKEN`
- direct port forwarding on `32400/TCP` if you prefer classic router-based remote access
- mesh VPN access such as Tailscale if you want private admin-only remote access

On WSL2/Windows hosts, the compose file mounts `/usr/lib/wsl/lib` into Plex so NVENC/NVDEC are available to the container when the host driver supports them.

### Overseerr

- connect to Plex at `http://plex:32400`
- connect to Radarr at `http://radarr:7878`
- connect to Sonarr at `http://sonarr:8989`
- default the movie/TV request profile to your 720p/1080p profile if you want 1080p-first with 720p fallback
- re-link Plex in Overseerr after a rebuild if the Plex machine ID changes

### Pi-hole

This repo uses Pi-hole v6-style env configuration, including:
- `FTLCONF_webserver_api_password`
- `FTLCONF_webserver_session_timeout`
- `FTLCONF_webserver_api_max_sessions`
- `FTLCONF_dns_listeningMode`

The current template keeps Pi-hole sessions long-lived and exposes both:
- `8080` as the primary web UI port
- `9080` as an alternate clean web UI origin if a browser gets stuck with stale site data

### Homepage

- keep widget keys and passwords out of Git
- use placeholders in tracked files only
- if you want tiles to work from devices other than the server itself, replace `localhost` hrefs with your server LAN IP or DNS name in the copied runtime config under `DOCKER_ROOT`

### Tdarr

Current repo configuration enables the NVIDIA runtime, mounts all media roots, and includes the WSL NVIDIA library path required for NVENC on supported Windows + WSL2 hosts.

What is safe to assume:
- Tdarr is useful today for both library scanning and transcode workflows
- the live stack has verified NVENC encoding with the bundled compose settings on supported hardware
- Plex hardware transcoding is also configured and validated separately
- you should still run a real encode test on your own hardware before assuming GPU throughput will match another host

## Homepage notes

The repo template uses `localhost` for browser-facing links and internal Docker hostnames for widgets where appropriate.

If you want Homepage to be usable from other devices on your LAN, change the `href` values in `homepage/config/services.yaml` from `localhost` to your server's LAN IP or DNS name.

## Backups

This repo now includes backup helpers under `scripts/`.

- `backup-media-stack.ps1` creates timestamped config backups
- `run-backup.cmd` is a task-friendly wrapper
- `install-backup-task.ps1` registers a Windows Task Scheduler job at 5:00 PM, 1:00 AM, and 9:00 AM
- you can schedule it with Windows Task Scheduler

The live stack uses a multi-run daily schedule rather than a single overnight run.

The provided task helper registers these run times:

- `5:00 PM`
- `1:00 AM`
- `9:00 AM`

## Updating

To update containers:

```powershell
docker compose pull
docker compose up -d
```

To update repo code:

```powershell
git pull origin main
```

## Troubleshooting

| Problem | Check |
|---|---|
| qB cannot download | Check `gluetun` health and forwarded port sync |
| Arr apps cannot import | Check categories, completed download handling, and root folders |
| Plex cannot see media | Check that the real files are under `DATA_ROOT\media\...` and mounted to `/media/...` |
| Homepage widgets fail | Check service URL vs widget URL mismatch and confirm API keys are local-only placeholders, not committed secrets |
| Pi-hole web UI fails | Confirm Pi-hole v6 env keys and password config, then try the alternate `9080` origin before assuming the password is wrong |
| Overseerr Plex sync fails | Re-link the current Plex machine ID and library IDs after a rebuild |
| Tdarr GPU jobs fail | Verify NVENC on the host before assuming the container config is enough |

## Known limitations

- Tdarr GPU encoding still depends on the host exposing working NVIDIA libraries into Docker.
- Plex remote access through Cloudflare Tunnel requires a real public domain in Cloudflare plus a valid tunnel run token.
- Homepage template files are intentionally placeholdered; real widget keys belong only in your untracked runtime config.

## Publishing safety

This repository is intended to stay free of:
- credentials
- API keys
- tokens
- local email addresses
- router credentials
- public IPs or tailnet IPs
- user-specific LAN identities beyond generic placeholders

Keep secrets only in untracked runtime config and `.env`.
