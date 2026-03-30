from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

if importlib.util.find_spec("fastapi") is None:
    pytest.skip("fastapi not installed", allow_module_level=True)

from starlette.testclient import TestClient

from transcriber_shell.api.app import create_app
from transcriber_shell.config import Settings
from transcriber_shell.models.job import PipelineResult


def test_health_endpoint_when_fastapi_installed() -> None:
    from transcriber_shell.api.app import app

    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_root_redirects_to_api_docs() -> None:
    from transcriber_shell.api.app import app

    client = TestClient(app, follow_redirects=False)
    r = client.get("/")
    assert r.status_code == 307
    assert r.headers.get("location") == "/docs"


def test_v1_transcribe_requires_bearer_when_api_key_configured() -> None:
    app = create_app(Settings(api_key="secret-token"))
    client = TestClient(app)
    r = client.post(
        "/v1/transcribe",
        data={"prompt": "{}"},
        files=[("files", ("a.jpg", b"\xff\xd8", "image/jpeg"))],
    )
    assert r.status_code == 401
    assert "detail" in r.json()


def test_v1_transcribe_rejects_wrong_bearer() -> None:
    app = create_app(Settings(api_key="secret-token"))
    client = TestClient(app)
    r = client.post(
        "/v1/transcribe",
        data={"prompt": "{}"},
        files=[("files", ("a.jpg", b"\xff\xd8", "image/jpeg"))],
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 401


def test_v1_transcribe_accepts_valid_bearer_with_mocked_pipeline() -> None:
    app = create_app(Settings(api_key="good-key"))
    client = TestClient(app)
    fake_lines = Path("/tmp/fake-lines.xml")
    fake_yaml = Path("/tmp/fake-out.yaml")
    result = PipelineResult(
        job_id="a",
        lines_xml_path=fake_lines,
        transcription_yaml_path=fake_yaml,
        text_line_count=2,
        errors=[],
        warnings=[],
    )
    with patch("transcriber_shell.api.app.run_pipeline", return_value=result):
        r = client.post(
            "/v1/transcribe",
            data={"prompt": "{}"},
            files=[("files", ("stem.jpg", b"\xff\xd8", "image/jpeg"))],
            headers={"Authorization": "Bearer good-key"},
        )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["job_id"] == "a"
    assert body[0]["text_line_count"] == 2
    assert body[0]["errors"] == []


def test_v1_transcribe_skip_gm_rejected() -> None:
    app = create_app(Settings(api_key=None))
    client = TestClient(app)
    r = client.post(
        "/v1/transcribe",
        data={"prompt": "{}", "skip_gm": "true"},
        files=[("files", ("a.jpg", b"\xff\xd8", "image/jpeg"))],
    )
    assert r.status_code == 422
    assert "skip_gm" in r.json()["detail"].lower()


def test_v1_transcribe_no_files_returns_422() -> None:
    app = create_app(Settings(api_key=None))
    client = TestClient(app)
    r = client.post("/v1/transcribe", data={"prompt": "{}"})
    assert r.status_code == 422


def test_v1_transcribe_invalid_provider_returns_422() -> None:
    app = create_app(Settings(api_key=None))
    client = TestClient(app)
    r = client.post(
        "/v1/transcribe",
        data={"prompt": "{}", "provider": "not-a-provider"},
        files=[("files", ("a.jpg", b"\xff\xd8", "image/jpeg"))],
    )
    assert r.status_code == 422
