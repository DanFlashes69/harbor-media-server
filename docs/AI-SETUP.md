# Harbor Media Server AI-Assisted Setup

Use this guide when you want an autonomous agent to take Harbor from a fresh clone to a mostly configured stack with as little manual interaction as possible.

Harbor already includes three automation layers:

1. [`setup.ps1`](../setup.ps1) for prerequisites, folders, volumes, and `.env`
2. [`scripts/bootstrap-media-stack.ps1`](../scripts/bootstrap-media-stack.ps1) for qBittorrent, SABnzbd, Prowlarr, the Arr apps, Recyclarr, and Homepage
3. [`scripts/safe-update-media-stack.ps1`](../scripts/safe-update-media-stack.ps1) for guarded update decisions and the update status page

The AI-assisted flow exists to drive those scripts, handle the remaining validation work, and optionally finish browser-only setup tasks such as Plex, Overseerr, Prowlarr, SABnzbd, or Cloudflare if your agent has browser access and you are comfortable providing the required credentials locally.

## What to give the agent up front

The smoother the run, the more of these details you provide at the start:

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
- whether you want Cloudflare Tunnel for Plex
- whether you want SABnzbd enabled for real Usenet downloads now
- whether you want the daily safe-update scheduled task installed
- whether you want the orchestrator profile enabled
- whether you want public starter Prowlarr indexers seeded

If you want the agent to finish account-linked tasks, also provide the relevant credentials locally when prompted:

- Plex login or claim path
- Overseerr first admin info
- Prowlarr private tracker credentials
- SABnzbd Usenet provider credentials
- NZB indexer credentials or API keys
- Cloudflare account access and tunnel/domain choices

## What the agent should automate

In the best-case path, the agent should:

1. run `setup.ps1`
2. verify `.env` is complete
3. confirm the OpenVPN profile is present
4. launch the stack
5. run `scripts/bootstrap-media-stack.ps1`
6. run `scripts/install-update-task.ps1` unless the user explicitly does not want the scheduled task
7. run `scripts/safe-update-media-stack.ps1 -Preview` so the status page is seeded
8. validate container health, service endpoints, recent logs, and the safe-update status page
9. if browser access is available, finish the remaining UI-only setup steps
10. re-run validation and report anything still manual or blocked

## What the agent should never do

Your prompt should explicitly tell the agent not to:

- commit or publish credentials, tokens, API keys, email addresses, VPN profiles, or personal runtime config
- change qBittorrent save paths, categories, bind interface, or listen port away from Harbor defaults unless you ask
- change Gluetun killswitch behavior or take over VPN provider settings
- rewrite Arr quality/import rules beyond what Harbor already codifies unless you ask
- overwrite local runtime configs blindly if they already contain working user data

## Recommended Codex prompt

Use this if you want a terminal-first local agent to do as much as possible from the repository and then stop cleanly on any browser-only/account-linked steps it cannot finish alone.

```text
You are initializing a Harbor Media Server install from this repository.

Work only inside the repository root. Use the repository's documented setup flow and keep all secrets local. Do not commit or print sensitive credentials, API keys, tokens, VPN profiles, or user-specific runtime config.

Your goals are:
1. Read README.md, docs/SETUP.md, and docs/SERVICE-SETUP.md.
2. Run setup.ps1 and complete the guided setup with the values I provide.
3. Verify that .env is complete enough for first launch.
4. Confirm the OpenVPN profile exists at DOCKER_ROOT\\gluetun\\custom.ovpn. If it is missing, stop and tell me exactly what is still needed.
5. Run docker compose up -d --build from the repository root.
6. Run scripts\\bootstrap-media-stack.ps1 unless there is a concrete blocker.
7. Verify qBittorrent, SABnzbd, Prowlarr, Radarr, Sonarr, Lidarr, Homepage, Plex, Pi-hole, Tdarr, and Gluetun health and endpoint reachability.
8. Verify qBittorrent is still bound to tun0 and that Harbor's safe defaults remain intact.
9. Install the Harbor safe-update scheduled task unless I tell you not to.
10. Run scripts\\safe-update-media-stack.ps1 -Preview and verify the update status page at http://localhost:8099.
11. If browser-only tasks remain, give me a short exact checklist in the right order instead of guessing.
12. If you see configuration drift, fix only what Harbor documents as safe to automate.

Do not:
- change VPN provider settings or Gluetun killswitch behavior
- change qBittorrent bind interface, save path, categories, or listen port away from Harbor defaults
- invent private tracker, Usenet, Plex, Overseerr, or Cloudflare credentials
- commit secrets to git

When you finish, give me:
- what was configured automatically
- what is still manual or blocked
- which services were validated successfully
- any warnings that are real operational risks
```

## Recommended Claude prompt

Use this if you want a browser-capable agent to do both the local setup and the browser-only finishing work.

```text
Initialize this Harbor Media Server repository from a fresh clone and take it as close as possible to the current documented Harbor state.

Follow the repo's setup flow in README.md, docs/SETUP.md, docs/SERVICE-SETUP.md, and docs/AI-SETUP.md.

Your priorities are:
1. Run setup.ps1 with the values I provide.
2. Confirm the OpenVPN profile exists at DOCKER_ROOT\\gluetun\\custom.ovpn.
3. Start the stack with docker compose up -d --build.
4. Run scripts\\bootstrap-media-stack.ps1.
5. Validate the main Harbor services and fix any safe-to-fix integration issues.
6. Install the Harbor safe-update scheduled task unless I tell you not to.
7. Run scripts\\safe-update-media-stack.ps1 -Preview and verify the update status page at http://localhost:8099.
8. In the browser, complete first-time Plex, Overseerr, Prowlarr, SABnzbd, and Cloudflare steps if I provide the necessary credentials or tokens.
9. Do not change Harbor's guarded infrastructure choices such as the Gluetun kill-switch, qBittorrent bind interface, qBittorrent categories, or Harbor's protected service wiring.
10. Keep secrets only in local runtime config and .env. Do not commit or print them in a way that would be unsafe to publish.

Browser-only tasks you may complete if I provide what you need:
- Plex claim/login and library confirmation
- Overseerr first admin setup and Plex connection
- Prowlarr private trackers or authenticated indexers
- SABnzbd provider server details and NZB indexers
- Cloudflare Tunnel creation, hostname routing, and Plex custom remote path

If something cannot be completed safely, stop and tell me the smallest exact next step.

Finish with:
- a list of what you configured
- a list of what remains manual
- a top-to-bottom validation summary
- any real warnings that could affect reliability
```

## Recommended generic autonomous-agent prompt

Use this for other local or browser-capable agents.

```text
Set up this Harbor Media Server repository end to end using the repository's own setup flow.

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
5. Install scripts/install-update-task.ps1 unless the user says not to.
6. Run scripts/safe-update-media-stack.ps1 -Preview and verify http://localhost:8099.
7. Validate health, connectivity, and the main service integrations.
8. Complete any browser-only setup only if you have access and the required credentials are provided locally.

Guardrails:
- do not commit secrets
- do not change Harbor's protected networking and VPN behavior
- do not rewrite qBittorrent core path, interface, category, or listen-port defaults
- do not rewrite Arr settings outside Harbor's documented automation scope
- do not claim success until the main Harbor services respond and the integration path is verified

If you hit a blocker, report the exact missing input instead of guessing.
```

## Browser-only task order

If your agent can use the browser and you provide the required credentials, this is the recommended order:

1. Plex claim or login and library confirmation
2. Overseerr first admin and Plex link
3. Prowlarr private trackers or authenticated indexers
4. SABnzbd provider servers and NZB indexers
5. Cloudflare Tunnel and Plex public hostname
6. Optional token-only Homepage widgets

## Final validation checklist for the agent

When the agent says Harbor is configured, it should verify at minimum:

- `docker compose ps`
- qBittorrent UI reachable
- SABnzbd UI reachable
- Prowlarr reachable
- Radarr reachable
- Sonarr reachable
- Lidarr reachable
- Homepage reachable
- update status page reachable
- Plex reachable locally
- Pi-hole API reachable
- Gluetun healthy
- qBittorrent still bound to `tun0`
- if Cloudflare is configured, Plex public hostname responds

If you want Harbor to feel "almost out of the box" after clone, the best pattern is:

- run `setup.ps1`
- run `scripts/bootstrap-media-stack.ps1`
- hand the repo to an autonomous agent with one of the prompts above
- let it finish the small set of remaining account-linked tasks
