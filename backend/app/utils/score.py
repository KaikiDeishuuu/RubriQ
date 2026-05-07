from __future__ import annotations


def clamp_score(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def round_score(value: float) -> float:
    return round(value, 2)
