import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


SCRIPT_PATH = Path(r"D:\harbor-media-server\scripts\nas_localhost_proxy.py")
LOG_DIR = Path(r"D:\harbor-media-server\logs")
STDOUT_LOG = LOG_DIR / "nas_localhost_proxy.out.log"
STDERR_LOG = LOG_DIR / "nas_localhost_proxy.err.log"
SUPERVISOR_LOG = LOG_DIR / "nas_localhost_proxy_supervisor.log"
TEST_PORTS = (3000, 32400, 5055, 8081)
CHECK_INTERVAL_SECONDS = 60


def write_log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with SUPERVISOR_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{timestamp} {message}\n")


def get_pythonw() -> str:
    candidates = [
        Path(r"C:\Python314\pythonw.exe"),
        Path(r"C:\Python313\pythonw.exe"),
        Path(r"C:\Python312\pythonw.exe"),
        Path(sys.executable),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def start_proxy() -> subprocess.Popen:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    stdout = STDOUT_LOG.open("ab")
    stderr = STDERR_LOG.open("ab")
    process = subprocess.Popen(
        [get_pythonw(), str(SCRIPT_PATH)],
        stdout=stdout,
        stderr=stderr,
        creationflags=creationflags,
        close_fds=False,
    )
    write_log(f"Started NAS localhost proxy pid={process.pid}")
    return process


def is_listening() -> bool:
    for port in TEST_PORTS:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            continue
    return False


def terminate_process(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    try:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def ensure_single_instance() -> None:
    pid_file = LOG_DIR / "nas_localhost_proxy_supervisor.pid"
    try:
        if pid_file.exists():
            existing_pid = int(pid_file.read_text(encoding="ascii").strip())
            if existing_pid and existing_pid != os.getpid():
                try:
                    os.kill(existing_pid, 0)
                    write_log(f"Supervisor already running pid={existing_pid}; exiting duplicate.")
                    sys.exit(0)
                except OSError:
                    pass
        pid_file.write_text(str(os.getpid()), encoding="ascii")
    except Exception:
        pass


def main() -> int:
    ensure_single_instance()
    child: subprocess.Popen | None = None
    write_log("Supervisor started.")
    while True:
        try:
            if child is None or child.poll() is not None:
                if child is not None and child.poll() is not None:
                    write_log(f"Proxy exited rc={child.returncode}; restarting.")
                child = start_proxy()
                time.sleep(3)

            if not is_listening():
                write_log("Proxy ports not listening; restarting proxy.")
                terminate_process(child)
                child = start_proxy()

            time.sleep(CHECK_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            terminate_process(child)
            return 0
        except Exception as exc:
            write_log(f"Supervisor error: {exc!r}")
            time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
