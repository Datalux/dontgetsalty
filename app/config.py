import hashlib
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _static_version() -> str:
    """A short hash of everything under app/static/, used as a cache-busting
    query string on CSS/JS links so a deploy invalidates browsers' old
    cached copies instead of silently serving a stale stylesheet."""
    h = hashlib.sha1()
    static_dir = BASE_DIR / "app" / "static"
    for path in sorted(static_dir.rglob("*")):
        if path.is_file():
            h.update(path.read_bytes())
    return h.hexdigest()[:10]


STATIC_VERSION = _static_version()

MIN_PLAYERS = int(os.environ.get("GGAME_MIN_PLAYERS", "3"))

# How long a disconnected player still counts toward "everyone has answered"
# thresholds (and toward the host still being present). Covers a plain page
# refresh or a brief network blip without prematurely skipping someone.
RECONNECT_GRACE_SECONDS = int(os.environ.get("GGAME_RECONNECT_GRACE_SECONDS", "30"))
