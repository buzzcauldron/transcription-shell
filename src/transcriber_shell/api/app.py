"""FastAPI app for multipart transcribe (optional dependency).

Note: avoid ``from __future__ import annotations`` here — it breaks FastAPI/Pydantic
OpenAPI generation for ``Request`` and multipart routes (see /openapi.json).
"""

import tempfile
from pathlib import Path
from typing import Any

from transcriber_shell import __version__ as _package_version
from transcriber_shell.config import Settings
from transcriber_shell.models.job import TranscribeJob
from transcriber_shell.pipeline.run import load_prompt_cfg_from_str, run_pipeline

_API_DESCRIPTION = """
**transcriber-shell** — manuscript transcription pipeline: lineation (mask / Kraken / Glyph Machina) → PageXML checks → LLM (Anthropic / OpenAI / Gemini) → protocol YAML validation.

**Interactive use:** run **`transcriber-shell gui`** for the desktop interface (recommended).

**HTTP:** `POST /v1/transcribe` with multipart `prompt` (YAML/JSON string) and `files` (images). Root `/` redirects to this documentation.

**Not on HTTP:** offline lines XML — use the CLI or GUI with **skip automated lineation** and a lines file.
""".strip()


def create_app(settings: Settings | None = None) -> Any:
    try:
        from fastapi import FastAPI, HTTPException, Request
        from starlette.datastructures import UploadFile
        from starlette.responses import JSONResponse, RedirectResponse
    except ImportError as e:
        raise RuntimeError("Install API extra: pip install 'transcriber-shell[api]'") from e

    s = settings or Settings()
    app = FastAPI(
        title="transcriber-shell",
        version=_package_version,
        description=_API_DESCRIPTION,
        swagger_ui_parameters={
            "docExpansion": "list",
            "tryItOutEnabled": True,
            "displayRequestDuration": True,
        },
        openapi_tags=[
            {"name": "ui", "description": "Browser-friendly entry points and docs."},
            {"name": "v1", "description": "Transcription API (multipart form)."},
        ],
    )

    @app.get("/", tags=["ui"], response_model=None)
    async def index() -> Any:
        """Avoid bare 404 at site root; send browsers to interactive API docs."""
        return RedirectResponse(url="/docs", status_code=307)

    # API key auth must not use Depends() on the same route as File+Form — it breaks OpenAPI
    # schema generation (Pydantic "class not fully defined" on /openapi.json).
    @app.middleware("http")
    async def api_key_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path.startswith("/v1/") and s.api_key:
            auth = request.headers.get("authorization") or ""
            if not auth.startswith("Bearer "):
                return JSONResponse(
                    {"detail": "missing or invalid Authorization"},
                    status_code=401,
                )
            token = auth.removeprefix("Bearer ").strip()
            if token != s.api_key:
                return JSONResponse({"detail": "invalid API key"}, status_code=401)
        return await call_next(request)

    def _form_bool(val: Any, default: bool = False) -> bool:
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        s = str(val).lower().strip()
        return s in ("1", "true", "yes", "on")

    @app.post(
        "/v1/transcribe",
        tags=["v1"],
        summary="Transcribe one or more images",
        description=(
            "Send **multipart/form-data** with fields: **`prompt`** (required, YAML or JSON string), "
            "**`files`** (one or more image parts, same field name), optional **`provider`**, **`model`**, "
            "**`inline_yaml`** (embed YAML text in the JSON response). "
            "Boolean form fields use strings like `true` / `false`. "
            "**`skip_gm`** is rejected here — use the CLI for offline lines XML."
        ),
    )
    async def transcribe_v1(request: Request) -> Any:
        form = await request.form()
        prompt = form.get("prompt")
        if not prompt or not isinstance(prompt, str):
            raise HTTPException(
                status_code=422,
                detail="prompt is required (YAML/JSON string in form field 'prompt')",
            )
        provider = form.get("provider")
        model = form.get("model")
        if isinstance(provider, str) and not provider.strip():
            provider = None
        if isinstance(model, str) and not model.strip():
            model = None
        skip_gm = _form_bool(form.get("skip_gm"), False)
        inline_yaml = _form_bool(form.get("inline_yaml"), False)

        file_parts = form.getlist("files")
        if not file_parts:
            single = form.get("files")
            file_parts = [single] if single is not None else []
        upload_files: list[UploadFile] = [f for f in file_parts if isinstance(f, UploadFile)]

        try:
            cfg = load_prompt_cfg_from_str(prompt)
        except (ValueError, OSError) as e:
            raise HTTPException(status_code=422, detail=f"invalid prompt: {e}") from e

        if skip_gm:
            raise HTTPException(
                status_code=422,
                detail="skip_gm is not supported on the HTTP API; use CLI with --lines-xml or --lines-xml-dir",
            )

        prov_raw = provider if isinstance(provider, str) else None
        prov = (prov_raw or s.default_provider).lower()
        if prov not in ("anthropic", "openai", "gemini", "ollama"):
            raise HTTPException(
                status_code=422,
                detail="provider must be anthropic, openai, gemini, or ollama",
            )

        model_override = model if isinstance(model, str) else None

        out: list[dict[str, Any]] = []
        for uf in upload_files:
            if not uf.filename:
                continue
            suffix = Path(uf.filename).suffix or ".jpg"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                body = await uf.read()
                tmp.write(body)
                tmp_path = Path(tmp.name)
            job_id = Path(uf.filename).stem[:120] or "job"
            job = TranscribeJob(
                job_id=job_id,
                image_path=tmp_path,
                prompt_cfg=cfg,
                provider=prov,
                model_override=model_override,
            )
            try:
                res = run_pipeline(
                    job,
                    skip_gm=False,
                    lines_xml_path=None,
                    require_text_line=True,
                    settings=s,
                )
            finally:
                tmp_path.unlink(missing_ok=True)

            item: dict[str, Any] = {
                "job_id": res.job_id,
                "errors": res.errors,
                "warnings": res.warnings,
                "text_line_count": res.text_line_count,
                "lines_xml_path": str(res.lines_xml_path) if res.lines_xml_path else None,
                "transcription_yaml_path": str(res.transcription_yaml_path)
                if res.transcription_yaml_path
                else None,
            }
            if inline_yaml and res.transcription_yaml_path and res.transcription_yaml_path.is_file():
                item["transcription_yaml"] = res.transcription_yaml_path.read_text(encoding="utf-8")
            out.append(item)

        if not out:
            raise HTTPException(status_code=422, detail="no files processed")
        return JSONResponse(content=out)

    @app.get("/health", tags=["ui"])
    async def health() -> dict[str, str]:
        """Liveness probe; no authentication required."""
        return {"status": "ok"}

    return app


# Uvicorn: transcriber_shell.api.app:app
app = create_app()
