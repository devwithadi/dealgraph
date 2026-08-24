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
    OPENROUTER = "openrouter"
    DEEPSEEK = "deepseek"
    DASHSCOPE = "dashscope"
    ZHIPU = "zhipu"
    OLLAMA = "ollama"


class AnalysisMode(ValueEnum):
    BEDROCK = "bedrock"
    OPENAI = "openai"
    OPENROUTER = "openrouter"
    DEEPSEEK = "deepseek"
    DASHSCOPE = "dashscope"
    ZHIPU = "zhipu"
    OLLAMA = "ollama"
    MIXED = "mixed"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"


class CitationTag(ValueEnum):
    VERIFIED = "verified"
    TRUSTED = "trusted"
    CLAIMED = "claimed"


EvidenceStatus = CitationTag

