#!/usr/bin/env python3
"""
Assess qBittorrent queue health using multiple live signals.

This tool is intentionally read-only. It does not pause, resume, delete, or
otherwise control torrents. It classifies items into practical buckets so a
human or a separate neutral monitor can reason about queue quality without
depending on one brittle rule like "seeders >= 5".
"""

from __future__ import annotations

import argparse
import json
import pathlib
import time
from collections import Counter
from typing import Any

import requests


QBIT_URL = "http://localhost:8081"
QBIT_USER = "admin"
QBIT_PASS = "adminadmin"
DEFAULT_OUTPUT_DIR = pathlib.Path(r"D:\harbor-media-server\reports\download-health")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assess live qBittorrent queue health.")
    parser.add_argument("--qbit-url", default=QBIT_URL)
    parser.add_argument("--username", default=QBIT_USER)
    parser.add_argument("--password", default=QBIT_PASS)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--new-grace-minutes", type=int, default=15)
    parser.add_argument("--stalled-grace-minutes", type=int, default=30)
    parser.add_argument("--recent-activity-minutes", type=int, default=20)
    parser.add_argument("--slow-speed-kib", type=int, default=128)
    parser.add_argument("--usable-availability", type=float, default=1.0)
    parser.add_argument("--low-availability", type=float, default=0.25)
    parser.add_argument("--high-progress", type=float, default=0.80)
    return parser.parse_args()


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def normalize_torrent_row(torrent: dict[str, Any], now_ts: int) -> dict[str, Any]:
    added_on = int(torrent.get("added_on") or 0)
    last_activity = int(torrent.get("last_activity") or 0)
    progress = float(torrent.get("progress") or 0.0)
    availability = float(torrent.get("availability") or 0.0)
    seeds = int(torrent.get("num_seeds") or 0)
    peers = int(torrent.get("num_leechs") or 0)
    dlspeed = int(torrent.get("dlspeed") or 0)
    has_metadata = bool(torrent.get("has_metadata"))
    state = str(torrent.get("state") or "")

    age_minutes = max((now_ts - added_on) / 60.0, 0.0) if added_on else 0.0
    if last_activity > 0:
        idle_minutes = max((now_ts - last_activity) / 60.0, 0.0)
    else:
        idle_minutes = age_minutes

    return {
        "hash": torrent.get("hash") or "",
        "name": torrent.get("name") or "",
        "state": state,
        "progress": progress,
        "availability": availability,
        "seeders": seeds,
        "peers": peers,
        "download_speed_bps": dlspeed,
        "download_speed_mbps": round(dlspeed / 1024 / 1024, 2),
        "has_metadata": has_metadata,
        "added_on": added_on,
        "last_activity": last_activity,
        "age_minutes": round(age_minutes, 1),
        "idle_minutes": round(idle_minutes, 1),
        "category": torrent.get("category") or "",
        "save_path": torrent.get("save_path") or "",
    }


def classify_torrent(row: dict[str, Any], args: argparse.Namespace) -> tuple[str, int, list[str]]:
    state = row["state"]
    progress = row["progress"]
    availability = row["availability"]
    seeds = row["seeders"]
    peers = row["peers"]
    dlspeed = row["download_speed_bps"]
    has_metadata = row["has_metadata"]
    age_minutes = row["age_minutes"]
    idle_minutes = row["idle_minutes"]

    reasons: list[str] = []
    score = 0

    if state in {"uploading", "stoppedUP", "forcedUP", "queuedUP"}:
        return ("completed", 100, ["already-complete"])

    if state in {"downloading", "forcedDL"}:
        score += 3
        reasons.append("active-download-state")
    elif state == "queuedDL":
        score += 2
        reasons.append("queued-for-download")
    elif state in {"stalledDL", "metaDL"}:
        score += 0
        reasons.append("stalled-or-metadata")
    elif state in {"stoppedDL", "missingFiles", "error"}:
        score -= 2
        reasons.append("non-working-state")

    if has_metadata:
        score += 2
        reasons.append("metadata-present")
    else:
        score -= 1
        reasons.append("metadata-missing")

    if availability >= args.usable_availability:
        score += 3
        reasons.append("good-availability")
    elif availability >= args.low_availability:
        score += 1
        reasons.append("some-availability")
    elif availability == 0:
        score -= 2
        reasons.append("no-availability")

    if seeds >= 5:
        score += 2
        reasons.append("strong-seed-count")
    elif seeds >= 1:
        score += 1
        reasons.append("some-seeds")
    else:
        score -= 1
        reasons.append("no-seeds")

    if peers >= 5:
        score += 1
        reasons.append("healthy-peer-count")
    elif peers >= 1:
        reasons.append("some-peers")

    if dlspeed >= args.slow_speed_kib * 1024:
        score += 2
        reasons.append("moving-at-useful-speed")
    elif dlspeed > 0:
        score += 1
        reasons.append("moving-slowly")

    if progress >= args.high_progress:
        score += 2
        reasons.append("high-progress")
    elif progress >= 0.20:
        score += 1
        reasons.append("partial-progress")

    if idle_minutes <= args.recent_activity_minutes:
        score += 1
        reasons.append("recent-activity")
    else:
        score -= 1
        reasons.append("no-recent-activity")

    if progress == 0 and age_minutes <= args.new_grace_minutes:
        return ("settling", score, reasons + ["within-new-item-grace"])

    if (
        progress == 0
        and availability == 0
        and seeds == 0
        and dlspeed == 0
        and age_minutes > args.new_grace_minutes
        and state in {"stoppedDL", "metaDL", "missingFiles", "error"}
    ):
        return ("dead", score, reasons + ["zero-signal-past-grace"])

    if (
        progress > 0
        and progress < args.high_progress
        and dlspeed == 0
        and availability == 0
        and seeds == 0
        and idle_minutes > args.stalled_grace_minutes
        and state in {"stalledDL", "metaDL", "stoppedDL"}
    ):
        return ("weak", score, reasons + ["stalled-low-progress-no-signal"])

    if (
        progress >= args.high_progress
        and dlspeed == 0
        and idle_minutes <= args.stalled_grace_minutes
    ):
        return ("watch", score, reasons + ["near-finish-stall"])

    if score >= 8:
        return ("healthy", score, reasons)
    if score >= 5:
        return ("usable", score, reasons)
    if score >= 2:
        return ("watch", score, reasons)
    return ("weak", score, reasons)


def build_markdown(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# qB Download Health",
        "",
        f"- Generated: `{summary['generated_at']}`",
        f"- Total torrents: `{summary['total_torrents']}`",
        f"- Total active download speed: `{summary['total_download_mbps']} MB/s`",
        "",
        "## Summary",
        "",
    ]
    for key, value in summary["counts"].items():
        lines.append(f"- {key}: `{value}`")

    lines.extend(["", "## Attention", ""])
    attention = [row for row in rows if row["classification"] in {"dead", "weak", "watch"}]
    if not attention:
        lines.append("- none")
    else:
        for row in attention[:50]:
            lines.append(
                f"- {row['classification']}: {row['name']} | "
                f"state={row['state']} | "
                f"progress={round(row['progress'] * 100, 2)}% | "
                f"availability={row['availability']} | "
                f"seeders={row['seeders']} | "
                f"speed={row['download_speed_mbps']} MB/s | "
                f"reasons={', '.join(row['reasons'])}"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    login = session.post(
        f"{args.qbit_url}/api/v2/auth/login",
        data={"username": args.username, "password": args.password},
        timeout=30,
    )
    login.raise_for_status()

    torrents_resp = session.get(f"{args.qbit_url}/api/v2/torrents/info?filter=all", timeout=60)
    torrents_resp.raise_for_status()
    torrents = torrents_resp.json()

    now_ts = int(time.time())
    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    total_download_bps = 0

    for torrent in torrents:
        row = normalize_torrent_row(torrent, now_ts)
        classification, score, reasons = classify_torrent(row, args)
        row["classification"] = classification
        row["score"] = score
        row["reasons"] = reasons
        counts[classification] += 1
        total_download_bps += row["download_speed_bps"]
        rows.append(row)

    rows.sort(
        key=lambda row: (
            {"dead": 0, "weak": 1, "watch": 2, "settling": 3, "usable": 4, "healthy": 5, "completed": 6}.get(
                row["classification"], 99
            ),
            row["score"],
            row["name"].casefold(),
        )
    )

    summary = {
        "generated_at": iso_now(),
        "total_torrents": len(rows),
        "total_download_mbps": round(total_download_bps / 1024 / 1024, 2),
        "counts": dict(counts),
    }

    json_path = output_dir / "qbit-download-health.json"
    md_path = output_dir / "qbit-download-health.md"
    json_path.write_text(json.dumps({"summary": summary, "torrents": rows}, indent=2), encoding="utf-8")
    md_path.write_text(build_markdown(summary, rows), encoding="utf-8")

    print(json.dumps({"summary": summary, "json": str(json_path), "markdown": str(md_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
