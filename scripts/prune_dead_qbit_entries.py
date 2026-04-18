#!/usr/bin/env python3
"""
Remove obviously dead qBittorrent entries without deleting payload files.

This is intentionally strict. It only removes queue entries that are doing
literally nothing useful:
- zero progress
- zero seeds
- zero availability
- zero download speed
- and in a non-working state such as stopped/meta/error/missingFiles
"""

from __future__ import annotations

import json
import sys

import requests


QBIT_URL = "http://localhost:8081"
QBIT_USER = "admin"
QBIT_PASS = "adminadmin"
DEAD_STATES = {"stoppedDL", "metaDL", "missingFiles", "error"}


def is_dead(torrent: dict) -> bool:
    state = str(torrent.get("state") or "")
    progress = float(torrent.get("progress") or 0.0)
    seeds = int(torrent.get("num_seeds") or 0)
    availability = float(torrent.get("availability") or 0.0)
    dlspeed = int(torrent.get("dlspeed") or 0)
    return (
        state in DEAD_STATES
        and progress == 0.0
        and seeds == 0
        and availability == 0.0
        and dlspeed == 0
    )


def main() -> int:
    session = requests.Session()
    login = session.post(
        f"{QBIT_URL}/api/v2/auth/login",
        data={"username": QBIT_USER, "password": QBIT_PASS},
        timeout=30,
    )
    login.raise_for_status()

    torrents_resp = session.get(f"{QBIT_URL}/api/v2/torrents/info?filter=all", timeout=60)
    torrents_resp.raise_for_status()
    torrents = torrents_resp.json()

    dead = [torrent for torrent in torrents if is_dead(torrent)]
    hashes = [str(torrent.get("hash") or "") for torrent in dead if torrent.get("hash")]

    if hashes:
        delete = session.post(
            f"{QBIT_URL}/api/v2/torrents/delete",
            data={"hashes": "|".join(hashes), "deleteFiles": "false"},
            timeout=120,
        )
        delete.raise_for_status()

    print(
        json.dumps(
            {
                "removed_dead_count": len(hashes),
                "removed_titles": [torrent.get("name") or "" for torrent in dead],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
