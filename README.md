# Maker Courseware

Maker Courseware is a local, CLI-launched web application that helps trainers turn a course brief plus supporting documents into draft plans and final teaching assets.

## MVP Features

- Create projects with a brief, target level, one or more courseware formats, and supporting files.
- Accept supporting uploads in `pdf`, `docx`, `pptx`, `txt`, `md`, `html`, and `zip`.
- Generate a draft courseware plan using the OpenAI Agents SDK.
- Revise the plan with direct outline edits and trainer feedback.
- Choose the GPT-5 model alias directly per project (`gpt-5.1`, `gpt-5.2`, `gpt-5.3-codex`, `gpt-5.4`, plus `gpt-5-mini`, `gpt-5-nano`, `gpt-5.4-mini`, and `gpt-5.4-nano` where available).
- Show progress while planning or generating content, with automatic project-page refresh when work completes.
- Approve a revision and generate final files for one or more of:
  - Jupyter notebook demonstration
  - Jupyter notebook exercise
  - Extended project
- Persist projects, revisions, uploads, and generated bundles locally with SQLite and filesystem storage.

## Requirements

- Python 3.11+
- `OPENAI_API_KEY` set in the environment

Optional model overrides:

- `MAKER_MODEL_CLASS_5_1`
- `MAKER_MODEL_CLASS_5_2`
- `MAKER_MODEL_CLASS_5_3`
- `MAKER_MODEL_CLASS_5_4`
- `MAKER_MODEL_CLASS_5_MINI`
- `MAKER_MODEL_CLASS_5_NANO`
- `MAKER_MODEL_CLASS_5_4_MINI`
- `MAKER_MODEL_CLASS_5_4_NANO`
- `MAKER_DEFAULT_MODEL_CLASS`
- `MAKER_DATA_DIR`
- `MAKER_HOST`
- `MAKER_PORT`

## Run

```bash
uv sync
uv run maker serve
```

The app stores local state inside `.maker-data/` by default.

If the app hits an unexpected server error, check `.maker-data/logs/maker.log`.
