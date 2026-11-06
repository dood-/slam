# SLAM video trajectory viewer

Local CPU reconstruction of a camera trajectory from MP4, with a Vue viewer and a single-process FastAPI API. There is no database or queue; one API worker owns the processing slot.

## Run locally

```sh
UV_CACHE_DIR=/tmp/slam-uv-cache uv run --project backend uvicorn slam.api:app --host 127.0.0.1 --port 8000
cd frontend && npm ci && npm run build && npm run preview -- --host 127.0.0.1 --port 4173
```

Open <http://127.0.0.1:4173>. Vite proxies `/api` to `http://127.0.0.1:8000`. Set `SLAM_STORAGE=/absolute/path` to choose the file-backed storage directory.

Restarting the API cancels an active child process; completed manifests remain available. A second run while one is active returns `409 processing_busy`; a later run creates a new directory and does not overwrite old results. Processing is CPU-bound and runtime depends on video, settings, and the installed pycolmap build.

## Verification

```sh
UV_CACHE_DIR=/tmp/slam-uv-cache uv run --project backend --extra test python -m pytest backend/tests -q
cd frontend && npm test -- --run
```

Lifecycle tests use only the public API and the documented controlled processor seam. Browser tests live in `tests/e2e` and require a running production preview plus `E2E_FIXTURE=/path/to/tiny-h264.mp4`; they never replace the production reconstruction engine.
