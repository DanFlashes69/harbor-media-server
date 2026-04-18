#!/usr/bin/env python3
"""
Prepare a bulk Overseerr review pack from a plain-text title list.

This script does not submit requests. It:
- reads a list of titles from a text/markdown file, or a structured JSON list
- searches Overseerr for each title
- preserves exact Overseerr/TMDb identity when the input already has it
- picks likely matches with a simple confidence score
- writes CSV/JSON/Markdown outputs plus a URL list you can open manually

It is designed to speed up large manual re-request passes without automating the
actual request submission.
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

import requests


DEFAULT_SETTINGS_PATH = pathlib.Path(
    r"\\synology.example.lan\docker\harbor\appdata\overseerr\config\settings.json"
)
DEFAULT_BASE_URL = "http://localhost:5055"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search Overseerr for a bulk list of titles and prepare a manual review pack."
    )
    parser.add_argument(
        "input_path",
        help="Path to a text/markdown file containing one title per line, or a JSON file with structured request items.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Overseerr base URL. Default: {DEFAULT_BASE_URL}",
    )
    parser.add_argument(
        "--settings-path",
        default=str(DEFAULT_SETTINGS_PATH),
        help=f"Path to Overseerr settings.json. Default: {DEFAULT_SETTINGS_PATH}",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="Overseerr API key. If omitted, it is read from settings.json.",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Directory for generated files. Defaults to the input file directory.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of candidate matches to keep per title. Default: 5",
    )
    parser.add_argument(
        "--sleep-ms",
        type=int,
        default=125,
        help="Delay between search calls in milliseconds. Default: 125",
    )
    return parser.parse_args()


def normalize_title(value: str) -> str:
    value = value.casefold()
    value = re.sub(r"^\s*\d+\s*[:.)-]\s*", "", value)
    value = re.sub(r"[\[\]{}()\"'`]", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_input_titles(path: pathlib.Path) -> list[str]:
    titles: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        line = re.sub(r"^\s*[-*]\s*", "", line)
        line = re.sub(r"^\s*\d+\s*[:.)-]\s*", "", line)
        title = line.strip()
        if title:
            titles.append(title)
    deduped: list[str] = []
    seen: set[str] = set()
    for title in titles:
        key = normalize_title(title)
        if key not in seen:
            seen.add(key)
            deduped.append(title)
    return deduped


def load_input_items(path: pathlib.Path) -> list[dict[str, Any]]:
    if path.suffix.casefold() != ".json":
        return [{"input_title": title} for title in parse_input_titles(path)]

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        if "items" in payload and isinstance(payload["items"], list):
            source_items = payload["items"]
        elif "re_request_titles" in payload and isinstance(payload["re_request_titles"], list):
            source_items = [{"title": title} for title in payload["re_request_titles"]]
        else:
            raise RuntimeError(f"Unsupported JSON input structure: {path}")
    elif isinstance(payload, list):
        source_items = payload
    else:
        raise RuntimeError(f"Unsupported JSON input structure: {path}")

    items: list[dict[str, Any]] = []
    for raw in source_items:
        if isinstance(raw, str):
            items.append({"input_title": raw})
            continue
        if not isinstance(raw, dict):
            continue
        if raw.get("category") not in (None, "re-request"):
            continue
        title = raw.get("input_title") or raw.get("title") or ""
        item = dict(raw)
        item["input_title"] = title
        items.append(item)
    return items


def load_api_key(settings_path: pathlib.Path) -> str:
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    api_key = settings.get("main", {}).get("apiKey", "")
    if not api_key:
        raise RuntimeError(f"No Overseerr API key found in {settings_path}")
    return api_key


def extract_year(raw_title: str) -> int | None:
    match = re.search(r"\b(19|20)\d{2}\b", raw_title)
    return int(match.group(0)) if match else None


@dataclass
class Candidate:
    media_type: str
    title: str
    original_title: str
    year: str
    media_id: int
    score: int
    confidence: str
    popularity: float
    available: bool
    service_url: str
    detail_url: str
    request_url: str
    reason: str
    raw: dict[str, Any]


def build_candidate(base_url: str, query_title: str, result: dict[str, Any]) -> Candidate:
    media_type = result.get("mediaType", "")
    title = result.get("title") or result.get("name") or ""
    original_title = result.get("originalTitle") or result.get("originalName") or ""
    release_date = result.get("releaseDate") or result.get("firstAirDate") or ""
    year = release_date[:4] if release_date else ""
    media_id = int(result.get("id"))
    popularity = float(result.get("popularity") or 0.0)
    media_info = result.get("mediaInfo") or {}
    available = bool(media_info.get("status") == 3 or media_info.get("status4k") == 3)

    detail_url = f"{base_url.rstrip('/')}/{media_type}/{media_id}"
    request_url = detail_url
    service_url = media_info.get("serviceUrl") or ""

    query_norm = normalize_title(query_title)
    title_norm = normalize_title(title)
    original_norm = normalize_title(original_title)
    query_year = extract_year(query_title)
    candidate_year = int(year) if year.isdigit() else None

    score = 0
    reasons: list[str] = []

    if title_norm == query_norm:
        score += 100
        reasons.append("exact-title")
    elif original_norm and original_norm == query_norm:
        score += 95
        reasons.append("exact-original-title")
    elif query_norm and title_norm.startswith(query_norm):
        score += 80
        reasons.append("prefix-title")
    elif query_norm and query_norm in title_norm:
        score += 70
        reasons.append("contains-title")
    elif query_norm and original_norm and query_norm in original_norm:
        score += 65
        reasons.append("contains-original-title")

    if query_year and candidate_year:
        if query_year == candidate_year:
            score += 20
            reasons.append("year-match")
        else:
            score -= min(15, abs(query_year - candidate_year))
            reasons.append("year-mismatch")

    if media_type in {"movie", "tv"}:
        score += 5

    if popularity > 0:
        score += min(10, int(popularity // 10))

    if available:
        score -= 5
        reasons.append("already-available")

    if score >= 110:
        confidence = "high"
    elif score >= 80:
        confidence = "medium"
    else:
        confidence = "low"

    return Candidate(
        media_type=media_type,
        title=title,
        original_title=original_title,
        year=year,
        media_id=media_id,
        score=score,
        confidence=confidence,
        popularity=popularity,
        available=available,
        service_url=service_url,
        detail_url=detail_url,
        request_url=request_url,
        reason=",".join(reasons),
        raw=result,
    )


def build_exact_candidate(base_url: str, media_type: str, media_id: int, payload: dict[str, Any]) -> Candidate:
    title = payload.get("title") or payload.get("name") or payload.get("originalTitle") or payload.get("originalName") or ""
    original_title = payload.get("originalTitle") or payload.get("originalName") or ""
    release_date = payload.get("releaseDate") or payload.get("firstAirDate") or ""
    year = release_date[:4] if release_date else ""
    media_info = payload.get("mediaInfo") or {}
    available = bool(media_info.get("status") == 3 or media_info.get("status4k") == 3)
    detail_url = f"{base_url.rstrip('/')}/{media_type}/{media_id}"
    return Candidate(
        media_type=media_type,
        title=title,
        original_title=original_title,
        year=year,
        media_id=media_id,
        score=999,
        confidence="high",
        popularity=float(payload.get("popularity") or 0.0),
        available=available,
        service_url=media_info.get("serviceUrl") or "",
        detail_url=detail_url,
        request_url=detail_url,
        reason="exact-id",
        raw=payload,
    )


def fetch_exact_candidate(
    session: requests.Session,
    base_url: str,
    media_type: str,
    media_id: int | None,
) -> Candidate | None:
    if media_type not in {"movie", "tv"} or not media_id:
        return None
    url = f"{base_url.rstrip('/')}/api/v1/{media_type}/{media_id}"
    response = session.get(url, timeout=30)
    response.raise_for_status()
    payload = response.json()
    return build_exact_candidate(base_url, media_type, media_id, payload)


def search_overseerr(
    session: requests.Session,
    base_url: str,
    title: str,
    limit: int,
) -> list[Candidate]:
    encoded_query = urllib.parse.quote(title, safe="")
    url = f"{base_url.rstrip('/')}/api/v1/search?query={encoded_query}"
    response = session.get(url, timeout=30)
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results", [])
    candidates = [
        build_candidate(base_url, title, result)
        for result in results
        if result.get("mediaType") in {"movie", "tv"}
    ]
    candidates.sort(
        key=lambda c: (
            -c.score,
            c.available,
            -c.popularity,
            c.title.casefold(),
        )
    )
    return candidates[:limit]


def main() -> int:
    args = parse_args()
    input_path = pathlib.Path(args.input_path)
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    output_dir = pathlib.Path(args.output_dir) if args.output_dir else input_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    api_key = args.api_key or load_api_key(pathlib.Path(args.settings_path))
    input_items = load_input_items(input_path)

    session = requests.Session()
    session.headers.update({"X-Api-Key": api_key})

    results: list[dict[str, Any]] = []
    for index, item in enumerate(input_items, start=1):
        title = str(item.get("input_title") or "")
        exact_media_type = str(item.get("type") or item.get("media_type") or "")
        exact_tmdb_id = item.get("tmdb_id")
        candidates: list[Candidate]
        exact_candidate = None
        if exact_media_type in {"movie", "tv"} and exact_tmdb_id:
            exact_candidate = fetch_exact_candidate(
                session,
                args.base_url,
                exact_media_type,
                int(exact_tmdb_id),
            )
        if exact_candidate:
            candidates = [exact_candidate]
        else:
            candidates = search_overseerr(session, args.base_url, title, args.limit)
        best = candidates[0] if candidates else None
        result_row = {
            "line_number": index,
            "input_title": title,
            "input_type": exact_media_type,
            "input_tmdb_id": exact_tmdb_id,
            "input_tvdb_id": item.get("tvdb_id"),
            "request_id": item.get("request_id"),
            "match_count": len(candidates),
            "best_match_confidence": best.confidence if best else "none",
            "best_match_type": best.media_type if best else "",
            "best_match_title": best.title if best else "",
            "best_match_year": best.year if best else "",
            "best_match_id": best.media_id if best else "",
            "best_match_available": best.available if best else "",
            "best_match_score": best.score if best else "",
            "best_match_reason": best.reason if best else "no-match",
            "best_match_url": best.request_url if best else "",
            "candidates": [
                {
                    "media_type": c.media_type,
                    "title": c.title,
                    "original_title": c.original_title,
                    "year": c.year,
                    "media_id": c.media_id,
                    "score": c.score,
                    "confidence": c.confidence,
                    "available": c.available,
                    "reason": c.reason,
                    "detail_url": c.detail_url,
                    "request_url": c.request_url,
                    "service_url": c.service_url,
                }
                for c in candidates
            ],
        }
        results.append(result_row)
        time.sleep(max(args.sleep_ms, 0) / 1000.0)

    stem = input_path.stem
    json_path = output_dir / f"{stem}_overseerr_review.json"
    csv_path = output_dir / f"{stem}_overseerr_review.csv"
    md_path = output_dir / f"{stem}_overseerr_review.md"
    urls_path = output_dir / f"{stem}_overseerr_review_urls.txt"

    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "line_number",
                "input_title",
                "match_count",
                "best_match_confidence",
                "best_match_type",
                "best_match_title",
                "best_match_year",
                "best_match_id",
                "best_match_available",
                "best_match_score",
                "best_match_reason",
                "best_match_url",
            ],
        )
        writer.writeheader()
        for row in results:
            writer.writerow({k: row[k] for k in writer.fieldnames})

    md_lines = [
        "# Overseerr Bulk Review",
        "",
        f"Input file: `{input_path}`",
        f"Titles processed: `{len(results)}`",
        "",
    ]
    urls: list[str] = []
    for row in results:
        md_lines.append(
            f"- {row['line_number']}: {row['input_title']} | "
            f"best={row['best_match_title'] or 'NO MATCH'} | "
            f"type={row['best_match_type'] or 'n/a'} | "
            f"confidence={row['best_match_confidence']} | "
            f"url={row['best_match_url'] or 'n/a'}"
        )
        if row["best_match_url"]:
            urls.append(row["best_match_url"])
    md_lines.append("")
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    urls_path.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")

    print(json.dumps(
        {
            "titles_processed": len(results),
            "output_files": {
                "json": str(json_path),
                "csv": str(csv_path),
                "markdown": str(md_path),
                "urls": str(urls_path),
            },
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())

