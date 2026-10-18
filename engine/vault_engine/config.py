"""Paths and persisted application settings."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ProviderKind = Literal["lmstudio", "ollama"]

DEFAULT_ENDPOINTS: dict[str, str] = {
    "lmstudio": "http://localhost:1234",
    "ollama": "http://localhost:11434",
}


def data_dir() -> Path:
    root = os.environ.get("WSOS_DATA_DIR") or str(
        Path(os.environ.get("LOCALAPPDATA", Path.home())) / "WorkspaceOS"
    )
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


class ModelRef(BaseModel):
    provider: ProviderKind
    model: str


class OcrSettings(BaseModel):
    engine: Literal["rapidocr", "tesseract", "vision", "none"] = "rapidocr"
    vision: ModelRef | None = None
    # Pages with fewer extractable characters than this are treated as scans.
    min_text_chars_per_page: int = 40
    languages: list[str] = Field(default_factory=lambda: ["it", "en"])


class AppSettings(BaseModel):
    endpoints: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_ENDPOINTS))
    default_embedding: ModelRef | None = None
    # LLM used for contextual chunk summaries and re-ranking.
    llm: ModelRef | None = None
    ocr: OcrSettings = Field(default_factory=OcrSettings)
    # Concurrent files processed per vault job.
    ingest_workers: int = 2
    embed_batch_size: int = 32
    # Agent loop.
    agent_max_steps: int = Field(10, ge=1, le=40)
    agent_max_tokens: int = Field(2048, ge=256, le=16384)
    # Let reasoning models think before answering: better plans, several times slower on CPU.
    agent_reasoning: bool = False


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "settings.json"
        self._lock = threading.Lock()
        self._settings = self._load()

    def _load(self) -> AppSettings:
        if self.path.exists():
            return AppSettings.model_validate_json(self.path.read_text(encoding="utf-8"))
        return AppSettings()

    def get(self) -> AppSettings:
        with self._lock:
            return self._settings.model_copy(deep=True)

    def update(self, patch: dict) -> AppSettings:
        with self._lock:
            merged = self._settings.model_dump() | patch
            self._settings = AppSettings.model_validate(merged)
            write_json_atomic(self.path, self._settings.model_dump())
            return self._settings.model_copy(deep=True)


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
