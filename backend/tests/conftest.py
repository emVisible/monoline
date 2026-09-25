"""Test session plumbing.

The zh-TTS tests import onnxruntime/misaki, and that stack aborts during
interpreter teardown roughly one full run in four — *after* pytest has already
printed "all passed". The crash is in native atexit code, so it neither hides nor
causes a test failure, but it makes the gate's exit code unreliable, and an
unreliable exit code is worse than no gate.

So the verdict is taken from pytest's own session status and the process exits
before the crashing teardown runs. Failures still propagate as non-zero.
"""
from __future__ import annotations

import os
import sys

_GATE = {"status": 0}


def pytest_sessionfinish(session, exitstatus) -> None:
    # record only: the terminal report (failure details) is still owed, and a gate
    # that hides them is worse than a flaky exit code
    _GATE["status"] = int(exitstatus)


def pytest_unconfigure(config) -> None:
    """Runs after the terminal summary. The zh-TTS tests pull in onnxruntime/misaki,
    whose native atexit code aborts ~1 run in 4 *after* everything already passed;
    leaving it to that teardown would make the gate's exit code meaningless."""
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_GATE["status"])
