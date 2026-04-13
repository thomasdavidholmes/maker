from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import uuid4

from .config import Settings
from .errors import GenerationError
from .models import NotebookArtifact, ProjectRecord, SampleProjectArtifact, content_type_labels


@dataclass(slots=True)
class MaterializedArtifact:
    bundle_path: str
    preview_metadata: dict[str, object]


class ArtifactBuilder:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def materialize_many(
        self,
        *,
        project: ProjectRecord,
        artifacts: list[tuple[str, NotebookArtifact | SampleProjectArtifact]],
    ) -> MaterializedArtifact:
        project_dir = self.settings.generated_dir / f"project-{project.id}"
        project_dir.mkdir(parents=True, exist_ok=True)

        token = uuid4().hex[:8]
        artifact_dir = project_dir / f"artifact-{token}"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        outputs: list[dict[str, object]] = []
        for content_type, artifact in artifacts:
            output_dir = artifact_dir / content_type
            output_dir.mkdir(parents=True, exist_ok=True)
            if isinstance(artifact, NotebookArtifact):
                output_preview = self._write_notebook(output_dir, artifact, content_type)
            else:
                output_preview = self._write_sample_project(output_dir, artifact, content_type)
            outputs.append(output_preview)

        bundle_path = shutil.make_archive(str(artifact_dir), "zip", root_dir=artifact_dir)
        preview_metadata = {
            "artifact_type": "multi_format",
            "summary": f"Generated {len(outputs)} courseware format(s): {', '.join(content_type_labels(project.content_types))}.",
            "outputs": outputs,
            "bundle_file": Path(bundle_path).name,
        }
        return MaterializedArtifact(bundle_path=bundle_path, preview_metadata=preview_metadata)

    def _write_notebook(
        self,
        artifact_dir: Path,
        artifact: NotebookArtifact,
        content_type: str,
    ) -> dict[str, object]:
        notebook_path = artifact_dir / self._safe_filename(artifact.filename, ".ipynb")
        notebook = {
            "cells": [self._notebook_cell(cell.cell_type, cell.source) for cell in artifact.cells],
            "metadata": {
                "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                "language_info": {"name": "python"},
                "maker": {"content_type": content_type, "title": artifact.title},
            },
            "nbformat": 4,
            "nbformat_minor": 5,
        }
        notebook_path.write_text(json.dumps(notebook, indent=2), encoding="utf-8")

        summary_path = artifact_dir / "README.txt"
        summary_path.write_text(
            f"{artifact.title}\n\n{artifact.summary}\n",
            encoding="utf-8",
        )
        return {
            "content_type": content_type,
            "summary": artifact.summary,
            "files": [
                f"{artifact_dir.name}/{notebook_path.name}",
                f"{artifact_dir.name}/{summary_path.name}",
            ],
        }

    def _write_sample_project(
        self,
        artifact_dir: Path,
        artifact: SampleProjectArtifact,
        content_type: str,
    ) -> dict[str, object]:
        project_root = artifact_dir / self._safe_directory_name(artifact.project_name)
        project_root.mkdir(parents=True, exist_ok=True)
        starter_root = project_root / "starter"
        solution_root = project_root / "solution"
        starter_root.mkdir(parents=True, exist_ok=True)
        solution_root.mkdir(parents=True, exist_ok=True)

        created_files: list[str] = []
        for generated_file in artifact.starter_files:
            relative_path = self._safe_relative_path(generated_file.path)
            output_path = starter_root / relative_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(generated_file.content, encoding="utf-8")
            relative_text = str(relative_path).replace("\\", "/")
            created_files.append(f"{artifact_dir.name}/{project_root.name}/starter/{relative_text}")

        for generated_file in artifact.solution_files:
            relative_path = self._safe_relative_path(generated_file.path)
            output_path = solution_root / relative_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(generated_file.content, encoding="utf-8")
            relative_text = str(relative_path).replace("\\", "/")
            created_files.append(f"{artifact_dir.name}/{project_root.name}/solution/{relative_text}")

        readme_path = project_root / "ARTIFACT_SUMMARY.md"
        exercises_text = "\n".join(
            f"## {section.title}\nGoal: {section.learner_goal}\n\n{section.instructions}\n"
            for section in artifact.exercise_sections
        )
        readme_path.write_text(
            f"# {artifact.project_name}\n\n"
            f"Stack: {artifact.inferred_stack}\n\n"
            f"{artifact.summary}\n\n"
            f"## Learner outcome\n\n{artifact.learner_outcome}\n\n"
            f"## Run instructions\n\n{artifact.run_instructions}\n\n"
            f"## Exercise sections\n\n{exercises_text}\n",
            encoding="utf-8",
        )
        created_files.append(f"{artifact_dir.name}/{project_root.name}/ARTIFACT_SUMMARY.md")
        return {
            "content_type": content_type,
            "summary": artifact.summary,
            "stack": artifact.inferred_stack,
            "files": created_files,
        }

    def _notebook_cell(self, cell_type: str, source: str) -> dict[str, object]:
        if cell_type not in {"markdown", "code"}:
            raise GenerationError(f"Unsupported notebook cell type: {cell_type}")
        cell: dict[str, object] = {"cell_type": cell_type, "metadata": {}, "source": source.splitlines(keepends=True)}
        if cell_type == "code":
            cell["execution_count"] = None
            cell["outputs"] = []
        return cell

    def _safe_filename(self, filename: str, suffix: str) -> str:
        safe = filename.replace("/", "-").replace("\\", "-").strip()
        if not safe.endswith(suffix):
            safe = f"{safe}{suffix}"
        return safe or f"artifact{suffix}"

    def _safe_directory_name(self, name: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in name.strip())
        return cleaned.strip("-") or "sample-project"

    def _safe_relative_path(self, relative_path: str) -> Path:
        candidate = PurePosixPath(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise GenerationError(f"Unsafe generated file path: {relative_path}")
        return Path(*candidate.parts)
