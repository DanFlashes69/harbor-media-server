# Harbor to Synology DS224+ Migration

This guide covers the most effective Harbor migration path from the current Windows PC deployment to a Synology DS224+.

## Recommended target architecture

Use a NAS-primary, PC-accelerator design.

## Current live migration state

The migration is already underway.

- DSM is installed and reachable at `synology.example.lan`
- Storage is configured as:
  - `SHR`
  - `Btrfs`
  - one main `Volume 1`
- `SSH` is enabled
- `SMB` is enabled
- Shared folders created on the NAS:
  - `docker`
  - `media`
  - `downloads`
  - `photos`
  - `quarantine`
  - `backups`
- Synology packages installed:
  - `Container Manager`
  - `Hyper Backup`
  - `Text Editor`
  - `Tailscale`
- Harbor runtime/config data has already started landing in:
  - `\\synology.example.lan\docker\harbor\appdata`
- The Harbor stack copy is staged at:
  - `\\synology.example.lan\docker\harbor\stacks\harbor-media-server`
- Initial data sync is active for:
  - `media`
  - `downloads`

## Actual placement decision for this migration

This is the current recommended split for the first usable Synology cutover.

### Put on the Synology NAS

- Shared storage for:
  - `media/movies`
  - `media/tv`
  - `media/music`
  - `photos`
  - `downloads`
  - `quarantine`
  - `docker`
- Harbor control and automation services:
  - `gluetun`
  - `qbittorrent`
  - `sabnzbd`
  - `port-updater`
  - `download-orchestrator`
  - `indexer-guardian`
  - `radarr`
  - `sonarr`
  - `lidarr`
  - `bazarr`
  - `prowlarr`
  - `flaresolverr`
  - `overseerr`
  - `homepage`
  - `update-status`
  - `portainer`
  - `recyclarr`
  - `watchtower` in monitor-only mode
  - `autoheal`
  - `clamav`
  - `scanner`
  - `unpackerr`

### Keep on the PC

- `Plex`
- `cloudflared`
- `Pi-hole`
- `Tdarr`
- full `Immich` stack:
  - `immich-server`
  - `immich-machine-learning`
  - `immich-redis`
  - `immich-postgres`

## Why these services stay on the PC for now

- `Plex`
  - the current Harbor Plex setup is already tuned around the PC GPU and the Cloudflare tunnel path
  - moving it too early would reduce transcoding headroom and create a second remote-access cutover at the same time
- `Tdarr`
  - the current deployment depends on stronger compute than the DS224+ provides
- `Immich`
  - the DS224+ memory budget is tighter than the current PC deployment
  - `Immich` and its database are better left on the PC for the first migration phase
- `Pi-hole`
  - DNS is foundational and should not be moved during the first Harbor cutover
  - keep it stable on the PC first, then move it later if desired

## Private deployment files prepared locally

The following private migration files now exist locally and are not intended for the public repo:

- `.env.synology.local`
- `docker-compose.synology.private.yml`
- `scripts/Invoke-SynologyDeltaSync.ps1`
- `scripts/Test-SynologyLibraryParity.ps1`

## Why this split is recommended

The DS224+ is a good storage and automation host, but it is still a 2-bay NAS with limited memory headroom. Harbor is more than a Plex box. It is a downloader, automation, orchestration, recovery, DNS, dashboard, and photo stack. Moving the always-on automation to the NAS makes sense. Keeping bursty compute on the PC preserves performance without making the whole stack depend on the PC being on.

## What can be modular

### Tdarr

This is the cleanest modular component.

- Run the Tdarr server on the NAS
- Run a Tdarr node on the PC
- When the PC is on, it contributes workers
- When the PC is off, Harbor still functions

### Immich machine learning

This can also be modular.

- Run `immich-server`, `immich-postgres`, and `immich-redis` on the NAS
- Run `immich-machine-learning` on the PC if the NAS is resource-constrained

### Plex

Plex is not modular in the same way.

- Plex transcodes on the machine where Plex itself is running
- A Plex server on the NAS cannot "borrow" the PC GPU for live transcoding

That means:

- `Plex on NAS` = simpler, always on, lower transcode ceiling
- `Plex on PC with media on NAS` = best transcode performance, but the PC must be on

## Best migration order

### Phase 1: Bring the NAS online

1. Install both drives
2. Power on the NAS
3. Connect it to the router
4. Install DSM
5. Update DSM fully
6. Upgrade RAM to 6 GB total before loading Harbor
7. Create an SHR or RAID 1 storage pool
8. Use `Btrfs`
9. Install `Container Manager`
10. Enable `SSH`
11. Create shared folders:
   - `docker`
   - `media`
   - `downloads`
   - `photos`
   - `quarantine`
   - `backups`

### Phase 2: Move storage first

Copy the data before cutting over services:

- `media`
- `photos`
- `downloads`
- `quarantine`

### Phase 3: Move downloader and Arr stack

Move these to the NAS first:

- `gluetun`
- `qbittorrent`
- `sabnzbd`
- `port-updater`
- `download-orchestrator`
- `indexer-guardian`
- `radarr`
- `sonarr`
- `lidarr`
- `bazarr`
- `prowlarr`
- `flaresolverr`
- `overseerr`

### Phase 4: Move control plane

- `homepage`
- `update-status`
- `portainer`
- `recyclarr`
- `cloudflared`
- `watchtower`
- `autoheal`
- `clamav`
- `scanner`
- `pihole`

### Phase 5: Decide compute placement

Choose one of these:

- `Plex on NAS`, `Tdarr node on PC`
- `Plex on PC`, `Tdarr node on PC`, rest on NAS
- `Immich on NAS`, `Immich ML on PC`

## Recommended Synology paths

Use local Synology paths, not Windows paths:

```text
/volume1/docker/harbor/
/volume1/media/movies
/volume1/media/tv
/volume1/media/music
/volume1/photos
/volume1/downloads
/volume1/quarantine
```

## What to avoid

- Do not migrate the stack to the NAS before DSM and storage are stable
- Do not assume the DS224+ will match the PC for heavy Plex transcoding
- Do not put the Harbor Postgres or SQLite-heavy runtime onto flaky remote storage
- Do not move everything at once without a staged cutover

## Harbor-side automation available now

Run the local export script from the current Harbor PC:

```powershell
.\scripts\export-synology-migration-bundle.ps1
```

This creates a migration bundle containing:

- current service inventory
- current running container state
- current Docker volumes
- current Harbor path map
- recommended Synology path map

Optional:

```powershell
.\scripts\export-synology-migration-bundle.ps1 -IncludeRuntimeConfigs
```

That also copies selected Harbor runtime configuration directories for faster manual migration work.

## Current discovery note

If the NAS is not being discovered from the PC yet, do not wait on Harbor work. You can still prepare the Harbor side in parallel:

- generate the migration bundle
- decide which services stay on the PC
- decide whether Plex remains PC-hosted or moves to the NAS
- prepare the Synology folder layout
