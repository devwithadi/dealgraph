"""Closed business states serialized in DealGraph artifacts."""

from enum import Enum


class ValueEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class Recommendation(ValueEnum):
    PASS = "Pass"
    WATCH = "Watch"
    TAKE_A_MEETING = "Take a meeting"


class AnalysisMode(ValueEnum):
    DETERMINISTIC_FALLBACK = "deterministic_fallback"
    OPENAI = "openai"
