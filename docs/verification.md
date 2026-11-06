# Verification evidence

This document records reproducible checks for the integration slice. It intentionally does not claim a check was run unless its command and result are recorded here.

## Backend lifecycle

Command:

```sh
UV_CACHE_DIR=/tmp/slam-uv-cache uv run --project backend --extra test python -m pytest backend/tests/test_lifecycle.py -q
```

Result: **3 passed** (one Starlette/httpx deprecation warning). Covered: busy concurrent start, cancellation, repeated cancellation, new start after cancellation, failed processor recovery, and process launch failure.

## Browser E2E

The deterministic Playwright suite is in `tests/e2e`. Run it against a production Vite preview and a controlled backend with `E2E_FIXTURE` set to a tiny H.264 MP4. No browser run was performed by this integration agent; shared browser verification and screenshots are maintained by the integration lead.
