"""``python -m monitor`` — the companion's entrypoint, as its own service on the backend image."""

from __future__ import annotations

import signal
import threading

from sqlmodel import Session, create_engine

from terp.core import configure_logging, get_settings

from monitor.watch import run


def main() -> int:
    """Watch the outbox until the process is asked to stop."""
    configure_logging()
    engine = create_engine(get_settings().DATABASE_URL, pool_pre_ping=True)
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    try:
        run(lambda: Session(engine), stop)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
