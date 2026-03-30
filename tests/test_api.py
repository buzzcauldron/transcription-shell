from __future__ import annotations

import importlib.util


def test_health_endpoint_when_fastapi_installed():
    if importlib.util.find_spec("fastapi") is None:
        return
    from starlette.testclient import TestClient

    from transcriber_shell.api.app import app

    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
