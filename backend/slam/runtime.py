"""File publication and process lifetime shared by reconstruction workers."""

import json
import os
import signal
import threading


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def event(**fields):
    print("SLAM_EVENT " + json.dumps(fields, allow_nan=False), flush=True)


def parent_guard():
    descriptor = os.environ.get("SLAM_PARENT_FD")
    if descriptor is None:
        return

    def watch():
        try:
            while os.read(int(descriptor), 1):
                pass
        finally:
            os.killpg(os.getpgrp(), signal.SIGTERM)

    threading.Thread(target=watch, daemon=True).start()
