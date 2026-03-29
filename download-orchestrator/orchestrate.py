import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value is not None else default


def env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value is not None else default


def env_csv(name: str, default: str) -> list[str]:
    value = os.environ.get(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Config:
    qbit_host: str = os.environ.get("QBIT_HOST", "gluetun")
    qbit_port: int = env_int("QBIT_PORT", 8081)
    qbit_user: str = os.environ.get("QBIT_USER", "")
    qbit_pass: str = os.environ.get("QBIT_PASS", "")
    downloads_path: str = os.environ.get("DOWNLOADS_PATH", "/downloads")
    state_dir: str = os.environ.get("STATE_DIR", "/state")
    gluetun_port_file: str = os.environ.get("GLUETUN_PORT_FILE", "/gluetun-port/forwarded_port")
    expected_interface: str = os.environ.get("EXPECTED_INTERFACE", "tun0")
    check_interval: int = env_int("CHECK_INTERVAL", 60)
    run_once: bool = env_bool("RUN_ONCE", False)
    observe_only: bool = env_bool("OBSERVE_ONLY", True)
    allow_torrent_control: bool = env_bool("ALLOW_TORRENT_CONTROL", False)
    allow_qbit_pref_writes: bool = env_bool("ALLOW_QBIT_PREF_WRITES", False)
    allow_advanced_qbit_pref_writes: bool = env_bool("ALLOW_ADVANCED_QBIT_PREF_WRITES", False)
    allow_qbit_recovery_actions: bool = env_bool("ALLOW_QBIT_RECOVERY_ACTIONS", False)
    allow_arr_commands: bool = env_bool("ALLOW_ARR_COMMANDS", False)
    allow_broken_download_recovery: bool = env_bool("ALLOW_BROKEN_DOWNLOAD_RECOVERY", False)
    allow_retroactive_arr_repair: bool = env_bool("ALLOW_RETROACTIVE_ARR_REPAIR", False)
    allow_backlog_arr_repair: bool = env_bool("ALLOW_BACKLOG_ARR_REPAIR", False)
    enable_speed_tuning: bool = env_bool("ENABLE_SPEED_TUNING", True)
    refresh_protected_baselines: bool = env_bool("REFRESH_PROTECTED_BASELINES", False)
    reserved_free_gb: float = env_float("RESERVED_FREE_GB", 20)
    emergency_free_gb: float = env_float("EMERGENCY_FREE_GB", 10)
    low_space_threshold_gb: float = env_float("LOW_SPACE_THRESHOLD_GB", 40)
    high_space_threshold_gb: float = env_float("HIGH_SPACE_THRESHOLD_GB", 120)
    max_active_downloads_low: int = env_int("MAX_ACTIVE_DOWNLOADS_LOW", 1)
    max_active_downloads_medium: int = env_int("MAX_ACTIVE_DOWNLOADS_MEDIUM", 3)
    max_active_downloads_high: int = env_int("MAX_ACTIVE_DOWNLOADS_HIGH", 6)
    healthy_availability_floor: float = env_float("HEALTHY_AVAILABILITY_FLOOR", 1.1)
    completion_priority_progress: float = env_float("COMPLETION_PRIORITY_PROGRESS", 0.8)
    completion_priority_remaining_gb: float = env_float("COMPLETION_PRIORITY_REMAINING_GB", 8)
    stall_failover_seconds: int = env_int("STALL_FAILOVER_SECONDS", 900)
    force_started_reserve_min_speed_bps: int = env_int("FORCE_STARTED_RESERVE_MIN_SPEED_BPS", 262144)
    manage_force_started: bool = env_bool("MANAGE_FORCE_STARTED", False)
    arr_history_lookback_hours: int = env_int("ARR_HISTORY_LOOKBACK_HOURS", 168)
    retro_repair_lookback_hours: int = env_int("RETRO_REPAIR_LOOKBACK_HOURS", 720)
    retro_repair_stale_hours: int = env_int("RETRO_REPAIR_STALE_HOURS", 24)
    import_grace_hours: int = env_int("IMPORT_GRACE_HOURS", 6)
    broken_download_grace_hours: int = env_int("BROKEN_DOWNLOAD_GRACE_HOURS", 2)
    max_arr_commands_per_cycle: int = env_int("MAX_ARR_COMMANDS_PER_CYCLE", 1)
    min_arr_command_interval_seconds: int = env_int("MIN_ARR_COMMAND_INTERVAL_SECONDS", 21600)
    arr_global_command_interval_seconds: int = env_int("ARR_GLOBAL_COMMAND_INTERVAL_SECONDS", 3600)
    max_arr_search_retries_broken: int = env_int("MAX_ARR_SEARCH_RETRIES_BROKEN", 2)
    max_arr_search_retries_orphan: int = env_int("MAX_ARR_SEARCH_RETRIES_ORPHAN", 1)
    max_arr_search_retries_queue_warning: int = env_int("MAX_ARR_SEARCH_RETRIES_QUEUE_WARNING", 2)
    max_arr_search_retries_history: int = env_int("MAX_ARR_SEARCH_RETRIES_HISTORY", 1)
    max_arr_search_retries_wanted: int = env_int("MAX_ARR_SEARCH_RETRIES_WANTED", 1)
    max_qbit_recovery_actions_per_cycle: int = env_int("MAX_QBIT_RECOVERY_ACTIONS_PER_CYCLE", 1)
    min_qbit_recovery_interval_seconds: int = env_int("MIN_QBIT_RECOVERY_INTERVAL_SECONDS", 7200)
    max_qbit_recovery_attempts_per_hash: int = env_int("MAX_QBIT_RECOVERY_ATTEMPTS_PER_HASH", 2)
    control_stability_cycles: int = env_int("CONTROL_STABILITY_CYCLES", 2)
    pref_stability_cycles: int = env_int("PREF_STABILITY_CYCLES", 2)
    min_torrent_action_interval_seconds: int = env_int("MIN_TORRENT_ACTION_INTERVAL_SECONDS", 300)
    min_pref_write_interval_seconds: int = env_int("MIN_PREF_WRITE_INTERVAL_SECONDS", 900)
    max_torrent_actions_per_cycle: int = env_int("MAX_TORRENT_ACTIONS_PER_CYCLE", 8)
    qbit_write_allowlist: tuple[str, ...] = tuple(
        env_csv(
            "QBIT_WRITE_ALLOWLIST",
            "max_active_downloads,max_active_torrents,max_active_uploads,max_connec,max_connec_per_torrent,max_uploads_per_torrent,connection_speed,max_concurrent_http_announces",
        )
    )
    speed_conn_floor: int = env_int("SPEED_CONN_FLOOR", 400)
    speed_conn_ceiling: int = env_int("SPEED_CONN_CEILING", 1000)
    speed_conn_per_torrent_focused: int = env_int("SPEED_CONN_PER_TORRENT_FOCUSED", 220)
    speed_conn_per_torrent_constrained: int = env_int("SPEED_CONN_PER_TORRENT_CONSTRAINED", 180)
    speed_conn_per_torrent_balanced: int = env_int("SPEED_CONN_PER_TORRENT_BALANCED", 140)
    speed_conn_per_torrent_expansive: int = env_int("SPEED_CONN_PER_TORRENT_EXPANSIVE", 100)
    speed_active_torrent_headroom_focused: int = env_int("SPEED_ACTIVE_TORRENT_HEADROOM_FOCUSED", 2)
    speed_active_torrent_headroom_constrained: int = env_int("SPEED_ACTIVE_TORRENT_HEADROOM_CONSTRAINED", 3)
    speed_active_torrent_headroom_balanced: int = env_int("SPEED_ACTIVE_TORRENT_HEADROOM_BALANCED", 4)
    speed_active_torrent_headroom_expansive: int = env_int("SPEED_ACTIVE_TORRENT_HEADROOM_EXPANSIVE", 6)
    speed_upload_slots_per_torrent_focused: int = env_int("SPEED_UPLOAD_SLOTS_PER_TORRENT_FOCUSED", 20)
    speed_upload_slots_per_torrent_constrained: int = env_int("SPEED_UPLOAD_SLOTS_PER_TORRENT_CONSTRAINED", 16)
    speed_upload_slots_per_torrent_balanced: int = env_int("SPEED_UPLOAD_SLOTS_PER_TORRENT_BALANCED", 12)
    speed_upload_slots_per_torrent_expansive: int = env_int("SPEED_UPLOAD_SLOTS_PER_TORRENT_EXPANSIVE", 10)
    speed_connection_rate_focused: int = env_int("SPEED_CONNECTION_RATE_FOCUSED", 40)
    speed_connection_rate_constrained: int = env_int("SPEED_CONNECTION_RATE_CONSTRAINED", 50)
    speed_connection_rate_balanced: int = env_int("SPEED_CONNECTION_RATE_BALANCED", 60)
    speed_connection_rate_expansive: int = env_int("SPEED_CONNECTION_RATE_EXPANSIVE", 80)
    speed_http_announces_focused: int = env_int("SPEED_HTTP_ANNOUNCES_FOCUSED", 90)
    speed_http_announces_constrained: int = env_int("SPEED_HTTP_ANNOUNCES_CONSTRAINED", 70)
    speed_http_announces_balanced: int = env_int("SPEED_HTTP_ANNOUNCES_BALANCED", 50)
    speed_http_announces_expansive: int = env_int("SPEED_HTTP_ANNOUNCES_EXPANSIVE", 40)
    enable_advanced_speed_advisories: bool = env_bool("ENABLE_ADVANCED_SPEED_ADVISORIES", True)


CONFIG = Config()
BASE_URL = f"http://{CONFIG.qbit_host}:{CONFIG.qbit_port}"
STATE_DIR = Path(CONFIG.state_dir)
HEARTBEAT_PATH = STATE_DIR / "heartbeat"
RUNTIME_STATE_PATH = STATE_DIR / "runtime-state.json"
SNAPSHOT_PATH = STATE_DIR / "snapshot.json"
ORPHAN_REPORT_PATH = STATE_DIR / "orphan-report.json"
QBIT_PREFS_PATH = STATE_DIR / "qbit-preferences.json"

ADVISORY_QBIT_PREF_KEYS = (
    "disk_cache",
    "disk_cache_ttl",
    "disk_queue_size",
    "async_io_threads",
    "request_queue_size",
    "send_buffer_low_watermark",
    "send_buffer_watermark",
    "send_buffer_watermark_factor",
    "socket_receive_buffer_size",
    "socket_send_buffer_size",
    "enable_piece_extent_affinity",
    "enable_coalesce_read_write",
    "peer_turnover",
    "peer_turnover_cutoff",
    "peer_turnover_interval",
    "file_pool_size",
    "checking_memory_use",
)

PROTECTED_QBIT_PREF_KEYS = (
    "current_network_interface",
    "listen_port",
    "save_path",
    "temp_path",
    "temp_path_enabled",
    "queueing_enabled",
    "proxy_type",
    "proxy_ip",
    "proxy_port",
    "proxy_hostname_lookup",
    "proxy_bittorrent",
    "proxy_misc",
    "proxy_rss",
    "web_ui_port",
    "web_ui_username",
    "web_ui_address",
    "use_https",
    "upnp",
)

EXPECTED_CATEGORY_PATHS = {
    "radarr": "/downloads/radarr",
    "sonarr": "/downloads/sonarr",
    "lidarr": "/downloads/lidarr",
}

ACTIVE_STATES = {
    "downloading",
    "forcedDL",
    "metaDL",
    "forcedMetaDL",
    "stalledDL",
    "checkingDL",
    "queuedDL",
}

DOWNLOADING_STATES = {
    "downloading",
    "forcedDL",
    "metaDL",
    "forcedMetaDL",
    "stalledDL",
    "checkingDL",
    "queuedDL",
    "pausedDL",
    "stoppedDL",
}


def log(message: str) -> None:
    print(f"[download-orchestrator] {message}", flush=True)


def now_ts() -> int:
    return int(time.time())


def gb_from_bytes(value: int) -> float:
    return value / (1024**3)


def format_gb(value: int) -> str:
    return f"{gb_from_bytes(value):.2f} GB"


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def read_forwarded_port(path: str) -> int | None:
    file_path = Path(path)
    if not file_path.exists():
        return None
    raw = file_path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    try:
        port = int(raw)
    except ValueError:
        return None
    return port if port > 0 else None


def stat_free_bytes(path: str) -> int:
    stats = os.statvfs(path)
    return stats.f_bavail * stats.f_frsize


class StateStore:
    def __init__(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.runtime = self._load_json(RUNTIME_STATE_PATH, {"stalled_since": {}, "last_decisions": {}})

    @staticmethod
    def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def write_runtime(self) -> None:
        RUNTIME_STATE_PATH.write_text(json.dumps(self.runtime, indent=2, sort_keys=True), encoding="utf-8")

    def write_snapshot(self, snapshot: dict[str, Any]) -> None:
        SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")

    def write_orphan_report(self, report: dict[str, Any]) -> None:
        ORPHAN_REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    def write_qbit_preferences(self, prefs: dict[str, Any]) -> None:
        QBIT_PREFS_PATH.write_text(json.dumps(prefs, indent=2, sort_keys=True), encoding="utf-8")

    def heartbeat(self) -> None:
        HEARTBEAT_PATH.write_text(str(now_ts()), encoding="utf-8")


class QBClient:
    def __init__(self) -> None:
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def _request(self, method: str, path: str, data: dict[str, Any] | None = None) -> bytes:
        payload = None
        headers: dict[str, str] = {}
        if data is not None:
            payload = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(f"{BASE_URL}{path}", data=payload, headers=headers, method=method)
        with self.opener.open(request, timeout=20) as response:
            return response.read()

    def login(self) -> None:
        body = self._request(
            "POST",
            "/api/v2/auth/login",
            {"username": CONFIG.qbit_user, "password": CONFIG.qbit_pass},
        ).decode()
        if body.strip() != "Ok.":
            raise RuntimeError(f"qBittorrent auth failed: {body!r}")

    def preferences(self) -> dict[str, Any]:
        return json.loads(self._request("GET", "/api/v2/app/preferences").decode())

    def info(self) -> list[dict[str, Any]]:
        return json.loads(self._request("GET", "/api/v2/torrents/info?sort=priority&reverse=false").decode())

    def categories(self) -> dict[str, Any]:
        return json.loads(self._request("GET", "/api/v2/torrents/categories").decode())

    def set_preferences(self, updates: dict[str, Any]) -> None:
        self._request("POST", "/api/v2/app/setPreferences", {"json": json.dumps(updates)})

    def stop(self, hashes: list[str]) -> None:
        if hashes:
            self._request("POST", "/api/v2/torrents/stop", {"hashes": "|".join(hashes)})

    def start(self, hashes: list[str]) -> None:
        if hashes:
            self._request("POST", "/api/v2/torrents/start", {"hashes": "|".join(hashes)})

    def recheck(self, hashes: list[str]) -> None:
        if hashes:
            self._request("POST", "/api/v2/torrents/recheck", {"hashes": "|".join(hashes)})

    def reannounce(self, hashes: list[str]) -> None:
        if hashes:
            self._request("POST", "/api/v2/torrents/reannounce", {"hashes": "|".join(hashes)})

    def delete(self, hashes: list[str], delete_files: bool = False) -> None:
        if hashes:
            self._request(
                "POST",
                "/api/v2/torrents/delete",
                {"hashes": "|".join(hashes), "deleteFiles": "true" if delete_files else "false"},
            )


class ArrHistoryCollector:
    APPS = {
        "radarr": {
            "config_path": Path("/arr/radarr/config.xml"),
            "base_url": "http://radarr:7878/api/v3",
            "history_path": "/history",
            "include_suffix": "&includeMovie=false",
            "search_command": "MoviesSearch",
            "entity_ids": ("movieId",),
        },
        "sonarr": {
            "config_path": Path("/arr/sonarr/config.xml"),
            "base_url": "http://sonarr:8989/api/v3",
            "history_path": "/history",
            "include_suffix": "&includeSeries=false&includeEpisode=false",
            "search_command": "EpisodeSearch",
            "entity_ids": ("episodeId",),
        },
        "lidarr": {
            "config_path": Path("/arr/lidarr/config.xml"),
            "base_url": "http://lidarr:8686/api/v1",
            "history_path": "/history",
            "include_suffix": "&includeArtist=false&includeAlbum=false&includeTrack=false",
            "search_command": "AlbumSearch",
            "entity_ids": ("albumId",),
        },
    }

    def __init__(self) -> None:
        self.api_keys = {name: self._read_api_key(meta["config_path"]) for name, meta in self.APPS.items()}

    def status(self) -> dict[str, dict[str, Any]]:
        status: dict[str, dict[str, Any]] = {}
        for name, meta in self.APPS.items():
            path = meta["config_path"]
            status[name] = {
                "configPresent": path.exists(),
                "apiKeyPresent": bool(self.api_keys.get(name)),
                "configPath": str(path),
            }
        return status

    @staticmethod
    def _read_api_key(path: Path) -> str | None:
        if not path.exists():
            return None
        try:
            root = ET.fromstring(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        api_node = root.find("ApiKey")
        return api_node.text.strip() if api_node is not None and api_node.text else None

    @staticmethod
    def _fetch_json(url: str) -> dict[str, Any]:
        with urllib.request.urlopen(url, timeout=20) as response:
            return json.loads(response.read().decode())

    def recent_events(self, lookback_hours: int) -> dict[str, dict[str, Any]]:
        cutoff = now_ts() - (lookback_hours * 3600)
        events: dict[str, dict[str, Any]] = {}

        for app_name, meta in self.APPS.items():
            api_key = self.api_keys.get(app_name)
            if not api_key:
                continue

            page = 1
            while True:
                url = (
                    f"{meta['base_url']}{meta['history_path']}?page={page}&pageSize=200"
                    f"&sortDirection=descending&sortKey=date{meta['include_suffix']}&apikey={api_key}"
                )
                payload = self._fetch_json(url)
                records = payload.get("records", [])
                if not records:
                    break

                stop_paging = False
                for record in records:
                    download_id = str(record.get("downloadId") or "").lower()
                    if not download_id:
                        continue

                    record_ts = self._parse_ts(record.get("date"))
                    if record_ts and record_ts < cutoff:
                        stop_paging = True
                        continue

                    entry = events.setdefault(download_id, {"apps": {}, "downloadId": download_id})
                    app_entry = entry["apps"].setdefault(app_name, {"records": []})
                    app_entry["records"].append(record)
                    app_entry["latestImported"] = self._latest_by_type(app_entry["records"], "imported")
                    app_entry["latestGrabbed"] = self._latest_by_type(app_entry["records"], "grabbed")

                if stop_paging or page >= payload.get("totalPages", page):
                    break
                page += 1

        return events

    def queue_records(self) -> dict[str, list[dict[str, Any]]]:
        snapshots: dict[str, list[dict[str, Any]]] = {}

        for app_name, meta in self.APPS.items():
            api_key = self.api_keys.get(app_name)
            if not api_key:
                continue

            records: list[dict[str, Any]] = []
            page = 1
            while True:
                url = (
                    f"{meta['base_url']}/queue?page={page}&pageSize=200"
                    f"&sortDirection=ascending&sortKey=timeleft&apikey={api_key}"
                )
                payload = self._fetch_json(url)
                page_records = payload.get("records", [])
                if not page_records:
                    break
                records.extend(page_records)
                if page >= payload.get("totalPages", page):
                    break
                page += 1

            snapshots[app_name] = records

        return snapshots

    def wanted_missing_records(self, app_names: tuple[str, ...] = ("radarr",)) -> dict[str, list[dict[str, Any]]]:
        snapshots: dict[str, list[dict[str, Any]]] = {}

        for app_name in app_names:
            meta = self.APPS.get(app_name)
            api_key = self.api_keys.get(app_name)
            if not meta or not api_key:
                continue

            records: list[dict[str, Any]] = []
            page = 1
            while True:
                url = (
                    f"{meta['base_url']}/wanted/missing?page={page}&pageSize=200"
                    f"&sortDirection=descending&sortKey=monitored&apikey={api_key}"
                )
                payload = self._fetch_json(url)
                page_records = payload.get("records", [])
                if not page_records:
                    break
                records.extend(page_records)
                if page >= payload.get("totalPages", page):
                    break
                page += 1

            snapshots[app_name] = records

        return snapshots

    def retry_download(self, app_name: str, grabbed_record: dict[str, Any]) -> dict[str, Any] | None:
        meta = self.APPS.get(app_name)
        api_key = self.api_keys.get(app_name)
        if not meta or not api_key:
            return None

        entity_ids = [int(grabbed_record.get(field, 0) or 0) for field in meta["entity_ids"]]
        entity_ids = [value for value in entity_ids if value > 0]
        if not entity_ids:
            return None

        payload_key = {
            "radarr": "movieIds",
            "sonarr": "episodeIds",
            "lidarr": "albumIds",
        }[app_name]
        payload = {"name": meta["search_command"], payload_key: entity_ids}
        url = f"{meta['base_url']}/command?apikey={api_key}"

        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode())

    def run_search_action(self, app_name: str, action: dict[str, Any]) -> dict[str, Any] | None:
        meta = self.APPS.get(app_name)
        api_key = self.api_keys.get(app_name)
        if not meta or not api_key:
            return None

        payload = {
            key: value
            for key, value in action.items()
            if key not in {"type", "app", "actionKey", "reason"}
        }
        if "command" in payload and "name" not in payload:
            payload["name"] = payload.pop("command")
        if "name" not in payload or not payload:
            return None

        url = f"{meta['base_url']}/command?apikey={api_key}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode())

    @staticmethod
    def _parse_ts(value: str | None) -> int | None:
        if not value:
            return None
        try:
            return int(time.mktime(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")))
        except Exception:
            return None

    @staticmethod
    def _latest_by_type(records: list[dict[str, Any]], keyword: str) -> dict[str, Any] | None:
        matches = [r for r in records if keyword.lower() in str(r.get("eventType", "")).lower()]
        if not matches:
            return None
        matches.sort(key=lambda r: r.get("date", ""), reverse=True)
        return matches[0]


def is_incomplete(torrent: dict[str, Any]) -> bool:
    return float(torrent.get("progress", 0) or 0) < 1 or int(torrent.get("amount_left", 0) or 0) > 0


def is_manageable(torrent: dict[str, Any]) -> bool:
    if not is_incomplete(torrent):
        return False
    if torrent.get("force_start", False) and not CONFIG.manage_force_started:
        return False
    return True


def is_active_download_state(state: str) -> bool:
    return state in ACTIVE_STATES


def remaining_bytes(torrent: dict[str, Any]) -> int:
    return int(torrent.get("amount_left", 0) or 0)


def progress_value(torrent: dict[str, Any]) -> float:
    return float(torrent.get("progress", 0) or 0)


def download_speed(torrent: dict[str, Any]) -> int:
    return int(torrent.get("dlspeed", 0) or 0)


def seed_count(torrent: dict[str, Any]) -> int:
    return int(torrent.get("num_seeds", 0) or 0)


def availability_value(torrent: dict[str, Any]) -> float:
    return float(torrent.get("availability", 0) or 0)


def has_metadata(torrent: dict[str, Any]) -> bool:
    return bool(torrent.get("has_metadata", True))


def is_missing_files_state(torrent: dict[str, Any]) -> bool:
    return str(torrent.get("state") or "") == "missingFiles"


def is_completion_priority(torrent: dict[str, Any]) -> bool:
    remaining_gb = gb_from_bytes(remaining_bytes(torrent))
    return progress_value(torrent) >= CONFIG.completion_priority_progress or remaining_gb <= CONFIG.completion_priority_remaining_gb


def is_swarm_healthy(torrent: dict[str, Any], stall_meta: dict[str, Any]) -> bool:
    if is_missing_files_state(torrent) or not has_metadata(torrent):
        return False
    if download_speed(torrent) > 0:
        return True
    if stall_meta.get("longStalled"):
        return False
    return seed_count(torrent) > 0 or availability_value(torrent) >= CONFIG.healthy_availability_floor


def is_dead_swarm(torrent: dict[str, Any], stall_meta: dict[str, Any]) -> bool:
    if is_missing_files_state(torrent):
        return True
    if not has_metadata(torrent):
        return True
    if download_speed(torrent) > 0:
        return False
    if stall_meta.get("longStalled"):
        return True
    return seed_count(torrent) <= 0 and availability_value(torrent) <= 0


def infer_app_name(torrent: dict[str, Any]) -> str | None:
    category = str(torrent.get("category") or "").strip().lower()
    if category in {"radarr", "sonarr", "lidarr"}:
        return category

    save_path = str(torrent.get("save_path") or "")
    for app_name in ("radarr", "sonarr", "lidarr"):
        if f"/downloads/{app_name}" in save_path.replace("\\", "/"):
            return app_name
    return None


def update_stall_state(store: StateStore, torrent: dict[str, Any]) -> dict[str, Any]:
    stalled_since = store.runtime.setdefault("stalled_since", {})
    torrent_hash = torrent["hash"]
    state = str(torrent.get("state") or "")
    dlspeed = int(torrent.get("dlspeed", 0) or 0)
    amount_left = int(torrent.get("amount_left", 0) or 0)
    active = is_active_download_state(state)

    if active and amount_left > 0 and dlspeed <= 0:
        stalled_since.setdefault(torrent_hash, now_ts())
    else:
        stalled_since.pop(torrent_hash, None)

    started_at = stalled_since.get(torrent_hash)
    stalled_seconds = max(0, now_ts() - started_at) if started_at else 0
    long_stalled = stalled_seconds >= CONFIG.stall_failover_seconds

    return {
        "stalledSeconds": stalled_seconds,
        "longStalled": long_stalled,
    }


def tunnel_guard(prefs: dict[str, Any], forwarded_port: int | None) -> tuple[bool, dict[str, Any]]:
    qbit_port = int(prefs.get("listen_port", 0) or 0)
    current_interface = str(prefs.get("current_network_interface") or "")
    queueing_enabled = bool(prefs.get("queueing_enabled", False))

    details = {
        "forwardedPort": forwarded_port,
        "listenPort": qbit_port,
        "currentInterface": current_interface,
        "expectedInterface": CONFIG.expected_interface,
        "queueingEnabled": queueing_enabled,
    }

    ok = (
        forwarded_port is not None
        and qbit_port == forwarded_port
        and current_interface == CONFIG.expected_interface
        and queueing_enabled
    )
    return ok, details


def protected_settings_guard(
    store: StateStore,
    prefs: dict[str, Any],
    categories: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    pref_values = {key: prefs.get(key) for key in PROTECTED_QBIT_PREF_KEYS if key in prefs}
    category_values = {
        name: categories.get(name, {}).get("savePath")
        for name in EXPECTED_CATEGORY_PATHS
        if name in categories
    }

    pref_baseline = store.runtime.get("protected_qbit_pref_baseline")
    category_baseline = store.runtime.get("protected_qbit_category_baseline")
    seeded = False

    if CONFIG.refresh_protected_baselines or pref_baseline is None:
        store.runtime["protected_qbit_pref_baseline"] = pref_values
        pref_baseline = pref_values
        seeded = True

    if CONFIG.refresh_protected_baselines or category_baseline is None:
        store.runtime["protected_qbit_category_baseline"] = category_values
        category_baseline = category_values
        seeded = True

    pref_drift = {}
    for key, baseline_value in pref_baseline.items():
        current_value = pref_values.get(key)
        if current_value != baseline_value:
            pref_drift[key] = {"baseline": baseline_value, "current": current_value}

    category_path_drift = {}
    missing_categories = []
    for category_name, expected_path in EXPECTED_CATEGORY_PATHS.items():
        category_payload = categories.get(category_name)
        if not category_payload:
            missing_categories.append(category_name)
            continue
        current_path = category_payload.get("savePath")
        if current_path != expected_path:
            category_path_drift[category_name] = {"expected": expected_path, "current": current_path}

    ok = not pref_drift and not category_path_drift and not missing_categories
    return ok, {
        "baselineSeeded": seeded,
        "prefBaselineCount": len(pref_baseline),
        "prefDrift": pref_drift,
        "categoryPathDrift": category_path_drift,
        "missingCategories": missing_categories,
    }


def compute_mode(free_bytes: int, viable_count: int) -> str:
    free_gb = gb_from_bytes(free_bytes)
    if viable_count <= 1:
        return "focused"
    if free_gb <= CONFIG.emergency_free_gb:
        return "emergency"
    if free_gb <= CONFIG.low_space_threshold_gb:
        return "constrained"
    if free_gb <= CONFIG.high_space_threshold_gb:
        return "balanced"
    return "expansive"


def count_budget_fit_candidates(
    candidates: list[dict[str, Any]],
    mode: str,
    free_bytes: int,
    stall_metadata: dict[str, dict[str, Any]],
) -> int:
    reserve_bytes = int(CONFIG.reserved_free_gb * (1024**3))
    budget_bytes = max(0, free_bytes - reserve_bytes)
    if budget_bytes <= 0:
        return 0

    projected_bytes = 0
    fit_count = 0
    for torrent in sorted(
        candidates,
        key=lambda torrent: selection_key(
            torrent,
            mode,
            stall_metadata.get(torrent["hash"], {"stalledSeconds": 0, "longStalled": False}),
        ),
    ):
        if not has_metadata(torrent):
            continue
        next_projection = projected_bytes + max(remaining_bytes(torrent), 0)
        if next_projection > budget_bytes:
            break
        projected_bytes = next_projection
        fit_count += 1
    return fit_count


def target_active_downloads(
    mode: str,
    candidates: list[dict[str, Any]],
    free_bytes: int,
    stall_metadata: dict[str, dict[str, Any]],
    workload_metrics: dict[str, Any],
) -> int:
    viable_count = len(candidates)
    if viable_count <= 0:
        return 0

    base_cap = {
        "focused": CONFIG.max_active_downloads_low,
        "emergency": CONFIG.max_active_downloads_low,
        "constrained": CONFIG.max_active_downloads_low,
        "balanced": CONFIG.max_active_downloads_medium,
        "expansive": CONFIG.max_active_downloads_high,
    }[mode]

    healthy_pool = workload_metrics["healthyCandidateCount"]
    completion_ready = workload_metrics["completionPriorityCount"]
    budget_fit_count = count_budget_fit_candidates(candidates, mode, free_bytes, stall_metadata)

    desired = min(base_cap, viable_count)

    if healthy_pool > 0:
        desired = min(desired, healthy_pool)

    if budget_fit_count > 0:
        desired = min(desired, budget_fit_count)

    if mode == "constrained" and completion_ready >= 2 and healthy_pool >= 2 and budget_fit_count >= 2:
        desired = max(desired, 2)
    elif mode == "balanced" and completion_ready >= 2 and healthy_pool >= 2:
        desired = max(desired, min(2, budget_fit_count or 2, healthy_pool))
    elif mode == "expansive":
        desired = max(desired, min(CONFIG.max_active_downloads_medium, healthy_pool or viable_count))

    if desired <= 0 and viable_count > 0:
        desired = 1
    return min(desired, viable_count)


def managed_active_download_budget(
    total_active_target: int,
    reserved_active_count: int,
    viable_count: int,
    weak_reserved_count: int = 0,
) -> int:
    managed_budget = max(0, total_active_target - max(0, reserved_active_count) - max(0, weak_reserved_count))
    if weak_reserved_count > 0 and reserved_active_count == 0 and viable_count > 0:
        managed_budget = max(1, managed_budget)
    return min(managed_budget, viable_count)


def collect_workload_metrics(candidates: list[dict[str, Any]], stall_metadata: dict[str, dict[str, Any]]) -> dict[str, Any]:
    scheduled = [torrent for torrent in candidates if is_active_download_state(str(torrent.get("state") or ""))]
    downloading = [torrent for torrent in candidates if str(torrent.get("state") or "") in {"downloading", "forcedDL"}]
    moving = [torrent for torrent in scheduled if download_speed(torrent) > 0]
    long_stalled = [torrent for torrent in candidates if stall_metadata.get(torrent["hash"], {}).get("longStalled")]
    metadata_missing = [torrent for torrent in candidates if not has_metadata(torrent)]
    missing_files = [torrent for torrent in candidates if is_missing_files_state(torrent)]
    high_availability = [torrent for torrent in candidates if availability_value(torrent) >= 1.5]
    healthy_candidates = [
        torrent
        for torrent in candidates
        if is_swarm_healthy(torrent, stall_metadata.get(torrent["hash"], {"stalledSeconds": 0, "longStalled": False}))
    ]
    dead_swarm = [
        torrent
        for torrent in candidates
        if is_dead_swarm(torrent, stall_metadata.get(torrent["hash"], {"stalledSeconds": 0, "longStalled": False}))
    ]
    completion_priority = [
        torrent
        for torrent in candidates
        if is_completion_priority(torrent)
        and not is_dead_swarm(torrent, stall_metadata.get(torrent["hash"], {"stalledSeconds": 0, "longStalled": False}))
    ]
    total_speed = sum(download_speed(torrent) for torrent in candidates)
    total_remaining = sum(remaining_bytes(torrent) for torrent in candidates)
    average_speed = int(total_speed / len(moving)) if moving else 0

    return {
        "candidateCount": len(candidates),
        "scheduledCount": len(scheduled),
        "downloadingStateCount": len(downloading),
        "movingCount": len(moving),
        "longStalledCount": len(long_stalled),
        "metadataMissingCount": len(metadata_missing),
        "missingFilesCount": len(missing_files),
        "highAvailabilityCount": len(high_availability),
        "healthyCandidateCount": len(healthy_candidates),
        "deadSwarmCount": len(dead_swarm),
        "completionPriorityCount": len(completion_priority),
        "totalDownloadSpeed": total_speed,
        "averageMovingSpeed": average_speed,
        "remainingBytes": total_remaining,
        "stalledRatio": round((len(long_stalled) / len(candidates)), 3) if candidates else 0,
    }


def should_reserve_active_download(torrent: dict[str, Any], stall_meta: dict[str, Any]) -> bool:
    state = str(torrent.get("state") or "")
    if state not in {"downloading", "forcedDL"}:
        return False
    if is_manageable(torrent):
        return False
    if not bool(torrent.get("force_start", False)):
        return True
    if bool(stall_meta.get("longStalled")):
        return False
    return download_speed(torrent) >= CONFIG.force_started_reserve_min_speed_bps


def is_weak_reserved_active_download(torrent: dict[str, Any], stall_meta: dict[str, Any]) -> bool:
    state = str(torrent.get("state") or "")
    if state not in {"downloading", "forcedDL"}:
        return False
    if is_manageable(torrent):
        return False
    return not should_reserve_active_download(torrent, stall_meta)


def reserved_active_downloads(
    torrents: list[dict[str, Any]],
    stall_metadata: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        torrent
        for torrent in torrents
        if should_reserve_active_download(
            torrent,
            stall_metadata.get(torrent["hash"], {"stalledSeconds": 0, "longStalled": False}),
        )
    ]


def weak_reserved_active_downloads(
    torrents: list[dict[str, Any]],
    stall_metadata: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        torrent
        for torrent in torrents
        if is_weak_reserved_active_download(
            torrent,
            stall_metadata.get(torrent["hash"], {"stalledSeconds": 0, "longStalled": False}),
        )
    ]


def selection_key(torrent: dict[str, Any], mode: str, stall_meta: dict[str, Any]) -> tuple[Any, ...]:
    progress = progress_value(torrent)
    dlspeed = download_speed(torrent)
    availability = availability_value(torrent)
    seeds = seed_count(torrent)
    torrent_has_metadata = has_metadata(torrent)
    remaining = remaining_bytes(torrent)
    added_on = int(torrent.get("added_on", 0) or 0)
    currently_moving = dlspeed > 0
    long_stalled = bool(stall_meta["longStalled"])
    state = str(torrent.get("state") or "")
    completion_priority = is_completion_priority(torrent)

    viability_bucket = 0
    if is_missing_files_state(torrent):
        viability_bucket = 4
    elif not torrent_has_metadata:
        viability_bucket = 3
    elif long_stalled:
        viability_bucket = 2
    elif seeds <= 0 and availability <= 0 and not currently_moving:
        viability_bucket = 1

    if mode in {"emergency", "constrained", "focused"}:
        return (
            viability_bucket,
            0 if currently_moving else 1,
            0 if completion_priority else 1,
            0 if state in {"downloading", "forcedDL"} else 1,
            -progress,
            remaining,
            added_on,
        )

    return (
        viability_bucket,
        0 if currently_moving else 1,
        -availability,
        -seeds,
        -progress,
        added_on,
    )


def choose_allowed(
    candidates: list[dict[str, Any]],
    mode: str,
    free_bytes: int,
    stall_metadata: dict[str, dict[str, Any]],
    target: int,
) -> list[dict[str, Any]]:
    if target <= 0:
        return []

    reserve_bytes = int(CONFIG.reserved_free_gb * (1024**3))
    budget_bytes = max(0, free_bytes - reserve_bytes)
    allowed: list[dict[str, Any]] = []
    projected_bytes = 0

    sorted_candidates = sorted(
        candidates,
        key=lambda torrent: selection_key(torrent, mode, stall_metadata.get(torrent["hash"], {"stalledSeconds": 0, "longStalled": False})),
    )

    for torrent in sorted_candidates:
        if len(allowed) >= target:
            break

        remaining = int(torrent.get("amount_left", 0) or 0)
        has_metadata = bool(torrent.get("has_metadata", True))
        unknown_size = not has_metadata or remaining <= 0
        next_projection = projected_bytes + max(remaining, 0)

        if not allowed:
            allowed.append(torrent)
            projected_bytes = next_projection
            continue

        if unknown_size:
            continue

        if next_projection <= budget_bytes:
            allowed.append(torrent)
            projected_bytes = next_projection

    return allowed


def qbit_speed_targets(mode: str, desired_active_downloads: int, workload_metrics: dict[str, Any]) -> tuple[dict[str, int], list[str]]:
    bucket = speed_mode_bucket(mode)
    per_torrent_connections = {
        "focused": CONFIG.speed_conn_per_torrent_focused,
        "constrained": CONFIG.speed_conn_per_torrent_constrained,
        "balanced": CONFIG.speed_conn_per_torrent_balanced,
        "expansive": CONFIG.speed_conn_per_torrent_expansive,
    }[bucket]
    torrent_headroom = {
        "focused": CONFIG.speed_active_torrent_headroom_focused,
        "constrained": CONFIG.speed_active_torrent_headroom_constrained,
        "balanced": CONFIG.speed_active_torrent_headroom_balanced,
        "expansive": CONFIG.speed_active_torrent_headroom_expansive,
    }[bucket]
    uploads_per_torrent = {
        "focused": CONFIG.speed_upload_slots_per_torrent_focused,
        "constrained": CONFIG.speed_upload_slots_per_torrent_constrained,
        "balanced": CONFIG.speed_upload_slots_per_torrent_balanced,
        "expansive": CONFIG.speed_upload_slots_per_torrent_expansive,
    }[bucket]
    connection_rate = {
        "focused": CONFIG.speed_connection_rate_focused,
        "constrained": CONFIG.speed_connection_rate_constrained,
        "balanced": CONFIG.speed_connection_rate_balanced,
        "expansive": CONFIG.speed_connection_rate_expansive,
    }[bucket]
    http_announces = {
        "focused": CONFIG.speed_http_announces_focused,
        "constrained": CONFIG.speed_http_announces_constrained,
        "balanced": CONFIG.speed_http_announces_balanced,
        "expansive": CONFIG.speed_http_announces_expansive,
    }[bucket]

    reasons: list[str] = [f"mode:{mode}"]
    active_downloads = max(1, desired_active_downloads)

    if workload_metrics["movingCount"] <= 1:
        per_torrent_connections += 20
        connection_rate += 5
        http_announces += 10
        reasons.append("single-moving-torrent-bias")

    if workload_metrics["movingCount"] == 0 and workload_metrics["healthyCandidateCount"] > 0:
        per_torrent_connections += 20
        connection_rate += 10
        http_announces += 10
        reasons.append("bootstrap-swarm-probe")

    if workload_metrics["stalledRatio"] >= 0.4:
        per_torrent_connections += 20
        torrent_headroom = max(2, torrent_headroom - 1)
        http_announces += 10
        reasons.append("stalled-swarm-tightening")

    if workload_metrics["highAvailabilityCount"] >= max(2, active_downloads * 2):
        per_torrent_connections += 10
        reasons.append("high-availability-headroom")

    if workload_metrics["healthyCandidateCount"] >= max(4, active_downloads * 4):
        torrent_headroom += 1
        connection_rate += 10
        http_announces += 10
        global_connection_bonus = 80
        reasons.append("healthy-swarm-expansion")
    else:
        global_connection_bonus = 0

    if 0 < workload_metrics["averageMovingSpeed"] < 1_000_000:
        per_torrent_connections += 20
        reasons.append("slow-moving-transfer-boost")

    if workload_metrics["completionPriorityCount"] >= max(2, active_downloads):
        per_torrent_connections += 10
        connection_rate += 5
        reasons.append("completion-priority-bias")

    if workload_metrics["deadSwarmCount"] >= max(5, active_downloads * 3):
        torrent_headroom = max(2, torrent_headroom - 1)
        global_connection_penalty = 40
        reasons.append("dead-swarm-trimming")
    else:
        global_connection_penalty = 0

    if workload_metrics["metadataMissingCount"] >= max(20, workload_metrics["candidateCount"] // 2):
        global_connection_penalty += 60
        reasons.append("metadata-backlog-trimming")

    active_torrents = active_downloads + torrent_headroom
    active_uploads = active_torrents
    global_connections = clamp(
        (active_downloads * per_torrent_connections) + 120 + global_connection_bonus - global_connection_penalty,
        CONFIG.speed_conn_floor,
        CONFIG.speed_conn_ceiling,
    )

    targets = {
        "max_active_downloads": active_downloads,
        "max_active_torrents": active_torrents,
        "max_active_uploads": active_uploads,
        "max_connec": global_connections,
        "max_connec_per_torrent": per_torrent_connections,
        "max_uploads_per_torrent": uploads_per_torrent,
        "connection_speed": connection_rate,
        "max_concurrent_http_announces": http_announces,
    }
    return targets, reasons


def advanced_qbit_speed_advisories(
    prefs: dict[str, Any],
    mode: str,
    desired_active_downloads: int,
    workload_metrics: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    if not CONFIG.enable_advanced_speed_advisories:
        return {}, ["advanced-speed-advisories-disabled"]

    bucket = speed_mode_bucket(mode)
    moving = max(1, workload_metrics["movingCount"])
    active_downloads = max(1, desired_active_downloads)

    targets = {
        "async_io_threads": clamp(6 + moving + active_downloads, 8, 24),
        "disk_cache": {
            "focused": 384,
            "constrained": 320,
            "balanced": 256,
            "expansive": 192,
        }[bucket],
        "disk_cache_ttl": {
            "focused": 300,
            "constrained": 240,
            "balanced": 180,
            "expansive": 120,
        }[bucket],
        "disk_queue_size": {
            "focused": 2097152,
            "constrained": 2097152,
            "balanced": 1572864,
            "expansive": 1048576,
        }[bucket],
        "request_queue_size": {
            "focused": 1200,
            "constrained": 1000,
            "balanced": 800,
            "expansive": 600,
        }[bucket],
        "enable_piece_extent_affinity": bucket in {"focused", "constrained", "balanced"},
        "enable_coalesce_read_write": bucket in {"focused", "constrained", "balanced"},
        "send_buffer_low_watermark": {
            "focused": 32,
            "constrained": 24,
            "balanced": 18,
            "expansive": 12,
        }[bucket],
        "send_buffer_watermark": {
            "focused": 1200,
            "constrained": 900,
            "balanced": 700,
            "expansive": 500,
        }[bucket],
        "send_buffer_watermark_factor": {
            "focused": 200,
            "constrained": 150,
            "balanced": 120,
            "expansive": 100,
        }[bucket],
        "socket_backlog_size": {
            "focused": 96,
            "constrained": 96,
            "balanced": 128,
            "expansive": 160,
        }[bucket],
        "socket_receive_buffer_size": 0,
        "socket_send_buffer_size": 0,
        "peer_turnover": {
            "focused": 8,
            "constrained": 6,
            "balanced": 4,
            "expansive": 4,
        }[bucket],
        "peer_turnover_cutoff": {
            "focused": 95,
            "constrained": 95,
            "balanced": 90,
            "expansive": 85,
        }[bucket],
        "peer_turnover_interval": {
            "focused": 180,
            "constrained": 240,
            "balanced": 300,
            "expansive": 420,
        }[bucket],
        "file_pool_size": clamp(80 + (moving * 20), 100, 240),
        "checking_memory_use": {
            "focused": 256,
            "constrained": 192,
            "balanced": 128,
            "expansive": 96,
        }[bucket],
    }

    reasons = [f"mode:{mode}"]
    reasons.append("live-promoted" if CONFIG.allow_advanced_qbit_pref_writes else "advisory-only")
    advisories: dict[str, dict[str, Any]] = {}
    for key, target in targets.items():
        if key not in prefs:
            continue
        current = prefs.get(key)
        if current == target:
            continue
        advisories[key] = {"current": current, "target": target}

    return advisories, reasons


def summarize_torrent(torrent: dict[str, Any], stall_meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "hash": torrent.get("hash"),
        "name": torrent.get("name"),
        "state": torrent.get("state"),
        "category": torrent.get("category"),
        "progress": round(float(torrent.get("progress", 0) or 0), 6),
        "dlspeed": int(torrent.get("dlspeed", 0) or 0),
        "eta": int(torrent.get("eta", 0) or 0),
        "numSeeds": int(torrent.get("num_seeds", 0) or 0),
        "numLeechs": int(torrent.get("num_leechs", 0) or 0),
        "availability": float(torrent.get("availability", 0) or 0),
        "amountLeft": int(torrent.get("amount_left", 0) or 0),
        "forceStart": bool(torrent.get("force_start", False)),
        "stalledSeconds": stall_meta["stalledSeconds"],
        "longStalled": stall_meta["longStalled"],
    }


def extract_arr_entity_id(app_name: str, record: dict[str, Any]) -> int:
    fields = {
        "radarr": ("movieId", "id"),
        "sonarr": ("episodeId", "id"),
        "lidarr": ("albumId", "id"),
    }.get(app_name, ())
    for field in fields:
        value = int(record.get(field, 0) or 0)
        if value > 0:
            return value
    return 0


def build_arr_search_action_for_entity(
    app_name: str | None,
    entity_id: int,
    arr_collector: ArrHistoryCollector,
    *,
    reason: str | None = None,
) -> dict[str, Any] | None:
    if not app_name or app_name not in arr_collector.APPS or entity_id <= 0:
        return None

    payload_field = {
        "radarr": "movieIds",
        "sonarr": "episodeIds",
        "lidarr": "albumIds",
    }.get(app_name)
    if not payload_field:
        return None

    action = {
        "type": "arr-search-command",
        "app": app_name,
        "command": arr_collector.APPS[app_name]["search_command"],
        payload_field: [entity_id],
    }
    if reason:
        action["reason"] = reason
    action["actionKey"] = stable_signature(
        {
            "app": app_name,
            "command": action["command"],
            payload_field: action[payload_field],
        }
    )
    return action


def build_arr_search_action(app_name: str | None, grabbed_record: dict[str, Any], arr_collector: ArrHistoryCollector) -> dict[str, Any] | None:
    return build_arr_search_action_for_entity(
        app_name,
        extract_arr_entity_id(app_name, grabbed_record) if app_name else 0,
        arr_collector,
    )


def build_arr_entity_event_index(arr_events: dict[str, dict[str, Any]]) -> dict[str, dict[int, dict[str, Any]]]:
    index: dict[str, dict[int, dict[str, Any]]] = {}
    for bundle in arr_events.values():
        for app_name, app_data in bundle.get("apps", {}).items():
            for record in app_data.get("records", []):
                entity_id = extract_arr_entity_id(app_name, record)
                if entity_id <= 0:
                    continue
                entry = index.setdefault(app_name, {}).setdefault(entity_id, {"records": []})
                entry["records"].append(record)
                entry["latestImported"] = ArrHistoryCollector._latest_by_type(entry["records"], "imported")
                entry["latestGrabbed"] = ArrHistoryCollector._latest_by_type(entry["records"], "grabbed")
                entry["latestFailed"] = ArrHistoryCollector._latest_by_type(entry["records"], "failed")
    return index


def build_arr_queue_index(arr_queue: dict[str, list[dict[str, Any]]]) -> dict[str, dict[int, list[dict[str, Any]]]]:
    index: dict[str, dict[int, list[dict[str, Any]]]] = {}
    for app_name, records in arr_queue.items():
        for record in records:
            entity_id = extract_arr_entity_id(app_name, record)
            if entity_id <= 0:
                continue
            index.setdefault(app_name, {}).setdefault(entity_id, []).append(record)
    return index


def queue_entry_has_file(app_name: str, record: dict[str, Any]) -> bool:
    field = {
        "radarr": "movieHasFile",
        "sonarr": "episodeHasFile",
        "lidarr": "albumHasFile",
    }.get(app_name)
    if field and field in record:
        return bool(record.get(field))
    return bool(record.get("hasFile"))


def first_parseable_ts(*values: Any) -> int:
    for value in values:
        parsed = ArrHistoryCollector._parse_ts(str(value)) if value else None
        if parsed:
            return parsed
    return 0


def normalize_action_history_entry(value: Any) -> dict[str, int]:
    if isinstance(value, dict):
        return {
            "lastTriggeredAt": int(value.get("lastTriggeredAt", 0) or 0),
            "triggerCount": int(value.get("triggerCount", 0) or 0),
        }
    last_triggered = int(value or 0)
    return {"lastTriggeredAt": last_triggered, "triggerCount": 1 if last_triggered else 0}


def retry_limit_for_reason(reason: str) -> int:
    return {
        "broken-replace": CONFIG.max_arr_search_retries_broken,
        "broken-salvage-fallback": CONFIG.max_arr_search_retries_broken,
        "completed-no-import": CONFIG.max_arr_search_retries_orphan,
        "queue-warning": CONFIG.max_arr_search_retries_queue_warning,
        "history-grabbed-no-import": CONFIG.max_arr_search_retries_history,
        "wanted-missing-stale": CONFIG.max_arr_search_retries_wanted,
    }.get(reason, CONFIG.max_arr_search_retries_orphan)


def build_orphan_report(
    torrents: list[dict[str, Any]],
    arr_events: dict[str, dict[str, Any]],
    arr_collector: ArrHistoryCollector,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "graceHours": CONFIG.import_grace_hours,
        "suspects": [],
        "brokenSuspects": [],
        "retroRepairCandidates": [],
        "backlogCandidates": [],
    }

    grace_cutoff = now_ts() - (CONFIG.import_grace_hours * 3600)
    broken_cutoff = now_ts() - (CONFIG.broken_download_grace_hours * 3600)

    for torrent in torrents:
        download_id = str(torrent.get("hash") or "").lower()
        app_name = infer_app_name(torrent)
        event_bundle = arr_events.get(download_id, {})
        app_event = event_bundle.get("apps", {}).get(app_name, {}) if app_name else {}
        imported = app_event.get("latestImported")
        grabbed = app_event.get("latestGrabbed")

        if is_incomplete(torrent):
            if (
                app_name
                and grabbed
                and not imported
                and is_missing_files_state(torrent)
            ):
                reference_ts = int(torrent.get("completion_on", 0) or 0) or int(torrent.get("added_on", 0) or 0)
                if reference_ts > 0 and reference_ts <= broken_cutoff:
                    broken_suspect = {
                        "hash": torrent.get("hash"),
                        "name": torrent.get("name"),
                        "category": torrent.get("category"),
                        "app": app_name,
                        "state": torrent.get("state"),
                        "savePath": torrent.get("save_path"),
                        "referenceTs": reference_ts,
                        "lane": "broken-recovery",
                        "priority": 5,
                        "recoveryMode": "replace",
                        "maxRetries": CONFIG.max_arr_search_retries_broken,
                        "recommendedActions": [],
                    }
                    if seed_count(torrent) > 0 or availability_value(torrent) > 0:
                        broken_suspect["recoveryMode"] = "salvage"
                        broken_suspect["recommendedActions"].extend(
                            [{"type": "qbit-recheck"}, {"type": "qbit-reannounce"}]
                        )

                    search_action = build_arr_search_action(app_name, grabbed, arr_collector)
                    if search_action:
                        broken_suspect["recommendedActions"].append(search_action)

                    report["brokenSuspects"].append(broken_suspect)
            continue

        completion_on = int(torrent.get("completion_on", 0) or 0)
        if completion_on <= 0 or completion_on > grace_cutoff or imported:
            continue

        suspect = {
            "hash": torrent.get("hash"),
            "name": torrent.get("name"),
            "category": torrent.get("category"),
            "app": app_name,
            "completionOn": completion_on,
            "savePath": torrent.get("save_path"),
            "state": torrent.get("state"),
            "lane": "completed-no-import",
            "priority": 20,
            "maxRetries": CONFIG.max_arr_search_retries_orphan,
        }

        if grabbed:
            suspect["grabbedEvent"] = {
                "eventType": grabbed.get("eventType"),
                "date": grabbed.get("date"),
            }
            search_action = build_arr_search_action(app_name, grabbed, arr_collector)
            if search_action:
                suspect["recommendedAction"] = search_action

        report["suspects"].append(suspect)

    report["suspects"].sort(key=lambda item: item["completionOn"])
    report["brokenSuspects"].sort(key=lambda item: item["referenceTs"])
    return report


def build_retroactive_arr_repair_candidates(
    torrents: list[dict[str, Any]],
    arr_events: dict[str, dict[str, Any]],
    arr_queue: dict[str, list[dict[str, Any]]],
    arr_collector: ArrHistoryCollector,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_action_keys: set[str] = set()
    stale_cutoff = now_ts() - (CONFIG.retro_repair_stale_hours * 3600)

    def add_candidate(candidate: dict[str, Any]) -> None:
        action = candidate.get("recommendedAction")
        action_key = str(action.get("actionKey") or "") if isinstance(action, dict) else ""
        if not action_key or action_key in seen_action_keys:
            return
        seen_action_keys.add(action_key)
        candidates.append(candidate)

    for app_name, records in arr_queue.items():
        for record in records:
            entity_id = extract_arr_entity_id(app_name, record)
            if entity_id <= 0:
                continue

            tracked_status = str(record.get("trackedDownloadStatus") or "").lower()
            status_messages = record.get("statusMessages") or []
            reference_ts = first_parseable_ts(record.get("added"))
            if tracked_status == "ok" and not status_messages:
                continue
            if reference_ts and reference_ts > stale_cutoff:
                continue
            if queue_entry_has_file(app_name, record):
                continue

            action = build_arr_search_action_for_entity(
                app_name,
                entity_id,
                arr_collector,
                reason="queue-warning",
            )
            if not action:
                continue

            add_candidate(
                {
                    "app": app_name,
                    "entityId": entity_id,
                    "title": record.get("title") or record.get("sourceTitle"),
                    "lane": "retro-queue-warning",
                    "reason": "queue-warning",
                    "priority": 10,
                    "maxRetries": CONFIG.max_arr_search_retries_queue_warning,
                    "referenceTs": reference_ts,
                    "trackedDownloadStatus": record.get("trackedDownloadStatus"),
                    "trackedDownloadState": record.get("trackedDownloadState"),
                    "downloadId": str(record.get("downloadId") or "").lower(),
                    "statusMessages": status_messages,
                    "recommendedAction": action,
                }
            )

    candidates.sort(key=lambda item: (int(item.get("priority", 99)), int(item.get("referenceTs", 0) or 0)))
    return candidates


def build_backlog_candidates(
    torrents: list[dict[str, Any]],
    arr_events: dict[str, dict[str, Any]],
    arr_queue: dict[str, list[dict[str, Any]]],
    arr_wanted: dict[str, list[dict[str, Any]]],
    arr_collector: ArrHistoryCollector,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_action_keys: set[str] = set()
    entity_index = build_arr_entity_event_index(arr_events)
    queue_index = build_arr_queue_index(arr_queue)
    qbit_hashes = {str(torrent.get("hash") or "").lower() for torrent in torrents}
    stale_cutoff = now_ts() - (CONFIG.retro_repair_stale_hours * 3600)
    lookback_cutoff = now_ts() - (CONFIG.retro_repair_lookback_hours * 3600)

    for app_name, entities in entity_index.items():
        queued_entities = set(queue_index.get(app_name, {}))
        for entity_id, entity_data in entities.items():
            imported = entity_data.get("latestImported")
            grabbed = entity_data.get("latestGrabbed")
            if imported or not grabbed:
                continue

            reference_ts = first_parseable_ts(grabbed.get("date"))
            if reference_ts <= 0 or reference_ts > stale_cutoff:
                continue
            if entity_id in queued_entities:
                continue

            download_id = str(grabbed.get("downloadId") or "").lower()
            if download_id and download_id in qbit_hashes:
                continue

            action = build_arr_search_action_for_entity(
                app_name,
                entity_id,
                arr_collector,
                reason="history-grabbed-no-import",
            )
            if not action:
                continue

            action_key = str(action.get("actionKey") or "")
            if action_key in seen_action_keys:
                continue
            seen_action_keys.add(action_key)

            candidates.append(
                {
                    "app": app_name,
                    "entityId": entity_id,
                    "title": grabbed.get("sourceTitle"),
                    "lane": "backlog-history",
                    "reason": "history-grabbed-no-import",
                    "priority": 25,
                    "maxRetries": CONFIG.max_arr_search_retries_history,
                    "referenceTs": reference_ts,
                    "downloadId": download_id,
                    "grabbedEvent": {
                        "eventType": grabbed.get("eventType"),
                        "date": grabbed.get("date"),
                    },
                    "recommendedAction": action,
                }
            )

    for record in arr_wanted.get("radarr", []):
        entity_id = extract_arr_entity_id("radarr", record)
        if entity_id <= 0 or not bool(record.get("monitored", False)) or bool(record.get("hasFile", False)):
            continue
        if record.get("isAvailable") is False:
            continue

        entity_data = entity_index.get("radarr", {}).get(entity_id, {})
        if entity_data.get("latestImported") or entity_id in queue_index.get("radarr", {}):
            continue

        added_ts = first_parseable_ts(record.get("added"))
        last_search_ts = first_parseable_ts(record.get("lastSearchTime"))
        reference_ts = last_search_ts or added_ts
        if reference_ts <= 0 or reference_ts > stale_cutoff:
            continue
        if added_ts and added_ts < lookback_cutoff:
            continue

        action = build_arr_search_action_for_entity(
            "radarr",
            entity_id,
            arr_collector,
            reason="wanted-missing-stale",
        )
        if not action:
            continue

        action_key = str(action.get("actionKey") or "")
        if action_key in seen_action_keys:
            continue
        seen_action_keys.add(action_key)

        candidates.append(
            {
                "app": "radarr",
                "entityId": entity_id,
                "title": record.get("title"),
                "lane": "backlog-wanted",
                "reason": "wanted-missing-stale",
                "priority": 35,
                "maxRetries": CONFIG.max_arr_search_retries_wanted,
                "referenceTs": reference_ts,
                "added": record.get("added"),
                "lastSearchTime": record.get("lastSearchTime"),
                "recommendedAction": action,
            }
        )

    candidates.sort(key=lambda item: (int(item.get("priority", 99)), int(item.get("referenceTs", 0) or 0)))
    return candidates


def maybe_apply_arr_recovery(
    store: StateStore,
    arr_collector: ArrHistoryCollector,
    report: dict[str, Any],
) -> dict[str, Any]:
    dispatch = {"triggered": [], "skipped": []}
    report["arrActions"] = dispatch

    if CONFIG.observe_only or not CONFIG.allow_arr_commands:
        return dispatch

    history = store.runtime.setdefault("arr_command_history", {})
    action_budget = max(1, CONFIG.max_arr_commands_per_cycle)
    triggered = 0
    now = now_ts()
    candidates: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    qbit_recovery_history = store.runtime.get("qbit_recovery_history", {})

    for suspect in report.get("brokenSuspects", []):
        if not CONFIG.allow_broken_download_recovery:
            continue
        if (
            CONFIG.allow_qbit_recovery_actions
            and suspect.get("recoveryMode") == "salvage"
            and normalize_action_history_entry(qbit_recovery_history.get(str(suspect.get("hash") or ""))).get("triggerCount", 0)
            < CONFIG.max_qbit_recovery_attempts_per_hash
        ):
            continue
        for action in suspect.get("recommendedActions", []):
            if action.get("type") == "arr-search-command":
                candidate = dict(suspect)
                candidate["reason"] = (
                    "broken-salvage-fallback"
                    if suspect.get("recoveryMode") == "salvage"
                    else "broken-replace"
                )
                candidate["maxRetries"] = retry_limit_for_reason(str(candidate.get("reason") or ""))
                candidates.append((int(candidate.get("priority", 5)), candidate, action))

    for suspect in report.get("suspects", []):
        action = suspect.get("recommendedAction")
        if isinstance(action, dict) and action.get("type") == "arr-search-command":
            candidates.append((int(suspect.get("priority", 20)), suspect, action))

    if CONFIG.allow_retroactive_arr_repair:
        for suspect in report.get("retroRepairCandidates", []):
            action = suspect.get("recommendedAction")
            if isinstance(action, dict) and action.get("type") == "arr-search-command":
                candidates.append((int(suspect.get("priority", 30)), suspect, action))

    if CONFIG.allow_backlog_arr_repair:
        for suspect in report.get("backlogCandidates", []):
            action = suspect.get("recommendedAction")
            if isinstance(action, dict) and action.get("type") == "arr-search-command":
                candidates.append((int(suspect.get("priority", 40)), suspect, action))

    candidates.sort(key=lambda item: (item[0], int(item[1].get("referenceTs", item[1].get("completionOn", 0)) or 0)))

    global_last_triggered = int(store.runtime.get("arr_last_command_at", 0) or 0)
    global_remaining = max(0, CONFIG.arr_global_command_interval_seconds - (now - global_last_triggered))
    if candidates and global_last_triggered and global_remaining > 0:
        dispatch["globalCooldownRemainingSeconds"] = global_remaining
        dispatch["skipped"].append({"reason": "global-cooldown", "remainingSeconds": global_remaining})
        return dispatch

    seen_action_keys: set[str] = set()
    for _, candidate, action in candidates:
        action_key = str(action.get("actionKey") or "")
        if not action_key or action_key in seen_action_keys:
            continue
        seen_action_keys.add(action_key)

        if triggered >= action_budget:
            dispatch["skipped"].append({"actionKey": action_key, "reason": "budget-exhausted"})
            continue

        history_entry = normalize_action_history_entry(history.get(action_key))
        retry_limit = int(candidate.get("maxRetries", retry_limit_for_reason(str(candidate.get("reason") or ""))) or 0)
        if retry_limit > 0 and history_entry["triggerCount"] >= retry_limit:
            dispatch["skipped"].append(
                {
                    "actionKey": action_key,
                    "reason": "retry-limit",
                    "triggerCount": history_entry["triggerCount"],
                    "maxRetries": retry_limit,
                }
            )
            continue

        last_triggered = history_entry["lastTriggeredAt"]
        if last_triggered and now - last_triggered < CONFIG.min_arr_command_interval_seconds:
            dispatch["skipped"].append(
                {
                    "actionKey": action_key,
                    "reason": "cooldown",
                    "remainingSeconds": CONFIG.min_arr_command_interval_seconds - (now - last_triggered),
                }
            )
            continue

        try:
            result = arr_collector.run_search_action(str(candidate.get("app") or ""), action)
            if result is not None:
                candidate["retryTriggered"] = result
                history[action_key] = {
                    "lastTriggeredAt": now,
                    "triggerCount": history_entry["triggerCount"] + 1,
                }
                store.runtime["arr_last_command_at"] = now
                triggered += 1
                dispatch["triggered"].append(
                    {
                        "actionKey": action_key,
                        "app": candidate.get("app"),
                        "lane": candidate.get("lane"),
                        "title": candidate.get("title"),
                        "reason": candidate.get("reason"),
                    }
                )
        except Exception as exc:
            candidate["retryError"] = str(exc)
            dispatch["skipped"].append({"actionKey": action_key, "reason": "error", "error": str(exc)})

    return dispatch


def maybe_apply_qbit_recovery(store: StateStore, client: QBClient, report: dict[str, Any]) -> dict[str, Any]:
    dispatch = {"triggered": [], "skipped": []}
    report["qbitRecoveryActions"] = dispatch

    if (
        CONFIG.observe_only
        or not CONFIG.allow_broken_download_recovery
        or not CONFIG.allow_qbit_recovery_actions
    ):
        return dispatch

    history = store.runtime.setdefault("qbit_recovery_history", {})
    action_budget = max(1, CONFIG.max_qbit_recovery_actions_per_cycle)
    triggered = 0
    now = now_ts()

    candidates = sorted(
        (
            suspect
            for suspect in report.get("brokenSuspects", [])
            if suspect.get("recoveryMode") == "salvage" and str(suspect.get("hash") or "")
        ),
        key=lambda item: int(item.get("referenceTs", 0) or 0),
    )

    for suspect in candidates:
        torrent_hash = str(suspect.get("hash") or "")
        if triggered >= action_budget:
            dispatch["skipped"].append({"hash": torrent_hash, "reason": "budget-exhausted"})
            continue

        history_entry = normalize_action_history_entry(history.get(torrent_hash))
        if history_entry["triggerCount"] >= CONFIG.max_qbit_recovery_attempts_per_hash:
            dispatch["skipped"].append(
                {
                    "hash": torrent_hash,
                    "reason": "retry-limit",
                    "triggerCount": history_entry["triggerCount"],
                    "maxRetries": CONFIG.max_qbit_recovery_attempts_per_hash,
                }
            )
            continue

        last_triggered = history_entry["lastTriggeredAt"]
        if last_triggered and now - last_triggered < CONFIG.min_qbit_recovery_interval_seconds:
            dispatch["skipped"].append(
                {
                    "hash": torrent_hash,
                    "reason": "cooldown",
                    "remainingSeconds": CONFIG.min_qbit_recovery_interval_seconds - (now - last_triggered),
                }
            )
            continue

        try:
            client.recheck([torrent_hash])
            client.reannounce([torrent_hash])
            history[torrent_hash] = {
                "lastTriggeredAt": now,
                "triggerCount": history_entry["triggerCount"] + 1,
            }
            suspect["qbitRecoveryTriggered"] = {"recheck": True, "reannounce": True}
            triggered += 1
            dispatch["triggered"].append(
                {
                    "hash": torrent_hash,
                    "title": suspect.get("name"),
                    "recoveryMode": suspect.get("recoveryMode"),
                }
            )
        except Exception as exc:
            suspect["qbitRecoveryError"] = str(exc)
            dispatch["skipped"].append({"hash": torrent_hash, "reason": "error", "error": str(exc)})

    return dispatch


def speed_mode_bucket(mode: str) -> str:
    if mode in {"focused", "emergency"}:
        return "focused"
    if mode == "constrained":
        return "constrained"
    if mode == "balanced":
        return "balanced"
    return "expansive"


def plan_qbit_pref_writes(
    prefs: dict[str, Any],
    desired_active_downloads: int,
    mode: str,
    workload_metrics: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any], list[str]]:
    desired: dict[str, Any] = {"max_active_downloads": desired_active_downloads}
    speed_reasons = ["speed-tuning-disabled"]
    if CONFIG.enable_speed_tuning:
        desired, speed_reasons = qbit_speed_targets(mode, desired_active_downloads, workload_metrics)

    if CONFIG.allow_advanced_qbit_pref_writes:
        advanced_targets, _ = advanced_qbit_speed_advisories(prefs, mode, desired_active_downloads, workload_metrics)
        for key, meta in advanced_targets.items():
            desired[key] = meta.get("target")

    updates: dict[str, Any] = {}
    diffs: dict[str, dict[str, Any]] = {}

    for key, target in desired.items():
        if key not in CONFIG.qbit_write_allowlist:
            continue

        current = prefs.get(key)
        if current != target:
            updates[key] = target
            diffs[key] = {"current": current, "target": target}

    return updates, diffs, desired, speed_reasons


def stable_signature(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def update_stability_guard(
    store: StateStore,
    mode: str,
    to_stop: list[str],
    to_start: list[str],
    pref_updates: dict[str, int],
) -> dict[str, Any]:
    stability = store.runtime.setdefault("stability", {})
    now = now_ts()

    mode_signature = mode
    selection_signature = stable_signature({"start": sorted(to_start), "stop": sorted(to_stop)})
    pref_signature = stable_signature(pref_updates)

    last_mode_signature = stability.get("modeSignature")
    last_selection_signature = stability.get("selectionSignature")
    last_pref_signature = stability.get("prefSignature")

    mode_stable_cycles = 1 if mode_signature != last_mode_signature else int(stability.get("modeStableCycles", 0)) + 1
    selection_stable_cycles = (
        1 if selection_signature != last_selection_signature else int(stability.get("selectionStableCycles", 0)) + 1
    )
    pref_stable_cycles = 1 if pref_signature != last_pref_signature else int(stability.get("prefStableCycles", 0)) + 1

    stability["modeSignature"] = mode_signature
    stability["selectionSignature"] = selection_signature
    stability["prefSignature"] = pref_signature
    stability["modeStableCycles"] = mode_stable_cycles
    stability["selectionStableCycles"] = selection_stable_cycles
    stability["prefStableCycles"] = pref_stable_cycles

    last_pref_write_at = int(stability.get("lastPrefWriteAt", 0) or 0)
    last_torrent_action_at = int(stability.get("lastTorrentActionAt", 0) or 0)
    pref_write_cooldown_remaining = max(0, CONFIG.min_pref_write_interval_seconds - (now - last_pref_write_at))
    torrent_action_cooldown_remaining = max(
        0,
        CONFIG.min_torrent_action_interval_seconds - (now - last_torrent_action_at),
    )

    pref_plan_present = bool(pref_updates)
    torrent_plan_present = bool(to_stop or to_start)

    pref_writes_ready = (
        pref_plan_present
        and pref_stable_cycles >= CONFIG.pref_stability_cycles
        and pref_write_cooldown_remaining <= 0
    )
    torrent_control_ready = (
        torrent_plan_present
        and selection_stable_cycles >= CONFIG.control_stability_cycles
        and torrent_action_cooldown_remaining <= 0
    )

    return {
        "modeStableCycles": mode_stable_cycles,
        "selectionStableCycles": selection_stable_cycles,
        "prefStableCycles": pref_stable_cycles,
        "prefWritesReady": pref_writes_ready,
        "torrentControlReady": torrent_control_ready,
        "prefWriteCooldownRemainingSeconds": pref_write_cooldown_remaining,
        "torrentActionCooldownRemainingSeconds": torrent_action_cooldown_remaining,
    }


def note_pref_write(store: StateStore) -> None:
    store.runtime.setdefault("stability", {})["lastPrefWriteAt"] = now_ts()


def note_torrent_action(store: StateStore) -> None:
    store.runtime.setdefault("stability", {})["lastTorrentActionAt"] = now_ts()


def plan_torrent_actions(
    candidates: list[dict[str, Any]],
    allowed_hashes: set[str],
    mode: str,
    stall_metadata: dict[str, dict[str, Any]],
    desired_active_downloads: int,
) -> tuple[list[str], list[str]]:
    start_candidates = [
        torrent
        for torrent in sorted(
            (torrent for torrent in candidates if torrent["hash"] in allowed_hashes),
            key=lambda item: selection_key(item, mode, stall_metadata[item["hash"]]),
        )
        if str(torrent.get("state") or "") in {"pausedDL", "stoppedDL", "queuedDL", "stalledDL", "metaDL", "checkingDL"}
    ]

    non_allowed_active = [
        torrent
        for torrent in candidates
        if torrent["hash"] not in allowed_hashes and is_active_download_state(str(torrent.get("state") or ""))
    ]
    current_downloaders = [
        torrent for torrent in candidates if str(torrent.get("state") or "") in {"downloading", "forcedDL"}
    ]
    downloader_overage = max(0, len(current_downloaders) - max(0, desired_active_downloads))
    hot_stop_candidates = sorted(
        (
            torrent
            for torrent in non_allowed_active
            if str(torrent.get("state") or "") in {"downloading", "forcedDL"}
        ),
        key=lambda item: selection_key(item, mode, stall_metadata[item["hash"]]),
        reverse=True,
    )
    cold_stop_candidates = sorted(
        (
            torrent
            for torrent in non_allowed_active
            if download_speed(torrent) <= 0
            and (
                is_dead_swarm(torrent, stall_metadata[torrent["hash"]])
                or stall_metadata[torrent["hash"]]["longStalled"]
                or str(torrent.get("state") or "") in {"queuedDL", "stalledDL", "metaDL", "checkingDL"}
            )
        ),
        key=lambda item: selection_key(item, mode, stall_metadata[item["hash"]]),
        reverse=True,
    )
    warm_stop_candidates = sorted(
        (
            torrent
            for torrent in non_allowed_active
            if torrent["hash"] not in {item["hash"] for item in cold_stop_candidates}
        ),
        key=lambda item: selection_key(item, mode, stall_metadata[item["hash"]]),
        reverse=True,
    )
    hot_stop_hashes = {torrent["hash"] for torrent in hot_stop_candidates}
    stop_candidates = hot_stop_candidates + cold_stop_candidates + [
        torrent for torrent in warm_stop_candidates if torrent["hash"] not in hot_stop_hashes
    ]

    action_budget = max(1, CONFIG.max_torrent_actions_per_cycle)
    if start_candidates and stop_candidates:
        start_budget = min(len(start_candidates), max(1, action_budget // 3))
        stop_budget = min(len(stop_candidates), max(1, action_budget - start_budget))
    else:
        start_budget = min(len(start_candidates), action_budget)
        stop_budget = min(len(stop_candidates), action_budget)

    to_start = [torrent["hash"] for torrent in start_candidates[:start_budget]]
    forced_hot_stops = [torrent["hash"] for torrent in hot_stop_candidates[:downloader_overage]]
    remaining_stop_budget = max(0, stop_budget - len(forced_hot_stops))
    existing_stop_hashes = set(forced_hot_stops)
    additional_stops = [
        torrent["hash"]
        for torrent in stop_candidates
        if torrent["hash"] not in existing_stop_hashes
    ][:remaining_stop_budget]
    to_stop = forced_hot_stops + additional_stops
    return to_stop, to_start


def maybe_apply_qbit_pref_writes(client: QBClient, updates: dict[str, Any], writes_ready: bool) -> bool:
    if not updates:
        return False

    if CONFIG.allow_qbit_pref_writes and not CONFIG.observe_only and writes_ready:
        client.set_preferences(updates)
        return True
    return False


def maybe_apply_torrent_control(client: QBClient, to_stop: list[str], to_start: list[str], control_ready: bool) -> bool:
    if CONFIG.observe_only or not CONFIG.allow_torrent_control or not control_ready:
        return False
    if to_stop:
        client.stop(to_stop)
    if to_start:
        client.start(to_start)
    return bool(to_stop or to_start)


def reconcile_cycle(store: StateStore) -> dict[str, Any]:
    if not CONFIG.qbit_user or not CONFIG.qbit_pass:
        raise RuntimeError("QBIT_USER/QBIT_PASS must be set")

    free_bytes = stat_free_bytes(CONFIG.downloads_path)
    forwarded_port = read_forwarded_port(CONFIG.gluetun_port_file)

    qbit = QBClient()
    qbit.login()
    prefs = qbit.preferences()
    store.write_qbit_preferences(prefs)
    categories = qbit.categories()
    torrents = qbit.info()

    previous_pref_keys = set(store.runtime.get("known_qbit_pref_keys", []))
    current_pref_keys = set(prefs.keys())
    new_pref_keys = sorted(current_pref_keys - previous_pref_keys)
    removed_pref_keys = sorted(previous_pref_keys - current_pref_keys)
    store.runtime["known_qbit_pref_keys"] = sorted(current_pref_keys)
    advisory_current_values = {key: prefs.get(key) for key in ADVISORY_QBIT_PREF_KEYS if key in prefs}

    guard_ok, guard_meta = tunnel_guard(prefs, forwarded_port)
    protected_ok, protected_meta = protected_settings_guard(store, prefs, categories)

    candidates = [torrent for torrent in torrents if is_manageable(torrent)]
    stall_metadata = {torrent["hash"]: update_stall_state(store, torrent) for torrent in candidates}
    reserved_downloaders = reserved_active_downloads(torrents, stall_metadata)
    weak_reserved_downloaders = weak_reserved_active_downloads(torrents, stall_metadata)
    workload_metrics = collect_workload_metrics(candidates, stall_metadata)
    viable_count = len(candidates)
    mode = compute_mode(free_bytes, viable_count)
    action_guard_ok = guard_ok and protected_ok
    desired_active_downloads_total = (
        target_active_downloads(
            mode,
            candidates,
            free_bytes,
            stall_metadata,
            workload_metrics,
        )
        if action_guard_ok
        else int(prefs.get("max_active_downloads", 0) or 0)
    )
    desired_active_downloads = managed_active_download_budget(
        desired_active_downloads_total,
        len(reserved_downloaders),
        viable_count,
        len(weak_reserved_downloaders),
    )
    allowed = choose_allowed(candidates, mode, free_bytes, stall_metadata, desired_active_downloads) if action_guard_ok else []
    allowed_hashes = {torrent["hash"] for torrent in allowed}
    to_stop, to_start = (
        plan_torrent_actions(candidates, allowed_hashes, mode, stall_metadata, desired_active_downloads)
        if action_guard_ok
        else ([], [])
    )
    pref_updates, pref_diff, pref_targets, speed_reasons = plan_qbit_pref_writes(
        prefs,
        desired_active_downloads_total,
        mode,
        workload_metrics,
    )
    advanced_speed_advisories, advanced_speed_reasons = advanced_qbit_speed_advisories(
        prefs,
        mode,
        desired_active_downloads_total,
        workload_metrics,
    )
    stability_meta = update_stability_guard(store, mode, to_stop, to_start, pref_updates)
    start_hashes = set(to_start)
    stop_hashes = set(to_stop)
    if action_guard_ok:
        if maybe_apply_qbit_pref_writes(qbit, pref_updates, stability_meta["prefWritesReady"]):
            note_pref_write(store)
        if maybe_apply_torrent_control(qbit, to_stop, to_start, stability_meta["torrentControlReady"]):
            note_torrent_action(store)

    arr_collector = ArrHistoryCollector()
    arr_status = arr_collector.status()
    arr_history_hours = max(CONFIG.arr_history_lookback_hours, CONFIG.retro_repair_lookback_hours)
    arr_events = arr_collector.recent_events(arr_history_hours)
    arr_queue = arr_collector.queue_records()
    arr_wanted = arr_collector.wanted_missing_records(("radarr",))
    orphan_report = build_orphan_report(torrents, arr_events, arr_collector)
    orphan_report["retroRepairCandidates"] = build_retroactive_arr_repair_candidates(
        torrents,
        arr_events,
        arr_queue,
        arr_collector,
    )
    orphan_report["backlogCandidates"] = build_backlog_candidates(
        torrents,
        arr_events,
        arr_queue,
        arr_wanted,
        arr_collector,
    )
    maybe_apply_qbit_recovery(store, qbit, orphan_report)
    maybe_apply_arr_recovery(store, arr_collector, orphan_report)
    store.write_orphan_report(orphan_report)

    snapshot = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "observeOnly": CONFIG.observe_only,
        "nonInterference": {
            "allowTorrentControl": CONFIG.allow_torrent_control,
            "allowQbitPreferenceWrites": CONFIG.allow_qbit_pref_writes,
            "allowAdvancedQbitPreferenceWrites": CONFIG.allow_advanced_qbit_pref_writes,
            "allowQbitRecoveryActions": CONFIG.allow_qbit_recovery_actions,
            "allowArrCommands": CONFIG.allow_arr_commands,
            "allowBrokenDownloadRecovery": CONFIG.allow_broken_download_recovery,
            "allowRetroactiveArrRepair": CONFIG.allow_retroactive_arr_repair,
            "allowBacklogArrRepair": CONFIG.allow_backlog_arr_repair,
        },
        "tunnelGuard": {
            "ok": guard_ok,
            **guard_meta,
        },
        "protectedIntegrationGuard": {
            "ok": protected_ok,
            **protected_meta,
        },
        "space": {
            "downloadsPath": CONFIG.downloads_path,
            "freeBytes": free_bytes,
            "freeGb": round(gb_from_bytes(free_bytes), 2),
            "reservedFreeGb": CONFIG.reserved_free_gb,
        },
        "policy": {
            "mode": mode,
            "candidateCount": viable_count,
            "allowedCount": len(allowed),
            "desiredActiveDownloads": desired_active_downloads_total,
            "desiredManagedDownloads": desired_active_downloads,
            "reservedActiveDownloads": len(reserved_downloaders),
            "weakReservedActiveDownloads": len(weak_reserved_downloaders),
            "prefUpdates": pref_updates,
            "prefDiff": pref_diff,
        },
        "speedPolicy": {
            "enabled": CONFIG.enable_speed_tuning,
            "actionGuardOk": action_guard_ok,
            "reasons": speed_reasons,
            "targets": pref_targets,
            "workloadMetrics": workload_metrics,
        },
        "advancedSpeedAdvisories": {
            "enabled": CONFIG.enable_advanced_speed_advisories,
            "reasons": advanced_speed_reasons,
            "targets": advanced_speed_advisories,
        },
        "stabilityGuard": stability_meta,
        "qbitPreferenceAudit": {
            "snapshotPath": str(QBIT_PREFS_PATH),
            "preferenceCount": len(current_pref_keys),
            "newKeys": new_pref_keys,
            "removedKeys": removed_pref_keys,
            "writeAllowlist": CONFIG.qbit_write_allowlist,
            "advancedWritesLive": CONFIG.allow_advanced_qbit_pref_writes,
            "advisoryOnlyCandidates": advisory_current_values,
        },
        "arrAudit": arr_status,
        "arrQueueAudit": {app: len(records) for app, records in arr_queue.items()},
        "arrWantedAudit": {app: len(records) for app, records in arr_wanted.items()},
        "actions": {
            "start": to_start,
            "stop": to_stop,
        },
        "actionDetails": {
            "start": [
                summarize_torrent(torrent, stall_metadata[torrent["hash"]])
                for torrent in candidates
                if torrent["hash"] in start_hashes
            ],
            "stop": [
                summarize_torrent(torrent, stall_metadata[torrent["hash"]])
                for torrent in candidates
                if torrent["hash"] in stop_hashes
            ],
        },
        "reservedActive": [summarize_torrent(torrent, {"stalledSeconds": 0, "longStalled": False}) for torrent in reserved_downloaders],
        "allowed": [summarize_torrent(torrent, stall_metadata[torrent["hash"]]) for torrent in allowed],
        "topCandidates": [
            summarize_torrent(torrent, stall_metadata[torrent["hash"]])
            for torrent in sorted(
                candidates,
                key=lambda item: selection_key(item, mode, stall_metadata[item["hash"]]),
            )[:10]
        ],
        "orphans": {
            "count": len(orphan_report["suspects"]),
            "brokenCount": len(orphan_report["brokenSuspects"]),
            "retroRepairCount": len(orphan_report["retroRepairCandidates"]),
            "backlogCount": len(orphan_report["backlogCandidates"]),
            "qbitRecoveryTriggered": len(orphan_report.get("qbitRecoveryActions", {}).get("triggered", [])),
            "arrRecoveryTriggered": len(orphan_report.get("arrActions", {}).get("triggered", [])),
            "reportPath": str(ORPHAN_REPORT_PATH),
        },
    }
    store.write_snapshot(snapshot)
    store.write_runtime()
    store.heartbeat()

    selected_names = ", ".join(torrent.get("name", "?") for torrent in allowed[:3]) or "none"
    if len(allowed) > 3:
        selected_names += f" +{len(allowed) - 3} more"

    action_mode = "observe-only" if CONFIG.observe_only else "active"
    log(
        f"mode={mode} guard_ok={guard_ok} protected_ok={protected_ok} action_mode={action_mode} free={format_gb(free_bytes)} "
        f"candidates={viable_count} allowed={len(allowed)} start={len(to_start)} stop={len(to_stop)} "
        f"orphans={len(orphan_report['suspects'])} retro={len(orphan_report['retroRepairCandidates'])} backlog={len(orphan_report['backlogCandidates'])} selected=[{selected_names}]"
    )

    return snapshot


def main() -> int:
    store = StateStore()

    while True:
        try:
            reconcile_cycle(store)
        except Exception as exc:
            log(f"ERROR {exc}")

        if CONFIG.run_once:
            return 0

        time.sleep(CONFIG.check_interval)


if __name__ == "__main__":
    sys.exit(main())
