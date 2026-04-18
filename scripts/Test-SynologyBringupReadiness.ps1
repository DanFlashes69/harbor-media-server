[CmdletBinding()]
param(
    [string]$NasHost = 'synology.example.lan'
)

$ErrorActionPreference = 'Stop'

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$envPath = Join-Path $repoRoot '.env.synology.local'
$composePath = Join-Path $repoRoot 'docker-compose.synology.private.yml'
$proxyPath = Join-Path $repoRoot 'scripts\nas_localhost_proxy.py'
$homepagePath = Join-Path $repoRoot 'homepage\config\services.yaml'
$overseerrSettingsPath = "\\$NasHost\docker\harbor\appdata\overseerr\config\settings.json"

function Import-DotEnv {
    param([string]$Path)

    $map = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if (-not $line -or $line.TrimStart().StartsWith('#')) {
            continue
        }
        $parts = $line -split '=', 2
        if ($parts.Count -ne 2) {
            continue
        }
        $map[$parts[0].Trim()] = $parts[1].Trim()
    }
    return $map
}

$envMap = Import-DotEnv -Path $envPath

$python = @"
import json
from pathlib import Path

import requests
import yaml

compose_path = Path(r'''$composePath''')
proxy_path = Path(r'''$proxyPath''')
homepage_path = Path(r'''$homepagePath''')
overseerr_settings_path = Path(r'''$overseerrSettingsPath''')
nas_host = r'''$NasHost'''
radarr_key = r'''$($envMap['RADARR_API_KEY'])'''
sonarr_key = r'''$($envMap['SONARR_API_KEY'])'''
lidarr_key = r'''$($envMap['LIDARR_API_KEY'])'''
prowlarr_key = r'''$($envMap['PROWLARR_API_KEY'])'''
qbit_user = r'''$($envMap['QBIT_USER'])'''
qbit_pass = r'''$($envMap['QBIT_PASS'])'''

result = {"checks": [], "warnings": [], "failures": []}
session = requests.Session()

def check(name, ok, detail):
    entry = {"name": name, "ok": bool(ok), "detail": detail}
    result["checks"].append(entry)
    if not ok:
        result["failures"].append(entry)

def warn(name, detail):
    result["warnings"].append({"name": name, "detail": detail})

def normalize_items(payload):
    if isinstance(payload, dict) and isinstance(payload.get("value"), list):
        return payload["value"]
    if isinstance(payload, list):
        return payload
    if payload is None:
        return []
    return [payload]

compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
services = compose["services"]
required_services = [
    "gluetun", "qbittorrent", "port-updater", "sabnzbd", "gluetun-namespace-guard",
    "radarr", "sonarr", "lidarr", "bazarr", "prowlarr", "flaresolverr",
    "plex", "overseerr", "clamav", "scanner", "download-orchestrator",
    "indexer-guardian", "homepage", "update-status", "pihole", "tdarr",
    "cloudflared", "immich-server", "immich-machine-learning", "immich-redis",
    "immich-postgres",
]
missing = [svc for svc in required_services if svc not in services]
check("Required NAS services present", not missing, {"missing": missing})

check("qBittorrent stays behind Gluetun", services["qbittorrent"].get("network_mode") == "service:gluetun", services["qbittorrent"].get("network_mode"))
check("Port updater stays behind Gluetun", services["port-updater"].get("network_mode") == "service:gluetun", services["port-updater"].get("network_mode"))
check("SABnzbd stays behind Gluetun", services["sabnzbd"].get("network_mode") == "service:gluetun", services["sabnzbd"].get("network_mode"))
check("Plex host port is mapped through 32401", "32401:32400" in services["plex"].get("ports", []), services["plex"].get("ports", []))
check("Immich host port is mapped through 2283", "2283:2283" in services["immich-server"].get("ports", []), services["immich-server"].get("ports", []))

scanner_health = " ".join(services["scanner"].get("healthcheck", {}).get("test", []))
check("Scanner healthcheck uses its own heartbeat", "scanner-heartbeat" in scanner_health, scanner_health)

proxy_text = proxy_path.read_text(encoding="utf-8")
check("Localhost bridge preserves Plex localhost on NAS port 32401", "32400: 32401" in proxy_text, "32400 -> 32401" if "32400: 32401" in proxy_text else "missing")
check("Localhost bridge includes Immich", "2283: 2283" in proxy_text, "2283 mapped" if "2283: 2283" in proxy_text else "missing")
check("Localhost bridge includes Tdarr UI", "8265: 8265" in proxy_text, "8265 mapped" if "8265: 8265" in proxy_text else "missing")

homepage = yaml.safe_load(homepage_path.read_text(encoding="utf-8"))
cards = {}
for section in homepage:
    for _, items in section.items():
        for item in items:
            for name, cfg in item.items():
                cards[name] = cfg

expected_hrefs = {
    "Plex": {f"http://{nas_host}:32401/web", "http://localhost:32400/web"},
    "Overseerr": {f"http://{nas_host}:5055", "http://localhost:5055"},
    "Immich": {f"http://{nas_host}:2283", "http://localhost:2283"},
    "Radarr": {f"http://{nas_host}:7878", "http://localhost:7878"},
    "Sonarr": {f"http://{nas_host}:8989", "http://localhost:8989"},
    "Lidarr": {f"http://{nas_host}:8686", "http://localhost:8686"},
    "Bazarr": {f"http://{nas_host}:6767", "http://localhost:6767"},
    "qBittorrent": {f"http://{nas_host}:8081", "http://localhost:8081"},
    "SABnzbd": {f"http://{nas_host}:8082", "http://localhost:8082"},
    "Prowlarr": {f"http://{nas_host}:9696", "http://localhost:9696"},
    "Pi-hole": {f"http://{nas_host}:9080/admin/", "http://127.0.0.1:9080/admin/", "http://localhost:9080/admin/"},
    "Tdarr": {f"http://{nas_host}:8265", "http://localhost:8265"},
    "Portainer": {f"http://{nas_host}:9000", "http://localhost:9000"},
    "Update Status": {f"http://{nas_host}:8099", "http://localhost:8099"},
}

for card_name, hrefs in expected_hrefs.items():
    actual_href = cards[card_name].get("href")
    check(f"Homepage {card_name} link points at NAS", actual_href in hrefs, actual_href)

immich = cards["Immich"]
check("Homepage Immich widget targets NAS-local service", immich.get("widget", {}).get("url") == "http://immich-server:2283", immich.get("widget", {}).get("url"))
check("Homepage Immich monitor targets NAS-local service", immich.get("siteMonitor") == "http://immich-server:2283/api/server/ping", immich.get("siteMonitor"))

update_status = cards["Update Status"]
check("Homepage Update Status uses NAS-local container URL", update_status.get("widget", {}).get("url") == "http://update-status/status.json", update_status.get("widget", {}).get("url"))
check("Homepage Update Status site monitor uses NAS-local container URL", update_status.get("siteMonitor") == "http://update-status", update_status.get("siteMonitor"))

def api_json(port, version, path, key):
    response = session.get(
        f"http://{nas_host}:{port}/api/{version}/{path}",
        headers={"X-Api-Key": key},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()

qbit_auth = session.post(
    f"http://{nas_host}:8081/api/v2/auth/login",
    data={"username": qbit_user, "password": qbit_pass},
    timeout=20,
)
check("qB API auth works", "Ok." in qbit_auth.text, qbit_auth.text.strip())
if "Ok." in qbit_auth.text:
    qbit_prefs = session.get(f"http://{nas_host}:8081/api/v2/app/preferences", timeout=20).json()
    check("qB default save path is NAS downloads", qbit_prefs.get("save_path") == "/downloads", qbit_prefs.get("save_path"))
    check("qB temp path is NAS downloads/incomplete", qbit_prefs.get("temp_path") == "/downloads/incomplete", qbit_prefs.get("temp_path"))
    check("qB bind interface remains tun0", qbit_prefs.get("current_network_interface") == "tun0", qbit_prefs.get("current_network_interface"))

radarr_roots = normalize_items(api_json(7878, "v3", "rootfolder", radarr_key))
sonarr_roots = normalize_items(api_json(8989, "v3", "rootfolder", sonarr_key))
lidarr_roots = normalize_items(api_json(8686, "v1", "rootfolder", lidarr_key))
sonarr_clients = normalize_items(api_json(8989, "v3", "downloadclient", sonarr_key))
lidarr_clients = normalize_items(api_json(8686, "v1", "downloadclient", lidarr_key))
prowlarr_apps = normalize_items(api_json(9696, "v1", "applications", prowlarr_key))
prowlarr_clients = normalize_items(api_json(9696, "v1", "downloadclient", prowlarr_key))
prowlarr_proxies = normalize_items(api_json(9696, "v1", "indexerProxy", prowlarr_key))

check("Radarr root folder is /movies", any(row.get("path") == "/movies" for row in radarr_roots), radarr_roots)
check("Sonarr root folder is /tv", any(row.get("path") == "/tv" for row in sonarr_roots), sonarr_roots)
check("Lidarr root folder is /music", any(row.get("path") == "/music" for row in lidarr_roots), lidarr_roots)

def client_matches(clients, expected_host):
    for client in clients:
        fields = {field.get("name"): field.get("value") for field in client.get("fields", [])}
        if fields.get("host") == expected_host:
            return True
    return False

check("Sonarr qB client points at gluetun", client_matches(sonarr_clients, "gluetun"), sonarr_clients)
check("Lidarr qB client points at gluetun", client_matches(lidarr_clients, "gluetun"), lidarr_clients)
check("Prowlarr qB client points at gluetun", client_matches(prowlarr_clients, "gluetun"), prowlarr_clients)

expected_app_urls = {"http://radarr:7878", "http://sonarr:8989", "http://lidarr:8686"}
actual_app_urls = set()
for app in prowlarr_apps:
    fields = {field.get("name"): field.get("value") for field in app.get("fields", [])}
    if fields.get("baseUrl"):
        actual_app_urls.add(fields["baseUrl"])
check(
    "Prowlarr apps point at internal NAS service names",
    expected_app_urls.issubset(actual_app_urls),
    sorted(actual_app_urls),
)

if not prowlarr_proxies:
    warn("Prowlarr indexer proxies", "No indexer proxies are configured. FlareSolverr is preserved, but Prowlarr is not currently wired to use it.")

try:
    overseerr = None
    try:
        if overseerr_settings_path.exists():
            overseerr = json.loads(overseerr_settings_path.read_text(encoding="utf-8"))
    except OSError:
        overseerr = None
    if overseerr is not None and (
        not overseerr.get("radarr")
        or not overseerr.get("sonarr")
        or not overseerr.get("public", {}).get("initialized")
    ):
        warn(
            "Overseerr staged configuration",
            {
                "initialized": overseerr.get("public", {}).get("initialized"),
                "radarrEntries": len(overseerr.get("radarr", [])),
                "sonarrEntries": len(overseerr.get("sonarr", [])),
            },
        )
except Exception as exc:
    warn("Overseerr staged configuration", f"Unexpected settings parse failure: {exc!r}")

for name, url in [
    ("Live Radarr ping", f"http://{nas_host}:7878/ping"),
    ("Live Sonarr ping", f"http://{nas_host}:8989/ping"),
    ("Live Lidarr ping", f"http://{nas_host}:8686/ping"),
    ("Live Prowlarr ping", f"http://{nas_host}:9696/ping"),
    ("Live Immich ping", f"http://{nas_host}:2283/api/server/ping"),
]:
    try:
        response = requests.get(url, timeout=10)
        check(name, response.status_code == 200, response.status_code)
    except Exception as exc:
        warn(name, repr(exc))

print(json.dumps(result, indent=2))
"@

$python | python -

