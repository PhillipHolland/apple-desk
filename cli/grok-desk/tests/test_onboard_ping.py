#!/usr/bin/env python3
"""Offline tests for the one-shot anonymous onboard ping.

Uses a temporary HOME. Does not open a socket.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

LIVE_HOME = os.environ.get("HOME", "")
ROOT = Path(tempfile.mkdtemp(prefix="apple-desk-onboard-ping-", dir="/tmp"))
FAKE_HOME = ROOT / "home"
FAKE_HOME.mkdir()
os.environ["HOME"] = str(FAKE_HOME)
os.environ.pop("GROK_DESK_NO_TELEMETRY", None)

LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

import onboard_ping  # noqa: E402


class FakeResp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status


def test_opt_out_sends_nothing():
    os.environ["GROK_DESK_NO_TELEMETRY"] = "1"
    try:
        with patch("urllib.request.urlopen") as opened:
            assert onboard_ping.maybe_ping() is False
            opened.assert_not_called()
        assert not onboard_ping.marker_path().exists()
    finally:
        os.environ.pop("GROK_DESK_NO_TELEMETRY", None)


def test_success_writes_marker_and_does_not_repeat():
    seen = []

    def fake_open(req, timeout=0):
        seen.append((req.full_url, req.data, req.get_method(), timeout, req.get_header("User-agent")))
        return FakeResp(204)

    with patch("urllib.request.urlopen", fake_open):
        assert onboard_ping.maybe_ping() is True
        assert onboard_ping.maybe_ping() is False
    assert seen == [(
        "https://apple-desk-counter.vercel.app/onboard",
        None,
        "GET",
        3,
        "grok-desk",
    )]
    assert "?" not in seen[0][0]
    assert onboard_ping.marker_path().read_text() == "1\n"


def test_failure_leaves_marker_unset():
    onboard_ping.marker_path().unlink()

    def boom(*_args, **_kwargs):
        raise TimeoutError("offline")

    with patch("urllib.request.urlopen", boom):
        assert onboard_ping.maybe_ping() is False
    assert not onboard_ping.marker_path().exists()


def test_non_2xx_leaves_marker_unset():
    with patch("urllib.request.urlopen", lambda *_a, **_k: FakeResp(500)):
        assert onboard_ping.maybe_ping() is False
    assert not onboard_ping.marker_path().exists()


def main():
    test_opt_out_sends_nothing()
    test_success_writes_marker_and_does_not_repeat()
    test_failure_leaves_marker_unset()
    test_non_2xx_leaves_marker_unset()
    if LIVE_HOME:
        os.environ["HOME"] = LIVE_HOME
    print("ok")


if __name__ == "__main__":
    main()
