"""Start the local API/UI and durable worker with clean shutdown (Linux/Windows)."""

import argparse
import signal
import subprocess
import sys
import time

from services.api.storage import DATA, ROOT, make_engine, migrate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not (ROOT / "apps/web/dist/index.html").exists():
        raise SystemExit("Build the web client first: cd apps/web && npm ci && npm run build")
    migrate(make_engine(DATA))
    children = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "services.api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
            ],
            cwd=ROOT,
        ),
        subprocess.Popen([sys.executable, "-m", "services.api.worker"], cwd=ROOT),
    ]
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        print(f"STRATOS API/UI on loopback port {args.port}; SQLite and cache at {DATA}", flush=True)
        while not stopping:
            for child in children:
                if child.poll() is not None:
                    raise RuntimeError(f"Child process exited with status {child.returncode}")
            time.sleep(0.25)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()
