"""Public API lifecycle tests using the documented controlled processor seam."""

import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from .test_contract import make_app, video_bytes


def wait_state(client, state, timeout=3):
    deadline = time.monotonic() + timeout
    value = None
    while time.monotonic() < deadline:
        value = client.get("/api/status").json()
        if value["state"] == state:
            return value
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {state}: {value}")


def processor(tmp_path, *, mode="success"):
    invocations = 0

    def command(video, run_dir, settings, metadata):
        nonlocal invocations
        invocations += 1
        script = run_dir / "controlled_processor.py"
        payload = {
            "state": "succeeded",
            "trajectory": {
                "schemaVersion": 1,
                "runId": run_dir.name,
                "videoId": metadata["id"],
                "video": metadata,
                "createdAt": run_dir.name,
                "engine": "controlled-test",
                "units": "arbitrary",
                "scaleSource": None,
                "poseConvention": "camera-to-world",
                "settings": settings,
                "primaryModelId": "model-a",
                "warnings": [],
                "models": [
                    {
                        "id": "model-a",
                        "camera": {
                            "model": "SIMPLE_RADIAL",
                            "width": 32,
                            "height": 24,
                            "params": [],
                        },
                        "samples": [],
                        "segments": [],
                        "quality": {
                            "registeredFrames": 0,
                            "sampledFrames": 0,
                            "coverage": 0,
                            "points3D": 0,
                            "meanReprojectionErrorPx": None,
                            "maxGapSec": 0,
                        },
                    }
                ],
            },
        }
        delay = 30 if mode == "sleep" and invocations == 1 else 0.01
        body = f"import json,time; time.sleep({delay}); "
        if mode == "fail":
            body += "raise SystemExit(7)"
        else:
            body += f"open({str(run_dir / 'manifest.json')!r}, 'w').write({json.dumps(payload)!r})"
        script.write_text(body)
        return [sys.executable, str(script)]

    return command


def upload(client):
    return client.post(
        "/api/videos", files={"file": ("clip.mp4", video_bytes(), "video/mp4")}
    ).json()["id"]


def test_busy_cancel_repeat_cancel_and_new_start(tmp_path):
    client = TestClient(make_app(tmp_path, processor(tmp_path, mode="sleep")))
    video_id = upload(client)
    first = client.post("/api/runs", json={"videoId": video_id}).json()
    run_id = first["runId"]
    assert client.post("/api/runs", json={"videoId": video_id}).status_code == 409
    cancelled = client.post(f"/api/runs/{run_id}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled"
    assert client.post(f"/api/runs/{run_id}/cancel").json()["state"] == "cancelled"
    second = client.post("/api/runs", json={"videoId": video_id})
    assert second.status_code == 202 and second.json()["runId"] != run_id
    wait_state(client, "succeeded")
    assert client.get("/api/results").json()[0]["runId"] == second.json()["runId"]


def test_start_failure_is_distinct_and_slot_recovers(tmp_path):
    def broken(*_args):
        return [sys.executable, "-c", "raise SystemExit(9)"]

    client = TestClient(make_app(tmp_path, broken))
    video_id = upload(client)
    run = client.post("/api/runs", json={"videoId": video_id}).json()
    status = wait_state(client, "failed")
    assert status["runId"] == run["runId"]
    assert status["error"]["code"] == "processing_failed"
    assert client.post("/api/runs", json={"videoId": video_id}).status_code == 202


def test_invalid_processor_command_returns_start_failed(tmp_path):
    def unavailable(*_args):
        return [str(tmp_path / "does-not-exist")]

    client = TestClient(make_app(tmp_path, unavailable))
    video_id = upload(client)
    response = client.post("/api/runs", json={"videoId": video_id})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "start_failed"


def test_completed_results_survive_new_app_instance(tmp_path):
    with TestClient(make_app(tmp_path, processor(tmp_path))) as client:
        video_id = upload(client)
        run_id = client.post("/api/runs", json={"videoId": video_id}).json()["runId"]
        wait_state(client, "succeeded")
    with TestClient(make_app(tmp_path)) as restarted:
        assert restarted.get("/api/status").json()["state"] == "idle"
        assert restarted.get("/api/results").json()[0]["runId"] == run_id
        assert restarted.get(f"/api/results/{run_id}").json()["videoId"] == video_id


def test_real_worker_exits_after_api_is_killed(tmp_path):
    """Observe process lifetime at the operating-system boundary, not controller internals."""
    import os
    import socket
    import subprocess
    import httpx
    import pytest

    if not Path("/proc/self/task").exists():
        pytest.skip("Linux/WSL process lifetime check")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = os.environ.copy()
    environment["SLAM_STORAGE"] = str(tmp_path)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    api = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "slam.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    child = None
    try:
        assert api.stderr is not None
        for line in api.stderr:
            if "Uvicorn running" in line:
                break
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5
        ) as client:
            video_id = upload(client)
            assert (
                client.post("/api/runs", json={"videoId": video_id}).status_code == 202
            )
        children = [
            pid
            for entry in Path(f"/proc/{api.pid}/task").glob("*/children")
            for pid in entry.read_text().split()
        ]
        assert children, "API did not launch an external reconstruction process"
        child = int(children[0])
        api.kill()
        api.wait(timeout=5)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            stat = Path(f"/proc/{child}/stat")
            if not stat.exists() or stat.read_text().split()[2] == "Z":
                break
            time.sleep(0.05)
        else:
            pytest.fail("Reconstruction survived loss of the API parent process")
    finally:
        if api.poll() is None:
            api.kill()
            api.wait(timeout=5)
        if child and Path(f"/proc/{child}/stat").exists():
            try:
                os.kill(child, 9)
            except ProcessLookupError:
                pass
