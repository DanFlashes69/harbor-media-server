# qBittorrent Orchestrator

This service is an optimizer, not a replacement control plane for the Harbor stack.

Its job is to:

- keep qBittorrent focused on the best torrents for the current conditions
- prioritize download completion when disk pressure is high
- watch for completed torrents that never make it into the media libraries
- stay aware of the VPN tunnel and forwarded port state
- adapt qB speed-related runtime settings within a narrow safe boundary

Its job is not to:

- change VPN provider settings
- change Gluetun firewall or killswitch rules
- change qBittorrent save paths, categories, ports, or WebUI auth
- rewrite Arr quality profiles, naming, import, or download client settings
- take ownership of Plex, Tdarr, Pi-hole, or any unrelated service

## qB Setting Awareness

The orchestrator does not assume a frozen qBittorrent settings schema.

On every cycle it:

- reads the full current preferences payload from qB
- writes a local settings inventory snapshot
- tracks newly seen and removed keys over time

This gives it visibility into current and newly introduced qB settings across upgrades without blindly mutating them.

Write behavior remains intentionally fenced:

- it only writes to a tiny explicit allowlist
- unknown or newly discovered qB settings are observed, never auto-tuned

That is how the service stays future-aware without becoming dangerous.

Current live write allowlist is intentionally tiny and focused on workload shaping, not client ownership:

- `max_active_downloads`
- `max_active_torrents`
- `max_active_uploads`
- `max_connec`
- `max_connec_per_torrent`
- `max_uploads_per_torrent`
- `connection_speed`
- `max_concurrent_http_announces`

The orchestrator now has an optional promoted advanced write tier for a still-bounded set of deeper qB performance knobs:

- `async_io_threads`
- `disk_cache`
- `disk_cache_ttl`
- `disk_queue_size`
- `request_queue_size`
- `enable_piece_extent_affinity`
- `enable_coalesce_read_write`
- `send_buffer_*`
- `socket_backlog_size`
- `socket_*_buffer_size`
- `peer_turnover*`
- `file_pool_size`
- `checking_memory_use`

Anything outside that reviewed allowlist remains advisory-only. The planner still computes a broader advisory set of deeper qB performance settings without auto-writing unknown or unreviewed keys.

The orchestrator does not own:

- interface binding
- listen port
- save paths
- categories
- WebUI auth
- proxy mode
- content layout
- TLS/WebUI exposure
- unknown future preferences until explicitly reviewed

## Non-Interference Contract

The orchestrator treats the existing stack as the source of truth.

Allowed writes are intentionally narrow and separately gated:

- `ALLOW_TORRENT_CONTROL=true`
  - permits `start` / `stop` calls for torrent workload shaping
- `ALLOW_QBIT_PREF_WRITES=true`
  - permits limited qB preference nudges from the safe allowlist
- `ALLOW_ARR_COMMANDS=true`
  - permits bounded Arr search commands for high-confidence repair candidates
- `ALLOW_BROKEN_DOWNLOAD_RECOVERY=true`
  - permits broken-download replacement via Arr search commands only when explicitly paired with Arr command writes
- `ALLOW_RETROACTIVE_ARR_REPAIR=true`
  - permits the same bounded Arr search path for high-confidence retro repair candidates

Arr-side writes are additionally fenced by:

- `MAX_ARR_COMMANDS_PER_CYCLE`
- `MIN_ARR_COMMAND_INTERVAL_SECONDS`

If those flags stay false, the orchestrator can still:

- collect state
- score torrents
- write snapshots
- report suspected import failures

This is the default recommended burn-in mode.

The control plane is also stability-gated on purpose:

- repeated identical plan cycles are required before writes are considered ready
- torrent start/stop actions have a cooldown window
- qB preference writes have a separate cooldown window
- per-cycle torrent actions are capped to avoid reshuffling the whole queue at once

That keeps the service adaptive without letting it thrash qB every minute.

## Safety Inputs

The orchestrator reads the following signals before it is allowed to act:

- qB current network interface
- qB listen port
- Gluetun forwarded port file
- qB queueing status
- actual free space on `/downloads`
- torrent progress, speed, seeds, availability, metadata state
- recent Arr history for imported vs grabbed items
- Arr config readability for Radarr / Sonarr / Lidarr history lookups

If the tunnel guard is not healthy, the orchestrator does not try to repair the VPN stack. It only records the degraded state and withholds workload changes.

## Policy Goals

### 1. Completion First Under Pressure

If free space is tight, the orchestrator shifts into focused or constrained modes:

- keeps only a very small active working set
- prefers torrents already far along
- avoids splitting scarce space across many partial downloads

This is what handles the "20 GB free, two 20 GB torrents" case: it should finish one before letting the other consume space.

### 2. Dynamic Active Window

The orchestrator derives a mode from:

- viable torrent count
- actual free bytes on `/downloads`

Current modes:

- `focused`
- `emergency`
- `constrained`
- `balanced`
- `expansive`

It then computes a desired active window rather than assuming a fixed global number forever.

### 2b. Dynamic Speed Tuning

Beyond queue width, the orchestrator can shape a narrow set of qB speed-related preferences based on mode:

- active download window
- total active torrent headroom
- active upload headroom
- global connection ceiling
- per-torrent connection ceiling
- upload slots per torrent
- connection attempt rate
- concurrent tracker announce ceiling

This lets a one-torrent situation behave differently from a dozens-of-torrents situation without hardcoding one static qB profile forever.

The orchestrator still keeps all unknown or unreviewed future qB keys in observation-only mode. Promoted advanced writes only apply to the reviewed allowlist above and remain fenced by the same stability and cooldown gates as the queue-window controls.

### 3. Swarm Viability Matters

Torrents with:

- active transfer
- real seed or availability
- complete metadata

are favored over dead or long-stalled items. Long-stalled torrents are deprioritized so healthier torrents can make progress.

### 4. Import Reconciliation

The orchestrator reads Arr history and writes an orphan report for completed torrents that appear to have never been imported after the grace period.

Current burn-in behavior:

- report only
- no automatic Arr search command unless explicitly enabled later

### 5. Broken Download Recovery

The orchestrator also tracks Arr-managed torrents stuck in `missingFiles` state.

The recovery layer is intentionally narrow:

- it only considers Arr-managed categories
- it skips items that already show a successful Arr import event
- it writes advisory qB salvage actions such as `recheck` / `reannounce`
- it writes Arr replacement actions for items that need a fresh search
- it does not change Arr settings or profiles

Automatic repair now follows a staged order:

- qB salvage first for salvageable `missingFiles` cases
- Arr replacement only after salvage attempts are exhausted or the item is clearly non-salvageable
- bounded retry counts and cooldowns per candidate

### 6. Retro Repair vs Backlog Discovery

The orchestrator now separates Arr repair into two lanes:

- `retroRepairCandidates`
  - high-confidence queue/import-failure cases that are eligible for bounded Arr retry
- `backlogCandidates`
  - older historical misses or stale Radarr wanted items that can be slowly auto-repaired behind a stricter global cooldown when explicitly enabled

That split is deliberate. It keeps the live repair surface narrow enough to be safe while still surfacing older request drift for later cleanup.

## Scenario Coverage

The image now includes `/app/scenario_suite.py` for policy checks covering:

- low-disk completion-first behavior
- expansive multi-torrent behavior
- single-torrent speed bias
- tunnel/port-forward drift blocking
- protected category/path drift blocking
- downloader-overage stop planning
- missing-files recovery planning
- imported-media no-op protection
- retro Arr history repair detection
- queue-warning repair detection
- bounded Arr command budget/cooldown behavior
- global Arr cooldown and retry-limit behavior
- qB salvage recovery cooldown and retry-limit behavior

## Burn-In Recommendation

Run in this order:

1. `OBSERVE_ONLY=true`
2. `ALLOW_TORRENT_CONTROL=false`
3. `ALLOW_QBIT_PREF_WRITES=false`
4. Review `/state/snapshot.json` and `/state/orphan-report.json`
5. Review `/state/qbit-preferences.json` and the qB preference diff inside `/state/snapshot.json`
6. Review `stabilityGuard`, `advancedSpeedAdvisories`, and `arrAudit` inside `/state/snapshot.json`
7. Enable torrent control first
8. Enable queue-window qB pref writes only after the selection logic is trusted
9. Enable Arr command writes only for high-confidence repair candidates
10. Keep backlog discovery visible, but separate from the auto-repair lane

## Runtime Outputs

The service writes to `/state`:

- `heartbeat`
- `runtime-state.json`
- `snapshot.json`
- `orphan-report.json`
- `qbit-preferences.json`

These files are the main debugging surface during burn-in.
