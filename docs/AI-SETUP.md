# Harbor Media Server Agent-Assisted Setup

This guide is for users who want to pair the normal Harbor setup scripts with an autonomous agent such as Codex, Claude, or another browser-capable local model.

The scripts still do the heavy lifting:

1. [`setup.ps1`](../setup.ps1) handles prerequisites, folders, volumes, and `.env`
2. [`scripts/bootstrap-media-stack.ps1`](../scripts/bootstrap-media-stack.ps1) handles qBittorrent, SABnzbd, Prowlarr, the Arr apps, Recyclarr, and Homepage
3. [`scripts/safe-update-media-stack.ps1`](../scripts/safe-update-media-stack.ps1) handles guarded update decisions and the update-status page

The agent layer is useful for:

- driving those scripts
- validating the stack end to end
- finishing browser-only steps
- filling in account-linked configuration once the required credentials are available locally

## Information to provide up front

The smoother the run, the more of these values should be ready before handing the repo to an agent:

- repository path
- `DOCKER_ROOT`
- `DATA_ROOT`
- `SERVER_HOST`
- timezone
- VPN username and password
- qBittorrent username and password
- Pi-hole password
- Immich database password
- Plex advertise URL
- whether Cloudflare Tunnel should be used for Plex
- whether SABnzbd should be active immediately
- whether the safe-update scheduled task should be installed

If the agent should finish account-linked tasks, also provide the relevant credentials locally when asked:

- Plex login or claim path
- Overseerr first admin details
- Prowlarr private tracker credentials
- SABnzbd provider credentials
- NZB indexer credentials or API keys
- Cloudflare token and hostname details

## What the agent should do

The recommended agent workflow is:

1. read `README.md`, `docs/SETUP.md`, and `docs/SERVICE-SETUP.md`
2. run `setup.ps1`
3. verify that `.env` is complete enough for the first launch
4. confirm the OpenVPN profile exists at `DOCKER_ROOT\gluetun\custom.ovpn`
5. run `docker compose up -d --build`
6. run `scripts\bootstrap-media-stack.ps1`
7. run `scripts\install-update-task.ps1` unless the user explicitly opts out
8. run `scripts\safe-update-media-stack.ps1 -Preview`
9. validate health, endpoints, and service integration
10. complete browser-only setup if the required credentials are available
11. report anything that is still manual or blocked

## What the agent should not do

The prompt should explicitly tell the agent not to:

- commit or publish credentials, tokens, API keys, VPN profiles, or user-specific runtime config
- change Gluetun kill-switch behavior or VPN provider settings without approval
- change qBittorrent bind interface, save paths, categories, or listen-port behavior away from Harbor defaults
- rewrite Arr quality or import rules beyond Harbor's documented scope unless asked
- overwrite working local runtime config blindly

## Recommended Codex prompt

```text
Set up this Harbor Media Server repository on a Windows host.

Read:
- README.md
- docs/SETUP.md
- docs/SERVICE-SETUP.md
- docs/AI-SETUP.md

Then:
1. Run setup.ps1.
2. Verify that .env is complete enough for the first launch.
3. Confirm the OpenVPN profile exists at DOCKER_ROOT\\gluetun\\custom.ovpn.
4. Run docker compose up -d --build from the repository root.
5. Run scripts\\bootstrap-media-stack.ps1.
6. Run scripts\\install-update-task.ps1 unless I tell you not to.
7. Run scripts\\safe-update-media-stack.ps1 -Preview and verify http://localhost:8099.
8. Validate qBittorrent, SABnzbd, Gluetun, Radarr, Sonarr, Lidarr, Prowlarr, Homepage, Plex, Pi-hole, Tdarr, and the orchestrator.
9. If browser-only work remains, stop with a short exact checklist in the right order.

Do not:
- commit or print secrets unsafely
- change VPN provider settings or Gluetun kill-switch behavior
- change qBittorrent bind interface, categories, save paths, or port behavior away from Harbor defaults
- invent credentials or tokens

Finish with:
- what was configured automatically
- what remains manual
- which services were validated successfully
- any real operational warnings
```

## Recommended Claude prompt

```text
Initialize this Harbor Media Server repository on a Windows host and take it as close as possible to the documented Harbor state.

Follow:
- README.md
- docs/SETUP.md
- docs/SERVICE-SETUP.md
- docs/AI-SETUP.md

Priorities:
1. Run setup.ps1.
2. Verify .env and the OpenVPN profile.
3. Start the stack with docker compose up -d --build.
4. Run scripts\\bootstrap-media-stack.ps1.
5. Run scripts\\install-update-task.ps1 unless I tell you not to.
6. Run scripts\\safe-update-media-stack.ps1 -Preview.
7. Validate the main Harbor services and fix safe-to-fix integration issues.
8. If browser access is available and I provide the credentials, complete Plex, Overseerr, Prowlarr, SABnzbd, and Cloudflare setup.

Guardrails:
- keep secrets local
- do not change Harbor's protected VPN and qBittorrent defaults
- do not rewrite Arr settings outside Harbor's documented automation scope
- do not claim success until the main service path is verified

If something cannot be completed safely, stop and report the exact missing input.
```

## Recommended generic agent prompt

```text
Set up this Harbor Media Server repository end to end using the repository's documented Windows-first setup flow.

Read:
- README.md
- docs/SETUP.md
- docs/SERVICE-SETUP.md
- docs/AI-SETUP.md

Then:
1. Run setup.ps1.
2. Verify .env and the OpenVPN profile.
3. Start the stack with docker compose up -d --build.
4. Run scripts/bootstrap-media-stack.ps1.
5. Run scripts/install-update-task.ps1 unless the user opts out.
6. Run scripts/safe-update-media-stack.ps1 -Preview and verify http://localhost:8099.
7. Validate health, connectivity, and service integration.
8. Finish browser-only setup only if the required credentials are available locally.

Do not:
- commit secrets
- change Harbor's protected VPN and qBittorrent defaults
- rewrite Arr settings outside Harbor's documented automation scope
- invent credentials, tokens, or provider details
```

## Browser-only task order

If the agent can use a browser and the required credentials are available, this is the preferred order:

1. Plex claim or login and library confirmation
2. Overseerr first admin setup and Plex link
3. Prowlarr private trackers and authenticated indexers
4. SABnzbd provider servers and premium NZB sources
5. Cloudflare Tunnel and Plex hostname setup
6. Optional token-only Homepage widgets

## Final validation checklist

Before declaring Harbor ready, the agent should verify:

- `docker compose ps`
- qBittorrent UI reachable
- SABnzbd UI reachable
- Prowlarr reachable
- Radarr reachable
- Sonarr reachable
- Lidarr reachable
- Homepage reachable
- update-status reachable
- Plex reachable locally
- Pi-hole reachable on `http://127.0.0.1:9080/admin/`
- Gluetun healthy
- qBittorrent still bound to `tun0`
- the orchestrator and Indexer Guardian are healthy

The standard pattern is:

1. run `setup.ps1`
2. run `scripts/bootstrap-media-stack.ps1`
3. hand the repository to an agent with one of the prompts above
4. let the agent finish validation and any remaining browser-only setup
