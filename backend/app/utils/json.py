from __future__ import annotations

import json
import re
from typing import Any

JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def strip_code_fences(text: str) -> str:
    candidate = text.strip()
    match = JSON_BLOCK_RE.search(candidate)
    if match:
        return match.group(1).strip()
    return candidate


def extract_json_text(text: str) -> str:
    candidate = strip_code_fences(text)
    start_candidates = [candidate.find("{"), candidate.find("[")]
    start_candidates = [index for index in start_candidates if index >= 0]
    if not start_candidates:
        return candidate
    start = min(start_candidates)
    end_object = candidate.rfind("}")
    end_array = candidate.rfind("]")
    end = max(end_object, end_array)
    if end >= start:
        return candidate[start : end + 1].strip()
    return candidate


def parse_json_maybe(text: str) -> Any:
    cleaned = extract_json_text(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        repaired = cleaned.replace("\r\n", "\n").replace("\r", "\n")
        repaired = repaired.replace("\t", "    ")
        return json.loads(repaired)


def dumps_pretty(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
