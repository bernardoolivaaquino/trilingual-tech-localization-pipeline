"""Single-pass protected-block restoration, integrity validation, and export."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

from src.models import LocalizationResult, ProtectedBlock
from src.parser import TOKEN_PATTERN


class TokenIntegrityError(ValueError):
    """Raised when protected tokens are missing, duplicated, or corrupted."""


class TokenValidationReport(BaseModel):
    """Validation summary comparing expected tokens vs. tokens in masked text."""

    valid: bool
    expected_count: int = Field(..., ge=0)
    present_count: int = Field(..., ge=0)
    missing_tokens: list[str] = Field(default_factory=list)
    duplicated_tokens: list[str] = Field(default_factory=list)
    unknown_tokens: list[str] = Field(default_factory=list)


class DocumentRebuilder:
    """Restores protected syntax blocks and validates zero-corruption exports."""

    def validate_tokens(
        self,
        masked_text: str,
        blocks: list[ProtectedBlock],
    ) -> TokenValidationReport:
        """Verify every expected token occurs exactly once and no unknown tokens exist."""
        expected_tokens = [block.token for block in blocks]
        expected_set = set(expected_tokens)

        found_tokens = [match.group(0) for match in TOKEN_PATTERN.finditer(masked_text)]
        counts = Counter(found_tokens)

        missing = [tok for tok in expected_tokens if counts[tok] == 0]
        duplicated = [tok for tok in expected_tokens if counts[tok] > 1]
        unknown = sorted({tok for tok in found_tokens if tok not in expected_set})
        intact_count = sum(1 for tok in expected_tokens if counts[tok] == 1)

        valid = not missing and not duplicated and not unknown
        return TokenValidationReport(
            valid=valid,
            expected_count=len(expected_tokens),
            present_count=intact_count,
            missing_tokens=missing,
            duplicated_tokens=duplicated,
            unknown_tokens=unknown,
        )

    def rebuild(
        self,
        masked_text: str,
        blocks: list[ProtectedBlock],
        strict: bool = True,
    ) -> str:
        """Restore protected blocks in a single non-recursive regex pass."""
        if strict:
            report = self.validate_tokens(masked_text, blocks)
            if not report.valid:
                raise TokenIntegrityError(
                    "Protected token integrity check failed: "
                    f"missing={report.missing_tokens}, "
                    f"duplicated={report.duplicated_tokens}, "
                    f"unknown={report.unknown_tokens}"
                )

        lookup = {block.token: block.original_content for block in blocks}

        def _replace(match: object) -> str:
            token = match.group(0)  # type: ignore[attr-defined]
            return lookup.get(token, token)

        return TOKEN_PATTERN.sub(_replace, masked_text)

    def verify_syntax_integrity(
        self,
        blocks: list[ProtectedBlock],
        rebuilt_text: str,
    ) -> bool:
        """Verify zero leaked tokens and verbatim presence of every protected block."""
        if TOKEN_PATTERN.search(rebuilt_text) is not None:
            return False

        expected_counts = Counter(block.original_content for block in blocks)
        for content, needed in expected_counts.items():
            if not content:
                continue
            if rebuilt_text.count(content) < needed:
                return False

        return True

    def export_document(self, result: LocalizationResult, output_path: Path) -> Path:
        """Write the final rebuilt Markdown document with UTF-8 encoding."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.final_rebuilt_text, encoding="utf-8")
        return output_path

    def export_audit_report(
        self,
        results: list[LocalizationResult],
        report_path: Path,
    ) -> Path:
        """Export structured localization and critic audit telemetry as JSON."""
        report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pipeline_version": "1.0.0",
            "results": [
                {
                    "source_path": res.source_path,
                    "target_language": res.target_language.value,
                    "output_path": res.output_path,
                    "final_score": res.final_score,
                    "passed": res.passed,
                    "syntax_integrity_verified": res.syntax_integrity_verified,
                    "protected_blocks_count": len(res.parse_result.blocks),
                    "ast_summary": res.parse_result.ast_summary,
                    "iterations": [
                        {
                            "iteration": it.iteration,
                            "score": it.critic_report.score,
                            "passed": it.critic_report.passed,
                            "token_integrity_rate": it.critic_report.token_integrity_rate,
                            "terminology_precision": it.critic_report.terminology_precision,
                            "source_terms_detected": it.critic_report.source_terms_detected,
                            "mandatory_terms_matched": it.critic_report.mandatory_terms_matched,
                            "forbidden_terms_found": it.critic_report.forbidden_terms_found,
                            "observations": [obs.model_dump() for obs in it.critic_report.observations],
                        }
                        for it in res.iterations
                    ],
                }
                for res in results
            ],
        }
        report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return report_path
