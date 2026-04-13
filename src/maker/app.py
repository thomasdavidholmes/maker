from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .agents import CONTENT_TYPE_LABELS
from .config import Settings, ensure_directories, get_settings
from .errors import MakerError, NotFoundError
from .logging_utils import configure_logging
from .models import CONTENT_TYPE_OPTIONS, MODEL_CLASS_OPTIONS, TARGET_LEVELS
from .repository import Repository
from .services import MakerService


def create_app(
    settings: Settings | None = None,
    *,
    repository: Repository | None = None,
    orchestrator=None,
) -> FastAPI:
    settings = settings or get_settings()
    ensure_directories(settings)
    logger = configure_logging(settings)
    repository = repository or Repository(settings.db_path)
    repository.init_db()

    service = MakerService(
        settings=settings,
        repository=repository,
        orchestrator=orchestrator,
    )

    app = FastAPI(title=settings.app_name)
    app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
    templates = Jinja2Templates(directory=str(settings.templates_dir))

    templates.env.globals["content_type_labels"] = CONTENT_TYPE_LABELS
    templates.env.globals["supported_uploads"] = "pdf, docx, pptx, txt, md, html, zip"

    app.state.service = service
    app.state.templates = templates
    app.state.settings = settings
    app.state.logger = logger
    app.state.jobs = set()

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        return _render_dashboard(request)

    @app.post("/projects", response_class=HTMLResponse)
    async def create_project(
        request: Request,
        title: str = Form(default=""),
        brief: str = Form(...),
        content_types: list[str] = Form(default=[]),
        model_class: str = Form(default="5.4"),
        target_level: str = Form(...),
        duration_text: str = Form(default=""),
        supporting_files: list[UploadFile] = File(default=[]),
    ) -> Response:
        service: MakerService = request.app.state.service
        try:
            project = await service.create_project(
                title=title,
                brief=brief,
                content_types=content_types,
                model_class=model_class,
                target_level=target_level,
                duration_text=duration_text,
                uploads=supporting_files,
            )
        except MakerError as exc:
            return _render_dashboard(request, error=str(exc), status_code=400)
        return RedirectResponse(url=f"/projects/{project.id}", status_code=303)

    @app.get("/projects/{project_id}", response_class=HTMLResponse)
    async def project_detail(request: Request, project_id: int) -> HTMLResponse:
        return _render_project(request, project_id)

    @app.post("/projects/{project_id}/plan")
    async def generate_initial_plan(request: Request, project_id: int) -> RedirectResponse:
        service: MakerService = request.app.state.service
        try:
            snapshot = service.get_snapshot(project_id)
            if snapshot.project.status in {"planning", "generating"}:
                return _redirect_to_project(project_id, error="Work is already in progress for this project.")
            _schedule_job(request, project_id, service.generate_initial_plan(project_id))
            return _redirect_to_project(project_id, message="Draft plan generation started.")
        except MakerError as exc:
            return _redirect_to_project(project_id, error=str(exc))

    @app.post("/projects/{project_id}/revisions/{revision_id}/revise")
    async def revise_plan(
        request: Request,
        project_id: int,
        revision_id: int,
        edited_outline: str = Form(...),
        trainer_feedback: str = Form(default=""),
    ) -> RedirectResponse:
        service: MakerService = request.app.state.service
        try:
            snapshot = service.get_snapshot(project_id)
            if snapshot.project.status in {"planning", "generating"}:
                return _redirect_to_project(project_id, error="Work is already in progress for this project.")
            _schedule_job(
                request,
                project_id,
                service.revise_plan(
                    project_id=project_id,
                    revision_id=revision_id,
                    edited_outline=edited_outline,
                    trainer_feedback=trainer_feedback,
                ),
            )
            return _redirect_to_project(project_id, message="Revision generation started.")
        except MakerError as exc:
            return _redirect_to_project(project_id, error=str(exc))

    @app.post("/projects/{project_id}/revisions/{revision_id}/approve")
    async def approve_and_generate(request: Request, project_id: int, revision_id: int) -> RedirectResponse:
        service: MakerService = request.app.state.service
        try:
            snapshot = service.get_snapshot(project_id)
            if snapshot.project.status in {"planning", "generating"}:
                return _redirect_to_project(project_id, error="Work is already in progress for this project.")
            _schedule_job(
                request,
                project_id,
                service.approve_and_generate(project_id=project_id, revision_id=revision_id),
            )
            return _redirect_to_project(project_id, message="Content generation started.")
        except MakerError as exc:
            return _redirect_to_project(project_id, error=str(exc))

    @app.get("/projects/{project_id}/status")
    async def project_status(request: Request, project_id: int) -> JSONResponse:
        service: MakerService = request.app.state.service
        snapshot = service.get_snapshot(project_id)
        return JSONResponse(
            {
                "project_id": project_id,
                "status": snapshot.project.status,
                "progress_phase": snapshot.project.progress_phase,
                "progress_message": snapshot.project.progress_message,
                "progress_percent": snapshot.project.progress_percent,
                "has_revision": bool(snapshot.revisions),
                "has_artifact": snapshot.latest_artifact is not None,
            }
        )

    @app.get("/projects/{project_id}/artifacts/{artifact_id}/download")
    async def download_artifact(request: Request, project_id: int, artifact_id: int) -> FileResponse:
        service: MakerService = request.app.state.service
        snapshot = service.get_snapshot(project_id)
        artifact = snapshot.latest_artifact
        if artifact is None or artifact.id != artifact_id:
            raise NotFoundError("Artifact bundle not found.")
        bundle_path = Path(artifact.bundle_path)
        return FileResponse(bundle_path, filename=bundle_path.name, media_type="application/zip")

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError) -> HTMLResponse:
        return _render_dashboard(request, error=str(exc), status_code=404)

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> HTMLResponse | RedirectResponse:
        request.app.state.logger.exception(
            "Unhandled exception for %s %s",
            request.method,
            request.url.path,
            exc_info=exc,
        )
        project_id = request.path_params.get("project_id")
        if project_id is not None:
            return _redirect_to_project(
                int(project_id),
                error=(
                    "An internal server error occurred. "
                    f"See {request.app.state.settings.log_file} for details."
                ),
            )
        return _render_dashboard(
            request,
            error=(
                "An internal server error occurred. "
                f"See {request.app.state.settings.log_file} for details."
            ),
            status_code=500,
        )

    return app


def _render_dashboard(
    request: Request,
    *,
    error: str | None = None,
    message: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    service: MakerService = request.app.state.service
    templates: Jinja2Templates = request.app.state.templates
    context = {
        "request": request,
        "projects": service.list_projects(),
        "content_types": CONTENT_TYPE_OPTIONS,
        "model_classes": MODEL_CLASS_OPTIONS,
        "target_levels": TARGET_LEVELS,
        "message": message or request.query_params.get("message"),
        "error": error or request.query_params.get("error"),
    }
    return templates.TemplateResponse(request, "index.html", context, status_code=status_code)


def _render_project(
    request: Request,
    project_id: int,
    *,
    error: str | None = None,
    message: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    service: MakerService = request.app.state.service
    templates: Jinja2Templates = request.app.state.templates
    snapshot = service.get_snapshot(project_id)
    current_revision = snapshot.revisions[0] if snapshot.revisions else None
    context = {
        "request": request,
        "snapshot": snapshot,
        "current_revision": current_revision,
        "content_type_labels": CONTENT_TYPE_LABELS,
        "message": message or request.query_params.get("message"),
        "error": error or request.query_params.get("error"),
    }
    return templates.TemplateResponse(request, "project_detail.html", context, status_code=status_code)


def _redirect_to_project(project_id: int, *, message: str | None = None, error: str | None = None) -> RedirectResponse:
    params = urlencode({key: value for key, value in {"message": message, "error": error}.items() if value})
    suffix = f"?{params}" if params else ""
    return RedirectResponse(url=f"/projects/{project_id}{suffix}", status_code=303)


def _schedule_job(request: Request, project_id: int, coroutine) -> None:
    task = asyncio.create_task(_run_project_job(request, project_id, coroutine))
    request.app.state.jobs.add(task)
    task.add_done_callback(request.app.state.jobs.discard)


async def _run_project_job(request: Request, project_id: int, coroutine) -> None:
    service: MakerService = request.app.state.service
    try:
        await coroutine
    except MakerError as exc:
        service.repository.update_project_progress(
            project_id,
            status="error",
            progress_phase="failed",
            progress_message=str(exc),
            progress_percent=100,
        )
        request.app.state.logger.warning("Project %s job failed: %s", project_id, exc)
    except Exception as exc:  # pragma: no cover - defensive branch
        service.repository.update_project_progress(
            project_id,
            status="error",
            progress_phase="failed",
            progress_message=f"Unexpected failure. See {request.app.state.settings.log_file} for details.",
            progress_percent=100,
        )
        request.app.state.logger.exception("Project %s background job failed", project_id, exc_info=exc)


app = create_app()
