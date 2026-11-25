"""Multi-agent translation and terminology auditing loop."""

from __future__ import annotations

import re
from pathlib import Path

from src.backends import DeterministicLocalizationBackend, TranslationBackend
from src.glossary import GlossaryEngine
from src.models import (
    CriticObservation,
    CriticReport,
    CriticSeverity,
    LocalizationResult,
    ParseResult,
    TargetLanguage,
    TranslationIteration,
)
from src.parser import MarkdownProtectedParser
from src.rebuilder import DocumentRebuilder

_HEADING_LINE_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
_TABLE_SEP_LINE_RE = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$", re.MULTILINE)
_CORRUPTED_TOKEN_RE = re.compile(
    r"_{1,2}(?:PROTECTED_BLOCK|BLOC_PROTEGE|BLOQUE_PROTEGIDO)_[A-Za-z0-9_]*_{1,2}"
)


class DomainTranslatorAgent:
    """Subagent translating masked technical Markdown while enforcing corporate glossary rules."""

    def __init__(
        self,
        glossary_engine: GlossaryEngine,
        backend: TranslationBackend | None = None,
    ) -> None:
        self.glossary_engine = glossary_engine
        self.backend: TranslationBackend = backend or DeterministicLocalizationBackend(
            glossary_engine=glossary_engine
        )

    def build_system_prompt(
        self,
        target_language: TargetLanguage,
        relevant_terms: list | None = None,
    ) -> str:
        """Assemble system instructions dynamically injecting glossary rules and token invariants."""
        lang_name = "French" if target_language == TargetLanguage.FR else "Spanish"
        glossary_rules = self.glossary_engine.build_prompt_rules(
            target_language=target_language,
            relevant_terms=relevant_terms,
        )
        return (
            f"You are DomainTranslatorAgent, an aerospace and software localization specialist.\n"
            f"Translate the masked Markdown document from English into {lang_name}.\n\n"
            f"STRICT SYNTAX INVARIANTS:\n"
            f"1. Preserve every __PROTECTED_BLOCK_XX__ token verbatim, in exact quantity and reading order.\n"
            f"2. Never translate, renumber, drop, duplicate, or reformat any __PROTECTED_BLOCK_XX__ token.\n"
            f"3. Preserve Markdown headings (#), bullet lists, and pipe table columns.\n\n"
            f"{glossary_rules}"
        )

    def build_correction_prompt(self, critic_report: CriticReport) -> str:
        """Convert structured TerminologyCriticAgent observations into an actionable revision prompt."""
        lines = [
            f"TerminologyCriticAgent rejected draft {critic_report.iteration} "
            f"(score={critic_report.score:.2f} < {critic_report.threshold:.2f}).",
            "Fix ALL of the following issues without altering any __PROTECTED_BLOCK_XX__ token:",
        ]
        for idx, obs in enumerate(critic_report.observations, start=1):
            lines.append(
                f"{idx}. [{obs.severity.value.upper()} | {obs.code}] {obs.message} "
                f"(found={obs.found!r}, expected={obs.expected!r}, penalty=-{obs.penalty})"
            )
        return "\n".join(lines)

    def translate(
        self,
        parse_result: ParseResult,
        target_language: TargetLanguage,
        feedback: CriticReport | None = None,
        previous_draft: str | None = None,
    ) -> tuple[str, str | None]:
        """Run one translation or critic-guided correction pass."""
        relevant_terms = self.glossary_engine.detect_source_terms(parse_result.masked_text)
        system_prompt = self.build_system_prompt(
            target_language=target_language,
            relevant_terms=relevant_terms or self.glossary_engine.glossary.terms,
        )
        correction_prompt = self.build_correction_prompt(feedback) if feedback is not None else None
        masked_output = self.backend.translate(
            masked_source=parse_result.masked_text,
            target_language=target_language,
            system_prompt=system_prompt,
            correction_prompt=correction_prompt,
            previous_draft=previous_draft,
            critic_report=feedback,
        )
        return masked_output, correction_prompt


class TerminologyCriticAgent:
    """Subagent auditing translations against protected tokens, glossary rules, and Markdown layout."""

    def __init__(
        self,
        glossary_engine: GlossaryEngine,
        pass_threshold: float = 95.0,
        rebuilder: DocumentRebuilder | None = None,
    ) -> None:
        self.glossary_engine = glossary_engine
        self.pass_threshold = pass_threshold
        self.rebuilder = rebuilder or DocumentRebuilder()

    def audit(
        self,
        parse_result: ParseResult,
        masked_translation: str,
        target_language: TargetLanguage,
        iteration: int = 1,
    ) -> CriticReport:
        """Score a masked translation (0-100) and emit structured observations."""
        observations: list[CriticObservation] = []
        total_penalty = 0.0

        # 1. Protected token integrity checks.
        validation = self.rebuilder.validate_tokens(masked_translation, parse_result.blocks)
        for tok in validation.missing_tokens:
            penalty = 25.0
            total_penalty += penalty
            observations.append(
                CriticObservation(
                    code="TOKEN_MISSING",
                    severity=CriticSeverity.CRITICAL,
                    message=f"Protected token {tok} was removed or altered during translation.",
                    expected=tok,
                    found=None,
                    penalty=penalty,
                )
            )
        for tok in validation.duplicated_tokens:
            penalty = 15.0
            total_penalty += penalty
            observations.append(
                CriticObservation(
                    code="TOKEN_DUPLICATED",
                    severity=CriticSeverity.MAJOR,
                    message=f"Protected token {tok} appears multiple times in translation.",
                    expected=tok,
                    found=tok,
                    penalty=penalty,
                )
            )
        for tok in validation.unknown_tokens:
            penalty = 20.0
            total_penalty += penalty
            observations.append(
                CriticObservation(
                    code="TOKEN_CORRUPTED",
                    severity=CriticSeverity.CRITICAL,
                    message=f"Unexpected or renumbered protected token {tok} detected.",
                    expected=None,
                    found=tok,
                    penalty=penalty,
                )
            )

        expected_token_set = {b.token for b in parse_result.blocks}
        corrupted_matches = [
            m.group(0)
            for m in _CORRUPTED_TOKEN_RE.finditer(masked_translation)
            if m.group(0) not in expected_token_set and m.group(0) not in validation.unknown_tokens
        ]
        for bad_tok in corrupted_matches:
            penalty = 20.0
            total_penalty += penalty
            observations.append(
                CriticObservation(
                    code="TOKEN_CORRUPTED",
                    severity=CriticSeverity.CRITICAL,
                    message=f"Malformed or translated placeholder token {bad_tok!r} detected.",
                    expected="exact __PROTECTED_BLOCK_XX__ token",
                    found=bad_tok,
                    penalty=penalty,
                )
            )

        # 2. Corporate glossary compliance checks.
        forbidden_hits = self.glossary_engine.find_forbidden_terms(
            masked_translation=masked_translation,
            target_language=target_language,
        )
        forbidden_term_ids: set[str] = set()
        for term, found_phrase in forbidden_hits:
            forbidden_term_ids.add(term.id)
            penalty = 8.0
            total_penalty += penalty
            observations.append(
                CriticObservation(
                    code="FORBIDDEN_TERM_USED",
                    severity=CriticSeverity.MAJOR,
                    message=f"Forbidden translation {found_phrase!r} used for {term.en!r}.",
                    term_id=term.id,
                    expected=term.target_term(target_language),
                    found=found_phrase,
                    penalty=penalty,
                )
            )

        source_terms = self.glossary_engine.detect_source_terms(parse_result.masked_text)
        mandatory_matched = 0
        for term in source_terms:
            expected_target = term.target_term(target_language)
            has_mandatory = self.glossary_engine.term_present_in_text(
                expected_target,
                masked_translation,
                case_sensitive=term.case_sensitive,
            )
            if has_mandatory and term.id not in forbidden_term_ids:
                mandatory_matched += 1
                continue

            if term.id in forbidden_term_ids:
                continue

            # Check if the English source term was left untranslated.
            left_untranslated = self.glossary_engine.term_present_in_text(
                term.en,
                masked_translation,
                case_sensitive=term.case_sensitive,
            )
            if left_untranslated and term.en.lower() != expected_target.lower():
                penalty = 5.0
                total_penalty += penalty
                observations.append(
                    CriticObservation(
                        code="UNTRANSLATED_TERM",
                        severity=CriticSeverity.MAJOR,
                        message=f"English source term {term.en!r} was left untranslated.",
                        term_id=term.id,
                        expected=expected_target,
                        found=term.en,
                        penalty=penalty,
                    )
                )
            else:
                penalty = 6.0
                total_penalty += penalty
                observations.append(
                    CriticObservation(
                        code="MANDATORY_TERM_MISSING",
                        severity=CriticSeverity.MAJOR,
                        message=f"Mandatory glossary term {expected_target!r} (for {term.en!r}) is missing.",
                        term_id=term.id,
                        expected=expected_target,
                        found=None,
                        penalty=penalty,
                    )
                )

        # 3. Markdown structural consistency checks (headings & table separators).
        src_headings = len(_HEADING_LINE_RE.findall(parse_result.masked_text))
        tgt_headings = len(_HEADING_LINE_RE.findall(masked_translation))
        if src_headings != tgt_headings:
            penalty = 4.0
            total_penalty += penalty
            observations.append(
                CriticObservation(
                    code="HEADING_STRUCTURE_MISMATCH",
                    severity=CriticSeverity.MINOR,
                    message="Markdown heading count differs between source and translation.",
                    expected=str(src_headings),
                    found=str(tgt_headings),
                    penalty=penalty,
                )
            )

        src_tables = len(_TABLE_SEP_LINE_RE.findall(parse_result.masked_text))
        tgt_tables = len(_TABLE_SEP_LINE_RE.findall(masked_translation))
        if src_tables != tgt_tables:
            penalty = 4.0
            total_penalty += penalty
            observations.append(
                CriticObservation(
                    code="TABLE_STRUCTURE_MISMATCH",
                    severity=CriticSeverity.MINOR,
                    message="Markdown table separator count differs between source and translation.",
                    expected=str(src_tables),
                    found=str(tgt_tables),
                    penalty=penalty,
                )
            )

        score = max(0.0, round(100.0 - total_penalty, 2))
        token_rate = (
            100.0
            if validation.expected_count == 0
            else round(100.0 * validation.present_count / validation.expected_count, 2)
        )
        term_precision = (
            100.0
            if not source_terms
            else round(100.0 * mandatory_matched / len(source_terms), 2)
        )
        passed = (
            score >= self.pass_threshold
            and validation.valid
            and not corrupted_matches
        )

        return CriticReport(
            iteration=iteration,
            target_language=target_language,
            score=score,
            passed=passed,
            threshold=self.pass_threshold,
            tokens_expected=validation.expected_count,
            tokens_intact=validation.present_count,
            token_integrity_rate=token_rate,
            source_terms_detected=len(source_terms),
            mandatory_terms_matched=mandatory_matched,
            forbidden_terms_found=len(forbidden_hits),
            terminology_precision=term_precision,
            observations=observations,
        )


class LocalizationSwarm:
    """Orchestrates deterministic parsing, translator-critic feedback loop, and rebuilding."""

    def __init__(
        self,
        glossary_engine: GlossaryEngine,
        translator: DomainTranslatorAgent | None = None,
        critic: TerminologyCriticAgent | None = None,
        parser: MarkdownProtectedParser | None = None,
        rebuilder: DocumentRebuilder | None = None,
    ) -> None:
        self.glossary_engine = glossary_engine
        self.parser = parser or MarkdownProtectedParser()
        self.rebuilder = rebuilder or DocumentRebuilder()
        self.translator = translator or DomainTranslatorAgent(glossary_engine=glossary_engine)
        self.critic = critic or TerminologyCriticAgent(
            glossary_engine=glossary_engine,
            rebuilder=self.rebuilder,
        )

    def localize_text(
        self,
        source_text: str,
        target_language: TargetLanguage,
        max_iterations: int = 3,
        source_path: str | None = None,
    ) -> LocalizationResult:
        """Parse, translate, audit, and auto-correct until score >= 95 or max_iterations."""
        parse_result = self.parser.parse(source_text)
        iterations: list[TranslationIteration] = []

        feedback: CriticReport | None = None
        previous_draft: str | None = None

        for idx in range(1, max(1, max_iterations) + 1):
            draft, corr_prompt = self.translator.translate(
                parse_result=parse_result,
                target_language=target_language,
                feedback=feedback,
                previous_draft=previous_draft,
            )
            report = self.critic.audit(
                parse_result=parse_result,
                masked_translation=draft,
                target_language=target_language,
                iteration=idx,
            )
            iterations.append(
                TranslationIteration(
                    iteration=idx,
                    masked_translation=draft,
                    critic_report=report,
                    correction_prompt_used=corr_prompt,
                )
            )
            previous_draft = draft
            feedback = report
            if report.passed:
                break

        last_iter = iterations[-1]
        token_ok = last_iter.critic_report.token_integrity_rate == 100.0 and not any(
            obs.code in ("TOKEN_MISSING", "TOKEN_DUPLICATED", "TOKEN_CORRUPTED")
            for obs in last_iter.critic_report.observations
        )
        rebuilt = self.rebuilder.rebuild(
            masked_text=last_iter.masked_translation,
            blocks=parse_result.blocks,
            strict=token_ok,
        )
        syntax_verified = token_ok and self.rebuilder.verify_syntax_integrity(
            parse_result.blocks,
            rebuilt,
        )

        return LocalizationResult(
            source_path=source_path,
            target_language=target_language,
            parse_result=parse_result,
            iterations=iterations,
            final_masked_text=last_iter.masked_translation,
            final_rebuilt_text=rebuilt,
            final_score=last_iter.critic_report.score,
            passed=last_iter.critic_report.passed,
            syntax_integrity_verified=syntax_verified,
            output_path=None,
        )

    def localize_file(
        self,
        input_path: Path,
        target_languages: list[TargetLanguage],
        output_dir: Path,
        max_iterations: int = 3,
        export_audit: bool = True,
    ) -> list[LocalizationResult]:
        """Localize a Markdown file into each requested target language and export artifacts."""
        source_text = input_path.read_text(encoding="utf-8")
        stem = input_path.stem
        if stem.endswith("_en"):
            stem = stem[:-3]

        results: list[LocalizationResult] = []
        for lang in target_languages:
            result = self.localize_text(
                source_text=source_text,
                target_language=lang,
                max_iterations=max_iterations,
                source_path=str(input_path),
            )
            out_file = output_dir / f"{stem}_{lang.value}.md"
            self.rebuilder.export_document(result, out_file)
            result.output_path = str(out_file)
            results.append(result)

        if export_audit:
            self.rebuilder.export_audit_report(results, output_dir / "translation_audit_report.json")

        return results
