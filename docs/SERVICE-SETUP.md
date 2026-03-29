# Harbor Media Server Service Setup Reference

This guide explains how each major Harbor service is meant to be configured, what the repo automates already, and what still requires operator input.

Use this alongside [SETUP.md](SETUP.md) when you want the full "what does this service need" view.

## Core networking and download path

| Service | What it does | What Harbor configures automatically | What you still provide or confirm |
|---|---|---|---|
| Gluetun | VPN tunnel and kill-switch namespace for qBittorrent and SABnzbd | Compose wiring, volumes, healthcheck, namespace guard compatibility | Your real OpenVPN profile in `DOCKER_ROOT\gluetun\custom.ovpn` and your real VPN credentials in `.env` |
| gluetun-namespace-guard | Restarts shared-namespace services when Gluetun recreates its network namespace | Full container setup and restart logic | Nothing |
| qBittorrent | Torrent download client | WebUI login bootstrap, safe defaults, `tun0` binding, `/downloads` paths, categories, Arr/Prowlarr wiring | Real qB credentials in `.env`; optional UI tuning if you want different behavior |
| SABnzbd | Usenet download client | Container, paths, categories, Homepage tile, optional provider bootstrap from `.env` | Real Usenet provider, real NZB indexers, optional retention/server tuning |
| port-updater | Syncs qB's listen port to the forwarded VPN port | Full container setup, Gluetun port-file mount, qB auth from `.env`, healthcheck | Valid qB credentials in `.env` |
| download-orchestrator | Keeps qB focused on finishable, healthy downloads, rotates away from dead swarms, and handles bounded repair/retry logic | Optional compose service, state directory, qB/Arr awareness, non-interference guardrails | Decide whether to run the `experimental` profile |

## Indexing, requests, and automation

| Service | What it does | What Harbor configures automatically | What you still provide or confirm |
|---|---|---|---|
| Prowlarr | Central indexer manager | qB and SAB download clients, Radarr/Sonarr/Lidarr app links, FlareSolverr proxy, starter public torrent pack, optional primary Newznab bootstrap from `.env` | Private trackers, authenticated indexers, NZB indexers, any provider-specific tuning |
| Indexer Guardian | Keeps Harbor-managed public indexers healthy | Container, state directory, managed-slot monitoring, repeated-failure replacement logic, stale Arr indexer cleanup | Any public-indexer strategy changes outside the Harbor-managed pack, plus all private/authenticated trackers |
| FlareSolverr | Proxy for Cloudflare-protected indexers | Container and Prowlarr proxy object | Nothing unless you want a different tagging strategy |
| Overseerr | User request portal | Container and network path | First admin onboarding, Plex authentication, request defaults |
| Radarr | Movie automation | Root folder, qB client, staged-disabled SAB client, named-volume storage | Any movie-quality/profile decisions beyond the included defaults |
| Sonarr | TV automation | Root folder, qB client, staged-disabled SAB client, named-volume storage | Any TV/anime policy decisions beyond the included defaults |
| Lidarr | Music automation | Root folder, qB client, staged-disabled SAB client, named-volume storage | Music-quality/profile decisions beyond the included defaults |
| Bazarr | Subtitle automation | Container and named-volume storage | Subtitle providers, language preferences, custom scoring |
| Recyclarr | Sync helper for release/profile guidance | Runtime config template, runtime API key patching | Any profile customizations beyond the included baseline |
| Unpackerr | Extracts archives for Arr workflows | Container and mounts | Nothing unless you want to customize extraction behavior |

## Media serving and libraries

| Service | What it does | What Harbor configures automatically | What you still provide or confirm |
|---|---|---|---|
| Plex | Streams the finished media library | Container, media mounts, transcode mount, GPU/NVENC wiring for supported hosts | First login or claim, library creation, optional remote-access choices |
| Tdarr | Library optimization and transcode workflows | Container, media mounts, GPU/NVENC wiring for supported hosts | Worker counts, libraries, and actual transcode workflows |
| Immich Server | Photo/video library frontend | Container, database/Redis wiring, storage mounts | First admin login and any mobile client/API setup |
| Immich ML | Immich machine-learning sidecar | Container wiring | Nothing |
| Immich Redis | Immich cache | Container wiring | Nothing |
| Immich Postgres | Immich database | Container wiring and storage | Nothing beyond your chosen database password in `.env` |

## Dashboard, network services, and operations

| Service | What it does | What Harbor configures automatically | What you still provide or confirm |
|---|---|---|---|
| Homepage | Unified dashboard | Runtime `services.yaml` generation for the main stack, safe widgets for services Harbor can auto-wire | Optional token-only widgets for Plex, Portainer, Immich, or Overseerr |
| update-status | Human-readable safe-update report page | Placeholder files from setup plus live report generation from `safe-update-media-stack.ps1` | Nothing if you keep the default `http://localhost:8099` route |
| Pi-hole | DNS filtering and ad blocking | Container, v6 env configuration, Homepage widget-ready routing | Decide whether only the server or the wider network should use it as DNS |
| Portainer | Docker UI | Container and port exposure | First admin login |
| cloudflared | Cloudflare Tunnel connector | Container and compose wiring if the token is present in `.env` | Cloudflare tunnel creation, hostname routing, domain ownership |
| autoheal | Restarts unhealthy services | Full container wiring and label-based monitoring | Nothing |
| Watchtower | Image update monitor | Full container wiring | Monitor-only by default; Harbor safe-update scripts decide when updates are applied |

## Security and safety services

| Service | What it does | What Harbor configures automatically | What you still provide or confirm |
|---|---|---|---|
| ClamAV | Antivirus daemon | Full container setup and scanner target | Nothing unless you want different signature/update behavior |
| scanner | Quarantine-first download safety scanner | Full container setup, stable-file logic, quarantine flow, ClamAV wiring | Optional media-header validation if you want stricter checks |

## Default internal service map

These are the main internal URLs Harbor expects when the stack is running:

| Service | Internal URL |
|---|---|
| qBittorrent | `http://gluetun:8081` |
| SABnzbd | `http://gluetun:8080` |
| Radarr | `http://radarr:7878` |
| Sonarr | `http://sonarr:8989` |
| Lidarr | `http://lidarr:8686` |
| Prowlarr | `http://prowlarr:9696` |
| FlareSolverr | `http://flaresolverr:8191` |
| Plex | `http://plex:32400` |
| Overseerr | `http://overseerr:5055` |
| Immich | `http://immich-server:2283` |
| Tdarr | `http://tdarr:8265` |
| Pi-hole | `http://pihole:80` |
| Update status | `http://update-status:80` |

## Default Harbor paths

| Purpose | Path |
|---|---|
| qB completed downloads | `/downloads` |
| qB incomplete downloads | `/downloads/incomplete` |
| SAB incomplete downloads | `/downloads/usenet/incomplete` |
| SAB complete downloads | `/downloads/usenet/complete` |
| Radarr root | `/movies` |
| Sonarr root | `/tv` |
| Lidarr root | `/music` |
| Plex movies | `/media/movies` |
| Plex TV | `/media/tv` |
| Plex music | `/media/music` |
| Plex photos | `/media/photos` |
| Scanner quarantine | `/quarantine` |

## What the repo gets close to out of the box

After `setup.ps1`, `docker compose up -d --build`, and `scripts/bootstrap-media-stack.ps1`, a new Harbor install should already have:

- the right directory structure
- the right named Docker volumes
- qBittorrent configured with Harbor-safe defaults
- SABnzbd configured as an optional secondary downloader
- SABnzbd able to become fully active automatically if the `.env` contains a real Usenet provider and Newznab indexer
- Radarr, Sonarr, and Lidarr linked to qBittorrent and staged for SABnzbd
- Prowlarr linked to the Arr apps, qBittorrent, SABnzbd, and FlareSolverr
- a starter public torrent indexer pack in Prowlarr unless you skipped it
- that starter public pack managed by the Indexer Guardian, so broken Harbor-managed public indexers can be replaced automatically without touching private trackers
- Homepage runtime links and key widgets
- the safe-update status page reachable on `http://localhost:8099`
- Recyclarr runtime keys filled in

The remaining tasks are mostly account-linked services such as Plex claim, Overseerr onboarding, Cloudflare, private trackers, and Usenet providers.
