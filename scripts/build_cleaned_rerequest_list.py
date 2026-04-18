#!/usr/bin/env python3
"""
Build a cleaned re-request list from the master Overseerr attention list.

This script removes titles that are already in the library or already in a
healthy/active queue path, leaving only items that still need manual re-request.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict
from typing import Any

import requests


DEFAULT_MASTER_JSON = pathlib.Path.home() / "Desktop" / "Overseerr_ReRequest_Mega_List.json"
DEFAULT_OUTPUT_JSON = pathlib.Path.home() / "Desktop" / "Overseerr_ReRequest_Final_Cleaned.json"
DEFAULT_OUTPUT_TXT = pathlib.Path.home() / "Desktop" / "Overseerr_ReRequest_Final_Cleaned.txt"
DEFAULT_ENV_PATH = pathlib.Path(__file__).resolve().parents[1] / ".env.synology.local"

QBIT_URL = "http://localhost:8081"
RADARR_URL = "http://localhost:7878/api/v3/movie"
SONARR_URL = "http://localhost:8989/api/v3/series"
DEFAULT_IGNORE_PATTERNS = (r"\bnaruto\b", r"\bone piece\b")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a cleaned re-request list from the master list.")
    parser.add_argument("--master-json", default=str(DEFAULT_MASTER_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-txt", default=str(DEFAULT_OUTPUT_TXT))
    parser.add_argument("--env-path", default=str(DEFAULT_ENV_PATH))
    parser.add_argument(
        "--ignore-pattern",
        action="append",
        default=[],
        help="Case-insensitive regex for titles to leave out of the re-request list. May be used more than once.",
    )
    return parser.parse_args()


def norm(value: str) -> str:
    value = (value or "").casefold().strip()
    value = re.sub(r'^\s*"|"\s*$', "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def load_master(path: pathlib.Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["items"] if isinstance(payload, dict) and "items" in payload else payload


def load_env(path: pathlib.Path) -> dict[str, str]:
    env_map: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env_map[key.strip()] = value.strip()
    return env_map


def build_current_state(
    qbit_user: str,
    qbit_pass: str,
    radarr_api: str,
    sonarr_api: str,
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    session = requests.Session()
    login = session.post(
        f"{QBIT_URL}/api/v2/auth/login",
        data={"username": qbit_user, "password": qbit_pass},
        timeout=20,
    )
    login.raise_for_status()
    torrents = session.get(f"{QBIT_URL}/api/v2/torrents/info?filter=all", timeout=30)
    torrents.raise_for_status()

    rad = requests.get(RADARR_URL, headers={"X-Api-Key": radarr_api}, timeout=30)
    rad.raise_for_status()
    son = requests.get(SONARR_URL, headers={"X-Api-Key": sonarr_api}, timeout=30)
    son.raise_for_status()

    rad_by_tmdb = {m.get("tmdbId"): m for m in rad.json() if m.get("tmdbId")}
    son_by_tvdb = {s.get("tvdbId"): s for s in son.json() if s.get("tvdbId")}
    return torrents.json(), rad_by_tmdb, son_by_tvdb


def build_healthy_qbit_names(torrents: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
    healthy: list[tuple[dict[str, Any], str]] = []
    for torrent in torrents:
        state = torrent.get("state") or ""
        progress = float(torrent.get("progress") or 0.0)
        seeds = int(torrent.get("num_seeds") or 0)
        availability = float(torrent.get("availability") or 0.0)
        has_metadata = bool(torrent.get("has_metadata"))

        is_healthy = False
        if state in {"downloading", "forcedDL"}:
            is_healthy = True
        elif state == "queuedDL" and has_metadata:
            is_healthy = True
        elif state in {"stalledDL", "metaDL"} and (seeds > 0 or availability >= 1.0):
            is_healthy = True
        elif state == "stoppedUP":
            is_healthy = True

        if is_healthy:
            healthy.append((torrent, norm(torrent.get("name") or "")))
    return healthy


def parse_requested_at(value: Any) -> tuple[str, int]:
    text = str(value or "")
    return (text, len(text))


def should_ignore_title(title: str, patterns: list[re.Pattern[str]]) -> bool:
    text = title or ""
    return any(pattern.search(text) for pattern in patterns)


def suppress_later_conflicting_requests(results: list[dict[str, Any]], summary: Counter[str]) -> None:
    by_title: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        media_type = str(row.get("type") or "")
        title_key = norm(str(row.get("title") or ""))
        if not media_type or not title_key:
            continue
        by_title[(media_type, title_key)].append(row)

    for _, rows in by_title.items():
        distinct_ids = {
            row.get("tmdb_id") or row.get("tvdb_id") or row.get("media_id")
            for row in rows
            if row.get("tmdb_id") or row.get("tvdb_id") or row.get("media_id")
        }
        if len(distinct_ids) <= 1:
            continue

        canonical = sorted(
            rows,
            key=lambda row: (
                parse_requested_at(row.get("requested_at")),
                int(row.get("request_id") or 0),
            ),
        )[0]

        for row in rows:
            if row is canonical:
                row["conflict_resolution"] = "kept-earliest-request"
                continue
            prior_category = str(row.get("category") or "re-request")
            if prior_category != "re-request":
                row["conflict_resolution"] = "non-rerequest-conflict"
                continue
            row["category"] = "suppressed-conflicting-duplicate"
            row["conflict_resolution"] = "later-same-title-different-id"
            row["canonical_request_id"] = canonical.get("request_id")
            row["canonical_tmdb_id"] = canonical.get("tmdb_id")
            row["canonical_title"] = canonical.get("title")
            summary[prior_category] -= 1
            summary["suppressed-conflicting-duplicate"] += 1


def main() -> int:
    args = parse_args()
    master_path = pathlib.Path(args.master_json)
    output_json = pathlib.Path(args.output_json)
    output_txt = pathlib.Path(args.output_txt)
    env_path = pathlib.Path(args.env_path)

    items = load_master(master_path)
    env_map = load_env(env_path)
    ignore_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in (list(DEFAULT_IGNORE_PATTERNS) + list(args.ignore_pattern))]
    torrents, rad_by_tmdb, son_by_tvdb = build_current_state(
        qbit_user=env_map["QBIT_USER"],
        qbit_pass=env_map["QBIT_PASS"],
        radarr_api=env_map["RADARR_API_KEY"],
        sonarr_api=env_map["SONARR_API_KEY"],
    )
    healthy_qbit = build_healthy_qbit_names(torrents)

    results: list[dict[str, Any]] = []
    summary: Counter[str] = Counter()

    for item in items:
        title = item.get("title") or ""
        media_type = item.get("type")
        ntitle = norm(title)
        category = "re-request"
        result: dict[str, Any] = dict(item)
        result["title"] = title
        result["type"] = media_type

        if should_ignore_title(title, ignore_patterns):
            category = "ignored-manual-handling"

        if media_type == "movie":
            movie = rad_by_tmdb.get(item.get("tmdb_id"))
            if category == "re-request" and movie and movie.get("hasFile"):
                category = "already-in-library"
                result["path"] = movie.get("path") or ""
            elif category == "re-request":
                for torrent, nname in healthy_qbit:
                    if ntitle and (ntitle in nname or nname in ntitle):
                        category = "already-queued-healthy"
                        result["qbit_name"] = torrent.get("name") or ""
                        result["state"] = torrent.get("state") or ""
                        break
        elif media_type == "tv":
            series = son_by_tvdb.get(item.get("tvdb_id"))
            if category == "re-request" and series:
                stats = series.get("statistics") or {}
                if (stats.get("episodeFileCount") or 0) > 0 and (
                    stats.get("episodeCount") or 0
                ) >= (stats.get("totalEpisodeCount") or 0):
                    category = "already-in-library"
                    result["path"] = series.get("path") or ""
            if category == "re-request":
                for torrent, nname in healthy_qbit:
                    if ntitle and (ntitle in nname or nname in ntitle):
                        category = "already-queued-healthy"
                        result["qbit_name"] = torrent.get("name") or ""
                        result["state"] = torrent.get("state") or ""
                        break

        result["category"] = category
        results.append(result)
        summary[category] += 1

    suppress_later_conflicting_requests(results, summary)

    final_titles = [row["title"] for row in results if row["category"] == "re-request"]
    output_json.write_text(
        json.dumps(
            {
                "summary": dict(summary),
                "re_request_count": len(final_titles),
                "items": results,
                "re_request_titles": final_titles,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    output_txt.write_text(
        "\n".join(f"{i}: {title}" for i, title in enumerate(final_titles, 1)) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "summary": dict(summary),
                "re_request_count": len(final_titles),
                "output_json": str(output_json),
                "output_txt": str(output_txt),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
