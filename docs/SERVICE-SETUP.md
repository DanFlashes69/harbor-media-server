# Harbor Media Server Service Setup Reference

This guide explains how each major Harbor service is intended to operate on a Windows host, what the repository configures automatically, and what still requires operator input.

Use it alongside [SETUP.md](SETUP.md) for the full installation flow.

## Core networking and download path

| Service | Role | What Harbor configures automatically | What still requires operator input |
|---|---|---|---|
| Gluetun | VPN tunnel and kill-switch namespace for qBittorrent and SABnzbd | Container wiring, healthcheck, mounts, namespace-guard compatibility | Real OpenVPN profile and valid VPN credentials |
| gluetun-namespace-guard | Restarts qB, SAB, and port-updater after a Gluetun namespace refresh | Full container wiring | Nothing |
| qBittorrent | Torrent client | WebUI bootstrap, safe defaults, `/downloads` paths, `tun0` binding, categories, Arr and Prowlarr integration | Real qB credentials in `.env` |
| SABnzbd | Optional Usenet client | Paths, categories, host whitelist, provider bootstrap, Arr and Prowlarr integration | Real provider credentials and any premium NZB sources |
| port-updater | Syncs qB listen port to the forwarded VPN port | Container wiring, forwarded-port file mount, qB auth, healthcheck | Valid qB credentials in `.env` |
| download-orchestrator | Active download selection, speed tuning, repair, and backlog sweep logic | Container, state directory, qB and Arr awareness, guarded writes, repair lanes | Nothing unless a different policy is desired |

## Indexing, requests, and automation

| Service | Role | What Harbor configures automatically | What still requires operator input |
|---|---|---|---|
| Prowlarr | Central indexer manager | App links, qB and SAB download clients, FlareSolverr proxy, public indexer set, optional Newznab source | Private trackers, authenticated sources, premium NZB sources |
| Indexer Guardian | Keeps the managed public indexer set healthy | Container, state directory, replacement logic, stale Arr cleanup | Private trackers and unmanaged sources |
| FlareSolverr | Proxy for Cloudflare-protected indexers | Container and Prowlarr proxy object | Optional tag strategy changes |
| Overseerr | Request portal | Container and network path | First admin setup and Plex link |
| Radarr | Movie automation | Root folder, qB client, SAB client, named-volume config | Movie-quality or release-policy changes beyond repo defaults |
| Sonarr | Television automation | Root folder, qB client, SAB client, named-volume config | Television or anime policy changes beyond repo defaults |
| Lidarr | Music automation | Root folder, qB client, SAB client, named-volume config | Music policy changes beyond repo defaults |
| Bazarr | Subtitle automation | Container and named-volume config | Subtitle providers and language scoring |
| Recyclarr | Profile and release-rule sync | Runtime API key patching and config template | Any custom quality or release profile tuning |
| Unpackerr | Archive extraction for Arr workflows | Container and mounts | Optional extraction tuning |

## Media serving and libraries

| Service | Role | What Harbor configures automatically | What still requires operator input |
|---|---|---|---|
| Plex | Serves movies, television, music, and photos | Container, mounts, transcode path, GPU wiring on supported hosts | Claim, login, libraries, and remote-access choices |
| Tdarr | Library optimization and transcoding | Container, mounts, GPU wiring on supported hosts | Library definitions, worker counts, and transcode rules |
| Immich Server | Photo and video library frontend | Container, database and Redis wiring, storage mounts | First admin setup and client onboarding |
| Immich ML | Immich machine-learning service | Container wiring | Nothing |
| Immich Redis | Immich cache | Container wiring | Nothing |
| Immich Postgres | Immich database | Container wiring and storage | Nothing beyond the password in `.env` |

## Dashboard, network services, and operations

| Service | Role | What Harbor configures automatically | What still requires operator input |
|---|---|---|---|
| Homepage | Unified dashboard | Runtime services file, safe widgets, generated links | Token-only widgets if desired |
| update-status | Safe-update report page | Placeholder files plus live reports from `safe-update-media-stack.ps1` | Nothing if the default route is acceptable |
| Pi-hole | DNS filtering and ad blocking | Container, v6 env keys, Homepage route and widget support | Whether the wider network should use Pi-hole as DNS |
| Portainer | Docker management UI | Container and port exposure | First admin login |
| cloudflared | Cloudflare Tunnel connector | Container and token wiring if the token is present | Tunnel creation, hostname mapping, and Cloudflare ownership |
| autoheal | Restarts unhealthy services | Container and label-based monitoring | Nothing |
| Watchtower | Image update monitor | Container in monitor-only mode | Nothing unless a different update policy is desired |

## Security and safety services

| Service | Role | What Harbor configures automatically | What still requires operator input |
|---|---|---|---|
| ClamAV | Antivirus daemon | Full container wiring and scanner target | Nothing unless signature behavior should be changed |
| scanner | Stable-file, quarantine-first download scanner | Container, mounts, ClamAV target, quarantine flow, header and extension checks | Optional stricter media-header validation |

## Internal service map

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
| update-status | `http://update-status:80` |

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

## What a fresh install already gets

After `setup.ps1`, `docker compose up -d --build`, and `scripts/bootstrap-media-stack.ps1`, a new Harbor install should already have:

- the correct folder layout
- the required named Docker volumes
- qBittorrent configured with Harbor-safe defaults
- SABnzbd prepared as a second downloader
- Radarr, Sonarr, and Lidarr linked to qBittorrent and staged for SABnzbd
- Prowlarr linked to the Arr apps, qBittorrent, SABnzbd, and FlareSolverr
- a managed public torrent indexer set in Prowlarr
- automatic public indexer cleanup and replacement through Indexer Guardian
- Homepage runtime links and core widgets
- the safe-update status page at `http://localhost:8099`
- Recyclarr runtime API keys filled in
- the orchestrator and repair loop running by default

The remaining tasks are primarily the account-linked pieces: Plex claim, Overseerr first admin, private trackers, SAB provider credentials, premium NZB sources, and Cloudflare.
