#!/usr/bin/env python3
"""
Refresh the master Overseerr request list directly from live Overseerr state.

This produces a reusable master JSON/TXT export of unique requested media, which
downstream scripts can then filter against the live NAS/library/queue state.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys
from typing import Any

import requests


DEFAULT_ENV_PATH = pathlib.Path(__file__).resolve().parents[1] / ".env.synology.local"
DEFAULT_SETTINGS_PATH = pathlib.Path(
    r"\\synology.example.lan\docker\harbor\appdata\overseerr\config\settings.json"
)
DEFAULT_DB_PATH = pathlib.Path(
    r"\\synology.example.lan\docker\harbor\appdata\overseerr\config\db\db.sqlite3"
)
DEFAULT_OUTPUT_JSON = pathlib.Path.home() / "Desktop" / "Overseerr_ReRequest_Mega_List.json"
DEFAULT_OUTPUT_TXT = pathlib.Path.home() / "Desktop" / "Overseerr_ReRequest_Mega_List.txt"
DEFAULT_RADARR_URL = "http://localhost:7878/api/v3/movie"
DEFAULT_SONARR_URL = "http://localhost:8989/api/v3/series"
DEFAULT_OVERSEERR_URL = "http://localhost:5055"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh the master request list from live Overseerr.")
    parser.add_argument("--env-path", default=str(DEFAULT_ENV_PATH))
    parser.add_argument("--settings-path", default=str(DEFAULT_SETTINGS_PATH))
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-txt", default=str(DEFAULT_OUTPUT_TXT))
    parser.add_argument("--radarr-url", default=DEFAULT_RADARR_URL)
    parser.add_argument("--sonarr-url", default=DEFAULT_SONARR_URL)
    parser.add_argument("--overseerr-url", default=DEFAULT_OVERSEERR_URL)
    parser.add_argument("--radarr-api-key", default="")
    parser.add_argument("--sonarr-api-key", default="")
    return parser.parse_args()


def load_env(path: pathlib.Path) -> dict[str, str]:
    if not path.exists():
        return {}
    env_map: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env_map[key.strip()] = value.strip()
    return env_map


def load_settings(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_api_key(cli_value: str, env_map: dict[str, str], env_key: str, label: str) -> str:
    value = cli_value or env_map.get(env_key, "")
    if not value:
        raise SystemExit(f"{label} missing. Set {env_key} in .env.synology.local or pass it explicitly.")
    return value


def load_arr_maps(
    radarr_url: str,
    sonarr_url: str,
    radarr_api: str,
    sonarr_api: str,
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    rad = requests.get(radarr_url, headers={"X-Api-Key": radarr_api}, timeout=30)
    rad.raise_for_status()
    son = requests.get(sonarr_url, headers={"X-Api-Key": sonarr_api}, timeout=30)
    son.raise_for_status()

    rad_by_tmdb = {m.get("tmdbId"): m for m in rad.json() if m.get("tmdbId")}
    son_by_tvdb = {s.get("tvdbId"): s for s in son.json() if s.get("tvdbId")}
    son_by_tmdb = {s.get("tmdbId"): s for s in son.json() if s.get("tmdbId")}
    return rad_by_tmdb, son_by_tvdb, son_by_tmdb


def fetch_title_from_overseerr(overseerr_url: str, api_key: str, media_type: str, tmdb_id: int | None) -> str:
    if not tmdb_id:
        return ""
    path = "movie" if media_type == "movie" else "tv"
    response = requests.get(
        f"{overseerr_url}/api/v1/{path}/{tmdb_id}",
        headers={"X-Api-Key": api_key},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get("title") or payload.get("name") or payload.get("originalTitle") or payload.get("originalName") or ""


def load_latest_requests(db_path: pathlib.Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            mr.id AS request_id,
            mr.createdAt AS requested_at,
            mr.status AS request_status,
            mr.type AS request_type,
            mr.mediaId AS media_id,
            m.mediaType AS media_type,
            m.tmdbId AS tmdb_id,
            m.tvdbId AS tvdb_id,
            u.username AS requested_by,
            u.email AS requested_by_email
        FROM media_request mr
        LEFT JOIN media m ON mr.mediaId = m.id
        LEFT JOIN user u ON mr.requestedById = u.id
        ORDER BY mr.createdAt DESC, mr.id DESC
        """
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()

    latest: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        key = (
            row.get("request_type") or row.get("media_type"),
            row.get("tmdb_id"),
            row.get("tvdb_id"),
            row.get("media_id"),
        )
        if key in seen:
            continue
        seen.add(key)
        latest.append(row)
    return latest


def main() -> int:
    args = parse_args()
    env_map = load_env(pathlib.Path(args.env_path))
    settings = load_settings(pathlib.Path(args.settings_path))
    api_key = settings.get("main", {}).get("apiKey", "")
    if not api_key:
        raise SystemExit("No Overseerr API key found in settings.json")

    radarr_api = resolve_api_key(args.radarr_api_key, env_map, "RADARR_API_KEY", "Radarr API key")
    sonarr_api = resolve_api_key(args.sonarr_api_key, env_map, "SONARR_API_KEY", "Sonarr API key")
    rad_by_tmdb, son_by_tvdb, son_by_tmdb = load_arr_maps(
        args.radarr_url,
        args.sonarr_url,
        radarr_api,
        sonarr_api,
    )
    requests_rows = load_latest_requests(pathlib.Path(args.db_path))

    items: list[dict[str, Any]] = []
    txt_lines: list[str] = []
    for index, row in enumerate(requests_rows, start=1):
        media_type = row.get("request_type") or row.get("media_type") or ""
        tmdb_id = row.get("tmdb_id")
        tvdb_id = row.get("tvdb_id")

        title = ""
        if media_type == "movie" and tmdb_id in rad_by_tmdb:
            title = rad_by_tmdb[tmdb_id].get("title") or ""
        elif media_type == "tv":
            if tvdb_id in son_by_tvdb:
                title = son_by_tvdb[tvdb_id].get("title") or ""
            elif tmdb_id in son_by_tmdb:
                title = son_by_tmdb[tmdb_id].get("title") or ""
        if not title:
            title = fetch_title_from_overseerr(args.overseerr_url, api_key, media_type, tmdb_id)

        item = {
            "request_id": row.get("request_id"),
            "type": media_type,
            "title": title,
            "requested_at": row.get("requested_at"),
            "request_status": row.get("request_status"),
            "requested_by": row.get("requested_by") or row.get("requested_by_email") or "",
            "media_id": row.get("media_id"),
            "tmdb_id": tmdb_id,
            "tvdb_id": tvdb_id,
        }
        items.append(item)
        txt_lines.append(f"{index}: {title}")

    output_json = pathlib.Path(args.output_json)
    output_txt = pathlib.Path(args.output_txt)
    output_json.write_text(
        json.dumps(
            {
                "summary": {"total_unique_requested_items": len(items)},
                "items": items,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    output_txt.write_text("\r\n".join(txt_lines) + "\r\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "total_unique_requested_items": len(items),
                "output_json": str(output_json),
                "output_txt": str(output_txt),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
