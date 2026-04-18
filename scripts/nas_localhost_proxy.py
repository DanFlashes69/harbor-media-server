import asyncio
import os
import signal
import socket
import time
from typing import Iterable


DISCOVERY_PORTS = (32401, 3000, 8081, 7878, 9696, 5055)
DISCOVERY_TIMEOUT = 0.35
DISCOVERY_CACHE_TTL = 30.0


def _candidate_hosts() -> list[str]:
    candidates: list[str] = []

    configured = os.environ.get("HARBOR_NAS_HOST", "").strip()
    if configured:
        candidates.append(configured)

    candidates.extend(
        [
            "synology.example.lan",
            "synology.example.lan",
            "synology-ds224p",
            "synology-ds224plus",
            "diskstation",
        ]
    )

    # Preserve order while dropping duplicates/empties.
    seen = set()
    ordered: list[str] = []
    for host in candidates:
        if host and host not in seen:
            ordered.append(host)
            seen.add(host)
    return ordered


def _can_connect(host: str, ports: Iterable[int], timeout: float = DISCOVERY_TIMEOUT) -> bool:
    for port in ports:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def _scan_local_subnet() -> str | None:
    for suffix in range(2, 255):
        host = f"192.168.1.{suffix}"
        if _can_connect(host, DISCOVERY_PORTS, timeout=0.18):
            return host
    return None


class TargetResolver:
    def __init__(self) -> None:
        self._host: str | None = None
        self._expires_at = 0.0

    def discover(self, *, force: bool = False) -> str | None:
        now = time.monotonic()
        if not force and self._host and now < self._expires_at:
            return self._host

        for candidate in _candidate_hosts():
            if _can_connect(candidate, DISCOVERY_PORTS):
                self._host = candidate
                self._expires_at = now + DISCOVERY_CACHE_TTL
                return self._host

        scanned = _scan_local_subnet()
        if scanned:
            self._host = scanned
            self._expires_at = now + DISCOVERY_CACHE_TTL
            return self._host

        self._host = None
        self._expires_at = now + 5.0
        return None


TARGET = TargetResolver()

# Keep the same localhost UX for NAS-moved services. Most ports are 1:1, but
# Plex currently binds to 32401 on the NAS while preserving localhost:32400 on
# the PC bridge.
PORT_MAP = {
    3000: 3000,    # Homepage
    3001: 3001,    # Gitea
    2283: 2283,    # Immich
    32400: 32401,  # Plex
    5055: 5055,    # Overseerr
    5000: 5000,    # DSM HTTP
    5001: 5001,    # DSM HTTPS
    6767: 6767,    # Bazarr
    7878: 7878,    # Radarr
    8081: 8081,    # qBittorrent
    8082: 8082,    # SABnzbd
    8099: 8099,    # Update status
    8265: 8265,    # Tdarr
    8686: 8686,    # Lidarr
    8989: 8989,    # Sonarr
    9000: 9000,    # Portainer
    9080: 9080,    # Pi-hole
    9696: 9696,    # Prowlarr
}


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def handle_client(
    local_reader: asyncio.StreamReader,
    local_writer: asyncio.StreamWriter,
    target_port: int,
) -> None:
    remote_reader = None
    remote_writer = None
    for force in (False, True):
        host = TARGET.discover(force=force)
        if not host:
            continue
        try:
            remote_reader, remote_writer = await asyncio.open_connection(host, target_port)
            break
        except Exception:
            continue

    if remote_reader is None or remote_writer is None:
        local_writer.close()
        try:
            await local_writer.wait_closed()
        except Exception:
            pass
        return

    await asyncio.gather(
        pipe(local_reader, remote_writer),
        pipe(remote_reader, local_writer),
        return_exceptions=True,
    )


async def main() -> None:
    servers = []
    for local_port, target_port in PORT_MAP.items():
        server = await asyncio.start_server(
            lambda r, w, p=target_port: handle_client(r, w, p),
            host="127.0.0.1",
            port=local_port,
        )
        servers.append(server)

    stop_event = asyncio.Event()

    def stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop)
        except NotImplementedError:
            pass

    await stop_event.wait()

    for server in servers:
        server.close()
        await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())

