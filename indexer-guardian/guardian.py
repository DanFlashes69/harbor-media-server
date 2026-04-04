import copy
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Config:
    prowlarr_url: str = os.environ.get("PROWLARR_URL", "http://prowlarr:9696")
    radarr_url: str = os.environ.get("RADARR_URL", "http://radarr:7878")
    sonarr_url: str = os.environ.get("SONARR_URL", "http://sonarr:8989")
    lidarr_url: str = os.environ.get("LIDARR_URL", "http://lidarr:8686")
    state_dir: str = os.environ.get("STATE_DIR", "/state")
    check_interval_seconds: int = env_int("CHECK_INTERVAL_SECONDS", 900)
    run_once: bool = env_bool("RUN_ONCE", False)
    replacement_failure_threshold: int = env_int("REPLACEMENT_FAILURE_THRESHOLD", 3)
    validation_timeout_seconds: int = env_int("VALIDATION_TIMEOUT_SECONDS", 30)
    replacement_cooldown_seconds: int = env_int("REPLACEMENT_COOLDOWN_SECONDS", 21600)
    replacement_history_ttl_seconds: int = env_int("REPLACEMENT_HISTORY_TTL_SECONDS", 604800)
    app_sync_cooldown_seconds: int = env_int("APP_SYNC_COOLDOWN_SECONDS", 3600)
    log_signal_lookback_hours: int = env_int("LOG_SIGNAL_LOOKBACK_HOURS", 24)
    log_signal_line_limit: int = env_int("LOG_SIGNAL_LINE_LIMIT", 4000)
    log_failure_threshold: int = env_int("LOG_FAILURE_THRESHOLD", 5)
    soft_log_failure_threshold: int = env_int("SOFT_LOG_FAILURE_THRESHOLD", 8)
    managed_tag_label: str = os.environ.get("MANAGED_INDEXER_TAG_LABEL", "harbor-managed-indexer")


CONFIG = Config()
STATE_DIR = Path(CONFIG.state_dir)
HEARTBEAT_PATH = STATE_DIR / "heartbeat"
SNAPSHOT_PATH = STATE_DIR / "snapshot.json"
RUNTIME_STATE_PATH = STATE_DIR / "runtime-state.json"

PROWLARR_CONFIG_XML = "/arr/prowlarr/config.xml"
RADARR_CONFIG_XML = "/arr/radarr/config.xml"
SONARR_CONFIG_XML = "/arr/sonarr/config.xml"
LIDARR_CONFIG_XML = "/arr/lidarr/config.xml"

PROWLARR_LOG_DIR = "/arr/prowlarr/logs"
RADARR_LOG_DIR = "/arr/radarr/logs"
SONARR_LOG_DIR = "/arr/sonarr/logs"
LIDARR_LOG_DIR = "/arr/lidarr/logs"

HARD_LOG_FAILURE_PATTERNS = (
    "invalid torrent file contents",
    "memory stream is not expandable",
    "no categories provided",
    "invalid category for value",
)

SOFT_LOG_FAILURE_PATTERNS = (
    "too many requests",
    "rate limit",
    "http request failed",
)

GENERIC_FIELD_COPY_PREFIXES = (
    "baseSettings.",
    "torrentBaseSettings.",
)

GENERIC_FIELD_COPY_NAMES = {
    "apiurl",
    "sort",
    "downloadlink",
    "downloadlink2",
    "prefer_magnet_links",
    "animeStandardFormatSearch",
}

SLOT_DEFINITIONS: dict[str, dict[str, Any]] = {
    "general_primary": {
        "seedDefinition": "1337x",
        "priority": 10,
        "appProfileId": 1,
        "replacementPool": ["1337x", "torrentproject2", "torrentdownload", "0magnet", "magnetdownload", "rutor"],
        "testQuery": {"q": "matrix", "cat": "2000"},
    },
    "tv_primary": {
        "seedDefinition": "eztv",
        "priority": 15,
        "appProfileId": 1,
        "replacementPool": ["eztv", "torrentdownloads", "1337x", "bitsearch", "kickasstorrents-ws"],
        "testQuery": {"q": "office", "cat": "5000"},
    },
    "anime_primary": {
        "seedDefinition": "nyaasi",
        "priority": 25,
        "appProfileId": 1,
        "replacementPool": ["nyaasi", "1337x", "bitsearch", "torrentdownloads"],
        "testQuery": {"q": "one piece", "cat": "5070"},
    },
    "general_secondary": {
        "seedDefinition": "bitsearch",
        "priority": 20,
        "appProfileId": 1,
        "replacementPool": ["bitsearch", "torrentproject2", "0magnet", "magnetdownload", "rutor", "torrentdownload", "limetorrents"],
        "testQuery": {"q": "matrix", "cat": "2000"},
    },
    "movies_primary": {
        "seedDefinition": "yts",
        "priority": 40,
        "appProfileId": 1,
        "replacementPool": ["yts", "torrentdownload", "torrentproject2", "0magnet", "magnetdownload", "thepiratebay"],
        "testQuery": {"q": "matrix", "cat": "2000"},
    },
    "general_tertiary": {
        "seedDefinition": "torrentproject2",
        "priority": 35,
        "appProfileId": 1,
        "replacementPool": ["torrentproject2", "bitsearch", "0magnet", "magnetdownload", "rutor", "torrentdownload", "thepiratebay"],
        "testQuery": {"q": "matrix", "cat": "2000"},
    },
}

CURATED_FIELD_DEFAULTS: dict[str, dict[str, Any]] = {
    "1337x": {
        "torrentBaseSettings.appMinimumSeeders": 5,
        "downloadlink": 0,
        "downloadlink2": 1,
        "sort": 2,
        "type": 1,
    },
    "eztv": {
        "torrentBaseSettings.appMinimumSeeders": 5,
    },
    "limetorrents": {
        "torrentBaseSettings.appMinimumSeeders": 5,
        "downloadlink": 1,
        "downloadlink2": 0,
        "sort": 0,
    },
    "nyaasi": {
        "torrentBaseSettings.appMinimumSeeders": 5,
        "prefer_magnet_links": True,
    },
    "thepiratebay": {
        "torrentBaseSettings.appMinimumSeeders": 5,
        "apiurl": "apibay.org",
    },
    "yts": {
        "apiurl": "movies-api.accel.li",
    },
    "bitsearch": {
        "torrentBaseSettings.appMinimumSeeders": 5,
    },
    "torrentdownloads": {
        "torrentBaseSettings.appMinimumSeeders": 5,
    },
    "torrentdownload": {
        "torrentBaseSettings.appMinimumSeeders": 5,
    },
    "kickasstorrents-ws": {
        "torrentBaseSettings.appMinimumSeeders": 5,
    },
    "torrentproject2": {
        "torrentBaseSettings.appMinimumSeeders": 5,
    },
    "0magnet": {
        "torrentBaseSettings.appMinimumSeeders": 5,
    },
    "magnetdownload": {
        "torrentBaseSettings.appMinimumSeeders": 5,
    },
    "rutor": {
        "torrentBaseSettings.appMinimumSeeders": 5,
    },
}


def log(message: str) -> None:
    print(f"[indexer-guardian] {message}", flush=True)


def now_ts() -> int:
    return int(time.time())


def read_api_key(path: str) -> str:
    tree = ET.parse(path)
    root = tree.getroot()
    api_key = root.findtext("ApiKey", default="")
    if not api_key:
        raise RuntimeError(f"API key not found in {path}")
    return api_key


class StateStore:
    def __init__(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.runtime = self._load_json(
            RUNTIME_STATE_PATH,
            {
                "slotState": {},
                "failureState": {},
                "replacementHistory": [],
                "lastReplacementAt": 0,
            },
        )

    @staticmethod
    def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return copy.deepcopy(default)

    def write_runtime(self) -> None:
        RUNTIME_STATE_PATH.write_text(json.dumps(self.runtime, indent=2, sort_keys=True), encoding="utf-8")

    def write_snapshot(self, payload: dict[str, Any]) -> None:
        SNAPSHOT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        HEARTBEAT_PATH.write_text(str(now_ts()), encoding="utf-8")


class JsonApiClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> Any:
        data = None
        headers = {"X-Api-Key": self.api_key}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            if not body.strip():
                return None
            return json.loads(body)

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("POST", path, payload=payload)

    def put(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("PUT", path, payload=payload)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)


def arr_health(client: JsonApiClient, path: str) -> list[dict[str, Any]]:
    result = client.get(path)
    return result if isinstance(result, list) else []


def parse_warning_indexers(messages: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for item in messages:
        if item.get("source") not in {"IndexerLongTermStatusCheck", "IndexerStatusCheck"}:
            continue
        message = str(item.get("message") or "")
        markers = (
            "Indexers unavailable due to failures for more than 6 hours:",
            "Indexers unavailable due to failures:",
        )
        marker = next((candidate for candidate in markers if candidate in message), None)
        if not marker:
            continue
        suffix = message.split(marker, 1)[1]
        for raw_name in suffix.split(","):
            cleaned = raw_name.strip()
            if cleaned.endswith("(Prowlarr)"):
                cleaned = cleaned[: -len("(Prowlarr)")].strip()
            if cleaned:
                names.add(cleaned)
    return names


def indexer_field_map(indexer: dict[str, Any]) -> dict[str, Any]:
    values = {}
    for field in indexer.get("fields", []):
        if "name" in field and "value" in field:
            values[field["name"]] = field["value"]
    return values


def ensure_managed_tag(prowlarr: JsonApiClient) -> int | None:
    tags = prowlarr.get("/api/v1/tag")
    for tag in tags:
        if tag.get("label") == CONFIG.managed_tag_label:
            return int(tag["id"])
    created = prowlarr.post("/api/v1/tag", {"label": CONFIG.managed_tag_label})
    return int(created["id"]) if created and "id" in created else None


def seed_slot_state(
    store: StateStore,
    indexers: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    slot_state = store.runtime.get("slotState", {})
    by_definition = {item.get("definitionName"): item for item in indexers}
    used_ids = {slot.get("id") for slot in slot_state.values() if slot.get("id")}

    for slot_name, slot_meta in SLOT_DEFINITIONS.items():
        current = slot_state.get(slot_name)
        if current and any(item.get("id") == current.get("id") for item in indexers):
            continue

        chosen = by_definition.get(slot_meta["seedDefinition"])
        if not chosen:
            pool = slot_meta["replacementPool"]
            chosen = next(
                (
                    item
                    for item in indexers
                    if item.get("definitionName") in pool and item.get("id") not in used_ids
                ),
                None,
            )
        if chosen:
            slot_state[slot_name] = {
                "id": chosen.get("id"),
                "definitionName": chosen.get("definitionName"),
                "name": chosen.get("name"),
                "priority": chosen.get("priority", slot_meta["priority"]),
                "appProfileId": chosen.get("appProfileId", slot_meta["appProfileId"]),
                "tags": list(chosen.get("tags", [])),
                "seedDefinition": slot_meta["seedDefinition"],
            }
            used_ids.add(chosen.get("id"))
        else:
            slot_state.setdefault(
                slot_name,
                {
                    "id": None,
                    "definitionName": slot_meta["seedDefinition"],
                    "name": slot_meta["seedDefinition"],
                    "priority": slot_meta["priority"],
                    "appProfileId": slot_meta["appProfileId"],
                    "tags": [],
                    "seedDefinition": slot_meta["seedDefinition"],
                },
            )

    store.runtime["slotState"] = slot_state
    return slot_state


def candidate_blacklisted(store: StateStore, slot_name: str, definition_name: str) -> bool:
    cutoff = now_ts() - CONFIG.replacement_history_ttl_seconds
    history = store.runtime.get("replacementHistory", [])
    filtered = [item for item in history if int(item.get("ts", 0)) >= cutoff]
    store.runtime["replacementHistory"] = filtered
    return any(
        item.get("slot") == slot_name and item.get("definitionName") == definition_name
        for item in filtered
    )


def note_replacement_history(store: StateStore, slot_name: str, definition_name: str, reason: str) -> None:
    history = store.runtime.setdefault("replacementHistory", [])
    current_ts = now_ts()
    history.append(
            {
                "slot": slot_name,
                "definitionName": definition_name,
                "reason": reason,
                "ts": current_ts,
        }
    )
    store.runtime["lastReplacementAt"] = current_ts
    slot_state = store.runtime.setdefault("lastReplacementAtBySlot", {})
    slot_state[slot_name] = current_ts


def normalize_tag_list(tags: list[int], managed_tag_id: int | None) -> list[int]:
    combined = list(tags)
    if managed_tag_id and managed_tag_id not in combined:
        combined.append(managed_tag_id)
    return sorted({int(tag) for tag in combined})


def app_sync_cooldown_remaining(store: StateStore, app_name: str) -> int:
    sync_state = store.runtime.setdefault("lastApplicationSyncAt", {})
    last_sync = int(sync_state.get(app_name.lower(), 0) or 0)
    if last_sync <= 0:
        return 0
    remaining = CONFIG.app_sync_cooldown_seconds - (now_ts() - last_sync)
    return max(0, remaining)


def note_app_sync(store: StateStore, app_name: str) -> None:
    sync_state = store.runtime.setdefault("lastApplicationSyncAt", {})
    sync_state[app_name.lower()] = now_ts()


def choose_candidate_definition(
    slot_name: str,
    active_definitions: set[str],
    store: StateStore,
) -> str | None:
    for definition in candidate_definition_sequence(slot_name, active_definitions, store):
        return definition
    return None


def candidate_definition_sequence(
    slot_name: str,
    active_definitions: set[str],
    store: StateStore,
) -> list[str]:
    pool = SLOT_DEFINITIONS[slot_name]["replacementPool"]
    ordered: list[str] = []
    for definition in pool:
        if definition in active_definitions:
            continue
        if candidate_blacklisted(store, slot_name, definition):
            continue
        ordered.append(definition)
    return ordered


def should_copy_field(field_name: str) -> bool:
    if field_name in GENERIC_FIELD_COPY_NAMES:
        return True
    return any(field_name.startswith(prefix) for prefix in GENERIC_FIELD_COPY_PREFIXES)


def build_replacement_payload(
    slot_name: str,
    current_indexer: dict[str, Any] | None,
    template: dict[str, Any],
    managed_tag_id: int | None,
) -> dict[str, Any]:
    slot_meta = SLOT_DEFINITIONS[slot_name]
    payload = copy.deepcopy(template)
    payload["enable"] = True
    payload["priority"] = current_indexer.get("priority", slot_meta["priority"]) if current_indexer else slot_meta["priority"]
    payload["appProfileId"] = current_indexer.get("appProfileId", slot_meta["appProfileId"]) if current_indexer else slot_meta["appProfileId"]
    payload["tags"] = normalize_tag_list(list(current_indexer.get("tags", [])) if current_indexer else [], managed_tag_id)
    if current_indexer and "downloadClientId" in current_indexer:
        payload["downloadClientId"] = current_indexer["downloadClientId"]

    current_field_values = indexer_field_map(current_indexer or {})
    curated_defaults = CURATED_FIELD_DEFAULTS.get(template.get("definitionName", ""), {})
    for field in payload.get("fields", []):
        field_name = field.get("name")
        if not field_name:
            continue
        if field_name == "baseUrl":
            template_urls = list(template.get("indexerUrls", []) or [])
            current_base_url = current_field_values.get("baseUrl")
            if current_base_url in template_urls:
                field["value"] = current_base_url
            elif template_urls:
                field["value"] = template_urls[0]
            continue
        if field_name in curated_defaults:
            field["value"] = curated_defaults[field_name]
            continue
        if current_indexer and should_copy_field(field_name) and field_name in current_field_values:
            field["value"] = current_field_values[field_name]

    return payload


def proxy_test(
    prowlarr_api_key: str,
    indexer_id: int,
    query: dict[str, str],
) -> tuple[bool, dict[str, Any]]:
    params = {
        "t": "search",
        "limit": "1",
        "offset": "0",
    }
    params.update(query)
    url = f"{CONFIG.prowlarr_url.rstrip('/')}/{indexer_id}/api?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"X-Api-Key": prowlarr_api_key}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=CONFIG.validation_timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="ignore")
            return True, {
                "status": response.status,
                "snippet": body[:250],
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        return False, {
            "status": exc.code,
            "snippet": body[:250],
        }
    except Exception as exc:  # pragma: no cover - network path
        return False, {
            "status": "ERR",
            "snippet": str(exc),
        }


def application_name_map(prowlarr: JsonApiClient) -> dict[str, dict[str, Any]]:
    applications = prowlarr.get("/api/v1/applications")
    return {str(item.get("name") or "").strip().lower(): item for item in applications if isinstance(item, dict)}


def queue_application_indexer_sync(prowlarr: JsonApiClient, application_id: int) -> None:
    prowlarr.post("/api/v1/command", {"name": "ApplicationIndexerSync", "applicationId": int(application_id)})


def queue_arr_health_check(arr_client: JsonApiClient, health_path: str) -> Any:
    try:
        return arr_client.get(health_path)
    except Exception:
        return None


def field_value(fields: list[dict[str, Any]], name: str) -> Any:
    for field in fields:
        if field.get("name") == name:
            return field.get("value")
    return None


def parse_prowlarr_indexer_id(base_url: str | None) -> int | None:
    if not base_url:
        return None
    parsed = urllib.parse.urlparse(str(base_url))
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return None
    try:
        return int(parts[0])
    except ValueError:
        return None


def current_prowlarr_name_by_id(indexers: list[dict[str, Any]]) -> dict[int, str]:
    return {
        int(item["id"]): str(item.get("name") or "")
        for item in indexers
        if item.get("id") is not None and item.get("name")
    }


def stale_app_indexers(arr_indexers: list[dict[str, Any]], current_indexers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current_names = current_prowlarr_name_by_id(current_indexers)
    stale: list[dict[str, Any]] = []

    for item in arr_indexers:
        name = str(item.get("name") or "")
        if not name.endswith(" (Prowlarr)"):
            continue
        base_url = field_value(item.get("fields", []), "baseUrl")
        if "prowlarr" not in str(base_url or ""):
            continue
        prowlarr_indexer_id = parse_prowlarr_indexer_id(str(base_url))
        if prowlarr_indexer_id is None:
            continue
        expected_name = name[: -len(" (Prowlarr)")].strip()
        current_name = current_names.get(prowlarr_indexer_id)
        if current_name != expected_name:
            stale.append(
                {
                    "id": item.get("id"),
                    "name": name,
                    "baseUrl": base_url,
                    "referencedProwlarrIndexerId": prowlarr_indexer_id,
                    "currentProwlarrName": current_name,
                }
            )

    return stale


def delete_arr_indexer(arr_client: JsonApiClient, api_root: str, indexer_id: int) -> None:
    arr_client.delete(f"{api_root}/{int(indexer_id)}")


def recent_log_files(*directories: str) -> list[Path]:
    cutoff = time.time() - (CONFIG.log_signal_lookback_hours * 3600)
    files: list[Path] = []
    for directory in directories:
        path = Path(directory)
        if not path.exists():
            continue
        for candidate in path.glob("*"):
            if not candidate.is_file():
                continue
            if candidate.suffix.lower() not in {".txt", ".log"} and ".txt" not in candidate.name.lower() and ".log" not in candidate.name.lower():
                continue
            try:
                if candidate.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            files.append(candidate)
    return sorted(files, key=lambda item: item.stat().st_mtime, reverse=True)


def indexer_identifiers(indexer: dict[str, Any]) -> set[str]:
    identifiers: set[str] = set()
    name = str(indexer.get("name") or "").strip()
    definition_name = str(indexer.get("definitionName") or "").strip()
    if name:
        identifiers.add(name.lower())
    if definition_name:
        identifiers.add(definition_name.lower())
        identifiers.add(f"[{definition_name.lower()}]")
    return identifiers


def line_matches_indexer(line_lower: str, indexer: dict[str, Any]) -> bool:
    identifiers = indexer_identifiers(indexer)
    if not identifiers:
        return False
    return any(identifier and identifier in line_lower for identifier in identifiers)


def collect_indexer_log_signals(current_indexers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {
        str(indexer.get("name") or ""): {"count": 0, "hardCount": 0, "softCount": 0, "samples": []}
        for indexer in current_indexers
        if indexer.get("name")
    }
    if not reports:
        return reports

    files = recent_log_files(PROWLARR_LOG_DIR, RADARR_LOG_DIR, SONARR_LOG_DIR, LIDARR_LOG_DIR)
    if not files:
        return reports

    for file_path in files:
        try:
            lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for raw_line in lines[-CONFIG.log_signal_line_limit :]:
            line_lower = raw_line.lower()
            hard_match = any(pattern in line_lower for pattern in HARD_LOG_FAILURE_PATTERNS)
            soft_match = any(pattern in line_lower for pattern in SOFT_LOG_FAILURE_PATTERNS)
            if not hard_match and not soft_match:
                continue
            for indexer in current_indexers:
                name = str(indexer.get("name") or "")
                if not name or not line_matches_indexer(line_lower, indexer):
                    continue
                report = reports.setdefault(name, {"count": 0, "hardCount": 0, "softCount": 0, "samples": []})
                report["count"] += 1
                if hard_match:
                    report["hardCount"] += 1
                if soft_match:
                    report["softCount"] += 1
                if len(report["samples"]) < 5:
                    report["samples"].append(raw_line.strip())
    return reports


def healthy_warning_heal_plan(
    warning_names_by_app: dict[str, set[str]],
    slot_reports: dict[str, Any],
) -> dict[str, list[str]]:
    healthy_by_name: dict[str, bool] = {}
    for report in slot_reports.values():
        current = report.get("current") or {}
        name = current.get("name")
        if not name:
            continue
        proxy_status = (report.get("proxyTest") or {}).get("status")
        healthy_by_name[str(name)] = proxy_status == 200

    plan: dict[str, list[str]] = {}
    for app_name, warning_names in warning_names_by_app.items():
        healable = sorted(name for name in warning_names if healthy_by_name.get(name))
        if healable:
            plan[app_name] = healable
    return plan


def replacement_due(
    store: StateStore,
    slot_name: str,
    current_name: str,
    current_test_ok: bool,
    warning_names: set[str],
    hard_log_failure_count: int,
    soft_log_failure_count: int,
) -> tuple[bool, dict[str, Any]]:
    failure_state = store.runtime.setdefault("failureState", {})
    entry = failure_state.setdefault(slot_name, {"count": 0, "lastFailureTs": 0, "lastSuccessTs": 0})
    warning_present = current_name in warning_names
    log_failure_present = hard_log_failure_count >= CONFIG.log_failure_threshold
    soft_log_failure_present = warning_present and soft_log_failure_count >= CONFIG.soft_log_failure_threshold
    critical_log_failure = hard_log_failure_count >= (CONFIG.log_failure_threshold * 3)
    if current_test_ok and not log_failure_present and not soft_log_failure_present:
        entry["count"] = 0
        entry["lastSuccessTs"] = now_ts()
        return False, {
            "warningPresent": warning_present,
            "failureCount": 0,
            "logFailureCount": hard_log_failure_count,
            "softLogFailureCount": soft_log_failure_count,
            "persistentSoftFailure": False,
            "criticalLogFailure": False,
        }

    entry["count"] = int(entry.get("count", 0)) + 1
    entry["lastFailureTs"] = now_ts()
    due = (
        entry["count"] >= CONFIG.replacement_failure_threshold
        or warning_present
        or log_failure_present
        or soft_log_failure_present
    )
    return due, {
        "warningPresent": warning_present,
        "failureCount": entry["count"],
        "logFailureCount": hard_log_failure_count,
        "softLogFailureCount": soft_log_failure_count,
        "persistentSoftFailure": soft_log_failure_present,
        "criticalLogFailure": critical_log_failure,
    }


def replacement_cooldown_remaining(store: StateStore, slot_name: str | None = None) -> int:
    if slot_name:
        slot_state = store.runtime.setdefault("lastReplacementAtBySlot", {})
        last_replacement = int(slot_state.get(slot_name, 0) or 0)
        if last_replacement <= 0:
            return 0
    else:
        last_replacement = int(store.runtime.get("lastReplacementAt", 0) or 0)
    if last_replacement <= 0:
        return 0
    remaining = CONFIG.replacement_cooldown_seconds - (now_ts() - last_replacement)
    return max(0, remaining)


def delete_indexer(prowlarr: JsonApiClient, indexer_id: int) -> None:
    prowlarr.delete(f"/api/v1/indexer/{indexer_id}")


def create_indexer(prowlarr: JsonApiClient, payload: dict[str, Any]) -> dict[str, Any]:
    created = prowlarr.post("/api/v1/indexer", payload)
    if not isinstance(created, dict) or "id" not in created:
        raise RuntimeError("Prowlarr did not return a created indexer payload.")
    return created


def gather_warning_names(radarr: JsonApiClient, sonarr: JsonApiClient, lidarr: JsonApiClient) -> dict[str, set[str]]:
    return {
        "radarr": parse_warning_indexers(arr_health(radarr, "/api/v3/health")),
        "sonarr": parse_warning_indexers(arr_health(sonarr, "/api/v3/health")),
        "lidarr": parse_warning_indexers(arr_health(lidarr, "/api/v1/health")),
    }


def execute_cycle(store: StateStore) -> dict[str, Any]:
    prowlarr_key = read_api_key(PROWLARR_CONFIG_XML)
    radarr_key = read_api_key(RADARR_CONFIG_XML)
    sonarr_key = read_api_key(SONARR_CONFIG_XML)
    lidarr_key = read_api_key(LIDARR_CONFIG_XML)

    prowlarr = JsonApiClient(CONFIG.prowlarr_url, prowlarr_key)
    radarr = JsonApiClient(CONFIG.radarr_url, radarr_key)
    sonarr = JsonApiClient(CONFIG.sonarr_url, sonarr_key)
    lidarr = JsonApiClient(CONFIG.lidarr_url, lidarr_key)

    managed_tag_id = ensure_managed_tag(prowlarr)
    applications_by_name = application_name_map(prowlarr)
    schema_list = prowlarr.get("/api/v1/indexer/schema")
    schema_by_definition = {item.get("definitionName"): item for item in schema_list}
    current_indexers = prowlarr.get("/api/v1/indexer")
    slot_state = seed_slot_state(store, current_indexers)
    warning_names_by_app = gather_warning_names(radarr, sonarr, lidarr)
    prowlarr_warning_names = parse_warning_indexers(arr_health(prowlarr, "/api/v1/health"))
    warning_names = set(prowlarr_warning_names).union(*warning_names_by_app.values())
    log_signal_reports = collect_indexer_log_signals(current_indexers)

    active_definitions = {item.get("definitionName") for item in current_indexers if item.get("enable")}
    current_by_id = {item.get("id"): item for item in current_indexers}
    actions: list[dict[str, Any]] = []
    slot_reports: dict[str, Any] = {}
    overall_cooldown_remaining = replacement_cooldown_remaining(store)

    for slot_name, slot_info in slot_state.items():
        slot_cooldown_remaining = replacement_cooldown_remaining(store, slot_name)
        current = current_by_id.get(slot_info.get("id"))
        slot_query = SLOT_DEFINITIONS[slot_name]["testQuery"]
        report = {
            "slot": slot_name,
            "current": None,
            "proxyTest": None,
            "replacementAttempted": False,
            "replacementPerformed": False,
            "cooldownRemainingSeconds": slot_cooldown_remaining,
        }

        if current is None:
            candidate_definitions = candidate_definition_sequence(slot_name, active_definitions, store)
            report["current"] = {"missing": True, "expectedDefinition": slot_info.get("definitionName")}
            if candidate_definitions and slot_cooldown_remaining == 0:
                report["candidateAttempts"] = []
                for candidate_definition in candidate_definitions:
                    template = schema_by_definition.get(candidate_definition)
                    if not template:
                        report["candidateAttempts"].append(
                            {
                                "definitionName": candidate_definition,
                                "status": "schema-missing",
                            }
                        )
                        continue
                    payload = build_replacement_payload(slot_name, None, template, managed_tag_id)
                    try:
                        created = create_indexer(prowlarr, payload)
                    except Exception as exc:
                        note_replacement_history(store, slot_name, candidate_definition, "candidate-create-failed")
                        report["candidateAttempts"].append(
                            {
                                "definitionName": candidate_definition,
                                "status": "create-failed",
                                "error": str(exc),
                            }
                        )
                        continue
                    ok, result = proxy_test(prowlarr_key, int(created["id"]), slot_query)
                    report["replacementAttempted"] = True
                    report["candidateDefinition"] = candidate_definition
                    report["candidateTest"] = result
                    report["candidateAttempts"].append(
                        {
                            "definitionName": candidate_definition,
                            "status": "validated" if ok else "failed-validation",
                            "test": result,
                        }
                    )
                    if ok:
                        slot_info.update(
                            {
                                "id": created["id"],
                                "definitionName": created.get("definitionName", candidate_definition),
                                "name": created.get("name"),
                                "priority": created.get("priority"),
                                "appProfileId": created.get("appProfileId"),
                                "tags": list(created.get("tags", [])),
                            }
                        )
                        active_definitions.add(candidate_definition)
                        note_replacement_history(store, slot_name, candidate_definition, "slot-recreated")
                        report["replacementPerformed"] = True
                        actions.append(
                            {
                                "slot": slot_name,
                                "action": "recreated",
                                "definitionName": candidate_definition,
                            }
                        )
                        break
                    delete_indexer(prowlarr, int(created["id"]))
                    note_replacement_history(store, slot_name, candidate_definition, "candidate-failed-validation")
            slot_reports[slot_name] = report
            continue

        report["current"] = {
            "id": current.get("id"),
            "name": current.get("name"),
            "definitionName": current.get("definitionName"),
            "priority": current.get("priority"),
            "appProfileId": current.get("appProfileId"),
            "tags": list(current.get("tags", [])),
            "enable": bool(current.get("enable")),
        }
        report["logSignals"] = log_signal_reports.get(str(current.get("name") or ""), {"count": 0, "samples": []})
        ok, test_result = proxy_test(prowlarr_key, int(current["id"]), slot_query)
        report["proxyTest"] = test_result
        due, due_meta = replacement_due(
            store,
            slot_name,
            str(current.get("name") or ""),
            ok,
            warning_names,
            int((report.get("logSignals") or {}).get("hardCount", 0) or 0),
            int((report.get("logSignals") or {}).get("softCount", 0) or 0),
        )
        report["replacementGate"] = due_meta
        slot_cooldown_remaining = 0 if bool(due_meta.get("criticalLogFailure")) else slot_cooldown_remaining
        report["cooldownRemainingSeconds"] = slot_cooldown_remaining

        if not due or slot_cooldown_remaining > 0:
            slot_reports[slot_name] = report
            continue

        candidate_definitions = candidate_definition_sequence(slot_name, active_definitions - {current.get("definitionName")}, store)
        if not candidate_definitions:
            report["replacementAttempted"] = False
            report["replacementSkippedReason"] = "no-candidate"
            slot_reports[slot_name] = report
            continue

        report["candidateAttempts"] = []
        for candidate_definition in candidate_definitions:
            template = schema_by_definition.get(candidate_definition)
            if not template:
                report["candidateAttempts"].append(
                    {
                        "definitionName": candidate_definition,
                        "status": "schema-missing",
                    }
                )
                continue

            payload = build_replacement_payload(slot_name, current, template, managed_tag_id)
            try:
                created = create_indexer(prowlarr, payload)
            except Exception as exc:
                note_replacement_history(store, slot_name, candidate_definition, "candidate-create-failed")
                report["candidateAttempts"].append(
                    {
                        "definitionName": candidate_definition,
                        "status": "create-failed",
                        "error": str(exc),
                    }
                )
                continue

            candidate_ok, candidate_test = proxy_test(prowlarr_key, int(created["id"]), slot_query)
            report["replacementAttempted"] = True
            report["candidateDefinition"] = candidate_definition
            report["candidateTest"] = candidate_test
            report["candidateAttempts"].append(
                {
                    "definitionName": candidate_definition,
                    "status": "validated" if candidate_ok else "failed-validation",
                    "test": candidate_test,
                }
            )

            if candidate_ok:
                try:
                    delete_indexer(prowlarr, int(current["id"]))
                except Exception as exc:  # pragma: no cover - live safety fallback
                    report["oldDeleteWarning"] = str(exc)

                slot_info.update(
                    {
                        "id": created["id"],
                        "definitionName": created.get("definitionName", candidate_definition),
                        "name": created.get("name"),
                        "priority": created.get("priority"),
                        "appProfileId": created.get("appProfileId"),
                        "tags": list(created.get("tags", [])),
                    }
                )
                note_replacement_history(store, slot_name, candidate_definition, f"replaced:{current.get('definitionName')}")
                report["replacementPerformed"] = True
                actions.append(
                    {
                        "slot": slot_name,
                        "action": "replaced",
                        "oldDefinition": current.get("definitionName"),
                        "oldName": current.get("name"),
                        "newDefinition": candidate_definition,
                        "newName": created.get("name"),
                    }
                )
                break

            try:
                delete_indexer(prowlarr, int(created["id"]))
            except Exception:
                pass
            note_replacement_history(store, slot_name, candidate_definition, "candidate-failed-validation")

        slot_reports[slot_name] = report

    warning_heal_plan = healthy_warning_heal_plan(warning_names_by_app, slot_reports)
    application_syncs: dict[str, Any] = {}
    stale_indexer_cleanup: dict[str, list[dict[str, Any]]] = {}
    arr_indexer_api_roots = {
        "radarr": "/api/v3/indexer",
        "sonarr": "/api/v3/indexer",
        "lidarr": "/api/v1/indexer",
    }
    arr_health_api_roots = {
        "radarr": "/api/v3/health",
        "sonarr": "/api/v3/health",
        "lidarr": "/api/v1/health",
    }
    arr_clients = {
        "radarr": radarr,
        "sonarr": sonarr,
        "lidarr": lidarr,
    }

    for app_name, client in arr_clients.items():
        arr_indexers = client.get(arr_indexer_api_roots[app_name])
        stale_entries = stale_app_indexers(arr_indexers, current_indexers)
        stale_indexer_cleanup[app_name] = stale_entries
        for entry in stale_entries:
            delete_arr_indexer(client, arr_indexer_api_roots[app_name], int(entry["id"]))
            actions.append(
                {
                    "action": "deleted-stale-app-indexer",
                    "application": app_name.capitalize(),
                    "indexer": entry["name"],
                    "referencedProwlarrIndexerId": entry["referencedProwlarrIndexerId"],
                    "currentProwlarrName": entry["currentProwlarrName"],
                }
            )

    replacement_sync_required = any(action.get("action") in {"recreated", "replaced"} for action in actions)

    for app_name, healable_names in warning_heal_plan.items():
        app_report = {
            "indexers": healable_names,
            "performed": False,
            "cooldownRemainingSeconds": app_sync_cooldown_remaining(store, app_name),
        }
        if stale_indexer_cleanup.get(app_name):
            app_report["skippedReason"] = "stale-cleanup"
            application_syncs[app_name] = app_report
            continue
        app = applications_by_name.get(app_name.lower())
        if not app:
            app_report["skippedReason"] = "application-missing"
            application_syncs[app_name] = app_report
            continue
        if not app.get("enable", False):
            app_report["skippedReason"] = "application-disabled"
            application_syncs[app_name] = app_report
            continue
        if app_report["cooldownRemainingSeconds"] > 0:
            app_report["skippedReason"] = "cooldown"
            application_syncs[app_name] = app_report
            continue

        queue_application_indexer_sync(prowlarr, int(app["id"]))
        queue_arr_health_check(client, arr_health_api_roots[app_name])
        note_app_sync(store, app_name)
        app_report["performed"] = True
        actions.append(
            {
                "action": "application-indexer-sync",
                "application": app.get("name", app_name),
                "indexers": healable_names,
            }
        )
        actions.append(
            {
                "action": "application-health-check",
                "application": app.get("name", app_name),
            }
        )
        application_syncs[app_name] = app_report

    if replacement_sync_required:
        for app_name, client in arr_clients.items():
            if app_name in application_syncs:
                continue
            app = applications_by_name.get(app_name.lower())
            app_report = {
                "indexers": [],
                "performed": False,
                "cooldownRemainingSeconds": app_sync_cooldown_remaining(store, app_name),
                "reason": "replacement-sync",
            }
            if stale_indexer_cleanup.get(app_name):
                app_report["skippedReason"] = "stale-cleanup"
                application_syncs[app_name] = app_report
                continue
            if not app:
                app_report["skippedReason"] = "application-missing"
                application_syncs[app_name] = app_report
                continue
            if not app.get("enable", False):
                app_report["skippedReason"] = "application-disabled"
                application_syncs[app_name] = app_report
                continue
            if app_report["cooldownRemainingSeconds"] > 0:
                app_report["skippedReason"] = "cooldown"
                application_syncs[app_name] = app_report
                continue

            queue_application_indexer_sync(prowlarr, int(app["id"]))
            queue_arr_health_check(client, arr_health_api_roots[app_name])
            note_app_sync(store, app_name)
            app_report["performed"] = True
            actions.append(
                {
                    "action": "application-indexer-sync",
                    "application": app.get("name", app_name),
                    "reason": "replacement-sync",
                }
            )
            actions.append(
                {
                    "action": "application-health-check",
                    "application": app.get("name", app_name),
                    "reason": "replacement-sync",
                }
            )
            application_syncs[app_name] = app_report

    snapshot = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "warnings": {key: sorted(value) for key, value in {**warning_names_by_app, "prowlarr": prowlarr_warning_names}.items()},
        "logSignals": log_signal_reports,
        "warningHealPlan": warning_heal_plan,
        "staleAppIndexers": stale_indexer_cleanup,
        "applicationSyncs": application_syncs,
        "cooldownRemainingSeconds": overall_cooldown_remaining,
        "actions": actions,
        "slots": slot_reports,
        "managedTagLabel": CONFIG.managed_tag_label,
    }
    return snapshot


def main() -> None:
    store = StateStore()
    while True:
        try:
            snapshot = execute_cycle(store)
            store.write_runtime()
            store.write_snapshot(snapshot)
            action_count = len(snapshot["actions"])
            slot_summary = ", ".join(
                f"{slot}:{'ok' if (details.get('proxyTest', {}) or {}).get('status') == 200 else 'warn'}"
                for slot, details in snapshot["slots"].items()
            )
            log(f"actions={action_count} cooldown={snapshot['cooldownRemainingSeconds']}s slots=[{slot_summary}]")
        except Exception as exc:  # pragma: no cover - live loop
            failure = {
                "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "error": str(exc),
            }
            store.write_snapshot(failure)
            log(f"error={exc}")

        if CONFIG.run_once:
            break
        time.sleep(CONFIG.check_interval_seconds)


if __name__ == "__main__":
    main()
