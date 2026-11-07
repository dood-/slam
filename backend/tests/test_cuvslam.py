"""GPU-independent checks of odometry gaps, coordinate frames and engine routing."""

import io
import json
from types import SimpleNamespace

import av
import numpy as np
from fastapi.testclient import TestClient
from slam import cuvslam_worker

from .test_contract import make_app, video_bytes
from .test_lifecycle import processor, upload, wait_state


def test_new_world_after_tracking_loss_is_not_joined(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    with av.open(buffer, "w", "mp4") as output:
        stream = output.add_stream("mpeg4", rate=5)
        stream.width, stream.height, stream.pix_fmt = 32, 24, "yuv420p"
        for i in range(8):
            frame = av.VideoFrame.from_ndarray(
                np.full((24, 32, 3), i * 20, dtype=np.uint8), "rgb24"
            )
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    video = tmp_path / "clip.mp4"
    video.write_bytes(buffer.getvalue())
    outputs = iter([10, 11, None, 99, 100, None, None, None])

    class Tracker:
        def track(self, timestamp, images):
            position = next(outputs)
            pose = (
                None
                if position is None
                else SimpleNamespace(
                    pose=SimpleNamespace(
                        translation=[position, 0, 0], rotation=[0, 0, 0, 1]
                    )
                )
            )
            return SimpleNamespace(world_from_rig=pose), None

    monkeypatch.setattr(cuvslam_worker, "create_tracker", lambda *_: Tracker())
    settings = {"maxImageSize": 960, "focalRatio": 0.8}
    samples, paths, size = cuvslam_worker.track_video(
        video, settings, {"frameCount": 8}
    )
    models = cuvslam_worker.export_models(samples, paths, size, settings, 1.6)
    assert len(models) == 2
    assert [s["timeSec"] for s in samples] == [i / 5 for i in range(8)]
    assert models[0]["samples"][0]["position"] == [0, 0, 0]
    assert models[0]["samples"][1]["position"] == [1, 0, 0]
    assert models[0]["samples"][3]["position"] is None
    assert models[1]["samples"][0]["position"] is None
    assert models[1]["samples"][3]["position"] == [0, 0, 0]
    assert models[1]["samples"][4]["position"] == [1, 0, 0]
    assert all(s["segmentId"] is None for s in models[0]["samples"][2:])
    assert models[0]["quality"]["registeredFrames"] == 2


def test_engine_validation_and_unavailable_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("SLAM_CUVSLAM_PYTHON", str(tmp_path / "missing-python"))
    with TestClient(make_app(tmp_path)) as client:
        video_id = upload(client)
        engines = {option["id"]: option for option in client.get("/api/engines").json()}
        assert engines["colmap"]["available"] and not engines["cuvslam"]["available"]
        assert (
            client.post(
                "/api/runs", json={"videoId": video_id, "engine": "arbitrary-command"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/runs",
                json={
                    "videoId": video_id,
                    "engine": "cuvslam",
                    "settings": {"focalRatio": 0},
                },
            ).status_code
            == 422
        )
        unavailable = client.post(
            "/api/runs", json={"videoId": video_id, "engine": "cuvslam"}
        )
        assert unavailable.status_code == 503
        assert unavailable.json()["error"]["code"] == "engine_unavailable"
        assert client.get("/api/status").json()["state"] == "idle"
        assert not list((tmp_path / "runs").iterdir())


def test_cuvslam_request_persists_settings_and_cancel_releases_slot(tmp_path):
    with TestClient(make_app(tmp_path, processor(tmp_path, mode="sleep"))) as client:
        video_id = upload(client)
        request = {
            "videoId": video_id,
            "engine": "cuvslam",
            "settings": {"maxImageSize": 960, "focalRatio": 0.9},
        }
        response = client.post("/api/runs", json=request)
        assert response.status_code == 202 and response.json()["engine"] == "cuvslam"
        run_id = response.json()["runId"]
        saved = json.loads((tmp_path / "runs" / run_id / "request.json").read_text())
        assert saved["engine"] == "cuvslam"
        assert saved["settings"] == {"maxImageSize": 960, "focalRatio": 0.9}
        assert client.post("/api/runs", json=request).status_code == 409
        assert client.post(f"/api/runs/{run_id}/cancel").json()["state"] == "cancelled"
        restarted = client.post("/api/runs", json=request)
        assert restarted.status_code == 202
        wait_state(client, "succeeded")


def test_default_engine_remains_colmap(tmp_path):
    with TestClient(make_app(tmp_path, processor(tmp_path))) as client:
        video_id = client.post(
            "/api/videos", files={"file": ("clip.mp4", video_bytes(), "video/mp4")}
        ).json()["id"]
        run_id = client.post("/api/runs", json={"videoId": video_id}).json()["runId"]
        wait_state(client, "succeeded")
        saved = json.loads((tmp_path / "runs" / run_id / "request.json").read_text())
        assert saved["engine"] == "colmap" and "focalRatio" not in saved["settings"]
