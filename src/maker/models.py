from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

CONTENT_TYPE_OPTIONS = [
    ("notebook_demo", "Jupyter notebook demonstration"),
    ("notebook_exercise", "Jupyter notebook exercise"),
    ("sample_project", "Extended project"),
]

MODEL_CLASS_OPTIONS = [
    ("5.1", "gpt-5.1"),
    ("5.2", "gpt-5.2"),
    ("5.3", "gpt-5.3-codex"),
    ("5.4", "gpt-5.4"),
    ("5-mini", "gpt-5-mini"),
    ("5-nano", "gpt-5-nano"),
    ("5.4-mini", "gpt-5.4-mini"),
    ("5.4-nano", "gpt-5.4-nano"),
]

TARGET_LEVELS = [
    "Beginner",
    "Intermediate",
    "Advanced",
    "Expert",
]

PROJECT_STATUSES = {
    "draft",
    "planning",
    "plan_ready",
    "approved",
    "generated",
    "error",
}

REVISION_STATUSES = {
    "draft",
    "approved",
    "superseded",
    "generation_failed",
    "generated",
}


def parse_content_types(raw_value: str) -> list[str]:
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        parsed = raw_value
    if isinstance(parsed, str):
        values = [parsed]
    else:
        values = [str(item) for item in parsed]
    allowed = {value for value, _label in CONTENT_TYPE_OPTIONS}
    return [value for value in values if value in allowed]


def serialize_content_types(content_types: list[str]) -> str:
    return json.dumps(content_types)


def content_type_labels(content_types: list[str]) -> list[str]:
    label_map = dict(CONTENT_TYPE_OPTIONS)
    return [label_map[value] for value in content_types if value in label_map]


@dataclass(slots=True)
class ProjectRecord:
    id: int
    title: str
    brief: str
    content_types: list[str]
    model_class: str
    target_level: str
    duration_text: str
    status: str
    progress_phase: str | None
    progress_message: str | None
    progress_percent: int
    created_at: str
    updated_at: str

    @property
    def primary_content_type(self) -> str | None:
        return self.content_types[0] if self.content_types else None

    @property
    def content_type_labels(self) -> list[str]:
        return content_type_labels(self.content_types)


@dataclass(slots=True)
class SourceFileRecord:
    id: int
    project_id: int
    original_name: str
    media_type: str
    stored_path: str
    extracted_text_path: str | None
    extraction_status: str
    metadata_json: dict[str, Any]
    created_at: str


@dataclass(slots=True)
class PlanRevisionRecord:
    id: int
    project_id: int
    revision_number: int
    agent_plan_text: str
    editable_outline_text: str
    trainer_feedback_text: str | None
    status: str
    created_at: str


@dataclass(slots=True)
class ArtifactBundleRecord:
    id: int
    project_id: int
    approved_revision_id: int
    bundle_path: str
    preview_metadata: dict[str, Any]
    created_at: str


@dataclass(slots=True)
class ProjectSnapshot:
    project: ProjectRecord
    source_files: list[SourceFileRecord]
    revisions: list[PlanRevisionRecord]
    latest_artifact: ArtifactBundleRecord | None


class NotebookCell(BaseModel):
    cell_type: str = Field(description="markdown or code")
    source: str = Field(description="Raw cell source text")


class NotebookArtifact(BaseModel):
    filename: str = Field(description="Notebook filename ending in .ipynb")
    title: str
    summary: str
    cells: list[NotebookCell]


class ProjectFileArtifact(BaseModel):
    path: str = Field(description="Relative file path inside the project")
    description: str
    content: str


class ProjectExerciseSection(BaseModel):
    title: str
    learner_goal: str
    instructions: str


class SampleProjectArtifact(BaseModel):
    project_name: str
    inferred_stack: str
    summary: str
    run_instructions: str
    learner_outcome: str
    exercise_sections: list[ProjectExerciseSection]
    starter_files: list[ProjectFileArtifact]
    solution_files: list[ProjectFileArtifact]
