#!/usr/bin/env python3
"""
Sync Overseerr request state to the real live Harbor stack state.

Goals:
- Keep "requested" only for items that are actively being pursued right now.
- Remove obviously dead qBittorrent backlog entries under 80% progress.
- Preserve anything already over 80% complete.
- Preserve library/available media rows so Overseerr can still show availability.
- Back up Overseerr's database before any destructive change.
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

import paramiko
import requests


DEFAULT_ENV_PATH = pathlib.Path(__file__).resolve().parents[1] / ".env.synology.local"
DEFAULT_REPORT_DIR = pathlib.Path(__file__).resolve().parents[1] / "reports" / "overseerr-sync"
QBIT_URL = "http://localhost:8081"
RADARR_URL = "http://localhost:7878/api/v3"
SONARR_URL = "http://localhost:8989/api/v3"
OVERSEERR_DB_PATH = "/volume1/docker/harbor/appdata/overseerr/config/db/db.sqlite3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync Overseerr request state to live qB/Arr state.")
    parser.add_argument("--env-path", default=str(DEFAULT_ENV_PATH))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--nas-host", default="synology.example.lan")
    parser.add_argument("--nas-user", default="harboradmin")
    parser.add_argument("--nas-password", default="change_me")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Default is dry-run.")
    parser.add_argument(
        "--wipe-queue",
        action="store_true",
        help="Remove the entire qB queue. Complete entries keep files; incomplete entries delete files.",
    )
    parser.add_argument(
        "--clear-all-requests",
        action="store_true",
        help="Delete every Overseerr request row, not just stale ones.",
    )
    parser.add_argument(
        "--purge-incomplete-dir",
        action="store_true",
        help="Also purge orphaned files from /volume1/downloads/incomplete after queue cleanup.",
    )
    parser.add_argument(
        "--sleep-after-qbit-delete",
        type=int,
        default=5,
        help="Seconds to wait after qB dead-entry deletion before recomputing live pursuit state.",
    )
    return parser.parse_args()


def load_env(path: pathlib.Path) -> dict[str, str]:
    env_map: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env_map[key.strip()] = value.strip()
    return env_map


def norm_title(value: str) -> str:
    value = (value or "").casefold().strip()
    return " ".join(value.split())


def make_qbit_session(username: str, password: str) -> requests.Session:
    session = requests.Session()
    login = session.post(
        f"{QBIT_URL}/api/v2/auth/login",
        data={"username": username, "password": password},
        timeout=30,
    )
    login.raise_for_status()
    return session


def fetch_qbit_torrents(session: requests.Session) -> list[dict[str, Any]]:
    response = session.get(f"{QBIT_URL}/api/v2/torrents/info?filter=all", timeout=90)
    response.raise_for_status()
    return response.json()


def fetch_arr_json(url: str, api_key: str) -> Any:
    response = requests.get(url, headers={"X-Api-Key": api_key}, timeout=90)
    response.raise_for_status()
    return response.json()


def fetch_live_arr_state(radarr_api: str, sonarr_api: str) -> dict[str, Any]:
    movies = fetch_arr_json(f"{RADARR_URL}/movie", radarr_api)
    series = fetch_arr_json(f"{SONARR_URL}/series", sonarr_api)
    radarr_queue = fetch_arr_json(
        f"{RADARR_URL}/queue/details?includeUnknownMovieItems=true&page=1&pageSize=10000",
        radarr_api,
    )
    sonarr_queue = fetch_arr_json(
        f"{SONARR_URL}/queue/details?includeUnknownSeriesItems=true&page=1&pageSize=10000",
        sonarr_api,
    )
    if isinstance(radarr_queue, dict):
        radarr_queue = radarr_queue.get("records", [])
    if isinstance(sonarr_queue, dict):
        sonarr_queue = sonarr_queue.get("records", [])
    return {
        "movies": movies,
        "series": series,
        "radarr_queue": radarr_queue,
        "sonarr_queue": sonarr_queue,
    }


def movie_key_from_tmdb(tmdb_id: Any) -> tuple[str, int] | None:
    if tmdb_id in (None, ""):
        return None
    return ("movie", int(tmdb_id))


def tv_key_from_values(tvdb_id: Any, tmdb_id: Any) -> tuple[str, str, int] | None:
    if tvdb_id not in (None, ""):
        return ("tv", "tvdb", int(tvdb_id))
    if tmdb_id not in (None, ""):
        return ("tv", "tmdb", int(tmdb_id))
    return None


def media_key_from_overseerr_row(row: dict[str, Any]) -> tuple[str, int] | tuple[str, str, int] | None:
    media_type = row.get("mediaType")
    if media_type == "movie":
        return movie_key_from_tmdb(row.get("tmdbId"))
    if media_type == "tv":
        return tv_key_from_values(row.get("tvdbId"), row.get("tmdbId"))
    return None


def qbit_is_dead_candidate(torrent: dict[str, Any]) -> bool:
    state = str(torrent.get("state") or "")
    progress = float(torrent.get("progress") or 0.0)
    seeds = int(torrent.get("num_seeds") or 0)
    availability = float(torrent.get("availability") or 0.0)
    has_metadata = bool(torrent.get("has_metadata"))
    dlspeed = int(torrent.get("dlspeed") or 0)
    return (
        progress < 0.8
        and state in {"stoppedDL", "metaDL", "missingFiles", "error"}
        and dlspeed == 0
        and seeds == 0
        and availability <= 0
        and (not has_metadata or state != "metaDL")
    )


def qbit_is_active_pursuit(torrent: dict[str, Any], queue_record: dict[str, Any] | None = None) -> bool:
    if not torrent:
        return False
    state = str(torrent.get("state") or "")
    progress = float(torrent.get("progress") or 0.0)
    seeds = int(torrent.get("num_seeds") or 0)
    availability = float(torrent.get("availability") or 0.0)
    has_metadata = bool(torrent.get("has_metadata"))

    if progress >= 0.8:
        return True
    if state in {"downloading", "forcedDL"}:
        return True
    if state == "queuedDL" and has_metadata:
        return True
    if state == "stalledDL" and (availability > 0 or seeds > 0):
        return True
    if state == "metaDL" and has_metadata and availability > 0:
        return True
    if (
        queue_record
        and int(queue_record.get("sizeleft") or 0) == 0
        and str(queue_record.get("trackedDownloadStatus") or "").casefold() == "ok"
        and progress >= 1.0
    ):
        return True
    return False


def build_arr_lookup(arr_state: dict[str, Any]) -> dict[str, Any]:
    movies_by_arr_id = {movie.get("id"): movie for movie in arr_state["movies"] if movie.get("id") is not None}
    series_by_arr_id = {series.get("id"): series for series in arr_state["series"] if series.get("id") is not None}
    return {
        "movies_by_arr_id": movies_by_arr_id,
        "series_by_arr_id": series_by_arr_id,
    }


def build_available_library_keys(arr_state: dict[str, Any]) -> set[tuple[Any, ...]]:
    keys: set[tuple[Any, ...]] = set()
    for movie in arr_state["movies"]:
        if movie.get("hasFile"):
            key = movie_key_from_tmdb(movie.get("tmdbId"))
            if key:
                keys.add(key)
    for series in arr_state["series"]:
        stats = series.get("statistics") or {}
        if (stats.get("episodeFileCount") or 0) > 0 and (
            stats.get("episodeCount") or 0
        ) >= (stats.get("totalEpisodeCount") or 0):
            key = tv_key_from_values(series.get("tvdbId"), series.get("tmdbId"))
            if key:
                keys.add(key)
    return keys


def build_active_pursuit_keys(
    qbit_torrents: list[dict[str, Any]],
    arr_state: dict[str, Any],
) -> tuple[set[tuple[Any, ...]], dict[tuple[Any, ...], list[str]]]:
    qbit_by_hash = {
        str(torrent.get("hash") or "").lower(): torrent
        for torrent in qbit_torrents
        if torrent.get("hash")
    }
    lookups = build_arr_lookup(arr_state)
    active_keys: set[tuple[Any, ...]] = set()
    reasons: dict[tuple[Any, ...], list[str]] = defaultdict(list)

    for record in arr_state["radarr_queue"]:
        movie = lookups["movies_by_arr_id"].get(record.get("movieId"))
        if not movie:
            continue
        key = movie_key_from_tmdb(movie.get("tmdbId"))
        if not key:
            continue
        protocol = str(record.get("protocol") or "").casefold()
        download_id = str(record.get("downloadId") or "").lower()
        if protocol == "usenet":
            if str(record.get("trackedDownloadStatus") or "").casefold() == "ok":
                active_keys.add(key)
                reasons[key].append("radarr-usenet")
        elif protocol == "torrent":
            torrent = qbit_by_hash.get(download_id)
            if qbit_is_active_pursuit(torrent, record):
                active_keys.add(key)
                reasons[key].append(f"radarr-torrent:{torrent.get('state') if torrent else 'missing'}")

    for record in arr_state["sonarr_queue"]:
        series = lookups["series_by_arr_id"].get(record.get("seriesId"))
        if not series:
            continue
        key = tv_key_from_values(series.get("tvdbId"), series.get("tmdbId"))
        if not key:
            continue
        protocol = str(record.get("protocol") or "").casefold()
        download_id = str(record.get("downloadId") or "").lower()
        if protocol == "usenet":
            if str(record.get("trackedDownloadStatus") or "").casefold() == "ok":
                active_keys.add(key)
                reasons[key].append("sonarr-usenet")
        elif protocol == "torrent":
            torrent = qbit_by_hash.get(download_id)
            if qbit_is_active_pursuit(torrent, record):
                active_keys.add(key)
                reasons[key].append(f"sonarr-torrent:{torrent.get('state') if torrent else 'missing'}")

    return active_keys, reasons


def build_qbit_dead_candidates(qbit_torrents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [torrent for torrent in qbit_torrents if qbit_is_dead_candidate(torrent)]


def run_remote_python(host: str, user: str, password: str, script: str) -> str:
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    command = f"python3 -c \"import base64; exec(base64.b64decode('{encoded}').decode())\""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        username=user,
        password=password,
        timeout=30,
        banner_timeout=30,
        auth_timeout=30,
    )
    stdin, stdout, stderr = client.exec_command(command)
    out = stdout.read().decode("utf-8", "ignore")
    err = stderr.read().decode("utf-8", "ignore")
    client.close()
    if err and not out:
        raise RuntimeError(err.strip())
    return out


def run_remote_shell(host: str, user: str, password: str, command: str) -> str:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        username=user,
        password=password,
        timeout=30,
        banner_timeout=30,
        auth_timeout=30,
    )
    stdin, stdout, stderr = client.exec_command(command, get_pty=True)
    out = stdout.read().decode("utf-8", "ignore")
    err = stderr.read().decode("utf-8", "ignore")
    client.close()
    if err and not out:
        raise RuntimeError(err.strip())
    return out


def fetch_overseerr_rows(host: str, user: str, password: str) -> dict[str, list[dict[str, Any]]]:
    script = f"""
import json
import sqlite3

conn = sqlite3.connect({OVERSEERR_DB_PATH!r})
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute(
    \"\"\"
    SELECT
        mr.id AS request_id,
        mr.mediaId,
        mr.status,
        mr.type,
        m.mediaType,
        m.tmdbId,
        m.tvdbId,
        m.ratingKey,
        m.ratingKey4k,
        m.mediaAddedAt
    FROM media_request mr
    LEFT JOIN media m ON mr.mediaId = m.id
    ORDER BY mr.id
    \"\"\"
)
request_rows = [dict(row) for row in cur.fetchall()]
cur.execute(
    \"\"\"
    SELECT
        id,
        mediaType,
        tmdbId,
        tvdbId,
        ratingKey,
        ratingKey4k,
        mediaAddedAt
    FROM media
    ORDER BY id
    \"\"\"
)
media_rows = [dict(row) for row in cur.fetchall()]
conn.close()
print(json.dumps({{"request_rows": request_rows, "media_rows": media_rows}}))
"""
    payload = run_remote_python(host, user, password, script)
    return json.loads(payload)


def backup_overseerr_db(host: str, user: str, password: str, timestamp: str) -> str:
    backup_path = f"{OVERSEERR_DB_PATH}.pre-request-sync-{timestamp}"
    run_remote_shell(host, user, password, f"cp {OVERSEERR_DB_PATH} {backup_path}")
    return backup_path


def apply_overseerr_cleanup(
    host: str,
    user: str,
    password: str,
    request_ids_to_delete: list[int],
    media_ids_to_delete: list[int],
) -> dict[str, Any]:
    payload_json = json.dumps(
        {
            "request_ids": request_ids_to_delete,
            "media_ids": media_ids_to_delete,
        }
    )
    script = f"""
import json
import sqlite3

payload = json.loads({payload_json!r})
conn = sqlite3.connect({OVERSEERR_DB_PATH!r})
conn.execute('PRAGMA foreign_keys=ON')
cur = conn.cursor()
deleted_requests = 0
deleted_media = 0

if payload['request_ids']:
    cur.executemany('DELETE FROM media_request WHERE id = ?', [(value,) for value in payload['request_ids']])
    deleted_requests = cur.rowcount if cur.rowcount != -1 else len(payload['request_ids'])

if payload['media_ids']:
    cur.executemany('DELETE FROM media WHERE id = ?', [(value,) for value in payload['media_ids']])
    deleted_media = cur.rowcount if cur.rowcount != -1 else len(payload['media_ids'])

conn.commit()
conn.close()
print(json.dumps({{"deleted_requests": deleted_requests, "deleted_media": deleted_media}}))
"""
    payload = run_remote_python(host, user, password, script)
    return json.loads(payload)


def delete_qbit_hashes(session: requests.Session, hashes: list[str], delete_files: bool) -> None:
    if not hashes:
        return
    batch_size = 64
    for start in range(0, len(hashes), batch_size):
        batch = hashes[start : start + batch_size]
        response = session.post(
            f"{QBIT_URL}/api/v2/torrents/delete",
            data={"hashes": "|".join(batch), "deleteFiles": "true" if delete_files else "false"},
            timeout=120,
        )
        response.raise_for_status()


def build_qbit_cleanup_buckets(
    qbit_torrents: list[dict[str, Any]],
    wipe_queue: bool,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    candidates = qbit_torrents if wipe_queue else build_qbit_dead_candidates(qbit_torrents)
    delete_with_files: list[str] = []
    delete_without_files: list[str] = []

    for torrent in candidates:
        torrent_hash = str(torrent.get("hash") or "").lower()
        if not torrent_hash:
            continue
        progress = float(torrent.get("progress") or 0.0)
        if progress >= 1.0:
            delete_without_files.append(torrent_hash)
        else:
            delete_with_files.append(torrent_hash)

    return candidates, delete_with_files, delete_without_files


def purge_orphaned_incomplete_dir(host: str, user: str, password: str) -> str:
    command = (
        "if [ -d /volume1/downloads/incomplete ]; then "
        "find /volume1/downloads/incomplete -mindepth 1 -maxdepth 1 -exec rm -rf {} +; "
        "echo PURGED; "
        "else echo MISSING; fi"
    )
    return run_remote_shell(host, user, password, command).strip()


def describe_media_title(
    key: tuple[Any, ...] | None,
    arr_state: dict[str, Any],
) -> str:
    if not key:
        return ""
    if key[0] == "movie":
        tmdb_id = key[1]
        for movie in arr_state["movies"]:
            if movie.get("tmdbId") == tmdb_id:
                return movie.get("title") or ""
        return ""
    if key[0] == "tv":
        mode = key[1]
        id_value = key[2]
        for series in arr_state["series"]:
            candidate = series.get("tvdbId") if mode == "tvdb" else series.get("tmdbId")
            if candidate == id_value:
                return series.get("title") or ""
        return ""
    return ""


def build_request_cleanup_plan(
    overseerr_rows: dict[str, list[dict[str, Any]]],
    active_pursuit_keys: set[tuple[Any, ...]],
    available_library_keys: set[tuple[Any, ...]],
    arr_state: dict[str, Any],
    clear_all_requests: bool = False,
) -> dict[str, Any]:
    request_rows = overseerr_rows["request_rows"]
    media_rows = overseerr_rows["media_rows"]

    kept_requests: list[dict[str, Any]] = []
    stale_requests: list[dict[str, Any]] = []
    for row in request_rows:
        key = media_key_from_overseerr_row(row)
        title = describe_media_title(key, arr_state)
        row["derived_title"] = title
        row["derived_key"] = list(key) if key else None
        if not clear_all_requests and key in active_pursuit_keys:
            kept_requests.append(row)
        else:
            stale_requests.append(row)

    stale_media_ids = {row["mediaId"] for row in stale_requests if row.get("mediaId") is not None}
    active_media_ids = {row["mediaId"] for row in kept_requests if row.get("mediaId") is not None}

    media_rows_to_delete: list[dict[str, Any]] = []
    for media_row in media_rows:
        if media_row["id"] not in stale_media_ids:
            continue
        if media_row["id"] in active_media_ids:
            continue
        key = media_key_from_overseerr_row(media_row)
        in_library = (
            key in available_library_keys
            or bool(media_row.get("ratingKey"))
            or bool(media_row.get("ratingKey4k"))
            or bool(media_row.get("mediaAddedAt"))
        )
        if not in_library:
            media_row["derived_title"] = describe_media_title(key, arr_state)
            media_row["derived_key"] = list(key) if key else None
            media_rows_to_delete.append(media_row)

    return {
        "kept_requests": kept_requests,
        "stale_requests": stale_requests,
        "media_rows_to_delete": media_rows_to_delete,
    }


def write_report(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    env_map = load_env(pathlib.Path(args.env_path))
    report_dir = pathlib.Path(args.report_dir)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    qbit_session = make_qbit_session(env_map["QBIT_USER"], env_map["QBIT_PASS"])
    qbit_torrents_before = fetch_qbit_torrents(qbit_session)
    qbit_cleanup_candidates, delete_with_files_hashes, delete_without_files_hashes = build_qbit_cleanup_buckets(
        qbit_torrents_before,
        wipe_queue=args.wipe_queue,
    )

    qbit_manifest = {
        "generated_at": datetime.now().isoformat(),
        "mode": "wipe-queue" if args.wipe_queue else "dead-only",
        "qbit_total_before": len(qbit_torrents_before),
        "candidate_count": len(qbit_cleanup_candidates),
        "delete_with_files_count": len(delete_with_files_hashes),
        "delete_without_files_count": len(delete_without_files_hashes),
        "candidates": [
            {
                "hash": torrent.get("hash"),
                "name": torrent.get("name"),
                "state": torrent.get("state"),
                "progress": torrent.get("progress"),
                "availability": torrent.get("availability"),
                "num_seeds": torrent.get("num_seeds"),
            }
            for torrent in qbit_cleanup_candidates
        ],
    }
    write_report(report_dir / f"qbit-queue-cleanup-{timestamp}.json", qbit_manifest)

    incomplete_dir_purge_result = "not-run"
    if args.apply:
        if delete_with_files_hashes:
            delete_qbit_hashes(qbit_session, delete_with_files_hashes, delete_files=True)
        if delete_without_files_hashes:
            delete_qbit_hashes(qbit_session, delete_without_files_hashes, delete_files=False)
        if args.purge_incomplete_dir:
            incomplete_dir_purge_result = purge_orphaned_incomplete_dir(
                args.nas_host,
                args.nas_user,
                args.nas_password,
            )
        elif args.wipe_queue:
            incomplete_dir_purge_result = purge_orphaned_incomplete_dir(
                args.nas_host,
                args.nas_user,
                args.nas_password,
            )
        time.sleep(args.sleep_after_qbit_delete)

    qbit_torrents_after = fetch_qbit_torrents(qbit_session)
    arr_state = fetch_live_arr_state(env_map["RADARR_API_KEY"], env_map["SONARR_API_KEY"])
    active_pursuit_keys, active_reasons = build_active_pursuit_keys(qbit_torrents_after, arr_state)
    available_library_keys = build_available_library_keys(arr_state)
    overseerr_rows = fetch_overseerr_rows(args.nas_host, args.nas_user, args.nas_password)
    cleanup_plan = build_request_cleanup_plan(
        overseerr_rows,
        active_pursuit_keys,
        available_library_keys,
        arr_state,
        clear_all_requests=args.clear_all_requests,
    )

    summary = {
        "generated_at": datetime.now().isoformat(),
        "mode": "apply" if args.apply else "dry-run",
        "queue_cleanup_mode": "wipe-queue" if args.wipe_queue else "dead-only",
        "qbit_total_before": len(qbit_torrents_before),
        "qbit_total_after": len(qbit_torrents_after),
        "qbit_cleanup_candidates": len(qbit_cleanup_candidates),
        "qbit_delete_with_files_count": len(delete_with_files_hashes),
        "qbit_delete_without_files_count": len(delete_without_files_hashes),
        "active_pursuit_keys": len(active_pursuit_keys),
        "available_library_keys": len(available_library_keys),
        "overseerr_request_rows_total": len(overseerr_rows["request_rows"]),
        "overseerr_kept_request_rows": len(cleanup_plan["kept_requests"]),
        "overseerr_stale_request_rows": len(cleanup_plan["stale_requests"]),
        "overseerr_media_rows_to_delete": len(cleanup_plan["media_rows_to_delete"]),
        "incomplete_dir_purge_result": incomplete_dir_purge_result,
        "active_pursuit_titles": sorted(
            {
                describe_media_title(key, arr_state)
                for key in active_pursuit_keys
                if describe_media_title(key, arr_state)
            }
        ),
        "active_pursuit_reasons": {
            " | ".join(map(str, key)): sorted(set(values))
            for key, values in active_reasons.items()
        },
        "qbit_states_after": dict(Counter(str(torrent.get("state") or "") for torrent in qbit_torrents_after)),
    }

    report_payload = {
        "summary": summary,
        "qbit_cleanup_candidates": qbit_manifest["candidates"],
        "stale_overseerr_requests": cleanup_plan["stale_requests"],
        "kept_overseerr_requests": cleanup_plan["kept_requests"],
        "media_rows_to_delete": cleanup_plan["media_rows_to_delete"],
    }
    report_path = report_dir / f"overseerr-request-sync-{timestamp}.json"
    write_report(report_path, report_payload)

    result: dict[str, Any] = {
        "summary": summary,
        "report_path": str(report_path),
        "qbit_manifest_path": str(report_dir / f"qbit-queue-cleanup-{timestamp}.json"),
    }

    if args.apply:
        backup_path = backup_overseerr_db(args.nas_host, args.nas_user, args.nas_password, timestamp)
        db_result = apply_overseerr_cleanup(
            args.nas_host,
            args.nas_user,
            args.nas_password,
            request_ids_to_delete=[int(row["request_id"]) for row in cleanup_plan["stale_requests"]],
            media_ids_to_delete=[int(row["id"]) for row in cleanup_plan["media_rows_to_delete"]],
        )
        run_remote_shell(args.nas_host, args.nas_user, args.nas_password, "docker restart overseerr >/dev/null 2>&1 && echo restarted")
        result["backup_path"] = backup_path
        result["db_result"] = db_result

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

