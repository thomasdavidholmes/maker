from __future__ import annotations

from typing import Iterable

from fastapi import UploadFile

from .agents import OpenAIAgentOrchestrator, Orchestrator
from .config import Settings
from .errors import GenerationError, NotFoundError, ValidationError
from .files import StoredUpload, is_supported_filename, store_upload
from .generation import ArtifactBuilder
from .models import CONTENT_TYPE_OPTIONS, MODEL_CLASS_OPTIONS, ArtifactBundleRecord, PlanRevisionRecord, ProjectSnapshot
from .repository import Repository


class MakerService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: Repository,
        orchestrator: Orchestrator | None = None,
        artifact_builder: ArtifactBuilder | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.orchestrator = orchestrator
        self.artifact_builder = artifact_builder or ArtifactBuilder(settings)

    def list_projects(self):
        return self.repository.list_projects()

    def get_snapshot(self, project_id: int) -> ProjectSnapshot:
        snapshot = self.repository.get_snapshot(project_id)
        if snapshot is None:
            raise NotFoundError("Project not found.")
        return snapshot

    async def create_project(
        self,
        *,
        title: str,
        brief: str,
        content_types: list[str],
        model_class: str,
        target_level: str,
        duration_text: str,
        uploads: Iterable[UploadFile],
    ):
        normalized_title = title.strip() or self._derive_title(brief)
        allowed_content_types = dict(CONTENT_TYPE_OPTIONS)
        allowed_model_classes = {value for value, _label in MODEL_CLASS_OPTIONS}
        selected_content_types = [value for value in content_types if value in allowed_content_types]
        if not selected_content_types:
            raise ValidationError("Select at least one courseware format.")
        if model_class not in allowed_model_classes:
            raise ValidationError("Unsupported model class selected.")
        if not brief.strip():
            raise ValidationError("A project brief is required.")

        project = self.repository.create_project(
            title=normalized_title,
            brief=brief.strip(),
            content_types=selected_content_types,
            model_class=model_class.strip() or "5.4",
            target_level=target_level.strip() or "Beginner",
            duration_text=duration_text.strip() or "Not specified",
        )

        for upload in uploads:
            if not upload.filename:
                continue
            if not is_supported_filename(upload.filename):
                raise ValidationError(
                    f"Unsupported file type for '{upload.filename}'. Supported types: pdf, docx, pptx, txt, md, html, zip."
                )
            stored_upload = await store_upload(project_id=project.id, upload=upload, settings=self.settings)
            self._save_upload(project.id, stored_upload)
        return project

    async def generate_initial_plan(self, project_id: int) -> PlanRevisionRecord:
        snapshot = self.get_snapshot(project_id)
        self._progress(project_id, status="planning", phase="starting", message="Preparing project context.", percent=10)
        self._progress(project_id, phase="ingesting", message="Reading uploads and assembling source context.", percent=30)
        plan_text = await self._orchestrator().generate_initial_plan(snapshot.project, snapshot.source_files)
        return self.repository.create_plan_revision(
            project_id=project_id,
            agent_plan_text=plan_text,
            editable_outline_text=plan_text,
            trainer_feedback_text=None,
        )

    async def revise_plan(
        self,
        *,
        project_id: int,
        revision_id: int,
        edited_outline: str,
        trainer_feedback: str,
    ) -> PlanRevisionRecord:
        snapshot = self.get_snapshot(project_id)
        revision = self._get_revision(snapshot, revision_id)
        if revision.status not in {"draft", "generation_failed"}:
            raise ValidationError("Only the latest editable revision can be revised.")
        self._progress(project_id, status="planning", phase="starting", message="Preparing revision request.", percent=10)
        self._progress(project_id, phase="revising", message="Reworking the outline with your edits and feedback.", percent=45)
        plan_text = await self._orchestrator().revise_plan(
            snapshot.project,
            snapshot.source_files,
            edited_outline.strip() or revision.editable_outline_text,
            trainer_feedback.strip(),
        )
        return self.repository.create_plan_revision(
            project_id=project_id,
            agent_plan_text=plan_text,
            editable_outline_text=plan_text,
            trainer_feedback_text=trainer_feedback.strip() or None,
        )

    async def approve_and_generate(self, *, project_id: int, revision_id: int) -> ArtifactBundleRecord:
        snapshot = self.get_snapshot(project_id)
        revision = self._get_revision(snapshot, revision_id)
        if revision.status == "generated":
            latest = snapshot.latest_artifact
            if latest is None:
                raise GenerationError("The revision is marked generated but no artifact bundle was found.")
            return latest
        if revision.status == "draft":
            revision = self.repository.approve_revision(revision_id)
        elif revision.status == "generation_failed":
            revision = self.repository.approve_revision(revision_id)
        elif revision.status != "approved":
            raise ValidationError("Only approved or draft revisions can generate files.")

        try:
            format_count = max(len(snapshot.project.content_types), 1)
            self._progress(
                project_id,
                status="generating",
                phase="starting",
                message="Preparing approved outline for content generation.",
                percent=8,
            )
            generated_outputs = []
            for index, content_type in enumerate(snapshot.project.content_types, start=1):
                start_percent = 15 + int(((index - 1) / format_count) * 70)
                finish_percent = 15 + int((index / format_count) * 70)
                self._progress(
                    project_id,
                    phase="generating",
                    message=f"Generating {content_type.replace('_', ' ')} ({index}/{format_count}).",
                    percent=start_percent,
                )
                artifact = await self._orchestrator().generate_artifact(
                    snapshot.project,
                    snapshot.source_files,
                    revision,
                    content_type,
                )
                generated_outputs.append((content_type, artifact))
                self._progress(
                    project_id,
                    phase="packaging",
                    message=f"Finished {content_type.replace('_', ' ')} ({index}/{format_count}).",
                    percent=finish_percent,
                )
            self._progress(project_id, phase="packaging", message="Packaging outputs into a downloadable bundle.", percent=92)
            materialized = self.artifact_builder.materialize_many(
                project=snapshot.project,
                artifacts=generated_outputs,
            )
            bundle = self.repository.create_artifact_bundle(
                project_id=project_id,
                approved_revision_id=revision.id,
                bundle_path=materialized.bundle_path,
                preview_metadata=materialized.preview_metadata,
            )
            self.repository.mark_revision_generated(revision.id)
            return bundle
        except Exception as exc:
            self.repository.mark_revision_generation_failed(revision.id)
            raise GenerationError(str(exc)) from exc

    def _save_upload(self, project_id: int, stored_upload: StoredUpload) -> None:
        self.repository.add_source_file(
            project_id=project_id,
            original_name=stored_upload.original_name,
            media_type=stored_upload.media_type,
            stored_path=stored_upload.stored_path,
            extracted_text_path=stored_upload.extracted_text_path,
            extraction_status=stored_upload.extraction_status,
            metadata_json=stored_upload.metadata_json,
        )

    def _derive_title(self, brief: str) -> str:
        first_line = next((line.strip() for line in brief.splitlines() if line.strip()), "New courseware project")
        return " ".join(first_line.split()[:8])[:80]

    def _get_revision(self, snapshot: ProjectSnapshot, revision_id: int) -> PlanRevisionRecord:
        revision = next((item for item in snapshot.revisions if item.id == revision_id), None)
        if revision is None:
            raise NotFoundError("Revision not found for this project.")
        return revision

    def _orchestrator(self) -> Orchestrator:
        if self.orchestrator is None:
            self.orchestrator = OpenAIAgentOrchestrator(self.settings)
        return self.orchestrator

    def _progress(self, project_id: int, *, status: str | None = None, phase: str, message: str, percent: int) -> None:
        self.repository.update_project_progress(
            project_id,
            status=status,
            progress_phase=phase,
            progress_message=message,
            progress_percent=percent,
        )
