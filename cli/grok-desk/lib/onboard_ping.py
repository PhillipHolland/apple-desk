"""One anonymous onboard-ok request. No body, no query, no identifiers."""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path

URL = "https://apple-desk-counter.vercel.app/onboard"
MARKER_NAME = "onboard-pinged"


def marker_path() -> Path:
    return Path.home() / ".cache" / "grok-desk" / MARKER_NAME


def maybe_ping() -> bool:
    """Send the one-shot hit. True only when a 2xx response was received.

    Never raises. A network failure leaves the marker unset so a later
    success can retry. The marker is written only after HTTP 2xx.
    """
    if os.environ.get("GROK_DESK_NO_TELEMETRY") == "1":
        return False
    marker = marker_path()
    try:
        if marker.exists():
            return False
    except OSError:
        return False
    req = urllib.request.Request(
        URL,
        method="GET",
        headers={"User-Agent": "grok-desk"},
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
    except Exception:
        return False
    if not (200 <= int(code) < 300):
        return False
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(marker.parent, 0o700)
        marker.write_text("1\n")
        os.chmod(marker, 0o600)
    except OSError:
        return True
    return True
