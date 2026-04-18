#!/usr/bin/env python3
"""
Build a deduplicated master recovery list from the older desktop list plus the
current unhealthy qB backlog report.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import OrderedDict


DEFAULT_OLD_LIST = pathlib.Path.home() / "Desktop" / "Harbor_Dead_And_Rerequest_List.txt"
DEFAULT_HEALTH_JSON = pathlib.Path(r"D:\harbor-media-server\reports\download-health\qbit-download-health.json")
DEFAULT_OUTPUT_TXT = pathlib.Path.home() / "Desktop" / "Harbor_Master_Recovery_List.txt"
DEFAULT_OUTPUT_JSON = pathlib.Path(r"D:\harbor-media-server\reports\overseerr-request-tool\Harbor_Master_Recovery_List.json")
DEFAULT_IGNORE_PATTERNS = (r"\bnaruto\b", r"\bone piece\b")
UNHEALTHY_CLASSIFICATIONS = {"dead", "weak", "watch"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a deduplicated master recovery list.")
    parser.add_argument("--old-list", default=str(DEFAULT_OLD_LIST))
    parser.add_argument("--health-json", default=str(DEFAULT_HEALTH_JSON))
    parser.add_argument("--output-txt", default=str(DEFAULT_OUTPUT_TXT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    return parser.parse_args()


def strip_numbering(line: str) -> str:
    return re.sub(r"^\s*\d+\s*:\s*", "", line or "").strip()


def dedupe_key(title: str) -> str:
    text = strip_numbering(title).casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def should_ignore(title: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(pattern.search(title) for pattern in patterns)


def load_old_titles(path: pathlib.Path) -> list[str]:
    if not path.exists():
        return []
    return [strip_numbering(line) for line in path.read_text(encoding="utf-8").splitlines() if strip_numbering(line)]


def load_unhealthy_torrents(path: pathlib.Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    titles: list[str] = []
    for row in payload.get("torrents", []):
        if row.get("classification") in UNHEALTHY_CLASSIFICATIONS:
            name = str(row.get("name") or "").strip()
            if name:
                titles.append(name)
    return titles


def main() -> int:
    args = parse_args()
    old_list_path = pathlib.Path(args.old_list)
    health_json_path = pathlib.Path(args.health_json)
    output_txt_path = pathlib.Path(args.output_txt)
    output_json_path = pathlib.Path(args.output_json)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)

    ignore_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in DEFAULT_IGNORE_PATTERNS]

    combined = load_old_titles(old_list_path) + load_unhealthy_torrents(health_json_path)
    kept: "OrderedDict[str, str]" = OrderedDict()
    ignored: list[str] = []
    duplicates = 0

    for raw_title in combined:
        title = strip_numbering(raw_title)
        if not title:
            continue
        if should_ignore(title, ignore_patterns):
            ignored.append(title)
            continue
        key = dedupe_key(title)
        if not key:
            continue
        if key in kept:
            duplicates += 1
            continue
        kept[key] = title

    titles = list(kept.values())
    output_txt_path.write_text(
        "\n".join(f"{index}: {title}" for index, title in enumerate(titles, 1)) + "\n",
        encoding="utf-8",
    )
    output_json_path.write_text(
        json.dumps(
            {
                "summary": {
                    "total_items": len(titles),
                    "source_old_list_count": len(load_old_titles(old_list_path)),
                    "source_unhealthy_qbit_count": len(load_unhealthy_torrents(health_json_path)),
                    "duplicates_removed": duplicates,
                    "ignored_manual_handling_count": len(ignored),
                    "ignored_patterns": list(DEFAULT_IGNORE_PATTERNS),
                },
                "items": titles,
                "ignored_titles": ignored,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "total_items": len(titles),
                "output_txt": str(output_txt_path),
                "output_json": str(output_json_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
