"""Domain models and schemas for the trilingual technical localization pipeline."""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field, computed_field


class BlockKind(str, Enum):
    """Category of syntax-protected element extracted from Markdown."""

    FENCED_CODE = "fenced_code"
    INDENTED_CODE = "indented_code"
    INLINE_CODE = "inline_code"
    XML_BLOCK = "xml_block"
    XML_TAG = "xml_tag"
    LATEX_DISPLAY = "latex_display"
    LATEX_INLINE = "latex_inline"


class TargetLanguage(str, Enum):
    """Supported localization target languages."""

    FR = "fr"
    ES = "es"


class ProtectedBlock(BaseModel):
    """Single syntax-protected fragment replaced by an immutable token."""

    token: str = Field(..., description="Placeholder token, e.g. __PROTECTED_BLOCK_01__")
    index: int = Field(..., ge=1, description="1-based reading-order index")
    kind: BlockKind
    original_content: str
    start_line: int = Field(..., ge=1)
    end_line: int = Field(..., ge=1)
    metadata: dict[str, str] = Field(default_factory=dict)


class ParseResult(BaseModel):
    """Output of the deterministic AST + regex preprocessing step."""

    original_text: str
    masked_text: str
    blocks: list[ProtectedBlock] = Field(default_factory=list)
    ast_summary: dict[str, int] = Field(default_factory=dict)

    @computed_field
    @property
    def token_map(self) -> dict[str, str]:
        """Return a mapping from placeholder token to original verbatim content."""
        return {block.token: block.original_content for block in self.blocks}


class GlossaryTerm(BaseModel):
    """Single trilingual terminology rule with mandatory and forbidden variants."""

    id: str
    domain: str
    en: str
    en_aliases: list[str] = Field(default_factory=list)
    fr: str
    es: str
    forbidden_fr: list[str] = Field(default_factory=list)
    forbidden_es: list[str] = Field(default_factory=list)
    case_sensitive: bool = False
    notes: str = ""

    def target_term(self, language: TargetLanguage) -> str:
        """Return the mandatory translation for the requested target language."""
        return self.fr if language == TargetLanguage.FR else self.es

    def forbidden_terms(self, language: TargetLanguage) -> list[str]:
        """Return forbidden mistranslations for the requested target language."""
        return self.forbidden_fr if language == TargetLanguage.FR else self.forbidden_es


class Glossary(BaseModel):
    """Validated corporate terminology glossary."""

    version: str
    domain: str
    languages: list[str]
    terms: list[GlossaryTerm]


class CriticSeverity(str, Enum):
    """Severity of a terminology or structural audit observation."""

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class CriticObservation(BaseModel):
    """Structured finding emitted by TerminologyCriticAgent."""

    code: str
    severity: CriticSeverity
    message: str
    term_id: str | None = None
    expected: str | None = None
    found: str | None = None
    penalty: float = Field(..., ge=0.0)


class CriticReport(BaseModel):
    """Structured audit verdict for one translation iteration."""

    iteration: int = Field(..., ge=1)
    target_language: TargetLanguage
    score: float = Field(..., ge=0.0, le=100.0)
    passed: bool
    threshold: float = 95.0
    tokens_expected: int = Field(..., ge=0)
    tokens_intact: int = Field(..., ge=0)
    token_integrity_rate: float = Field(..., ge=0.0, le=100.0)
    source_terms_detected: int = Field(..., ge=0)
    mandatory_terms_matched: int = Field(..., ge=0)
    forbidden_terms_found: int = Field(..., ge=0)
    terminology_precision: float = Field(..., ge=0.0, le=100.0)
    observations: list[CriticObservation] = Field(default_factory=list)


class TranslationIteration(BaseModel):
    """Record of one translator-critic cycle."""

    iteration: int = Field(..., ge=1)
    masked_translation: str
    critic_report: CriticReport
    correction_prompt_used: str | None = None


class LocalizationResult(BaseModel):
    """Complete end-to-end result for a single target language."""

    source_path: str | None = None
    target_language: TargetLanguage
    parse_result: ParseResult
    iterations: list[TranslationIteration] = Field(default_factory=list)
    final_masked_text: str
    final_rebuilt_text: str
    final_score: float = Field(..., ge=0.0, le=100.0)
    passed: bool
    syntax_integrity_verified: bool
    output_path: str | None = None


class LanguageEvalComparison(BaseModel):
    """Quantitative before/after comparison for the critic feedback loop."""

    language: TargetLanguage
    terms_in_source: int = Field(..., ge=0)
    before_score: float = Field(..., ge=0.0, le=100.0)
    after_score: float = Field(..., ge=0.0, le=100.0)
    score_delta: float
    before_terminology_precision: float = Field(..., ge=0.0, le=100.0)
    after_terminology_precision: float = Field(..., ge=0.0, le=100.0)
    precision_delta: float
    before_forbidden_violations: int = Field(..., ge=0)
    after_forbidden_violations: int = Field(..., ge=0)
    before_token_integrity: float = Field(..., ge=0.0, le=100.0)
    after_token_integrity: float = Field(..., ge=0.0, le=100.0)
    iterations_required: int = Field(..., ge=1)
