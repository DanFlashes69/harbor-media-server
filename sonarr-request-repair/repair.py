import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


SONARR_URL = os.environ.get("SONARR_URL", "http://sonarr:8989").rstrip("/")
SONARR_API_KEY = os.environ.get("SONARR_API_KEY", "").strip()
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "180"))
REFRESH_TTL_SECONDS = int(os.environ.get("REFRESH_TTL_SECONDS", "1800"))
SEARCH_TTL_SECONDS = int(os.environ.get("SEARCH_TTL_SECONDS", "21600"))
STATE_PATH = Path(os.environ.get("STATE_PATH", "/state/state.json"))
HEARTBEAT_PATH = Path(os.environ.get("HEARTBEAT_PATH", "/tmp/heartbeat"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except Exception:
        return None


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"refresh": {}, "search": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"refresh": {}, "search": {}}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def write_heartbeat() -> None:
    HEARTBEAT_PATH.write_text(utc_now().isoformat(), encoding="utf-8")


class SonarrClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({"X-Api-Key": api_key})

    def get(self, path: str, **params):
        response = self.session.get(f"{self.base_url}{path}", params=params, timeout=60)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, payload: dict):
        response = self.session.post(f"{self.base_url}{path}", json=payload, timeout=60)
        response.raise_for_status()
        return response.json()

    def put(self, path: str, payload: dict):
        response = self.session.put(f"{self.base_url}{path}", json=payload, timeout=60)
        response.raise_for_status()
        return response.json()


def chunked(values: list[int], size: int):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def refresh_series_if_needed(client: SonarrClient, state: dict, series: dict) -> bool:
    total_episode_count = ((series.get("statistics") or {}).get("totalEpisodeCount")) or 0
    monitored_seasons = [
        season
        for season in (series.get("seasons") or [])
        if int(season.get("seasonNumber", 0)) > 0 and season.get("monitored")
    ]
    if total_episode_count > 0 or not monitored_seasons:
        return False

    key = str(series["id"])
    last_refresh = parse_dt(state.get("refresh", {}).get(key))
    if last_refresh and (utc_now() - last_refresh).total_seconds() < REFRESH_TTL_SECONDS:
        return False

    client.post("/api/v3/command", {"name": "RefreshSeries", "seriesId": int(series["id"])})
    state.setdefault("refresh", {})[key] = utc_now().isoformat()
    print(f"[refresh] queued RefreshSeries for {series['title']}")
    return True


def repair_series(client: SonarrClient, state: dict, series: dict) -> None:
    season_map = {
        int(season.get("seasonNumber", 0)): bool(season.get("monitored"))
        for season in (series.get("seasons") or [])
    }
    monitored_seasons = [season_number for season_number, monitored in season_map.items() if season_number > 0 and monitored]
    if not monitored_seasons:
        return

    episodes = client.get("/api/v3/episode", seriesId=int(series["id"]))
    repair_ids: list[int] = []
    repaired_seasons: set[int] = set()
    for episode in episodes:
        season_number = int(episode.get("seasonNumber", 0))
        if season_number <= 0:
            continue
        if not season_map.get(season_number):
            continue
        if episode.get("hasFile"):
            continue
        if episode.get("monitored"):
            continue
        repair_ids.append(int(episode["id"]))
        repaired_seasons.add(season_number)

    if repair_ids:
        for batch in chunked(repair_ids, 500):
            client.put("/api/v3/episode/monitor", {"episodeIds": batch, "monitored": True})
        print(f"[repair] {series['title']}: monitored {len(repair_ids)} missing episodes")

    if not repaired_seasons:
        return

    for season_number in sorted(repaired_seasons):
        search_key = f"{series['id']}:{season_number}"
        last_search = parse_dt(state.get("search", {}).get(search_key))
        if last_search and (utc_now() - last_search).total_seconds() < SEARCH_TTL_SECONDS:
            continue
        client.post(
            "/api/v3/command",
            {
                "name": "SeasonSearch",
                "seriesId": int(series["id"]),
                "seasonNumber": int(season_number),
            },
        )
        state.setdefault("search", {})[search_key] = utc_now().isoformat()
        print(f"[search] queued SeasonSearch for {series['title']} season {season_number}")


def main() -> int:
    if not SONARR_API_KEY:
        print("SONARR_API_KEY is required", file=sys.stderr)
        return 1

    client = SonarrClient(SONARR_URL, SONARR_API_KEY)

    while True:
        state = load_state()
        write_heartbeat()
        try:
            series_list = client.get("/api/v3/series")
            for series in series_list:
                if not series.get("monitored"):
                    continue
                if refresh_series_if_needed(client, state, series):
                    continue
                repair_series(client, state, series)
            save_state(state)
        except Exception as exc:
            print(f"[error] {exc}", file=sys.stderr)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
