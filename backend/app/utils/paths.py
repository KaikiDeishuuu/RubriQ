from __future__ import annotations

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
PROMPTS_DIR = ROOT_DIR / "prompts"
STORAGE_DIR = ROOT_DIR / "storage"


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
