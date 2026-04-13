from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from maker.app import create_app
from maker.config import Settings
from maker.models import NotebookArtifact, NotebookCell, PlanRevisionRecord, ProjectRecord, SampleProjectArtifact, SourceFileRecord


class FakeOrchestrator:
    async def generate_initial_plan(self, project: ProjectRecord, source_files: list[SourceFileRecord]) -> str:
        return (
            f"# {project.title}\n\n"
            "1. Welcome and goals (15 min)\n"
            "2. Guided walkthrough (35 min)\n"
            "3. Learner activity (25 min)\n"
            "4. Reflection and wrap-up (15 min)\n"
        )

    async def revise_plan(
        self,
        project: ProjectRecord,
        source_files: list[SourceFileRecord],
        current_outline: str,
        trainer_feedback: str,
    ) -> str:
        return f"{current_outline}\n\nTrainer note: {trainer_feedback or 'No extra feedback'}"

    async def generate_artifact(
        self,
        project: ProjectRecord,
        source_files: list[SourceFileRecord],
        approved_revision: PlanRevisionRecord,
        content_type: str,
    ) -> NotebookArtifact | SampleProjectArtifact:
        if content_type == "sample_project":
            return SampleProjectArtifact(
                project_name="training-sample",
                inferred_stack="Python",
                summary="A compact project bundle for classroom discussion.",
                run_instructions="Run `uv run python main.py`.",
                learner_outcome="Learners complete a starter project and compare their work to a full solution.",
                exercise_sections=[
                    {
                        "title": "Implement the workflow",
                        "learner_goal": "Finish the missing application behavior.",
                        "instructions": "Work through the starter project TODOs and verify the completed workflow.",
                    }
                ],
                starter_files=[
                    {
                        "path": "main.py",
                        "description": "Entry point with learner TODOs",
                        "content": "def main():\n    # TODO: implement the main workflow\n    pass\n",
                    },
                    {
                        "path": "README.md",
                        "description": "Project overview",
                        "content": "# Training Sample Starter\n",
                    },
                ],
                solution_files=[
                    {
                        "path": "main.py",
                        "description": "Completed entry point",
                        "content": "def main():\n    print('hello from maker')\n\n\nif __name__ == '__main__':\n    main()\n",
                    },
                    {
                        "path": "README.md",
                        "description": "Solution overview",
                        "content": "# Training Sample Solution\n",
                    },
                ],
            )
        return NotebookArtifact(
            filename="demo-notebook.ipynb",
            title="Demo notebook",
            summary="Notebook generated for the approved outline.",
            cells=[
                NotebookCell(cell_type="markdown", source="# Demo notebook"),
                NotebookCell(cell_type="code", source="print('ready')"),
            ],
        )


def make_settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / ".maker-data"
    return Settings(
        app_name="Maker Courseware",
        repo_root=tmp_path,
        package_root=Path(__file__).resolve().parents[1] / "src" / "maker",
        data_dir=data_dir,
        db_path=data_dir / "maker.db",
        logs_dir=data_dir / "logs",
        log_file=data_dir / "logs" / "maker.log",
        uploads_dir=data_dir / "uploads",
        extracted_dir=data_dir / "extracted",
        generated_dir=data_dir / "generated",
        model_class_5_1="fake-model-5.1",
        model_class_5_2="fake-model-5.2",
        model_class_5_3="fake-model-5.3",
        model_class_5_4="fake-model-5.4",
        model_class_5_mini="fake-model-5-mini",
        model_class_5_nano="fake-model-5-nano",
        model_class_5_4_mini="fake-model-5.4-mini",
        model_class_5_4_nano="fake-model-5.4-nano",
        default_model_class="5.4",
        host="127.0.0.1",
        port=8000,
    )


def create_test_client(tmp_path: Path) -> TestClient:
    app = create_app(settings=make_settings(tmp_path), orchestrator=FakeOrchestrator())
    return TestClient(app)


def wait_for_project_idle(client: TestClient, project_id: int, timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/projects/{project_id}/status")
        data = response.json()
        if data["status"] not in {"planning", "generating"}:
            return data
        time.sleep(0.05)
    raise AssertionError(f"Project {project_id} did not finish in time.")


def test_dashboard_hides_deferred_content_types(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Jupyter notebook demonstration" in response.text
    assert "Microsoft word software exercise" not in response.text
    assert "Powerpoint lecture" not in response.text
    assert "gpt-5.1" in response.text
    assert "gpt-5.4" in response.text
    assert "gpt-5-mini" in response.text
    assert "gpt-5.4-nano" in response.text


def test_project_revision_and_generation_flow(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        create_response = client.post(
            "/projects",
            data={
                "title": "Python loops",
                "brief": "Create a beginner-friendly notebook about Python loops.",
                "content_types": "notebook_demo",
                "model_class": "5.4",
                "target_level": "Beginner",
                "duration_text": "90 minutes",
            },
            files={"supporting_files": ("notes.txt", b"Loops repeat instructions.", "text/plain")},
            follow_redirects=False,
        )
        assert create_response.status_code == 303
        project_url = create_response.headers["location"]

        project_page = client.get(project_url)
        assert "Python loops" in project_page.text

        plan_response = client.post(f"{project_url}/plan", follow_redirects=False)
        assert plan_response.status_code == 303
        wait_for_project_idle(client, 1)

        detail_page = client.get(project_url)
        assert "Revision 1" in detail_page.text

        app = client.app
        snapshot = app.state.service.get_snapshot(1)
        current_revision = snapshot.revisions[0]

        revise_response = client.post(
            f"/projects/1/revisions/{current_revision.id}/revise",
            data={
                "edited_outline": current_revision.editable_outline_text + "\n5. Knowledge check",
                "trainer_feedback": "Add a short recap task.",
            },
            follow_redirects=False,
        )
        assert revise_response.status_code == 303
        wait_for_project_idle(client, 1)

        snapshot = app.state.service.get_snapshot(1)
        latest_revision = snapshot.revisions[0]
        assert latest_revision.revision_number == 2
        assert snapshot.revisions[1].status == "superseded"

        approve_response = client.post(
            f"/projects/1/revisions/{latest_revision.id}/approve",
            follow_redirects=False,
        )
        assert approve_response.status_code == 303
        wait_for_project_idle(client, 1)

        snapshot = app.state.service.get_snapshot(1)
        assert snapshot.project.status == "generated"
        assert snapshot.latest_artifact is not None

        download_response = client.get(
            f"/projects/1/artifacts/{snapshot.latest_artifact.id}/download"
        )
        assert download_response.status_code == 200
        assert download_response.headers["content-type"] == "application/zip"


def test_html_and_zip_uploads_are_extracted(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("lesson.md", "# Lesson\n\nThis archive contains lesson guidance.")
    buffer.seek(0)

    with create_test_client(tmp_path) as client:
        response = client.post(
            "/projects",
            data={
                "title": "Archive test",
                "brief": "Check extraction coverage.",
                "content_types": "sample_project",
                "model_class": "5.4",
                "target_level": "Intermediate",
                "duration_text": "Half day",
            },
            files=[
                ("supporting_files", ("reference.html", b"<html><body><h1>Reference</h1><p>HTML notes</p></body></html>", "text/html")),
                ("supporting_files", ("materials.zip", buffer.getvalue(), "application/zip")),
            ],
            follow_redirects=False,
        )
        assert response.status_code == 303

        snapshot = client.app.state.service.get_snapshot(1)
        assert len(snapshot.source_files) == 2
        assert snapshot.source_files[0].extraction_status == "extracted"
        assert snapshot.source_files[1].metadata_json["members"][0]["status"] == "extracted"


def test_multiple_courseware_formats_generate_single_bundle(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        response = client.post(
            "/projects",
            data={
                "title": "Multi format",
                "brief": "Create both a demo notebook and a sample project for Python functions.",
                "content_types": ["notebook_demo", "sample_project"],
                "model_class": "5.4",
                "target_level": "Beginner",
                "duration_text": "2 hours",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        client.post("/projects/1/plan", follow_redirects=False)
        wait_for_project_idle(client, 1)
        snapshot = client.app.state.service.get_snapshot(1)
        revision = snapshot.revisions[0]
        client.post(f"/projects/1/revisions/{revision.id}/approve", follow_redirects=False)
        final_status = wait_for_project_idle(client, 1)

        snapshot = client.app.state.service.get_snapshot(1)
        assert snapshot.latest_artifact is not None
        outputs = snapshot.latest_artifact.preview_metadata["outputs"]
        assert len(outputs) == 2
        assert {output["content_type"] for output in outputs} == {"notebook_demo", "sample_project"}
        sample_project_output = next(output for output in outputs if output["content_type"] == "sample_project")
        assert any("/starter/" in file_name for file_name in sample_project_output["files"])
        assert any("/solution/" in file_name for file_name in sample_project_output["files"])
        assert final_status["progress_percent"] == 100
