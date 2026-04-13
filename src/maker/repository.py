from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import (
    ArtifactBundleRecord,
    PlanRevisionRecord,
    ProjectRecord,
    ProjectSnapshot,
    SourceFileRecord,
    parse_content_types,
    serialize_content_types,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init_db(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    brief TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    quality_mode TEXT NOT NULL DEFAULT 'balanced',
                    model_class TEXT NOT NULL DEFAULT '5.4',
                    target_level TEXT NOT NULL,
                    duration_text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress_phase TEXT,
                    progress_message TEXT,
                    progress_percent INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS source_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    original_name TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    extracted_text_path TEXT,
                    extraction_status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plan_revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    revision_number INTEGER NOT NULL,
                    agent_plan_text TEXT NOT NULL,
                    editable_outline_text TEXT NOT NULL,
                    trainer_feedback_text TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, revision_number)
                );

                CREATE TABLE IF NOT EXISTS artifact_bundles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    approved_revision_id INTEGER NOT NULL REFERENCES plan_revisions(id),
                    bundle_path TEXT NOT NULL,
                    preview_metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_project_column(connection, "quality_mode", "TEXT NOT NULL DEFAULT 'balanced'")
            self._ensure_project_column(connection, "model_class", "TEXT NOT NULL DEFAULT '5.4'")
            self._ensure_project_column(connection, "progress_phase", "TEXT")
            self._ensure_project_column(connection, "progress_message", "TEXT")
            self._ensure_project_column(connection, "progress_percent", "INTEGER NOT NULL DEFAULT 0")

    def list_projects(self) -> list[ProjectRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM projects
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()
        return [self._row_to_project(row) for row in rows]

    def create_project(
        self,
        *,
        title: str,
        brief: str,
        content_types: list[str],
        model_class: str,
        target_level: str,
        duration_text: str,
    ) -> ProjectRecord:
        created_at = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO projects (
                    title, brief, content_type, quality_mode, model_class, target_level, duration_text,
                    status, progress_phase, progress_message, progress_percent, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    brief,
                    serialize_content_types(content_types),
                    "balanced",
                    model_class,
                    target_level,
                    duration_text,
                    "draft",
                    None,
                    None,
                    0,
                    created_at,
                    created_at,
                ),
            )
            project_id = int(cursor.lastrowid)
            row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return self._row_to_project(row)

    def get_project(self, project_id: int) -> ProjectRecord | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return self._row_to_project(row) if row else None

    def update_project_status(self, project_id: int, status: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
                (status, utc_now(), project_id),
            )

    def update_project_progress(
        self,
        project_id: int,
        *,
        status: str | None = None,
        progress_phase: str | None = None,
        progress_message: str | None = None,
        progress_percent: int | None = None,
    ) -> None:
        assignments: list[str] = ["updated_at = ?"]
        values: list[Any] = [utc_now()]
        if status is not None:
            assignments.append("status = ?")
            values.append(status)
        if progress_phase is not None:
            assignments.append("progress_phase = ?")
            values.append(progress_phase)
        if progress_message is not None:
            assignments.append("progress_message = ?")
            values.append(progress_message)
        if progress_percent is not None:
            assignments.append("progress_percent = ?")
            values.append(progress_percent)
        values.append(project_id)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE projects SET {', '.join(assignments)} WHERE id = ?",
                tuple(values),
            )

    def clear_project_progress(self, project_id: int, *, status: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE projects
                SET status = ?, progress_phase = NULL, progress_message = NULL, progress_percent = 100, updated_at = ?
                WHERE id = ?
                """,
                (status, utc_now(), project_id),
            )

    def add_source_file(
        self,
        *,
        project_id: int,
        original_name: str,
        media_type: str,
        stored_path: str,
        extracted_text_path: str | None,
        extraction_status: str,
        metadata_json: dict[str, Any],
    ) -> SourceFileRecord:
        created_at = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO source_files (
                    project_id, original_name, media_type, stored_path, extracted_text_path,
                    extraction_status, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    original_name,
                    media_type,
                    stored_path,
                    extracted_text_path,
                    extraction_status,
                    json.dumps(metadata_json),
                    created_at,
                ),
            )
            file_id = int(cursor.lastrowid)
            row = connection.execute("SELECT * FROM source_files WHERE id = ?", (file_id,)).fetchone()
        return self._row_to_source_file(row)

    def list_source_files(self, project_id: int) -> list[SourceFileRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM source_files
                WHERE project_id = ?
                ORDER BY id ASC
                """,
                (project_id,),
            ).fetchall()
        return [self._row_to_source_file(row) for row in rows]

    def create_plan_revision(
        self,
        *,
        project_id: int,
        agent_plan_text: str,
        editable_outline_text: str,
        trainer_feedback_text: str | None,
        status: str = "draft",
    ) -> PlanRevisionRecord:
        created_at = utc_now()
        with self.connect() as connection:
            next_revision = connection.execute(
                "SELECT COALESCE(MAX(revision_number), 0) + 1 FROM plan_revisions WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
            connection.execute(
                """
                UPDATE plan_revisions
                SET status = 'superseded'
                WHERE project_id = ? AND status = 'draft'
                """,
                (project_id,),
            )
            cursor = connection.execute(
                """
                INSERT INTO plan_revisions (
                    project_id, revision_number, agent_plan_text, editable_outline_text,
                    trainer_feedback_text, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    next_revision,
                    agent_plan_text,
                    editable_outline_text,
                    trainer_feedback_text,
                    status,
                    created_at,
                ),
            )
            revision_id = int(cursor.lastrowid)
            connection.execute(
                """
                UPDATE projects
                SET status = ?, progress_phase = NULL, progress_message = NULL, progress_percent = 100, updated_at = ?
                WHERE id = ?
                """,
                ("plan_ready", utc_now(), project_id),
            )
            row = connection.execute("SELECT * FROM plan_revisions WHERE id = ?", (revision_id,)).fetchone()
        return self._row_to_revision(row)

    def get_revision(self, revision_id: int) -> PlanRevisionRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM plan_revisions WHERE id = ?",
                (revision_id,),
            ).fetchone()
        return self._row_to_revision(row) if row else None

    def list_revisions(self, project_id: int) -> list[PlanRevisionRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM plan_revisions
                WHERE project_id = ?
                ORDER BY revision_number DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._row_to_revision(row) for row in rows]

    def approve_revision(self, revision_id: int) -> PlanRevisionRecord:
        with self.connect() as connection:
            revision_row = connection.execute(
                "SELECT project_id FROM plan_revisions WHERE id = ?",
                (revision_id,),
            ).fetchone()
            if revision_row is None:
                raise ValueError("Revision not found")
            project_id = revision_row["project_id"]
            connection.execute(
                """
                UPDATE plan_revisions
                SET status = 'superseded'
                WHERE project_id = ? AND status = 'draft' AND id != ?
                """,
                (project_id, revision_id),
            )
            connection.execute(
                "UPDATE plan_revisions SET status = 'approved' WHERE id = ?",
                (revision_id,),
            )
            connection.execute(
                """
                UPDATE projects
                SET status = ?, progress_phase = NULL, progress_message = NULL, progress_percent = 100, updated_at = ?
                WHERE id = ?
                """,
                ("approved", utc_now(), project_id),
            )
            row = connection.execute("SELECT * FROM plan_revisions WHERE id = ?", (revision_id,)).fetchone()
        return self._row_to_revision(row)

    def mark_revision_generated(self, revision_id: int) -> None:
        with self.connect() as connection:
            revision_row = connection.execute(
                "SELECT project_id FROM plan_revisions WHERE id = ?",
                (revision_id,),
            ).fetchone()
            if revision_row is None:
                return
            connection.execute("UPDATE plan_revisions SET status = 'generated' WHERE id = ?", (revision_id,))
            connection.execute(
                """
                UPDATE projects
                SET status = ?, progress_phase = NULL, progress_message = NULL, progress_percent = 100, updated_at = ?
                WHERE id = ?
                """,
                ("generated", utc_now(), revision_row["project_id"]),
            )

    def mark_revision_generation_failed(self, revision_id: int) -> None:
        with self.connect() as connection:
            revision_row = connection.execute(
                "SELECT project_id FROM plan_revisions WHERE id = ?",
                (revision_id,),
            ).fetchone()
            if revision_row is None:
                return
            connection.execute(
                "UPDATE plan_revisions SET status = 'generation_failed' WHERE id = ?",
                (revision_id,),
            )
            connection.execute(
                """
                UPDATE projects
                SET status = ?, progress_phase = ?, progress_message = ?, progress_percent = ?, updated_at = ?
                WHERE id = ?
                """,
                ("error", "failed", "Generation failed. Check the project page or logs for details.", 100, utc_now(), revision_row["project_id"]),
            )

    def create_artifact_bundle(
        self,
        *,
        project_id: int,
        approved_revision_id: int,
        bundle_path: str,
        preview_metadata: dict[str, Any],
    ) -> ArtifactBundleRecord:
        created_at = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO artifact_bundles (
                    project_id, approved_revision_id, bundle_path, preview_metadata, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (project_id, approved_revision_id, bundle_path, json.dumps(preview_metadata), created_at),
            )
            artifact_id = int(cursor.lastrowid)
            row = connection.execute("SELECT * FROM artifact_bundles WHERE id = ?", (artifact_id,)).fetchone()
        return self._row_to_artifact(row)

    def get_artifact_bundle(self, artifact_id: int) -> ArtifactBundleRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM artifact_bundles WHERE id = ?",
                (artifact_id,),
            ).fetchone()
        return self._row_to_artifact(row) if row else None

    def get_latest_artifact_for_project(self, project_id: int) -> ArtifactBundleRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM artifact_bundles
                WHERE project_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
        return self._row_to_artifact(row) if row else None

    def get_snapshot(self, project_id: int) -> ProjectSnapshot | None:
        project = self.get_project(project_id)
        if project is None:
            return None
        return ProjectSnapshot(
            project=project,
            source_files=self.list_source_files(project_id),
            revisions=self.list_revisions(project_id),
            latest_artifact=self.get_latest_artifact_for_project(project_id),
        )

    def _row_to_project(self, row: sqlite3.Row) -> ProjectRecord:
        model_class = row["model_class"] or self._model_class_from_legacy_quality(row["quality_mode"])
        return ProjectRecord(
            id=row["id"],
            title=row["title"],
            brief=row["brief"],
            content_types=parse_content_types(row["content_type"]),
            model_class=model_class,
            target_level=row["target_level"],
            duration_text=row["duration_text"],
            status=row["status"],
            progress_phase=row["progress_phase"],
            progress_message=row["progress_message"],
            progress_percent=row["progress_percent"] or 0,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _model_class_from_legacy_quality(self, quality_mode: str | None) -> str:
        mapping = {
            "fast": "5.1",
            "balanced": "5.2",
            "high": "5.4",
            "ultra": "5.4",
        }
        return mapping.get((quality_mode or "").strip(), "5.4")

    def _ensure_project_column(self, connection: sqlite3.Connection, name: str, definition: str) -> None:
        existing = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(projects)").fetchall()
        }
        if name not in existing:
            connection.execute(f"ALTER TABLE projects ADD COLUMN {name} {definition}")

    def _row_to_source_file(self, row: sqlite3.Row) -> SourceFileRecord:
        return SourceFileRecord(
            id=row["id"],
            project_id=row["project_id"],
            original_name=row["original_name"],
            media_type=row["media_type"],
            stored_path=row["stored_path"],
            extracted_text_path=row["extracted_text_path"],
            extraction_status=row["extraction_status"],
            metadata_json=json.loads(row["metadata_json"] or "{}"),
            created_at=row["created_at"],
        )

    def _row_to_revision(self, row: sqlite3.Row) -> PlanRevisionRecord:
        return PlanRevisionRecord(
            id=row["id"],
            project_id=row["project_id"],
            revision_number=row["revision_number"],
            agent_plan_text=row["agent_plan_text"],
            editable_outline_text=row["editable_outline_text"],
            trainer_feedback_text=row["trainer_feedback_text"],
            status=row["status"],
            created_at=row["created_at"],
        )

    def _row_to_artifact(self, row: sqlite3.Row) -> ArtifactBundleRecord:
        return ArtifactBundleRecord(
            id=row["id"],
            project_id=row["project_id"],
            approved_revision_id=row["approved_revision_id"],
            bundle_path=row["bundle_path"],
            preview_metadata=json.loads(row["preview_metadata"] or "{}"),
            created_at=row["created_at"],
        )
