from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Any

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    prompt_path = PROMPTS_DIR / name
    return prompt_path.read_text(encoding="utf-8")


def _normalize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def render_prompt(name: str, **variables: Any) -> str:
    template = Template(load_prompt(name))
    rendered_variables = {key: _normalize_value(value) for key, value in variables.items()}
    return template.safe_substitute(rendered_variables)
