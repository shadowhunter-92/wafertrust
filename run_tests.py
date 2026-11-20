"""Deterministic test runner for the full WaferTrust suite.

Run:  python run_tests.py

The HSMS tests drive secsgem 0.3.0, whose passive/active connections spawn
non-daemon receiver and reconnect threads. On Windows its disconnect/reconnect
path has a race: the peer closing the socket fires _disconnected while the
endpoint is still enabled, spawning a fresh thread that disable() never joins.
That can block interpreter shutdown after every test has passed, or deadlock in
disable()'s busy wait. test_secs_transport.py suppresses those reconnect handlers
for the test process (the tests connect once and never reconnect), so disable()
joins only its own thread and both plain `python -m unittest` and this runner exit
cleanly.

This runner adds a deterministic guarantee on top: it collects the real unittest
result, flushes output, then exits with the correct status via os._exit so any
residual third-party cleanup thread cannot hang CI. It does not change what is
tested or hide failures: a failing suite still exits non-zero. The standalone
demos close a single connected link and exit on their own.
"""
from __future__ import annotations

import os
import sys
import unittest

MODULES = ("test_hardening", "test_custody_anchor", "test_secs_transport")


def main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in MODULES:
        suite.addTests(loader.loadTestsFromName(name))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.stdout.flush()
    sys.stderr.flush()
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    code = main()
    os._exit(code)