from __future__ import annotations

import os
import re
from typing import Protocol

from .config import Settings
from .errors import ConfigurationError, GenerationError
from .files import load_extracted_text
from .models import (
    CONTENT_TYPE_OPTIONS,
    NotebookArtifact,
    PlanRevisionRecord,
    ProjectRecord,
    SampleProjectArtifact,
    SourceFileRecord,
    content_type_labels,
)

try:  # pragma: no cover - dependency availability varies by environment
    from agents import Agent, Runner
except ImportError:  # pragma: no cover - dependency availability varies by environment
    Agent = None
    Runner = None


CONTENT_TYPE_LABELS = dict(CONTENT_TYPE_OPTIONS)


class Orchestrator(Protocol):
    async def generate_initial_plan(self, project: ProjectRecord, source_files: list[SourceFileRecord]) -> str:
        ...

    async def revise_plan(
        self,
        project: ProjectRecord,
        source_files: list[SourceFileRecord],
        current_outline: str,
        trainer_feedback: str,
    ) -> str:
        ...

    async def generate_artifact(
        self,
        project: ProjectRecord,
        source_files: list[SourceFileRecord],
        approved_revision: PlanRevisionRecord,
        content_type: str,
    ) -> NotebookArtifact | SampleProjectArtifact:
        ...


class OpenAIAgentOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if Agent is None or Runner is None:
            raise ConfigurationError(
                "The openai-agents package is not installed. Run `uv sync` before starting the app."
            )
        if not os.getenv("OPENAI_API_KEY"):
            raise ConfigurationError(
                "OPENAI_API_KEY is not visible to the running app process. "
                "If you set it recently, restart `uv run maker serve` and, if needed, restart the Codex app or terminal session."
            )

    async def generate_initial_plan(self, project: ProjectRecord, source_files: list[SourceFileRecord]) -> str:
        agent = Agent(
            name="Courseware Planner",
            instructions=(
                "You are designing courseware for professional trainers. "
                "Return markdown only, with no preamble. "
                "Be concrete, teachable, and format-aware. "
                "Produce: "
                "1. a short 'Course Goal' section, "
                "2. an 'Audience and Assumptions' section, "
                "3. a numbered session outline with timings, learning outcomes, teaching method, and resources per section, "
                "4. an 'Assessment and Success Checks' section, and "
                "5. a short 'Final Deliverables' section describing what the generated files should contain for each requested format. "
                "The outline must be specific enough that a downstream generation agent can turn it into concrete teaching materials without guessing."
            ),
            model=self._select_plan_model(project),
        )
        prompt = self._build_plan_prompt(project, source_files)
        return await self._run_text(agent, prompt)

    async def revise_plan(
        self,
        project: ProjectRecord,
        source_files: list[SourceFileRecord],
        current_outline: str,
        trainer_feedback: str,
    ) -> str:
        agent = Agent(
            name="Courseware Revision Agent",
            instructions=(
                "Revise courseware outlines based on trainer edits and feedback. "
                "Return markdown only. Preserve explicit trainer edits unless they conflict with the brief. "
                "Strengthen specificity, sequencing, timing realism, learner activities, and assessment points. "
                "Keep the structure generation-ready so a separate content generator can implement it with minimal ambiguity."
            ),
            model=self._select_revision_model(project),
        )
        prompt = (
            f"{self._project_block(project)}\n\n"
            f"Trainer-edited outline:\n{current_outline}\n\n"
            f"Trainer feedback:\n{trainer_feedback or 'No extra feedback supplied.'}\n\n"
            f"Source material:\n{self._source_context(source_files)}\n\n"
            "Return an updated markdown outline suitable for final approval."
        )
        return await self._run_text(agent, prompt)

    async def generate_artifact(
        self,
        project: ProjectRecord,
        source_files: list[SourceFileRecord],
        approved_revision: PlanRevisionRecord,
        content_type: str,
    ) -> NotebookArtifact | SampleProjectArtifact:
        artifact_prompt = (
            f"{self._project_block(project)}\n"
            f"Generating output format: {CONTENT_TYPE_LABELS.get(content_type, content_type)}\n\n"
            f"{self._format_role_guidance(project, content_type)}\n\n"
            f"{self._duration_guidance(project, content_type)}\n\n"
            f"Approved outline:\n{approved_revision.editable_outline_text}\n\n"
            f"Source material:\n{self._source_context(source_files)}\n\n"
        )
        if content_type == "sample_project":
            agent = Agent(
                name="Sample Project Generator",
                instructions=(
                    "Generate an extended project for learners. Infer the most suitable stack "
                    "from the brief and sources, defaulting to Python when ambiguous. "
                    "This output must be distinct from any notebook exercise or notebook demonstration also requested. "
                    "Return structured output with a project name, inferred stack, summary, run instructions, learner outcome, "
                    "exercise sections, starter files, and solution files. "
                    "The starter files must contain realistic TODO markers and partially completed code for learners to finish. "
                    "The solution files must be fully completed and aligned to the same project. "
                    "For longer durations, expand the project into multiple milestones, modules, or tasks rather than a tiny scaffold."
                ),
                model=self._select_generation_model(project, content_type),
                output_type=SampleProjectArtifact,
            )
        else:
            notebook_style = (
                "Create a runnable demonstration notebook with explanatory markdown and code."
                if content_type == "notebook_demo"
                else "Create an exercise notebook with learner prompts, scaffolded code, increasing challenge, and clear task framing."
            )
            agent = Agent(
                name="Notebook Generator",
                instructions=(
                    f"{notebook_style} Return structured output with a filename, title, summary, "
                    "and an ordered set of markdown/code cells. "
                    "Make the notebook instructor-ready: markdown cells should explain intent and transitions, "
                    "and code cells should be purposeful, aligned to the approved outline, and realistic for the stated learner level. "
                    "If this is an exercise notebook, it must be a standalone set of learner exercises, not the same exercise sequence as the extended project."
                ),
                model=self._select_generation_model(project, content_type),
                output_type=NotebookArtifact,
            )
        result = await Runner.run(agent, artifact_prompt)
        return self._ensure_structured_output(result.final_output)

    def _build_plan_prompt(self, project: ProjectRecord, source_files: list[SourceFileRecord]) -> str:
        return (
            f"{self._project_block(project)}\n\n"
            f"{self._portfolio_guidance(project)}\n\n"
            f"{self._duration_guidance(project, None)}\n\n"
            f"Source material:\n{self._source_context(source_files)}\n\n"
            "Create the first draft plan as markdown that a trainer can edit directly before approval."
        )

    def _project_block(self, project: ProjectRecord) -> str:
        return (
            f"Project title: {project.title}\n"
            f"Requested output formats: {', '.join(content_type_labels(project.content_types))}\n"
            f"Target level: {project.target_level}\n"
            f"Model class: {project.model_class}\n"
            f"Duration: {project.duration_text}\n"
            f"Brief:\n{project.brief}"
        )

    def _portfolio_guidance(self, project: ProjectRecord) -> str:
        if len(project.content_types) <= 1:
            return "Design a single strong deliverable for the requested format."
        return (
            "Design separate, complementary deliverables for each requested format. "
            "Do not repeat the exact same exercise across formats. "
            "Use the notebook exercise for guided introduction and skill-building, "
            "use the notebook demonstration for worked examples and explanation, "
            "and use the extended project for a larger multi-stage applied task with starter TODOs and a full reference solution."
        )

    def _format_role_guidance(self, project: ProjectRecord, content_type: str) -> str:
        siblings = [label for label in content_type_labels(project.content_types) if CONTENT_TYPE_LABELS.get(content_type) != label]
        sibling_text = f"Other requested formats: {', '.join(siblings)}." if siblings else "No other formats requested."
        if content_type == "notebook_demo":
            role = (
                "Role: create an instructor-led demonstration that teaches concepts through worked examples, narrative explanation, and runnable code."
            )
        elif content_type == "notebook_exercise":
            role = (
                "Role: create a standalone notebook exercise that introduces the topic through guided learner tasks, checkpoints, and escalating practice."
            )
        else:
            role = (
                "Role: create an extended project that acts as a larger applied exercise with multiple milestones, starter TODOs, and a full solution."
            )
        return f"{role} {sibling_text}"

    def _duration_guidance(self, project: ProjectRecord, content_type: str | None) -> str:
        total_minutes = self._parse_duration_minutes(project.duration_text)
        allocated_minutes = self._allocated_minutes(project, content_type, total_minutes)
        human_minutes = f"approximately {allocated_minutes} minutes" if allocated_minutes else f"the stated duration of {project.duration_text}"

        scale = "brief"
        if allocated_minutes and allocated_minutes >= 300:
            scale = "full_day"
        elif allocated_minutes and allocated_minutes >= 180:
            scale = "substantial"
        elif allocated_minutes and allocated_minutes >= 90:
            scale = "moderate"

        base = f"This deliverable should feel substantial for {human_minutes} of learning time."
        if content_type == "sample_project":
            if scale == "full_day":
                specifics = (
                    "For a full-day project, include multiple milestones, several TODO-driven files or modules, debugging or extension tasks, and a complete reference solution."
                )
            elif scale == "substantial":
                specifics = (
                    "Include several staged TODOs across the project, at least a few learner milestones, and a complete reference solution."
                )
            else:
                specifics = (
                    "Include clear learner tasks in starter files with TODO markers and provide a full completed solution."
                )
        elif content_type == "notebook_exercise":
            if scale == "full_day":
                specifics = (
                    "A full-day exercise notebook should contain many substantial exercises, checkpoints, and extension tasks rather than a few simple questions."
                )
            elif scale == "substantial":
                specifics = (
                    "Use multiple exercise blocks with increasing difficulty, recap prompts, and enough material to occupy a long guided session."
                )
            else:
                specifics = (
                    "Include a sensible sequence of learner exercises with scaffolding and feedback points."
                )
        elif content_type == "notebook_demo":
            specifics = (
                "Use enough worked examples, explanations, and transitions to realistically support the allocated teaching time."
            )
        else:
            specifics = (
                "Distribute the total duration across the requested formats and make each deliverable appropriately substantial for its role."
            )
        return f"{base} {specifics}"

    def _allocated_minutes(self, project: ProjectRecord, content_type: str | None, total_minutes: int | None) -> int | None:
        if total_minutes is None:
            return None
        if content_type is None or len(project.content_types) <= 1:
            return total_minutes
        weights = {
            "notebook_demo": 0.25,
            "notebook_exercise": 0.35,
            "sample_project": 0.40,
        }
        selected_weights = {name: weights.get(name, 1.0) for name in project.content_types}
        total_weight = sum(selected_weights.values()) or 1.0
        return max(30, int(total_minutes * (selected_weights.get(content_type, 1.0) / total_weight)))

    def _parse_duration_minutes(self, duration_text: str) -> int | None:
        text = duration_text.strip().lower()
        if not text:
            return None
        if "full day" in text:
            return 360
        if "half day" in text:
            return 180
        hour_match = re.search(r"(\d+(?:\.\d+)?)\s*(hour|hours|hr|hrs)", text)
        minute_match = re.search(r"(\d+)\s*(minute|minutes|min|mins)", text)
        if hour_match:
            hours = float(hour_match.group(1))
            minutes = int(hours * 60)
            if minute_match:
                minutes += int(minute_match.group(1))
            return minutes
        if minute_match:
            return int(minute_match.group(1))
        return None

    def _source_context(self, source_files: list[SourceFileRecord]) -> str:
        if not source_files:
            return "No supporting files were supplied."

        chunks: list[str] = []
        for source_file in source_files:
            text = load_extracted_text(source_file.extracted_text_path)
            excerpt = text[:6000].strip() or f"[No extracted text available: {source_file.extraction_status}]"
            chunks.append(
                f"File: {source_file.original_name}\n"
                f"Status: {source_file.extraction_status}\n"
                f"Excerpt:\n{excerpt}"
            )
        return "\n\n---\n\n".join(chunks)

    async def _run_text(self, agent: Agent, prompt: str) -> str:
        result = await Runner.run(agent, prompt)
        output = result.final_output
        if not isinstance(output, str):
            raise GenerationError("The planning agent did not return text output.")
        return output.strip()

    def _ensure_structured_output(self, output: object) -> NotebookArtifact | SampleProjectArtifact:
        if isinstance(output, (NotebookArtifact, SampleProjectArtifact)):
            return output
        raise GenerationError("The generation agent returned an unexpected artifact shape.")

    def _select_plan_model(self, project: ProjectRecord) -> str:
        return self._model_for_class(project.model_class)

    def _select_revision_model(self, project: ProjectRecord) -> str:
        return self._model_for_class(project.model_class)

    def _select_generation_model(self, project: ProjectRecord, content_type: str) -> str:
        return self._model_for_class(project.model_class)

    def _model_for_class(self, model_class: str) -> str:
        model_map = {
            "5.1": self.settings.model_class_5_1,
            "5.2": self.settings.model_class_5_2,
            "5.3": self.settings.model_class_5_3,
            "5.4": self.settings.model_class_5_4,
            "5-mini": self.settings.model_class_5_mini,
            "5-nano": self.settings.model_class_5_nano,
            "5.4-mini": self.settings.model_class_5_4_mini,
            "5.4-nano": self.settings.model_class_5_4_nano,
        }
        return model_map.get(model_class, self.settings.model_class_5_4)
