#!/usr/bin/env python3
"""
Restore Overseerr request state only for media that is currently in the library.

This is intended for the case where request rows were cleared too aggressively.
It restores library-backed request/media/season_request rows from an older backup
without bringing back stale incomplete request state.
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
from datetime import datetime
from typing import Any

import paramiko
import requests


DEFAULT_ENV_PATH = pathlib.Path(__file__).resolve().parents[1] / ".env.synology.local"
DEFAULT_REPORT_DIR = pathlib.Path(__file__).resolve().parents[1] / "reports" / "overseerr-sync"
DEFAULT_BACKUP_DB = "/volume1/docker/harbor/appdata/overseerr/config/db/db.sqlite3.pre-request-sync-20260412-192309"
LIVE_DB = "/volume1/docker/harbor/appdata/overseerr/config/db/db.sqlite3"
RADARR_URL = "http://localhost:7878/api/v3/movie"
SONARR_URL = "http://localhost:8989/api/v3/series"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Restore library-backed Overseerr requests from backup.")
    parser.add_argument("--env-path", default=str(DEFAULT_ENV_PATH))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--backup-db", default=DEFAULT_BACKUP_DB)
    parser.add_argument("--nas-host", default="synology.example.lan")
    parser.add_argument("--nas-user", default="harboradmin")
    parser.add_argument("--nas-password", default="change_me")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Default is dry-run.")
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


def movie_key(tmdb_id: Any) -> tuple[str, int] | None:
    if tmdb_id in (None, ""):
        return None
    return ("movie", int(tmdb_id))


def tv_key(tvdb_id: Any, tmdb_id: Any) -> tuple[str, str, int] | None:
    if tvdb_id not in (None, ""):
        return ("tv", "tvdb", int(tvdb_id))
    if tmdb_id not in (None, ""):
        return ("tv", "tmdb", int(tmdb_id))
    return None


def media_key_from_row(row: dict[str, Any]) -> tuple[Any, ...] | None:
    if row.get("mediaType") == "movie":
        return movie_key(row.get("tmdbId"))
    if row.get("mediaType") == "tv":
        return tv_key(row.get("tvdbId"), row.get("tmdbId"))
    return None


def fetch_library_keys(radarr_api: str, sonarr_api: str) -> set[tuple[Any, ...]]:
    keys: set[tuple[Any, ...]] = set()
    movies = requests.get(RADARR_URL, headers={"X-Api-Key": radarr_api}, timeout=90).json()
    series = requests.get(SONARR_URL, headers={"X-Api-Key": sonarr_api}, timeout=90).json()
    for movie in movies:
        if movie.get("hasFile"):
            key = movie_key(movie.get("tmdbId"))
            if key:
                keys.add(key)
    for show in series:
        stats = show.get("statistics") or {}
        if (stats.get("episodeFileCount") or 0) > 0 and (
            stats.get("episodeCount") or 0
        ) >= (stats.get("totalEpisodeCount") or 0):
            key = tv_key(show.get("tvdbId"), show.get("tmdbId"))
            if key:
                keys.add(key)
    return keys


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


def fetch_backup_rows(host: str, user: str, password: str, backup_db: str) -> dict[str, Any]:
    script = f"""
import json
import sqlite3

conn = sqlite3.connect({backup_db!r})
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute(
    \"\"\"
    SELECT
        mr.id AS request_id,
        mr.status,
        mr.createdAt,
        mr.updatedAt,
        mr.type,
        mr.mediaId,
        mr.requestedById,
        mr.modifiedById,
        mr.is4k,
        mr.serverId,
        mr.profileId,
        mr.rootFolder,
        mr.languageProfileId,
        mr.tags,
        mr.isAutoRequest,
        m.id AS media_id,
        m.mediaType,
        m.tmdbId,
        m.tvdbId,
        m.imdbId,
        m.status AS media_status,
        m.createdAt AS media_createdAt,
        m.updatedAt AS media_updatedAt,
        m.lastSeasonChange,
        m.status4k,
        m.mediaAddedAt,
        m.serviceId,
        m.serviceId4k,
        m.externalServiceId,
        m.externalServiceId4k,
        m.externalServiceSlug,
        m.externalServiceSlug4k,
        m.ratingKey,
        m.ratingKey4k
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
        seasonNumber,
        status,
        createdAt,
        updatedAt,
        requestId
    FROM season_request
    ORDER BY id
    \"\"\"
)
season_request_rows = [dict(row) for row in cur.fetchall()]
conn.close()
print(json.dumps({{"request_rows": request_rows, "season_request_rows": season_request_rows}}))
"""
    return json.loads(run_remote_python(host, user, password, script))


def backup_live_db(host: str, user: str, password: str, timestamp: str) -> str:
    backup_path = f"{LIVE_DB}.pre-library-request-restore-{timestamp}"
    run_remote_shell(host, user, password, f"cp {LIVE_DB} {backup_path}")
    return backup_path


def apply_restore(
    host: str,
    user: str,
    password: str,
    media_rows: list[dict[str, Any]],
    request_rows: list[dict[str, Any]],
    season_request_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    def run_media_batch(batch: list[dict[str, Any]]) -> None:
        payload_json = json.dumps(batch)
        script = f"""
import json
import sqlite3

conn = sqlite3.connect({LIVE_DB!r})
conn.execute('PRAGMA foreign_keys=ON')
cur = conn.cursor()
for row in json.loads({payload_json!r}):
    cur.execute(
        '''
        INSERT OR REPLACE INTO media (
            id, mediaType, tmdbId, tvdbId, imdbId, status, createdAt, updatedAt,
            lastSeasonChange, status4k, mediaAddedAt, serviceId, serviceId4k,
            externalServiceId, externalServiceId4k, externalServiceSlug,
            externalServiceSlug4k, ratingKey, ratingKey4k
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            row['media_id'], row['mediaType'], row['tmdbId'], row['tvdbId'], row['imdbId'],
            row['media_status'], row['media_createdAt'], row['media_updatedAt'],
            row['lastSeasonChange'], row['status4k'], row['mediaAddedAt'], row['serviceId'],
            row['serviceId4k'], row['externalServiceId'], row['externalServiceId4k'],
            row['externalServiceSlug'], row['externalServiceSlug4k'], row['ratingKey'], row['ratingKey4k']
        )
    )
conn.commit()
conn.close()
print(json.dumps({{"inserted_media_rows": {len(batch)}}}))
"""
        run_remote_python(host, user, password, script)

    def run_request_batch(batch: list[dict[str, Any]]) -> None:
        payload_json = json.dumps(batch)
        script = f"""
import json
import sqlite3

conn = sqlite3.connect({LIVE_DB!r})
conn.execute('PRAGMA foreign_keys=ON')
cur = conn.cursor()
for row in json.loads({payload_json!r}):
    cur.execute(
        '''
        INSERT OR REPLACE INTO media_request (
            id, status, createdAt, updatedAt, type, mediaId, requestedById,
            modifiedById, is4k, serverId, profileId, rootFolder,
            languageProfileId, tags, isAutoRequest
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            row['request_id'], row['status'], row['createdAt'], row['updatedAt'],
            row['type'], row['mediaId'], row['requestedById'], row['modifiedById'],
            row['is4k'], row['serverId'], row['profileId'], row['rootFolder'],
            row['languageProfileId'], row['tags'], row['isAutoRequest']
        )
    )
conn.commit()
conn.close()
print(json.dumps({{"inserted_request_rows": {len(batch)}}}))
"""
        run_remote_python(host, user, password, script)

    def run_season_request_batch(batch: list[dict[str, Any]]) -> None:
        payload_json = json.dumps(batch)
        script = f"""
import json
import sqlite3

conn = sqlite3.connect({LIVE_DB!r})
conn.execute('PRAGMA foreign_keys=ON')
cur = conn.cursor()
for row in json.loads({payload_json!r}):
    cur.execute(
        '''
        INSERT OR REPLACE INTO season_request (
            id, seasonNumber, status, createdAt, updatedAt, requestId
        ) VALUES (?, ?, ?, ?, ?, ?)
        ''',
        (
            row['id'], row['seasonNumber'], row['status'], row['createdAt'],
            row['updatedAt'], row['requestId']
        )
    )
conn.commit()
conn.close()
print(json.dumps({{"inserted_season_request_rows": {len(batch)}}}))
"""
        run_remote_python(host, user, password, script)

    batch_size = 40
    for start in range(0, len(media_rows), batch_size):
        run_media_batch(media_rows[start : start + batch_size])
    for start in range(0, len(request_rows), batch_size):
        run_request_batch(request_rows[start : start + batch_size])
    for start in range(0, len(season_request_rows), batch_size):
        run_season_request_batch(season_request_rows[start : start + batch_size])

    return {
        "restored_media_rows": len(media_rows),
        "restored_request_rows": len(request_rows),
        "restored_season_request_rows": len(season_request_rows),
    }


def main() -> int:
    args = parse_args()
    env_map = load_env(pathlib.Path(args.env_path))
    report_dir = pathlib.Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    library_keys = fetch_library_keys(env_map["RADARR_API_KEY"], env_map["SONARR_API_KEY"])
    backup_rows = fetch_backup_rows(args.nas_host, args.nas_user, args.nas_password, args.backup_db)

    request_rows_to_restore: list[dict[str, Any]] = []
    media_rows_to_restore_map: dict[int, dict[str, Any]] = {}
    request_ids_to_restore: set[int] = set()
    for row in backup_rows["request_rows"]:
        key = media_key_from_row(row)
        if key not in library_keys:
            continue
        request_rows_to_restore.append(row)
        request_ids_to_restore.add(int(row["request_id"]))
        media_rows_to_restore_map[int(row["media_id"])] = row

    season_request_rows_to_restore = [
        row
        for row in backup_rows["season_request_rows"]
        if int(row["requestId"]) in request_ids_to_restore
    ]

    report_payload = {
        "summary": {
            "generated_at": datetime.now().isoformat(),
            "mode": "apply" if args.apply else "dry-run",
            "library_key_count": len(library_keys),
            "restore_request_count": len(request_rows_to_restore),
            "restore_media_count": len(media_rows_to_restore_map),
            "restore_season_request_count": len(season_request_rows_to_restore),
        },
        "request_rows_to_restore": request_rows_to_restore,
        "season_request_rows_to_restore": season_request_rows_to_restore,
    }
    report_path = report_dir / f"overseerr-library-request-restore-{timestamp}.json"
    report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")

    result: dict[str, Any] = {
        "report_path": str(report_path),
        "summary": report_payload["summary"],
    }

    if args.apply:
        live_backup = backup_live_db(args.nas_host, args.nas_user, args.nas_password, timestamp)
        restore_result = apply_restore(
            args.nas_host,
            args.nas_user,
            args.nas_password,
            media_rows=list(media_rows_to_restore_map.values()),
            request_rows=request_rows_to_restore,
            season_request_rows=season_request_rows_to_restore,
        )
        run_remote_shell(args.nas_host, args.nas_user, args.nas_password, "docker restart overseerr >/dev/null 2>&1 && echo restarted")
        result["live_backup_path"] = live_backup
        result["restore_result"] = restore_result

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

