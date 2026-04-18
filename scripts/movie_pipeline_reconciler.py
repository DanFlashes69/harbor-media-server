#!/usr/bin/env python3
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union


ROOT = Path("/volume1/docker/harbor/stacks/harbor-media-server")
ENV_PATH = ROOT / ".env.synology.local"
DOWNLOADS_ROOT = Path("/volume1/downloads")
MOVIES_ROOT = Path("/volume1/media/movies")
PLEX_TOKEN_PATH = Path(
    "/volume1/docker/harbor/appdata/plex/config/Library/Application Support/Plex Media Server/.LocalAdminToken"
)
LOG_DIR = Path("/volume1/docker/harbor/appdata/update-guardian/status")
LOG_PATH = LOG_DIR / "movie-pipeline-reconciler.log"
LOCK_PATH = LOG_DIR / "movie-pipeline-reconciler.lock"

RADARR_URL = "http://127.0.0.1:7878"
QBIT_URL = "http://127.0.0.1:8081"
PLEX_URL = "http://127.0.0.1:32401"
MAX_RECENT_TORRENTS = 12
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".ts"}


def log(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def load_env() -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not ENV_PATH.exists():
        return data

    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key] = value
    return data


def normalize_title(title: str) -> str:
    return "".join(ch.lower() for ch in title if ch.isalnum())


def container_to_host(path: str) -> Path:
    if path.startswith("/downloads"):
        return DOWNLOADS_ROOT / path[len("/downloads") :].lstrip("/")
    if path.startswith("/movies"):
        return MOVIES_ROOT / path[len("/movies") :].lstrip("/")
    return Path(path)


def read_text_response(response) -> str:
    return response.read().decode("utf-8", "ignore")


def http_json(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Union[Dict[str, Any], List[Any]]] = None,
    timeout: int = 30,
    opener=None,
) -> Union[Dict[str, Any], List[Any]]:
    if params:
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{url}?{query}"

    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=body, headers=request_headers)
    request.method = "POST" if payload is not None else "GET"

    handler = opener.open if opener else urllib.request.urlopen
    with handler(request, timeout=timeout) as response:
        return json.loads(read_text_response(response))


def http_form(
    url: str,
    *,
    data: Dict[str, str],
    timeout: int = 30,
    opener=None,
) -> str:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(url, data=encoded)
    request.method = "POST"
    handler = opener.open if opener else urllib.request.urlopen
    with handler(request, timeout=timeout) as response:
        return read_text_response(response)


def wait_for_http(url: str, timeout_seconds: int = 30) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status < 500:
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def qbit_session(env: Dict[str, str]):
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    credential_pairs = []
    if env.get("QBIT_USER") and env.get("QBIT_PASS"):
        credential_pairs.append((env["QBIT_USER"], env["QBIT_PASS"]))
    credential_pairs.append(("admin", "adminadmin"))

    for username, password in credential_pairs:
        try:
            result = http_form(
                f"{QBIT_URL}/api/v2/auth/login",
                data={"username": username, "password": password},
                timeout=10,
                opener=opener,
            ).strip()
            if result == "Ok.":
                return opener
        except Exception:
            continue

    raise RuntimeError("qBittorrent authentication failed with all known credentials.")


def qbit_recent_completed(opener) -> List[Dict[str, Any]]:
    return http_json(
        f"{QBIT_URL}/api/v2/torrents/info",
        params={
            "filter": "completed",
            "category": "radarr",
            "sort": "completion_on",
            "reverse": "true",
        },
        timeout=20,
        opener=opener,
    )


def radarr_get(path: str, api_key: str, **params):
    return http_json(
        f"{RADARR_URL}/api/v3/{path}",
        params=params or None,
        headers={"X-Api-Key": api_key},
        timeout=30,
    )


def radarr_post(path: str, api_key: str, payload: Union[Dict[str, Any], List[Any]]):
    return http_json(
        f"{RADARR_URL}/api/v3/{path}",
        headers={"X-Api-Key": api_key},
        payload=payload,
        timeout=30,
    )


def get_movie(api_key: str, movie_id: int) -> Optional[Dict[str, Any]]:
    try:
        return radarr_get(f"movie/{movie_id}", api_key)
    except Exception:
        return None


def wait_for_movie_file(api_key: str, movie_id: int, timeout_seconds: int = 60) -> Optional[Dict[str, Any]]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        movie = get_movie(api_key, movie_id)
        if movie and movie.get("hasFile"):
            return movie
        time.sleep(5)
    return get_movie(api_key, movie_id)


def get_plex_movie_section_id(token: str) -> str:
    url = f"{PLEX_URL}/library/sections?{urllib.parse.urlencode({'X-Plex-Token': token})}"
    with urllib.request.urlopen(url, timeout=30) as response:
        root = ET.fromstring(read_text_response(response))

    for section in root.findall(".//Directory"):
        if (section.attrib.get("type") or "").lower() == "movie":
            key = section.attrib.get("key")
            if key:
                return key
    raise RuntimeError("Unable to find Plex movie library section.")


def get_plex_titles(token: str, section_id: str) -> Set[str]:
    params = {"X-Plex-Token": token}
    url = f"{PLEX_URL}/library/sections/{section_id}/all?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as response:
        root = ET.fromstring(read_text_response(response))

    titles: Set[str] = set()
    for video in root.findall(".//Video"):
        title = (video.attrib.get("title") or "").strip()
        if title:
            titles.add(normalize_title(title))
    return titles


def plex_refresh(token: str, section_id: str) -> None:
    url = f"{PLEX_URL}/library/sections/{section_id}/refresh?{urllib.parse.urlencode({'X-Plex-Token': token})}"
    with urllib.request.urlopen(url, timeout=20):
        pass
    log("Triggered Plex movie library refresh.")


def trigger_downloaded_movies_scan(api_key: str, folder: str) -> None:
    result = radarr_post(
        "command",
        api_key,
        {
            "name": "DownloadedMoviesScan",
            "path": folder,
            "downloadClient": "qBittorrent",
            "importMode": "auto",
        },
    )
    log(f"Triggered DownloadedMoviesScan for {folder}: command {result.get('id')}.")


def trigger_rescan_movie(api_key: str, movie_id: int) -> None:
    result = radarr_post("command", api_key, {"name": "RescanMovie", "movieId": movie_id})
    log(f"Triggered RescanMovie for movieId {movie_id}: command {result.get('id')}.")


def select_manual_import_item(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    best_item = None
    best_size = -1
    for item in items:
        source_path = container_to_host(item.get("path", ""))
        if source_path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        if not source_path.exists():
            continue
        size = source_path.stat().st_size
        if size > best_size:
            best_size = size
            best_item = item
    return best_item


def target_movie_path(item: Dict[str, Any]) -> Path:
    movie = item["movie"]
    source_path = container_to_host(item["path"])
    target_dir = container_to_host(movie["path"])
    target_dir.mkdir(parents=True, exist_ok=True)

    quality = item.get("quality", {}).get("quality", {}).get("name", "").strip()
    quality_suffix = f" {quality}" if quality else ""
    extension = source_path.suffix or ".mkv"
    safe_quality = quality_suffix.replace("/", "-")
    return target_dir / f"{movie['title']} ({movie['year']}){safe_quality}{extension}"


def copy_into_movie_folder(item: Dict[str, Any]) -> None:
    source_path = container_to_host(item["path"])
    target_path = target_movie_path(item)
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    if target_path.exists() and target_path.stat().st_size == source_path.stat().st_size:
        log(f"Target already exists for {item['movie']['title']}: {target_path}")
        return

    log(f"Copying fallback import {source_path} -> {target_path}")
    shutil.copy2(source_path, target_path)


def ensure_plex_visibility(token: str, section_id: str, title: str) -> Set[str]:
    plex_titles = get_plex_titles(token, section_id)
    if normalize_title(title) in plex_titles:
        return plex_titles

    plex_refresh(token, section_id)
    time.sleep(6)
    return get_plex_titles(token, section_id)


def repair_completed_torrent(
    api_key: str,
    plex_token: str,
    plex_section_id: str,
    plex_titles: Set[str],
    torrent: Dict[str, Any],
) -> Set[str]:
    folder = f"/downloads/{torrent['name']}"
    try:
        manual_items = radarr_get(
            "manualimport",
            api_key,
            folder=folder,
            filterExistingFiles="false",
        )
    except urllib.error.HTTPError as error:
        log(f"Manual import probe failed for {folder}: HTTP {error.code}")
        return plex_titles
    except Exception as error:
        log(f"Manual import probe failed for {folder}: {error!r}")
        return plex_titles

    if not manual_items:
        return plex_titles

    item = select_manual_import_item(manual_items)
    if not item:
        log(f"No usable manual import candidate found for {folder}.")
        return plex_titles

    movie = item["movie"]
    movie_id = movie["id"]
    title = movie["title"]
    current = get_movie(api_key, movie_id)
    in_plex = normalize_title(title) in plex_titles

    if current and current.get("hasFile") and in_plex:
        return plex_titles

    if current and current.get("hasFile") and not in_plex:
        log(f"{title} already has a Radarr file but is missing in Plex; refreshing Plex.")
        return ensure_plex_visibility(plex_token, plex_section_id, title)

    trigger_downloaded_movies_scan(api_key, folder)
    current = wait_for_movie_file(api_key, movie_id, timeout_seconds=25)
    if current and current.get("hasFile"):
        log(f"{title} imported successfully via DownloadedMoviesScan.")
        return ensure_plex_visibility(plex_token, plex_section_id, title)

    log(f"{title} still missing after auto-import. Applying copy-and-rescan fallback.")
    copy_into_movie_folder(item)
    trigger_rescan_movie(api_key, movie_id)
    current = wait_for_movie_file(api_key, movie_id, timeout_seconds=45)
    if current and current.get("hasFile"):
        log(f"{title} recovered by fallback copy and rescan.")
        return ensure_plex_visibility(plex_token, plex_section_id, title)

    log(f"{title} is still missing after fallback repair.")
    return plex_titles


def acquire_lock() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return -1

    os.write(fd, str(os.getpid()).encode("utf-8"))
    return fd


def main() -> int:
    lock_fd = acquire_lock()
    if lock_fd == -1:
        log("Another movie pipeline reconciler run is already in progress. Exiting.")
        return 0

    try:
        env = load_env()
        api_key = env["RADARR_API_KEY"]
        plex_token = PLEX_TOKEN_PATH.read_text(encoding="utf-8").strip()

        if not wait_for_http(f"{RADARR_URL}/ping", timeout_seconds=20):
            raise RuntimeError("Radarr is not reachable.")
        if not wait_for_http(f"{PLEX_URL}/identity", timeout_seconds=20):
            raise RuntimeError("Plex is not reachable.")

        qbit = qbit_session(env)
        section_id = get_plex_movie_section_id(plex_token)
        plex_titles = get_plex_titles(plex_token, section_id)
        torrents = qbit_recent_completed(qbit)

        log(f"Loaded {len(plex_titles)} Plex movie titles and {len(torrents)} completed Radarr torrents.")
        for torrent in torrents[:MAX_RECENT_TORRENTS]:
            plex_titles = repair_completed_torrent(api_key, plex_token, section_id, plex_titles, torrent)

        log("Movie pipeline reconciler run completed.")
        return 0
    except Exception as error:
        log(f"Movie pipeline reconciler failed: {error!r}")
        return 1
    finally:
        try:
            os.close(lock_fd)
        except Exception:
            pass
        try:
            LOCK_PATH.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
