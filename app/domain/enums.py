from enum import Enum


class ValueEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class Recommendation(ValueEnum):
    PASS = "Pass"
    WATCH = "Watch"
    TAKE_A_MEETING = "Take a meeting"


class AIProvider(ValueEnum):
    BEDROCK = "bedrock"
    OPENAI = "openai"


class AnalysisMode(ValueEnum):
    BEDROCK = "bedrock"
    OPENAI = "openai"
    MIXED = "mixed"
