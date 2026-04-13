from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str
    repo_root: Path
    package_root: Path
    data_dir: Path
    db_path: Path
    logs_dir: Path
    log_file: Path
    uploads_dir: Path
    extracted_dir: Path
    generated_dir: Path
    model_class_5_1: str
    model_class_5_2: str
    model_class_5_3: str
    model_class_5_4: str
    model_class_5_mini: str
    model_class_5_nano: str
    model_class_5_4_mini: str
    model_class_5_4_nano: str
    default_model_class: str
    host: str
    port: int

    @property
    def templates_dir(self) -> Path:
        return self.package_root / "templates"

    @property
    def static_dir(self) -> Path:
        return self.package_root / "static"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    package_root = Path(__file__).resolve().parent
    repo_root = package_root.parent.parent
    data_dir = Path(os.getenv("MAKER_DATA_DIR", repo_root / ".maker-data")).resolve()

    return Settings(
        app_name="Maker Courseware",
        repo_root=repo_root,
        package_root=package_root,
        data_dir=data_dir,
        db_path=data_dir / "maker.db",
        logs_dir=data_dir / "logs",
        log_file=data_dir / "logs" / "maker.log",
        uploads_dir=data_dir / "uploads",
        extracted_dir=data_dir / "extracted",
        generated_dir=data_dir / "generated",
        model_class_5_1=os.getenv("MAKER_MODEL_CLASS_5_1", "gpt-5.1"),
        model_class_5_2=os.getenv("MAKER_MODEL_CLASS_5_2", "gpt-5.2"),
        model_class_5_3=os.getenv("MAKER_MODEL_CLASS_5_3", "gpt-5.3-codex"),
        model_class_5_4=os.getenv("MAKER_MODEL_CLASS_5_4", "gpt-5.4"),
        model_class_5_mini=os.getenv("MAKER_MODEL_CLASS_5_MINI", "gpt-5-mini"),
        model_class_5_nano=os.getenv("MAKER_MODEL_CLASS_5_NANO", "gpt-5-nano"),
        model_class_5_4_mini=os.getenv("MAKER_MODEL_CLASS_5_4_MINI", "gpt-5.4-mini"),
        model_class_5_4_nano=os.getenv("MAKER_MODEL_CLASS_5_4_NANO", "gpt-5.4-nano"),
        default_model_class=os.getenv("MAKER_DEFAULT_MODEL_CLASS", "5.4"),
        host=os.getenv("MAKER_HOST", "127.0.0.1"),
        port=int(os.getenv("MAKER_PORT", "8000")),
    )


def ensure_directories(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.extracted_dir.mkdir(parents=True, exist_ok=True)
    settings.generated_dir.mkdir(parents=True, exist_ok=True)
