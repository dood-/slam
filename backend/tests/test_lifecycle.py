"""Public API lifecycle tests using the documented controlled processor seam."""

import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from test_contract import make_app, video_bytes


def wait_state(client, state, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = client.get('/api/status').json()
        if value['state'] == state:
            return value
        time.sleep(.01)
    raise AssertionError(f"timed out waiting for {state}: {value}")


def processor(tmp_path, *, mode='success'):
    invocations = 0
    def command(video, run_dir, settings, metadata):
        nonlocal invocations
        invocations += 1
        script = run_dir / 'controlled_processor.py'
        payload = {
            'state': 'succeeded',
            'trajectory': {
                'schemaVersion': 1, 'runId': run_dir.name, 'videoId': metadata['id'],
                'video': metadata, 'createdAt': run_dir.name, 'engine': 'controlled-test',
                'units': 'arbitrary', 'scaleSource': None, 'poseConvention': 'camera-to-world',
                'settings': settings, 'primaryModelId': 'model-a', 'warnings': [],
                'models': [{'id': 'model-a', 'camera': {'model': 'SIMPLE_RADIAL', 'width': 32,
                    'height': 24, 'params': []}, 'samples': [], 'segments': [],
                    'quality': {'registeredFrames': 0, 'sampledFrames': 0, 'coverage': 0,
                                'points3D': 0, 'meanReprojectionErrorPx': None, 'maxGapSec': 0}}],
            },
        }
        delay = 30 if mode == 'sleep' and invocations == 1 else 0.01
        body = f"import json,time; time.sleep({delay}); "
        if mode == 'fail':
            body += "raise SystemExit(7)"
        else:
            body += f"open({str(run_dir / 'manifest.json')!r}, 'w').write({json.dumps(payload)!r})"
        script.write_text(body)
        return [sys.executable, str(script)]
    return command


def upload(client):
    return client.post('/api/videos', files={'file': ('clip.mp4', video_bytes(), 'video/mp4')}).json()['id']


def test_busy_cancel_repeat_cancel_and_new_start(tmp_path):
    client = TestClient(make_app(tmp_path, processor(tmp_path, mode='sleep')))
    video_id = upload(client)
    first = client.post('/api/runs', json={'videoId': video_id}).json()
    run_id = first['runId']
    assert client.post('/api/runs', json={'videoId': video_id}).status_code == 409
    cancelled = client.post(f'/api/runs/{run_id}/cancel')
    assert cancelled.status_code == 200 and cancelled.json()['state'] == 'cancelled'
    assert client.post(f'/api/runs/{run_id}/cancel').json()['state'] == 'cancelled'
    second = client.post('/api/runs', json={'videoId': video_id})
    assert second.status_code == 202 and second.json()['runId'] != run_id
    wait_state(client, 'succeeded')
    assert client.get('/api/results').json()[0]['runId'] == second.json()['runId']


def test_start_failure_is_distinct_and_slot_recovers(tmp_path):
    def broken(*_args):
        return [sys.executable, '-c', 'raise SystemExit(9)']
    client = TestClient(make_app(tmp_path, broken))
    video_id = upload(client)
    run = client.post('/api/runs', json={'videoId': video_id}).json()
    status = wait_state(client, 'failed')
    assert status['runId'] == run['runId']
    assert status['error']['code'] == 'processing_failed'
    assert client.post('/api/runs', json={'videoId': video_id}).status_code == 202


def test_invalid_processor_command_returns_start_failed(tmp_path):
    def unavailable(*_args):
        return [str(tmp_path / 'does-not-exist')]
    client = TestClient(make_app(tmp_path, unavailable))
    video_id = upload(client)
    response = client.post('/api/runs', json={'videoId': video_id})
    assert response.status_code == 500
    assert response.json()['error']['code'] == 'start_failed'
