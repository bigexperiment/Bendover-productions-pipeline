#!/usr/bin/env python3
"""Keep tracker/serve.py running; restart automatically after crashes."""
from __future__ import annotations

import argparse
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACKER = Path(__file__).resolve().parent
PID_FILE = TRACKER / "studio.pid"
SERVE = TRACKER / "serve.py"
LOG = TRACKER / "studio.log"

_running = True
_child: subprocess.Popen[bytes] | None = None


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [supervisor] {message}\n"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line)


def shutdown(_signum: int, _frame) -> None:
    global _running, _child
    _running = False
    if _child is not None and _child.poll() is None:
        _child.terminate()
        try:
            _child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _child.kill()


def write_pid() -> None:
    PID_FILE.write_text(f"{os.getpid()}\n", encoding="utf-8")


def clear_pid() -> None:
    PID_FILE.unlink(missing_ok=True)


def detach_from_terminal() -> None:
    """Double-fork so Studio survives when the launching shell (e.g. Cursor agent) exits."""
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid > 0:
        os.close(write_fd)
        try:
            ready, _, _ = select.select([read_fd], [], [], 10.0)
            if ready:
                os.read(read_fd, 1)
            else:
                # grandchild didn't signal within 10s — it may have crashed
                sys.stderr.write("studio_supervisor: warning: daemon did not signal ready\n")
        except OSError:
            pass
        os.close(read_fd)
        raise SystemExit(0)

    os.close(read_fd)
    os.setsid()
    pid = os.fork()
    if pid > 0:
        raise SystemExit(0)

    os.chdir(ROOT)
    os.umask(0o022)
    with open(os.devnull, "r", encoding="utf-8") as devnull:
        os.dup2(devnull.fileno(), sys.stdin.fileno())

    write_pid()
    try:
        os.write(write_fd, b"\0")
    except OSError:
        pass
    os.close(write_fd)


def run_once() -> int:
    global _child
    log("starting serve.py")
    with LOG.open("a", encoding="utf-8") as log_handle:
        _child = subprocess.Popen(
            [sys.executable, "-u", str(SERVE)],
            cwd=ROOT,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        return _child.wait()


def supervise() -> int:
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    backoff = 1
    try:
        while _running:
            code = run_once()
            if not _running:
                break
            log(f"serve.py exited with code {code}; restarting in {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
    finally:
        clear_pid()
        log("supervisor stopped")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Supervise tracker/serve.py")
    parser.add_argument(
        "--detach",
        action="store_true",
        help="Fork into background so the server survives shell/agent exit",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.detach:
        log("detaching from terminal")
        detach_from_terminal()
    else:
        write_pid()

    return supervise()


if __name__ == "__main__":
    raise SystemExit(main())
