import json
import math
import os
import socket
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
    qbit_fallback_hosts: tuple[str, ...] = tuple(env_csv("QBIT_FALLBACK_HOSTS", ""))
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
    reserved_free_gb: float = env_float("RESERVED_FREE_GB", 1)
    emergency_free_gb: float = env_float("EMERGENCY_FREE_GB", 3)
    low_space_threshold_gb: float = env_float("LOW_SPACE_THRESHOLD_GB", 100)
    high_space_threshold_gb: float = env_float("HIGH_SPACE_THRESHOLD_GB", 1000)
    max_active_downloads_low: int = env_int("MAX_ACTIVE_DOWNLOADS_LOW", 2)
    max_active_downloads_medium: int = env_int("MAX_ACTIVE_DOWNLOADS_MEDIUM", 6)
    max_active_downloads_high: int = env_int("MAX_ACTIVE_DOWNLOADS_HIGH", 12)
    expansive_probe_slots: int = env_int("EXPANSIVE_PROBE_SLOTS", 6)
    healthy_availability_floor: float = env_float("HEALTHY_AVAILABILITY_FLOOR", 0.25)
    completion_priority_progress: float = env_float("COMPLETION_PRIORITY_PROGRESS", 0.8)
    completion_priority_remaining_gb: float = env_float("COMPLETION_PRIORITY_REMAINING_GB", 8)
    completion_reserve_progress: float = env_float("COMPLETION_RESERVE_PROGRESS", 0.95)
    completion_reserve_remaining_gb: float = env_float("COMPLETION_RESERVE_REMAINING_GB", 4)
    partial_progress_priority_floor: float = env_float("PARTIAL_PROGRESS_PRIORITY_FLOOR", 0.25)
    partial_resume_availability_floor: float = env_float("PARTIAL_RESUME_AVAILABILITY_FLOOR", 0.02)
    partial_resume_progress_floor: float = env_float("PARTIAL_RESUME_PROGRESS_FLOOR", 0.05)
    cold_dead_backlog_grace_seconds: int = env_int("COLD_DEAD_BACKLOG_GRACE_SECONDS", 14400)
    probe_rotation_seconds: int = env_int("PROBE_ROTATION_SECONDS", 120)
    probe_quarantine_seconds: int = env_int("PROBE_QUARANTINE_SECONDS", 900)
    stall_probe_seconds: int = env_int("STALL_PROBE_SECONDS", 240)
    stall_failover_seconds: int = env_int("STALL_FAILOVER_SECONDS", 900)
    force_started_reserve_min_speed_bps: int = env_int("FORCE_STARTED_RESERVE_MIN_SPEED_BPS", 262144)
    manage_force_started: bool = env_bool("MANAGE_FORCE_STARTED", False)
    arr_history_lookback_hours: int = env_int("ARR_HISTORY_LOOKBACK_HOURS", 168)
    retro_repair_lookback_hours: int = env_int("RETRO_REPAIR_LOOKBACK_HOURS", 720)
    retro_repair_stale_hours: int = env_int("RETRO_REPAIR_STALE_HOURS", 24)
    queue_integrity_stale_hours: int = env_int("QUEUE_INTEGRITY_STALE_HOURS", 6)
    queue_missing_download_stale_hours: int = env_int("QUEUE_MISSING_DOWNLOAD_STALE_HOURS", 2)
    arr_log_signal_lookback_hours: int = env_int("ARR_LOG_SIGNAL_LOOKBACK_HOURS", 168)
    arr_log_signal_sample_limit: int = env_int("ARR_LOG_SIGNAL_SAMPLE_LIMIT", 12)
    import_grace_hours: int = env_int("IMPORT_GRACE_HOURS", 6)
    broken_download_grace_hours: int = env_int("BROKEN_DOWNLOAD_GRACE_HOURS", 2)
    max_arr_commands_per_cycle: int = env_int("MAX_ARR_COMMANDS_PER_CYCLE", 2)
    min_arr_command_interval_seconds: int = env_int("MIN_ARR_COMMAND_INTERVAL_SECONDS", 21600)
    arr_global_command_interval_seconds: int = env_int("ARR_GLOBAL_COMMAND_INTERVAL_SECONDS", 300)
    broken_arr_command_interval_seconds: int = env_int("BROKEN_ARR_COMMAND_INTERVAL_SECONDS", 900)
    completed_arr_command_interval_seconds: int = env_int("COMPLETED_ARR_COMMAND_INTERVAL_SECONDS", 3600)
    retro_arr_command_interval_seconds: int = env_int("RETRO_ARR_COMMAND_INTERVAL_SECONDS", 1800)
    backlog_arr_command_interval_seconds: int = env_int("BACKLOG_ARR_COMMAND_INTERVAL_SECONDS", 3600)
    urgent_arr_global_command_interval_seconds: int = env_int("URGENT_ARR_GLOBAL_COMMAND_INTERVAL_SECONDS", 60)
    retro_arr_global_command_interval_seconds: int = env_int("RETRO_ARR_GLOBAL_COMMAND_INTERVAL_SECONDS", 120)
    backlog_arr_global_command_interval_seconds: int = env_int("BACKLOG_ARR_GLOBAL_COMMAND_INTERVAL_SECONDS", 180)
    broken_arr_retry_reset_seconds: int = env_int("BROKEN_ARR_RETRY_RESET_SECONDS", 43200)
    completed_arr_retry_reset_seconds: int = env_int("COMPLETED_ARR_RETRY_RESET_SECONDS", 43200)
    retro_arr_retry_reset_seconds: int = env_int("RETRO_ARR_RETRY_RESET_SECONDS", 86400)
    backlog_arr_retry_reset_seconds: int = env_int("BACKLOG_ARR_RETRY_RESET_SECONDS", 172800)
    arr_queue_cleanup_retry_reset_seconds: int = env_int("ARR_QUEUE_CLEANUP_RETRY_RESET_SECONDS", 86400)
    arr_command_budget_emergency: int = env_int("ARR_COMMAND_BUDGET_EMERGENCY", 1)
    arr_command_budget_repair_burst: int = env_int("ARR_COMMAND_BUDGET_REPAIR_BURST", 3)
    max_arr_search_retries_broken: int = env_int("MAX_ARR_SEARCH_RETRIES_BROKEN", 2)
    max_arr_search_retries_orphan: int = env_int("MAX_ARR_SEARCH_RETRIES_ORPHAN", 1)
    max_arr_search_retries_queue_warning: int = env_int("MAX_ARR_SEARCH_RETRIES_QUEUE_WARNING", 3)
    max_arr_search_retries_history: int = env_int("MAX_ARR_SEARCH_RETRIES_HISTORY", 2)
    max_arr_search_retries_wanted: int = env_int("MAX_ARR_SEARCH_RETRIES_WANTED", 2)
    max_qbit_recovery_actions_per_cycle: int = env_int("MAX_QBIT_RECOVERY_ACTIONS_PER_CYCLE", 1)
    min_qbit_recovery_interval_seconds: int = env_int("MIN_QBIT_RECOVERY_INTERVAL_SECONDS", 7200)
    max_qbit_recovery_attempts_per_hash: int = env_int("MAX_QBIT_RECOVERY_ATTEMPTS_PER_HASH", 2)
    min_qbit_stall_recovery_interval_seconds: int = env_int("MIN_QBIT_STALL_RECOVERY_INTERVAL_SECONDS", 900)
    max_qbit_stall_recovery_attempts_per_hash: int = env_int("MAX_QBIT_STALL_RECOVERY_ATTEMPTS_PER_HASH", 4)
    control_stability_cycles: int = env_int("CONTROL_STABILITY_CYCLES", 2)
    pref_stability_cycles: int = env_int("PREF_STABILITY_CYCLES", 2)
    min_torrent_action_interval_seconds: int = env_int("MIN_TORRENT_ACTION_INTERVAL_SECONDS", 60)
    min_rotation_action_interval_seconds: int = env_int("MIN_ROTATION_ACTION_INTERVAL_SECONDS", 30)
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

if CONFIG.low_space_threshold_gb < 100:
    object.__setattr__(CONFIG, "low_space_threshold_gb", 100.0)
if CONFIG.high_space_threshold_gb < 1000:
    object.__setattr__(CONFIG, "high_space_threshold_gb", 1000.0)
if CONFIG.emergency_free_gb < 25:
    object.__setattr__(CONFIG, "emergency_free_gb", 25.0)
if CONFIG.max_active_downloads_low < 2:
    object.__setattr__(CONFIG, "max_active_downloads_low", 2)
if CONFIG.max_active_downloads_medium < 6:
    object.__setattr__(CONFIG, "max_active_downloads_medium", 6)
if CONFIG.max_active_downloads_high < 12:
    object.__setattr__(CONFIG, "max_active_downloads_high", 12)
if CONFIG.expansive_probe_slots < 6:
    object.__setattr__(CONFIG, "expansive_probe_slots", 6)
if CONFIG.healthy_availability_floor > 0.25:
    object.__setattr__(CONFIG, "healthy_availability_floor", 0.25)
if CONFIG.min_torrent_action_interval_seconds > 60:
    object.__setattr__(CONFIG, "min_torrent_action_interval_seconds", 60)
if CONFIG.min_rotation_action_interval_seconds > 30:
    object.__setattr__(CONFIG, "min_rotation_action_interval_seconds", 30)

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

PASSIVE_BACKLOG_STATES = {
    "pausedDL",
    "stoppedDL",
    "queuedDL",
    "metaDL",
    "checkingDL",
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


def docker_default_gateway() -> str | None:
    route_path = Path("/proc/net/route")
    if not route_path.exists():
        return None
    try:
        lines = route_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 3:
            continue
        destination, gateway = parts[1], parts[2]
        if destination != "00000000":
            continue
        try:
            packed = bytes.fromhex(gateway)
            return socket.inet_ntoa(packed[::-1])
        except Exception:
            continue
    return None


def qbit_host_candidates() -> list[str]:
    candidates: list[str] = []

    def add(host: str | None) -> None:
        value = str(host or "").strip()
        if value and value not in candidates:
            candidates.append(value)

    add(CONFIG.qbit_host)
    for host in CONFIG.qbit_fallback_hosts:
        add(host)
    add(docker_default_gateway())
    return candidates


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
        self.runtime = self._load_json(
            RUNTIME_STATE_PATH,
            {
                "stalled_since": {},
                "last_decisions": {},
                "probe_quarantine_until": {},
            },
        )

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
        self.host_candidates = qbit_host_candidates()
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.base_url: str | None = None

    def _reset_session(self) -> None:
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def _base_url_for_host(self, host: str) -> str:
        return f"http://{host}:{CONFIG.qbit_port}"

    def _request_with_base(
        self,
        base_url: str,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
    ) -> bytes:
        payload = None
        headers: dict[str, str] = {}
        if data is not None:
            payload = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(f"{base_url}{path}", data=payload, headers=headers, method=method)
        with self.opener.open(request, timeout=20) as response:
            return response.read()

    def _login_to_host(self, host: str) -> None:
        self._reset_session()
        candidate_base_url = self._base_url_for_host(host)
        body = self._request_with_base(
            candidate_base_url,
            "POST",
            "/api/v2/auth/login",
            {"username": CONFIG.qbit_user, "password": CONFIG.qbit_pass},
        ).decode()
        if body.strip() != "Ok.":
            raise RuntimeError(f"qBittorrent auth failed: {body!r}")
        if self.base_url != candidate_base_url:
            log(f"qBittorrent endpoint={candidate_base_url}")
        self.base_url = candidate_base_url

    def login(self) -> None:
        last_error: Exception | None = None
        for host in self.host_candidates:
            try:
                self._login_to_host(host)
                return
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"Unable to reach qBittorrent via {self.host_candidates}: {last_error}")

    def _request(self, method: str, path: str, data: dict[str, Any] | None = None) -> bytes:
        if not self.base_url:
            self.login()
        assert self.base_url is not None
        try:
            return self._request_with_base(self.base_url, method, path, data)
        except Exception:
            previous_base_url = self.base_url
            self.login()
            if self.base_url != previous_base_url:
                log(f"qBittorrent failover={self.base_url}")
            return self._request_with_base(self.base_url, method, path, data)

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

    @staticmethod
    def _int_value(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _page_complete(cls, payload: dict[str, Any], page: int, page_records: list[dict[str, Any]], page_size: int) -> bool:
        total_pages = cls._int_value(payload.get("totalPages"))
        if total_pages and total_pages > 0:
            return page >= total_pages

        total_records = cls._int_value(payload.get("totalRecords"))
        if total_records is not None and total_records >= 0:
            return page * page_size >= total_records

        return len(page_records) < page_size

    def recent_events(self, lookback_hours: int) -> dict[str, dict[str, Any]]:
        cutoff = now_ts() - (lookback_hours * 3600)
        events: dict[str, dict[str, Any]] = {}
        page_size = 200

        for app_name, meta in self.APPS.items():
            api_key = self.api_keys.get(app_name)
            if not api_key:
                continue

            page = 1
            while True:
                url = (
                    f"{meta['base_url']}{meta['history_path']}?page={page}&pageSize={page_size}"
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

                if stop_paging or self._page_complete(payload, page, records, page_size):
                    break
                page += 1

        return events

    def queue_records(self) -> dict[str, list[dict[str, Any]]]:
        snapshots: dict[str, list[dict[str, Any]]] = {}
        page_size = 200

        for app_name, meta in self.APPS.items():
            api_key = self.api_keys.get(app_name)
            if not api_key:
                continue

            records: list[dict[str, Any]] = []
            page = 1
            while True:
                url = (
                    f"{meta['base_url']}/queue?page={page}&pageSize={page_size}"
                    f"&sortDirection=ascending&sortKey=timeleft&apikey={api_key}"
                )
                payload = self._fetch_json(url)
                page_records = payload.get("records", [])
                if not page_records:
                    break
                records.extend(page_records)
                if self._page_complete(payload, page, page_records, page_size):
                    break
                page += 1

            snapshots[app_name] = records

        return snapshots

    def wanted_missing_records(self, app_names: tuple[str, ...] = ("radarr",)) -> dict[str, list[dict[str, Any]]]:
        snapshots: dict[str, list[dict[str, Any]]] = {}
        page_size = 200

        for app_name in app_names:
            meta = self.APPS.get(app_name)
            api_key = self.api_keys.get(app_name)
            if not meta or not api_key:
                continue

            try:
                records: list[dict[str, Any]] = []
                page = 1
                while True:
                    url = (
                        f"{meta['base_url']}/wanted/missing?page={page}&pageSize={page_size}"
                        f"&sortDirection=descending&sortKey=monitored&apikey={api_key}"
                    )
                    payload = self._fetch_json(url)
                    page_records = payload.get("records", [])
                    if not page_records:
                        break
                    records.extend(page_records)
                    if self._page_complete(payload, page, page_records, page_size):
                        break
                    page += 1

                snapshots[app_name] = records
            except Exception as exc:
                log(f"wanted/missing fetch failed for {app_name}: {exc}")

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

    def recent_log_signals(self) -> dict[str, dict[str, Any]]:
        signal_patterns = {
            "import-warning": (
                "unable to import automatically",
                "import blocked",
                "import pending",
                "no files found are eligible for import",
                "unexpected considering the",
                "was not found in the grabbed release",
            ),
            "download-warning": (
                "download wasn't grabbed by",
                "download client is unavailable",
                "download client is not available",
                "failed to import download",
            ),
            "missing-files": (
                "missing files",
                "missingfile",
            ),
        }
        summaries: dict[str, dict[str, Any]] = {}
        cutoff = now_ts() - (CONFIG.arr_log_signal_lookback_hours * 3600)
        for app_name, meta in self.APPS.items():
            log_dir = meta["config_path"].parent / "logs"
            summary = {
                "logDir": str(log_dir),
                "filesScanned": 0,
                "signalCounts": {},
                "samples": [],
            }
            if not log_dir.exists():
                summaries[app_name] = summary
                continue
            candidates = sorted(
                [
                    path
                    for path in log_dir.iterdir()
                    if path.is_file() and path.suffix.lower() in {".txt", ".log"}
                ],
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for path in candidates:
                try:
                    if int(path.stat().st_mtime) < cutoff:
                        continue
                    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-1200:]
                except Exception:
                    continue
                summary["filesScanned"] += 1
                for line in lines:
                    lower_line = line.lower()
                    for signal_name, patterns in signal_patterns.items():
                        if not any(pattern in lower_line for pattern in patterns):
                            continue
                        counts = summary["signalCounts"]
                        counts[signal_name] = int(counts.get(signal_name, 0) or 0) + 1
                        if len(summary["samples"]) < CONFIG.arr_log_signal_sample_limit:
                            summary["samples"].append(
                                {
                                    "signal": signal_name,
                                    "file": path.name,
                                    "line": line.strip(),
                                }
                            )
                        break
            summaries[app_name] = summary
        return summaries

    def clear_queue_items(
        self,
        app_name: str,
        queue_ids: list[int],
        *,
        remove_from_client: bool = False,
        blocklist: bool = True,
    ) -> list[dict[str, Any]]:
        meta = self.APPS.get(app_name)
        api_key = self.api_keys.get(app_name)
        if not meta or not api_key:
            return []

        results: list[dict[str, Any]] = []
        for queue_id in sorted({int(queue_id) for queue_id in queue_ids if int(queue_id) > 0}):
            url = (
                f"{meta['base_url']}/queue/{queue_id}?apikey={api_key}"
                f"&removeFromClient={'true' if remove_from_client else 'false'}"
                f"&blocklist={'true' if blocklist else 'false'}"
            )
            request = urllib.request.Request(url, method="DELETE")
            with urllib.request.urlopen(request, timeout=20) as response:
                results.append({"queueId": queue_id, "status": getattr(response, "status", 200)})
        return results

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


def positive_timestamp(*values: Any) -> int:
    for value in values:
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            parsed = 0
        if parsed > 0:
            return parsed
    return 0


def recovery_reference_ts(torrent: dict[str, Any]) -> int:
    timestamps = []
    for key in ("completion_on", "seen_complete", "last_activity", "added_on"):
        value = positive_timestamp(torrent.get(key))
        if value > 0:
            timestamps.append(value)
    return max(timestamps) if timestamps else 0


def broken_swarm_should_salvage(torrent: dict[str, Any]) -> bool:
    return download_speed(torrent) > 0 or seed_count(torrent) > 0 or availability_value(torrent) > 0


def is_stalled_recovery_candidate(torrent: dict[str, Any], stall_meta: dict[str, Any]) -> bool:
    return str(torrent.get("state") or "") == "stalledDL" and bool(stall_meta.get("probeStalled"))


def is_completion_priority(torrent: dict[str, Any]) -> bool:
    remaining_gb = gb_from_bytes(remaining_bytes(torrent))
    return progress_value(torrent) >= CONFIG.completion_priority_progress or remaining_gb <= CONFIG.completion_priority_remaining_gb


def should_reserve_completion_priority_active(torrent: dict[str, Any], stall_meta: dict[str, Any]) -> bool:
    state = str(torrent.get("state") or "")
    if state not in {"downloading", "forcedDL", "stalledDL"}:
        return False
    if bool(stall_meta.get("longStalled")):
        return False
    progress = progress_value(torrent)
    remaining_gb = gb_from_bytes(remaining_bytes(torrent))
    if state == "stalledDL":
        reserve_worthy = progress >= max(CONFIG.completion_priority_progress, 0.8) or remaining_gb <= 0.5
        if not reserve_worthy:
            return False
        return (
            download_speed(torrent) > 0
            or seed_count(torrent) > 0
            or availability_value(torrent) > 0
            or remaining_gb <= 0.5
        )
    return progress >= CONFIG.completion_reserve_progress or remaining_gb <= CONFIG.completion_reserve_remaining_gb


def is_swarm_healthy(torrent: dict[str, Any], stall_meta: dict[str, Any]) -> bool:
    if is_missing_files_state(torrent) or not has_metadata(torrent):
        return False
    if download_speed(torrent) > 0:
        return True
    if stall_meta.get("probeStalled"):
        return False
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


def backlog_reference_ts(torrent: dict[str, Any]) -> int:
    return positive_timestamp(torrent.get("last_activity"), torrent.get("added_on"))


def is_cold_dead_backlog_candidate(torrent: dict[str, Any], stall_meta: dict[str, Any]) -> bool:
    if not is_manageable(torrent):
        return False

    state = str(torrent.get("state") or "")
    if state not in PASSIVE_BACKLOG_STATES:
        return False

    if progress_value(torrent) > 0:
        return False

    if download_speed(torrent) > 0:
        return False

    if seed_count(torrent) > 0 or availability_value(torrent) > 0:
        return False

    reference_ts = backlog_reference_ts(torrent)
    if reference_ts > 0 and (now_ts() - reference_ts) < CONFIG.cold_dead_backlog_grace_seconds:
        return False

    return is_dead_swarm(torrent, stall_meta)


def is_probe_rotation_candidate(torrent: dict[str, Any], stall_meta: dict[str, Any]) -> bool:
    if bool(torrent.get("force_start")) and not CONFIG.manage_force_started:
        return False
    if should_reserve_completion_priority_active(torrent, stall_meta):
        return False
    if is_near_complete_probe_candidate(torrent, stall_meta):
        return False
    if not is_active_download_state(str(torrent.get("state") or "")):
        return False
    if remaining_bytes(torrent) <= 0 or download_speed(torrent) > 0:
        return False
    return int(stall_meta.get("stalledSeconds", 0) or 0) >= CONFIG.probe_rotation_seconds


def should_quarantine_probe_on_stop(torrent: dict[str, Any], stall_meta: dict[str, Any]) -> bool:
    if bool(torrent.get("force_start")) and not CONFIG.manage_force_started:
        return False
    if should_reserve_completion_priority_active(torrent, stall_meta):
        return False
    if is_near_complete_probe_candidate(torrent, stall_meta):
        return False
    if not is_active_download_state(str(torrent.get("state") or "")):
        return False
    if remaining_bytes(torrent) <= 0:
        return False
    if download_speed(torrent) > 0:
        return False
    return True


def is_near_complete_probe_candidate(torrent: dict[str, Any], stall_meta: dict[str, Any]) -> bool:
    if is_missing_files_state(torrent):
        return False
    if not has_metadata(torrent):
        return False
    if bool(stall_meta.get("longStalled")) or bool(stall_meta.get("probeStalled")):
        return False
    if progress_value(torrent) < CONFIG.completion_reserve_progress:
        return False
    if download_speed(torrent) > 0:
        return True
    if seed_count(torrent) > 0:
        return True
    return availability_value(torrent) > 0.05


def prune_probe_quarantine(store: StateStore) -> dict[str, int]:
    raw = store.runtime.setdefault("probe_quarantine_until", {})
    now = now_ts()
    active: dict[str, int] = {}
    for torrent_hash, until_ts in list(raw.items()):
        try:
            parsed = int(until_ts or 0)
        except (TypeError, ValueError):
            continue
        if parsed > now:
            active[torrent_hash] = parsed
    store.runtime["probe_quarantine_until"] = active
    return active


def note_probe_quarantine(store: StateStore, hashes: list[str]) -> None:
    if not hashes:
        return
    quarantine = prune_probe_quarantine(store)
    until_ts = now_ts() + CONFIG.probe_quarantine_seconds
    for torrent_hash in hashes:
        quarantine[torrent_hash] = until_ts
    store.runtime["probe_quarantine_until"] = quarantine


def clear_probe_quarantine(store: StateStore, hashes: list[str]) -> None:
    if not hashes:
        return
    quarantine = prune_probe_quarantine(store)
    for torrent_hash in hashes:
        quarantine.pop(torrent_hash, None)
    store.runtime["probe_quarantine_until"] = quarantine


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
    probe_quarantine = store.runtime.setdefault("probe_quarantine_until", {})
    torrent_hash = torrent["hash"]
    state = str(torrent.get("state") or "")
    dlspeed = int(torrent.get("dlspeed", 0) or 0)
    amount_left = int(torrent.get("amount_left", 0) or 0)
    active = is_active_download_state(state)

    if active and amount_left > 0 and dlspeed <= 0:
        stalled_since.setdefault(torrent_hash, now_ts())
    else:
        stalled_since.pop(torrent_hash, None)
        probe_quarantine.pop(torrent_hash, None)

    started_at = stalled_since.get(torrent_hash)
    stalled_seconds = max(0, now_ts() - started_at) if started_at else 0
    probe_stalled = stalled_seconds >= CONFIG.stall_probe_seconds
    long_stalled = stalled_seconds >= CONFIG.stall_failover_seconds

    return {
        "stalledSeconds": stalled_seconds,
        "probeStalled": probe_stalled,
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
    # The qB listen port is intentionally dynamic because it follows the
    # Gluetun-forwarded port. tunnel_guard() already verifies that live
    # relationship, so protected baselines should focus on settings that are
    # expected to stay static across normal Harbor operation.
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
    else:
        normalized_pref_baseline = {
            key: value
            for key, value in pref_baseline.items()
            if key in PROTECTED_QBIT_PREF_KEYS
        }
        if normalized_pref_baseline != pref_baseline:
            store.runtime["protected_qbit_pref_baseline"] = normalized_pref_baseline
            pref_baseline = normalized_pref_baseline
            seeded = True

    if CONFIG.refresh_protected_baselines or category_baseline is None:
        store.runtime["protected_qbit_category_baseline"] = category_values
        category_baseline = category_values
        seeded = True
    else:
        normalized_category_baseline = {
            key: value
            for key, value in category_baseline.items()
            if key in EXPECTED_CATEGORY_PATHS
        }
        if normalized_category_baseline != category_baseline:
            store.runtime["protected_qbit_category_baseline"] = normalized_category_baseline
            category_baseline = normalized_category_baseline
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
    partial_resume_pool = workload_metrics.get("partialResumeCount", healthy_pool)
    completion_ready = workload_metrics["completionPriorityCount"]
    budget_fit_count = count_budget_fit_candidates(candidates, mode, free_bytes, stall_metadata)

    desired = min(base_cap, viable_count)

    if healthy_pool > 0:
        health_cap = healthy_pool
        if mode == "expansive":
            probe_slots = min(CONFIG.expansive_probe_slots, max(0, viable_count - healthy_pool))
            if workload_metrics["deadSwarmCount"] >= max(50, viable_count - healthy_pool):
                probe_slots = min(probe_slots, 1)
            health_cap += probe_slots
        desired = min(desired, health_cap)

    if budget_fit_count > 0:
        desired = min(desired, budget_fit_count)

    if mode == "constrained" and completion_ready >= 2 and healthy_pool >= 2 and budget_fit_count >= 2:
        desired = max(desired, 2)
    elif mode == "balanced" and completion_ready >= 2 and healthy_pool >= 2:
        desired = max(desired, min(2, budget_fit_count or 2, healthy_pool))
    elif mode == "expansive":
        expansive_resume_cap = max(
            healthy_pool + min(CONFIG.expansive_probe_slots, max(0, viable_count - healthy_pool)),
            min(partial_resume_pool, CONFIG.max_active_downloads_high),
        )
        desired = max(desired, min(CONFIG.max_active_downloads_high, expansive_resume_cap or viable_count))

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
    probe_stalled = [torrent for torrent in candidates if stall_metadata.get(torrent["hash"], {}).get("probeStalled")]
    long_stalled = [torrent for torrent in candidates if stall_metadata.get(torrent["hash"], {}).get("longStalled")]
    metadata_missing = [torrent for torrent in candidates if not has_metadata(torrent)]
    missing_files = [torrent for torrent in candidates if is_missing_files_state(torrent)]
    high_availability = [torrent for torrent in candidates if availability_value(torrent) >= 1.5]
    healthy_candidates = [
        torrent
        for torrent in candidates
        if is_swarm_healthy(torrent, stall_metadata.get(torrent["hash"], {"stalledSeconds": 0, "longStalled": False}))
    ]
    partial_resume = [
        torrent
        for torrent in candidates
        if is_partial_resume_candidate(torrent, stall_metadata.get(torrent["hash"], {"stalledSeconds": 0, "longStalled": False}))
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
        "probeStalledCount": len(probe_stalled),
        "longStalledCount": len(long_stalled),
        "metadataMissingCount": len(metadata_missing),
        "missingFilesCount": len(missing_files),
        "highAvailabilityCount": len(high_availability),
        "healthyCandidateCount": len(healthy_candidates),
        "partialResumeCount": len(partial_resume),
        "deadSwarmCount": len(dead_swarm),
        "completionPriorityCount": len(completion_priority),
        "totalDownloadSpeed": total_speed,
        "averageMovingSpeed": average_speed,
        "remainingBytes": total_remaining,
        "stalledRatio": round((len(probe_stalled) / len(candidates)), 3) if candidates else 0,
    }


def should_reserve_active_download(torrent: dict[str, Any], stall_meta: dict[str, Any]) -> bool:
    state = str(torrent.get("state") or "")
    if state not in {"downloading", "forcedDL"}:
        return False
    if is_manageable(torrent):
        return False
    if should_reserve_completion_priority_active(torrent, stall_meta):
        return True
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
    leechs = int(torrent.get("num_leechs", 0) or 0)
    torrent_has_metadata = has_metadata(torrent)
    remaining = remaining_bytes(torrent)
    added_on = int(torrent.get("added_on", 0) or 0)
    currently_moving = dlspeed > 0
    long_stalled = bool(stall_meta["longStalled"])
    probe_stalled = bool(stall_meta.get("probeStalled"))
    state = str(torrent.get("state") or "")
    healthy_swarm = is_swarm_healthy(torrent, stall_meta)
    dead_swarm = is_dead_swarm(torrent, stall_meta)
    finish_bias = (not dead_swarm) and progress >= CONFIG.partial_progress_priority_floor

    viability_bucket = 0
    if is_missing_files_state(torrent):
        viability_bucket = 4
    elif not torrent_has_metadata:
        viability_bucket = 3
    elif long_stalled:
        viability_bucket = 2
    elif probe_stalled and not currently_moving:
        viability_bucket = 1
    elif not healthy_swarm and not currently_moving:
        viability_bucket = 1
    elif seeds <= 0 and availability <= 0 and not currently_moving:
        viability_bucket = 2

    state_bucket = 0
    if not currently_moving:
        if state == "stalledDL":
            state_bucket = 2
        elif state in {"downloading", "forcedDL"}:
            state_bucket = 1
    peer_signal = -(min(seeds, 50) + min(leechs, 50))

    if mode in {"emergency", "constrained", "focused"}:
        return (
            0 if finish_bias else 1,
            0 if (finish_bias and currently_moving) else 1,
            -(progress if finish_bias else 0),
            remaining if finish_bias else 0,
            0 if currently_moving else 1,
            viability_bucket,
            state_bucket,
            peer_signal,
            -availability,
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


def is_partial_resume_candidate(torrent: dict[str, Any], stall_meta: dict[str, Any]) -> bool:
    if is_missing_files_state(torrent):
        return False
    if not has_metadata(torrent):
        return False
    if bool(stall_meta.get("probeStalled")) or bool(stall_meta.get("longStalled")):
        return False
    return (
        progress_value(torrent) >= CONFIG.partial_resume_progress_floor
        and availability_value(torrent) >= CONFIG.partial_resume_availability_floor
    )


def is_viable_probe_candidate(mode: str, torrent: dict[str, Any], stall_meta: dict[str, Any]) -> bool:
    if download_speed(torrent) > 0:
        return True
    if is_swarm_healthy(torrent, stall_meta):
        return True
    if seed_count(torrent) > 0:
        return True
    if availability_value(torrent) >= 1.0:
        return True
    return mode == "expansive" and is_partial_resume_candidate(torrent, stall_meta)


def is_finish_priority_probe_candidate(torrent: dict[str, Any], stall_meta: dict[str, Any]) -> bool:
    if is_missing_files_state(torrent):
        return False
    if not has_metadata(torrent):
        return False
    if bool(stall_meta.get("longStalled")) or bool(stall_meta.get("probeStalled")):
        return False
    if is_dead_swarm(torrent, stall_meta):
        return False

    progress = progress_value(torrent)
    if progress < CONFIG.partial_progress_priority_floor:
        return False

    if download_speed(torrent) > 0:
        return True
    if seed_count(torrent) > 0:
        return True

    return availability_value(torrent) > 0


def is_best_effort_probe_candidate(mode: str, torrent: dict[str, Any], stall_meta: dict[str, Any]) -> bool:
    if is_missing_files_state(torrent):
        return False
    if bool(stall_meta.get("longStalled")) or bool(stall_meta.get("probeStalled")):
        return False
    if download_speed(torrent) > 0:
        return True
    availability = availability_value(torrent)
    seeds = seed_count(torrent)
    progress = progress_value(torrent)
    if seeds > 0:
        return True
    if availability >= 0.15:
        return True
    if mode == "expansive" and is_partial_resume_candidate(torrent, stall_meta):
        return True
    if is_completion_priority(torrent) and progress >= 0.5 and availability > 0.05:
        return True
    return False


def is_metadata_bootstrap_candidate(mode: str, torrent: dict[str, Any], stall_meta: dict[str, Any]) -> bool:
    if mode != "expansive":
        return False
    if is_missing_files_state(torrent):
        return False
    if has_metadata(torrent):
        return False
    if bool(stall_meta.get("longStalled")) or bool(stall_meta.get("probeStalled")):
        return False
    state = str(torrent.get("state") or "")
    if state not in {"pausedDL", "stoppedDL", "queuedDL", "metaDL", "checkingDL"}:
        return False
    return int(torrent.get("trackers_count", 0) or 0) > 0


def choose_allowed(
    store: StateStore,
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
    active_downloader_count = sum(
        1 for torrent in candidates if str(torrent.get("state") or "") in {"downloading", "forcedDL"}
    )
    moving_downloader_count = sum(1 for torrent in candidates if download_speed(torrent) > 0)
    bootstrap_target = 0
    if mode == "expansive" and active_downloader_count < target:
        underfilled = moving_downloader_count <= 2 or active_downloader_count <= max(2, target // 2)
        if underfilled:
            bootstrap_target = min(target, max(6, min(CONFIG.expansive_probe_slots, 8)))

    sorted_candidates = sorted(
        candidates,
        key=lambda torrent: selection_key(torrent, mode, stall_metadata.get(torrent["hash"], {"stalledSeconds": 0, "longStalled": False})),
    )
    quarantined_hashes = set(prune_probe_quarantine(store).keys())
    preferred_candidates = [
        torrent
        for torrent in sorted_candidates
        if torrent["hash"] not in quarantined_hashes
        and not is_probe_rotation_candidate(
            torrent,
            stall_metadata.get(
                torrent["hash"],
                {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
            ),
        )
    ]
    selection_pool = preferred_candidates or sorted_candidates

    for torrent in selection_pool:
        if len(allowed) >= target:
            break

        remaining = int(torrent.get("amount_left", 0) or 0)
        has_metadata = bool(torrent.get("has_metadata", True))
        unknown_size = not has_metadata or remaining <= 0
        next_projection = projected_bytes + max(remaining, 0)
        stall_meta = stall_metadata.get(
            torrent["hash"],
            {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
        )
        viable = is_viable_probe_candidate(mode, torrent, stall_meta)
        bootstrap_candidate = (
            bootstrap_target > len(allowed)
            and (
                is_finish_priority_probe_candidate(torrent, stall_meta)
                or is_best_effort_probe_candidate(mode, torrent, stall_meta)
                or is_metadata_bootstrap_candidate(mode, torrent, stall_meta)
            )
        )

        if not allowed:
            finish_preferred = mode in {"emergency", "constrained", "focused"} and is_finish_priority_probe_candidate(
                torrent, stall_meta
            )
            if not finish_preferred and not viable and not bootstrap_candidate:
                continue
            allowed.append(torrent)
            projected_bytes = next_projection
            continue

        if not viable and not bootstrap_candidate:
            continue

        if unknown_size:
            if bootstrap_candidate:
                allowed.append(torrent)
                projected_bytes = next_projection
            continue

        if next_projection <= budget_bytes:
            allowed.append(torrent)
            projected_bytes = next_projection

    if bootstrap_target > len(allowed):
        existing_hashes = {torrent["hash"] for torrent in allowed}
        bootstrap_pool = [
            torrent
            for torrent in selection_pool
            if torrent["hash"] not in existing_hashes
            and (
                is_finish_priority_probe_candidate(
                    torrent,
                    stall_metadata.get(
                        torrent["hash"],
                        {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
                    ),
                )
                or is_best_effort_probe_candidate(
                    mode,
                    torrent,
                    stall_metadata.get(
                        torrent["hash"],
                        {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
                    ),
                )
                or is_metadata_bootstrap_candidate(
                    mode,
                    torrent,
                    stall_metadata.get(
                        torrent["hash"],
                        {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
                    ),
                )
            )
        ]
        for torrent in bootstrap_pool:
            if len(allowed) >= bootstrap_target:
                break
            remaining = int(torrent.get("amount_left", 0) or 0)
            next_projection = projected_bytes + max(remaining, 0)
            if remaining > 0 and next_projection > budget_bytes:
                continue
            allowed.append(torrent)
            projected_bytes = next_projection

    if allowed or target <= 0:
        return allowed

    fallback_pool = [
        torrent
        for torrent in selection_pool
        if is_best_effort_probe_candidate(
            mode,
            torrent,
            stall_metadata.get(
                torrent["hash"],
                {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
            ),
        )
    ]
    if fallback_pool:
        return [fallback_pool[0]]

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


def extract_arr_entity_ids(app_name: str, records: list[dict[str, Any]]) -> list[int]:
    ids = sorted({extract_arr_entity_id(app_name, record) for record in records if extract_arr_entity_id(app_name, record) > 0})
    return ids


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


def build_arr_search_action_for_entities(
    app_name: str | None,
    entity_ids: list[int],
    arr_collector: ArrHistoryCollector,
    *,
    reason: str | None = None,
) -> dict[str, Any] | None:
    if not app_name or app_name not in arr_collector.APPS:
        return None
    filtered_ids = sorted({int(entity_id) for entity_id in entity_ids if int(entity_id) > 0})
    if not filtered_ids:
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
        payload_field: filtered_ids,
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
    return build_arr_search_action_for_entities(
        app_name,
        [extract_arr_entity_id(app_name, grabbed_record)] if app_name else [],
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


def build_arr_queue_download_index(arr_queue: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    index: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for app_name, records in arr_queue.items():
        for record in records:
            download_id = str(record.get("downloadId") or "").lower()
            if not download_id:
                continue
            index.setdefault(app_name, {}).setdefault(download_id, []).append(record)
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


def flatten_status_messages(record: dict[str, Any]) -> list[str]:
    flattened: list[str] = []
    for item in record.get("statusMessages") or []:
        if isinstance(item, dict):
            messages = item.get("messages")
            if isinstance(messages, list):
                flattened.extend(str(message).strip() for message in messages if str(message).strip())
            elif messages:
                flattened.append(str(messages).strip())
            title = item.get("title")
            if title:
                flattened.append(str(title).strip())
        elif item:
            flattened.append(str(item).strip())
    return [message for message in flattened if message]


def wanted_entry_has_file(app_name: str, record: dict[str, Any]) -> bool:
    if app_name in {"radarr", "sonarr"}:
        return bool(record.get("hasFile", False))
    if app_name == "lidarr":
        stats = record.get("statistics") or {}
        track_file_count = int(stats.get("trackFileCount", 0) or 0)
        track_count = int(stats.get("trackCount", 0) or 0)
        return track_count > 0 and track_file_count >= track_count
    return False


def first_parseable_ts(*values: Any) -> int:
    for value in values:
        parsed = ArrHistoryCollector._parse_ts(str(value)) if value else None
        if parsed:
            return parsed
    return 0


def wanted_entry_reference_ts(app_name: str, record: dict[str, Any]) -> int:
    if app_name == "radarr":
        return first_parseable_ts(record.get("lastSearchTime"), record.get("added"))
    if app_name == "sonarr":
        return first_parseable_ts(record.get("lastSearchTime"), record.get("airDateUtc"))
    if app_name == "lidarr":
        return first_parseable_ts(record.get("lastSearchTime"), record.get("releaseDate"))
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
        "queue-import-warning": CONFIG.max_arr_search_retries_queue_warning,
        "queue-download-missing": CONFIG.max_arr_search_retries_queue_warning,
        "history-grabbed-no-import": CONFIG.max_arr_search_retries_history,
        "history-failed-no-import": CONFIG.max_arr_search_retries_history,
        "wanted-missing-stale": CONFIG.max_arr_search_retries_wanted,
    }.get(reason, CONFIG.max_arr_search_retries_orphan)


def reset_history_entry_if_stale(entry: dict[str, int], reset_seconds: int, now: int) -> dict[str, int]:
    if reset_seconds <= 0:
        return entry
    last_triggered = int(entry.get("lastTriggeredAt", 0) or 0)
    if last_triggered <= 0:
        return entry
    if now - last_triggered < reset_seconds:
        return entry
    return {"lastTriggeredAt": 0, "triggerCount": 0}


def candidate_lane(candidate: dict[str, Any]) -> str:
    return str(candidate.get("lane") or "")


def arr_candidate_interval_seconds(candidate: dict[str, Any]) -> int:
    lane = candidate_lane(candidate)
    if lane == "broken-recovery":
        return min(CONFIG.min_arr_command_interval_seconds, CONFIG.broken_arr_command_interval_seconds)
    if lane == "completed-no-import":
        return min(CONFIG.min_arr_command_interval_seconds, CONFIG.completed_arr_command_interval_seconds)
    if lane == "retro-queue-warning":
        return min(CONFIG.min_arr_command_interval_seconds, CONFIG.retro_arr_command_interval_seconds)
    if lane.startswith("backlog-"):
        return min(CONFIG.min_arr_command_interval_seconds, CONFIG.backlog_arr_command_interval_seconds)
    return CONFIG.min_arr_command_interval_seconds


def arr_candidate_retry_reset_seconds(candidate: dict[str, Any]) -> int:
    lane = candidate_lane(candidate)
    if lane == "broken-recovery":
        return CONFIG.broken_arr_retry_reset_seconds
    if lane == "completed-no-import":
        return CONFIG.completed_arr_retry_reset_seconds
    if lane == "retro-queue-warning":
        return CONFIG.retro_arr_retry_reset_seconds
    if lane.startswith("backlog-"):
        return CONFIG.backlog_arr_retry_reset_seconds
    return CONFIG.backlog_arr_retry_reset_seconds


def arr_recovery_budget(report: dict[str, Any], free_bytes: int | None) -> int:
    budget = max(1, CONFIG.max_arr_commands_per_cycle)
    broken_count = len(report.get("brokenSuspects", []))
    retro_count = len(report.get("retroRepairCandidates", []))
    backlog_count = len(report.get("backlogCandidates", []))
    free_gb = gb_from_bytes(free_bytes) if free_bytes is not None else None

    if broken_count > 0:
        return max(budget, CONFIG.arr_command_budget_repair_burst)
    if retro_count > 0:
        return max(budget, min(CONFIG.arr_command_budget_repair_burst, 2))
    if backlog_count > 0:
        if free_gb is not None and free_gb <= CONFIG.emergency_free_gb:
            return max(1, min(budget, CONFIG.arr_command_budget_emergency))
        return max(budget, min(CONFIG.arr_command_budget_repair_burst, 2))
    return budget


def arr_recovery_global_interval_seconds(report: dict[str, Any], free_bytes: int | None) -> int:
    broken_count = len(report.get("brokenSuspects", []))
    retro_count = len(report.get("retroRepairCandidates", []))
    backlog_count = len(report.get("backlogCandidates", []))
    free_gb = gb_from_bytes(free_bytes) if free_bytes is not None else None

    if broken_count > 0:
        return min(CONFIG.arr_global_command_interval_seconds, CONFIG.urgent_arr_global_command_interval_seconds)
    if retro_count > 0:
        return min(CONFIG.arr_global_command_interval_seconds, CONFIG.retro_arr_global_command_interval_seconds)
    if backlog_count > 0 and (free_gb is None or free_gb > CONFIG.emergency_free_gb):
        return min(CONFIG.arr_global_command_interval_seconds, CONFIG.backlog_arr_global_command_interval_seconds)
    return CONFIG.arr_global_command_interval_seconds


def qbit_recovery_limits(suspect: dict[str, Any]) -> tuple[int, int]:
    if str(suspect.get("brokenReason") or "") == "stalled-no-progress":
        return (
            CONFIG.max_qbit_stall_recovery_attempts_per_hash,
            CONFIG.min_qbit_stall_recovery_interval_seconds,
        )
    return (
        CONFIG.max_qbit_recovery_attempts_per_hash,
        CONFIG.min_qbit_recovery_interval_seconds,
    )


def build_orphan_report(
    torrents: list[dict[str, Any]],
    arr_events: dict[str, dict[str, Any]],
    arr_collector: ArrHistoryCollector,
    stall_metadata: dict[str, dict[str, Any]] | None = None,
    arr_queue: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "graceHours": CONFIG.import_grace_hours,
        "suspects": [],
        "brokenSuspects": [],
        "retroRepairCandidates": [],
        "backlogCandidates": [],
        "arrLogSignals": {},
    }

    grace_cutoff = now_ts() - (CONFIG.import_grace_hours * 3600)
    broken_cutoff = now_ts() - (CONFIG.broken_download_grace_hours * 3600)
    stall_metadata = stall_metadata or {}
    queue_download_index = build_arr_queue_download_index(arr_queue or {})

    for torrent in torrents:
        download_id = str(torrent.get("hash") or "").lower()
        app_name = infer_app_name(torrent)
        event_bundle = arr_events.get(download_id, {})
        app_event = event_bundle.get("apps", {}).get(app_name, {}) if app_name else {}
        imported = app_event.get("latestImported")
        grabbed = app_event.get("latestGrabbed")
        stall_meta = stall_metadata.get(download_id, {"stalledSeconds": 0, "longStalled": False})
        missing_files = is_missing_files_state(torrent)
        stalled_recovery = is_stalled_recovery_candidate(torrent, stall_meta)

        if is_incomplete(torrent):
            if (
                app_name
                and not imported
                and (missing_files or stalled_recovery)
            ):
                reference_ts = recovery_reference_ts(torrent)
                qualifies_for_recovery = False
                if missing_files and reference_ts > 0 and reference_ts <= broken_cutoff:
                    qualifies_for_recovery = True
                if stalled_recovery:
                    qualifies_for_recovery = True
                if qualifies_for_recovery:
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
                        "brokenReason": "missing-files" if missing_files else "stalled-no-progress",
                        "stalledSeconds": int(stall_meta.get("stalledSeconds", 0) or 0),
                        "recoveryMode": "replace",
                        "maxRetries": CONFIG.max_arr_search_retries_broken,
                        "recommendedActions": [],
                    }
                    if broken_swarm_should_salvage(torrent):
                        broken_suspect["recoveryMode"] = "salvage"
                        if missing_files:
                            broken_suspect["recommendedActions"].append({"type": "qbit-recheck"})
                        broken_suspect["recommendedActions"].append({"type": "qbit-reannounce"})
                        if stalled_recovery:
                            broken_suspect["recommendedActions"].append({"type": "qbit-soft-reset"})
                    else:
                        broken_suspect["recommendedActions"].append({"type": "qbit-delete", "deleteFiles": False})

                    queue_records = queue_download_index.get(app_name, {}).get(download_id, []) if app_name else []
                    queue_entity_ids = extract_arr_entity_ids(app_name, queue_records) if app_name and queue_records else []
                    if queue_entity_ids:
                        broken_suspect["entityIds"] = queue_entity_ids
                    queue_ids = sorted(
                        {
                            int(record.get("id", 0) or 0)
                            for record in queue_records
                            if int(record.get("id", 0) or 0) > 0
                        }
                    )
                    if queue_ids:
                        broken_suspect["queueIds"] = queue_ids
                        broken_suspect["queueCleanupAction"] = {
                            "type": "arr-queue-delete",
                            "queueIds": queue_ids,
                            "removeFromClient": False,
                            "blocklist": True,
                        }

                    search_action = None
                    if queue_entity_ids:
                        search_action = build_arr_search_action_for_entities(
                            app_name,
                            queue_entity_ids,
                            arr_collector,
                            reason="broken-replace" if broken_suspect["recoveryMode"] == "replace" else "broken-salvage-fallback",
                        )
                    if not search_action and grabbed:
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
    stale_cutoff = now_ts() - (CONFIG.queue_integrity_stale_hours * 3600)
    missing_download_cutoff = now_ts() - (CONFIG.queue_missing_download_stale_hours * 3600)
    qbit_index = {str(torrent.get("hash") or "").lower(): torrent for torrent in torrents}
    entity_index = build_arr_entity_event_index(arr_events)
    queue_download_index = build_arr_queue_download_index(arr_queue)

    def add_candidate(candidate: dict[str, Any]) -> None:
        action = candidate.get("recommendedAction")
        action_key = str(action.get("actionKey") or "") if isinstance(action, dict) else ""
        if not action_key or action_key in seen_action_keys:
            return
        seen_action_keys.add(action_key)
        candidates.append(candidate)

    for app_name, grouped_records in queue_download_index.items():
        for download_id, records in grouped_records.items():
            entity_ids = [
                entity_id
                for entity_id in extract_arr_entity_ids(app_name, records)
                if not any(
                    entity_index.get(app_name, {}).get(entity_id, {}).get("latestImported")
                    or queue_entry_has_file(app_name, record)
                    for record in records
                    if extract_arr_entity_id(app_name, record) == entity_id
                )
            ]
            if not entity_ids:
                continue

            representative = min(
                records,
                key=lambda record: first_parseable_ts(record.get("added")) or now_ts(),
            )
            tracked_statuses = {str(record.get("trackedDownloadStatus") or "").lower() for record in records}
            tracked_states = {str(record.get("trackedDownloadState") or "").lower() for record in records}
            statuses = {str(record.get("status") or "").lower() for record in records}
            messages = sorted({message for record in records for message in flatten_status_messages(record)})
            reference_ts = min(
                [timestamp for timestamp in (first_parseable_ts(record.get("added")) for record in records) if timestamp > 0] or [0]
            )
            qbit_torrent = qbit_index.get(download_id)
            if (
                "ok" in tracked_statuses
                and len(tracked_statuses) == 1
                and not messages
                and not ("downloading" in tracked_states and not qbit_torrent)
            ):
                continue
            if qbit_torrent and (is_missing_files_state(qbit_torrent) or is_stalled_recovery_candidate(qbit_torrent, {"probeStalled": True})):
                continue

            reason = "queue-warning"
            priority = 10
            if {"importblocked", "importpending"} & tracked_states:
                reason = "queue-import-warning"
                priority = 8
            elif "downloading" in tracked_states and not qbit_torrent:
                reason = "queue-download-missing"
                priority = 9

            cutoff = missing_download_cutoff if reason == "queue-download-missing" else stale_cutoff
            if reference_ts and reference_ts > cutoff:
                continue

            action = build_arr_search_action_for_entities(
                app_name,
                entity_ids,
                arr_collector,
                reason=reason,
            )
            if not action:
                continue

            candidate = {
                "app": app_name,
                "entityId": entity_ids[0],
                "entityIds": entity_ids,
                "queueIds": sorted({int(record.get("id", 0) or 0) for record in records if int(record.get("id", 0) or 0) > 0}),
                "title": representative.get("title") or representative.get("sourceTitle"),
                "lane": "retro-queue-warning",
                "reason": reason,
                "priority": priority,
                "maxRetries": CONFIG.max_arr_search_retries_queue_warning,
                "referenceTs": reference_ts,
                "trackedDownloadStatus": representative.get("trackedDownloadStatus"),
                "trackedDownloadState": representative.get("trackedDownloadState"),
                "downloadId": download_id,
                "statusMessages": messages,
                "recommendedAction": action,
            }
            if candidate["queueIds"] and reason in {"queue-import-warning", "queue-download-missing"}:
                candidate["queueCleanupAction"] = {
                    "type": "arr-queue-delete",
                    "queueIds": candidate["queueIds"],
                    "removeFromClient": False,
                    "blocklist": True,
                }
            if qbit_torrent and (not is_incomplete(qbit_torrent) or is_missing_files_state(qbit_torrent)):
                candidate["cleanupAction"] = {"type": "qbit-delete", "deleteFiles": False}
            add_candidate(candidate)

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
    history_groups: dict[tuple[str, str, str], dict[str, Any]] = {}

    for app_name, entities in entity_index.items():
        queued_entities = set(queue_index.get(app_name, {}))
        for entity_id, entity_data in entities.items():
            imported = entity_data.get("latestImported")
            grabbed = entity_data.get("latestGrabbed")
            failed = entity_data.get("latestFailed")
            if imported or (not grabbed and not failed):
                continue

            failed_newer_than_grabbed = bool(
                failed
                and (
                    not grabbed
                    or first_parseable_ts(failed.get("date")) >= first_parseable_ts(grabbed.get("date"))
                )
            )
            active_record = failed if failed_newer_than_grabbed else grabbed
            if active_record is None:
                continue
            reference_ts = first_parseable_ts(active_record.get("date"))
            if reference_ts <= 0 or reference_ts > stale_cutoff:
                continue
            if entity_id in queued_entities:
                continue

            download_id = str(active_record.get("downloadId") or "").lower()
            if download_id and download_id in qbit_hashes:
                continue

            reason = "history-failed-no-import" if failed_newer_than_grabbed else "history-grabbed-no-import"
            group_key = (app_name, download_id or f"entity:{entity_id}", reason)
            group = history_groups.setdefault(
                group_key,
                {
                    "app": app_name,
                    "entityIds": [],
                    "title": active_record.get("sourceTitle"),
                    "lane": "backlog-history",
                    "reason": reason,
                    "priority": 20 if failed_newer_than_grabbed else 25,
                    "maxRetries": CONFIG.max_arr_search_retries_history,
                    "referenceTs": reference_ts,
                    "downloadId": download_id,
                    "grabbedEvent": {
                        "eventType": active_record.get("eventType"),
                        "date": active_record.get("date"),
                    },
                },
            )
            group["entityIds"].append(entity_id)
            group["referenceTs"] = min(int(group.get("referenceTs", reference_ts) or reference_ts), reference_ts)

    for group in history_groups.values():
        entity_ids = sorted({int(entity_id) for entity_id in group.get("entityIds", []) if int(entity_id) > 0})
        if not entity_ids:
            continue
        action = build_arr_search_action_for_entities(
            str(group.get("app") or ""),
            entity_ids,
            arr_collector,
            reason=str(group.get("reason") or "history-grabbed-no-import"),
        )
        if not action:
            continue

        action_key = str(action.get("actionKey") or "")
        if action_key in seen_action_keys:
            continue
        seen_action_keys.add(action_key)

        candidates.append(
            {
                **group,
                "entityId": entity_ids[0],
                "entityIds": entity_ids,
                "recommendedAction": action,
            }
        )

    for app_name, records in arr_wanted.items():
        for record in records:
            entity_id = extract_arr_entity_id(app_name, record)
            if entity_id <= 0 or not bool(record.get("monitored", False)) or wanted_entry_has_file(app_name, record):
                continue
            if app_name == "radarr" and record.get("isAvailable") is False:
                continue

            entity_data = entity_index.get(app_name, {}).get(entity_id, {})
            if entity_data.get("latestImported") or entity_id in queue_index.get(app_name, {}):
                continue

            added_ts = first_parseable_ts(record.get("added"), record.get("airDateUtc"), record.get("releaseDate"))
            reference_ts = wanted_entry_reference_ts(app_name, record)
            if reference_ts <= 0 or reference_ts > stale_cutoff:
                continue
            if added_ts and added_ts < lookback_cutoff:
                continue

            action = build_arr_search_action_for_entity(
                app_name,
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
                    "app": app_name,
                    "entityId": entity_id,
                    "title": record.get("title"),
                    "lane": "backlog-wanted",
                    "reason": "wanted-missing-stale",
                    "priority": 35,
                    "maxRetries": CONFIG.max_arr_search_retries_wanted,
                    "referenceTs": reference_ts,
                    "added": record.get("added") or record.get("airDateUtc") or record.get("releaseDate"),
                    "lastSearchTime": record.get("lastSearchTime"),
                    "recommendedAction": action,
                }
            )

    candidates.sort(key=lambda item: (int(item.get("priority", 99)), int(item.get("referenceTs", 0) or 0)))
    return candidates


def maybe_apply_arr_recovery(
    store: StateStore,
    arr_collector: ArrHistoryCollector,
    client: QBClient,
    report: dict[str, Any],
    free_bytes: int | None = None,
) -> dict[str, Any]:
    dispatch = {"triggered": [], "skipped": []}
    report["arrActions"] = dispatch

    if CONFIG.observe_only or not CONFIG.allow_arr_commands:
        return dispatch

    history = store.runtime.setdefault("arr_command_history", {})
    queue_cleanup_history = store.runtime.setdefault("arr_queue_cleanup_history", {})
    action_budget = arr_recovery_budget(report, free_bytes)
    triggered = 0
    now = now_ts()
    candidates: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    qbit_recovery_history = store.runtime.get("qbit_recovery_history", {})
    effective_global_interval = arr_recovery_global_interval_seconds(report, free_bytes)
    dispatch["policy"] = {
        "actionBudget": action_budget,
        "globalIntervalSeconds": effective_global_interval,
        "freeGb": round(gb_from_bytes(free_bytes), 2) if free_bytes is not None else None,
    }

    for suspect in report.get("brokenSuspects", []):
        if not CONFIG.allow_broken_download_recovery:
            continue
        qbit_retry_limit, _ = qbit_recovery_limits(suspect)
        if (
            CONFIG.allow_qbit_recovery_actions
            and suspect.get("recoveryMode") == "salvage"
            and normalize_action_history_entry(qbit_recovery_history.get(str(suspect.get("hash") or ""))).get("triggerCount", 0)
            < qbit_retry_limit
        ):
            continue
        for action in suspect.get("recommendedActions", []):
            if action.get("type") == "arr-search-command":
                candidate = dict(suspect)
                candidate["cleanupAction"] = next(
                    (item for item in suspect.get("recommendedActions", []) if item.get("type") == "qbit-delete"),
                    None,
                )
                candidate["queueCleanupAction"] = candidate.get("queueCleanupAction")
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
    global_remaining = max(0, effective_global_interval - (now - global_last_triggered))
    if candidates and global_last_triggered and global_remaining > 0:
        dispatch["globalCooldownRemainingSeconds"] = global_remaining
        dispatch["skipped"].append({"reason": "global-cooldown", "remainingSeconds": global_remaining})

    seen_action_keys: set[str] = set()
    for _, candidate, action in candidates:
        action_key = str(action.get("actionKey") or "")
        if not action_key or action_key in seen_action_keys:
            continue
        seen_action_keys.add(action_key)

        if triggered >= action_budget:
            dispatch["skipped"].append({"actionKey": action_key, "reason": "budget-exhausted"})
            continue

        queue_cleanup_performed = False
        queue_cleanup_key = ""
        retry_reset_seconds = arr_candidate_retry_reset_seconds(candidate)
        action_interval_seconds = arr_candidate_interval_seconds(candidate)
        history_entry = reset_history_entry_if_stale(
            normalize_action_history_entry(history.get(action_key)),
            retry_reset_seconds,
            now,
        )
        retry_limit = int(candidate.get("maxRetries", retry_limit_for_reason(str(candidate.get("reason") or ""))) or 0)
        if retry_limit > 0 and history_entry["triggerCount"] >= retry_limit:
            if queue_cleanup_performed:
                triggered += 1
                dispatch["triggered"].append(
                    {
                        "actionKey": queue_cleanup_key or action_key,
                        "app": candidate.get("app"),
                        "lane": candidate.get("lane"),
                        "title": candidate.get("title"),
                        "reason": f"{candidate.get('reason')}:queue-cleanup",
                        "queueCleanupTriggered": candidate.get("queueCleanupTriggered"),
                    }
                )
            dispatch["skipped"].append(
                {
                    "actionKey": action_key,
                    "reason": "retry-limit",
                    "triggerCount": history_entry["triggerCount"],
                    "maxRetries": retry_limit,
                }
            )
            continue

        queue_cleanup_action = candidate.get("queueCleanupAction")
        if isinstance(queue_cleanup_action, dict):
            queue_cleanup_key = stable_signature(
                {
                    "app": candidate.get("app"),
                    "queueIds": [int(queue_id) for queue_id in queue_cleanup_action.get("queueIds", [])],
                    "blocklist": bool(queue_cleanup_action.get("blocklist", True)),
                    "removeFromClient": bool(queue_cleanup_action.get("removeFromClient", False)),
                }
            )
            cleanup_history_entry = reset_history_entry_if_stale(
                normalize_action_history_entry(queue_cleanup_history.get(queue_cleanup_key)),
                CONFIG.arr_queue_cleanup_retry_reset_seconds,
                now,
            )
            cleanup_retry_limit = 1
            cleanup_last_triggered = cleanup_history_entry["lastTriggeredAt"]
            if cleanup_retry_limit > 0 and cleanup_history_entry["triggerCount"] >= cleanup_retry_limit:
                dispatch["skipped"].append({"actionKey": queue_cleanup_key, "reason": "queue-cleanup-retry-limit"})
            elif cleanup_last_triggered and now - cleanup_last_triggered < action_interval_seconds:
                dispatch["skipped"].append(
                    {
                        "actionKey": queue_cleanup_key,
                        "reason": "queue-cleanup-cooldown",
                        "remainingSeconds": action_interval_seconds - (now - cleanup_last_triggered),
                    }
                )
            else:
                try:
                    queue_cleanup_result = arr_collector.clear_queue_items(
                        str(candidate.get("app") or ""),
                        [int(queue_id) for queue_id in queue_cleanup_action.get("queueIds", [])],
                        remove_from_client=bool(queue_cleanup_action.get("removeFromClient", False)),
                        blocklist=bool(queue_cleanup_action.get("blocklist", True)),
                    )
                    if queue_cleanup_result:
                        candidate["queueCleanupTriggered"] = queue_cleanup_result
                        queue_cleanup_history[queue_cleanup_key] = {
                            "lastTriggeredAt": now,
                            "triggerCount": cleanup_history_entry["triggerCount"] + 1,
                        }
                        queue_cleanup_performed = True
                except Exception as exc:
                    dispatch["skipped"].append({"actionKey": queue_cleanup_key, "reason": "queue-cleanup-error", "error": str(exc)})

        if global_remaining > 0:
            if queue_cleanup_performed:
                triggered += 1
                dispatch["triggered"].append(
                    {
                        "actionKey": queue_cleanup_key or action_key,
                        "app": candidate.get("app"),
                        "lane": candidate.get("lane"),
                        "title": candidate.get("title"),
                        "reason": f"{candidate.get('reason')}:queue-cleanup",
                        "queueCleanupTriggered": candidate.get("queueCleanupTriggered"),
                    }
                )
            continue

        last_triggered = history_entry["lastTriggeredAt"]
        if last_triggered and now - last_triggered < action_interval_seconds:
            if queue_cleanup_performed:
                triggered += 1
                dispatch["triggered"].append(
                    {
                        "actionKey": queue_cleanup_key or action_key,
                        "app": candidate.get("app"),
                        "lane": candidate.get("lane"),
                        "title": candidate.get("title"),
                        "reason": f"{candidate.get('reason')}:queue-cleanup",
                        "queueCleanupTriggered": candidate.get("queueCleanupTriggered"),
                    }
                )
            dispatch["skipped"].append(
                {
                    "actionKey": action_key,
                    "reason": "cooldown",
                    "remainingSeconds": action_interval_seconds - (now - last_triggered),
                }
            )
            continue

        try:
            cleanup_action = candidate.get("cleanupAction")
            if isinstance(cleanup_action, dict) and str(candidate.get("hash") or ""):
                client.delete(
                    [str(candidate.get("hash") or "")],
                    bool(cleanup_action.get("deleteFiles", False)),
                )
                candidate["cleanupTriggered"] = {
                    "type": cleanup_action.get("type"),
                    "deleteFiles": bool(cleanup_action.get("deleteFiles", False)),
                }
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
                        "queueCleanupTriggered": candidate.get("queueCleanupTriggered"),
                        "cleanupTriggered": candidate.get("cleanupTriggered"),
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
        retry_limit, cooldown_seconds = qbit_recovery_limits(suspect)
        if history_entry["triggerCount"] >= retry_limit:
            dispatch["skipped"].append(
                {
                    "hash": torrent_hash,
                    "reason": "retry-limit",
                    "triggerCount": history_entry["triggerCount"],
                    "maxRetries": retry_limit,
                }
            )
            continue

        last_triggered = history_entry["lastTriggeredAt"]
        if last_triggered and now - last_triggered < cooldown_seconds:
            dispatch["skipped"].append(
                {
                    "hash": torrent_hash,
                    "reason": "cooldown",
                    "remainingSeconds": cooldown_seconds - (now - last_triggered),
                }
            )
            continue

        try:
            action_types = {
                str(action.get("type") or "")
                for action in suspect.get("recommendedActions", [])
                if isinstance(action, dict)
            }
            applied = {"recheck": False, "reannounce": False, "softReset": False}
            if "qbit-recheck" in action_types:
                client.recheck([torrent_hash])
                applied["recheck"] = True
            if "qbit-reannounce" in action_types:
                client.reannounce([torrent_hash])
                applied["reannounce"] = True
            if "qbit-soft-reset" in action_types:
                client.stop([torrent_hash])
                client.start([torrent_hash])
                applied["softReset"] = True
            if not any(applied.values()):
                dispatch["skipped"].append({"hash": torrent_hash, "reason": "no-actions"})
                continue
            history[torrent_hash] = {
                "lastTriggeredAt": now,
                "triggerCount": history_entry["triggerCount"] + 1,
            }
            suspect["qbitRecoveryTriggered"] = applied
            triggered += 1
            dispatch["triggered"].append(
                {
                    "hash": torrent_hash,
                    "title": suspect.get("name"),
                    "recoveryMode": suspect.get("recoveryMode"),
                    "applied": applied,
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
    rotation_urgent: bool = False,
    no_active_downloads: bool = False,
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
    effective_torrent_action_interval = (
        min(CONFIG.min_torrent_action_interval_seconds, CONFIG.min_rotation_action_interval_seconds)
        if rotation_urgent
        else CONFIG.min_torrent_action_interval_seconds
    )
    torrent_action_cooldown_remaining = max(
        0,
        effective_torrent_action_interval - (now - last_torrent_action_at),
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
        and (no_active_downloads or selection_stable_cycles >= CONFIG.control_stability_cycles)
        and torrent_action_cooldown_remaining <= 0
    )

    return {
        "modeStableCycles": mode_stable_cycles,
        "selectionStableCycles": selection_stable_cycles,
        "prefStableCycles": pref_stable_cycles,
        "prefWritesReady": pref_writes_ready,
        "torrentControlReady": torrent_control_ready,
        "rotationUrgent": rotation_urgent,
        "prefWriteCooldownRemainingSeconds": pref_write_cooldown_remaining,
        "torrentActionCooldownRemainingSeconds": torrent_action_cooldown_remaining,
        "effectiveTorrentActionIntervalSeconds": effective_torrent_action_interval,
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
        if str(torrent.get("state") or "") in {"pausedDL", "stoppedDL", "queuedDL", "metaDL", "checkingDL"}
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


def maybe_apply_torrent_control(
    store: StateStore,
    client: QBClient,
    candidates: list[dict[str, Any]],
    stall_metadata: dict[str, dict[str, Any]],
    to_stop: list[str],
    to_start: list[str],
    control_ready: bool,
) -> bool:
    if CONFIG.observe_only or not CONFIG.allow_torrent_control or not control_ready:
        return False
    candidate_by_hash = {torrent["hash"]: torrent for torrent in candidates}
    probe_quarantine_hashes = [
        torrent_hash
        for torrent_hash in to_stop
        if torrent_hash in candidate_by_hash
        and should_quarantine_probe_on_stop(
            candidate_by_hash[torrent_hash],
            stall_metadata.get(
                torrent_hash,
                {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
            ),
        )
    ]
    if to_stop:
        client.stop(to_stop)
        note_probe_quarantine(store, probe_quarantine_hashes)
    if to_start:
        clear_probe_quarantine(store, to_start)
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

    manageable_torrents = [torrent for torrent in torrents if is_manageable(torrent)]
    stall_metadata = {torrent["hash"]: update_stall_state(store, torrent) for torrent in manageable_torrents}
    ignored_dead_noise = [
        torrent
        for torrent in manageable_torrents
        if is_cold_dead_backlog_candidate(
            torrent,
            stall_metadata.get(
                torrent["hash"],
                {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
            ),
        )
    ]
    ignored_dead_hashes = {torrent["hash"] for torrent in ignored_dead_noise}
    candidates = [torrent for torrent in manageable_torrents if torrent["hash"] not in ignored_dead_hashes]
    candidate_by_hash = {torrent["hash"]: torrent for torrent in candidates}
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
    allowed = choose_allowed(store, candidates, mode, free_bytes, stall_metadata, desired_active_downloads) if action_guard_ok else []
    allowed_hashes = {torrent["hash"] for torrent in allowed}
    to_stop, to_start = (
        plan_torrent_actions(candidates, allowed_hashes, mode, stall_metadata, desired_active_downloads)
        if action_guard_ok
        else ([], [])
    )
    rotation_urgent = workload_metrics.get("movingCount", 0) <= 0 and (
        bool(to_start)
        or any(
            torrent_hash in candidate_by_hash
            and is_probe_rotation_candidate(
                candidate_by_hash[torrent_hash],
                stall_metadata.get(
                    torrent_hash,
                    {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
                ),
            )
            for torrent_hash in to_stop
        )
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
    stability_meta = update_stability_guard(
        store,
        mode,
        to_stop,
        to_start,
        pref_updates,
        rotation_urgent,
        workload_metrics.get("movingCount", 0) <= 0,
    )
    start_hashes = set(to_start)
    stop_hashes = set(to_stop)
    if action_guard_ok:
        if maybe_apply_qbit_pref_writes(qbit, pref_updates, stability_meta["prefWritesReady"]):
            note_pref_write(store)
        if maybe_apply_torrent_control(
            store,
            qbit,
            candidates,
            stall_metadata,
            to_stop,
            to_start,
            stability_meta["torrentControlReady"],
        ):
            note_torrent_action(store)

    arr_collector = ArrHistoryCollector()
    arr_status = arr_collector.status()
    arr_history_hours = max(CONFIG.arr_history_lookback_hours, CONFIG.retro_repair_lookback_hours)
    arr_events = arr_collector.recent_events(arr_history_hours)
    arr_queue = arr_collector.queue_records()
    arr_wanted = arr_collector.wanted_missing_records(("radarr", "sonarr", "lidarr"))
    arr_log_signals = arr_collector.recent_log_signals()
    orphan_report = build_orphan_report(torrents, arr_events, arr_collector, stall_metadata, arr_queue=arr_queue)
    orphan_report["arrLogSignals"] = arr_log_signals
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
    maybe_apply_arr_recovery(store, arr_collector, qbit, orphan_report, free_bytes)
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
            "ignoredColdDeadCount": len(ignored_dead_noise),
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
        "probeRotation": {
            "quarantineCount": len(prune_probe_quarantine(store)),
            "rotationSeconds": CONFIG.probe_rotation_seconds,
            "quarantineSeconds": CONFIG.probe_quarantine_seconds,
        },
        "candidateNoise": {
            "ignoredColdDeadCount": len(ignored_dead_noise),
            "graceSeconds": CONFIG.cold_dead_backlog_grace_seconds,
            "examples": [
                summarize_torrent(
                    torrent,
                    stall_metadata.get(
                        torrent["hash"],
                        {"stalledSeconds": 0, "probeStalled": False, "longStalled": False},
                    ),
                )
                for torrent in ignored_dead_noise[:10]
            ],
        },
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
        "arrLogAudit": {
            app: {
                "filesScanned": int(summary.get("filesScanned", 0) or 0),
                "signalCounts": summary.get("signalCounts", {}),
            }
            for app, summary in arr_log_signals.items()
        },
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
            "arrLogSignalCount": sum(
                sum(int(value or 0) for value in (summary.get("signalCounts") or {}).values())
                for summary in arr_log_signals.values()
            ),
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
        finally:
            # Keep the container healthy as long as the worker loop itself is alive,
            # even if an individual cycle hits a transient qB/Arr timeout.
            store.heartbeat()

        if CONFIG.run_once:
            return 0

        time.sleep(CONFIG.check_interval)


if __name__ == "__main__":
    sys.exit(main())
