"""Corporate glossary loader, term detector, and prompt-rule builder."""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.models import Glossary, GlossaryTerm, TargetLanguage
from src.parser import TOKEN_PATTERN

_WORD_BOUNDARY_CHARS = r"A-Za-z0-9_À-ÖØ-öø-ÿ"
_LEFT_BOUNDARY = rf"(?<![{_WORD_BOUNDARY_CHARS}])"
_RIGHT_BOUNDARY = rf"(?![{_WORD_BOUNDARY_CHARS}])"

_INVARIANT_FUNCTION_WORDS = {
    "a",
    "à",
    "au",
    "aux",
    "de",
    "del",
    "des",
    "du",
    "en",
    "la",
    "las",
    "le",
    "les",
    "los",
    "para",
    "por",
    "y",
}


def load_glossary(path: Path) -> Glossary:
    """Load and validate a trilingual glossary JSON file."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Glossary.model_validate(raw)


def _normalize_apostrophes(text: str) -> str:
    return text.replace("’", "'").replace("`", "'")


def _strip_protected_tokens(text: str) -> str:
    return TOKEN_PATTERN.sub(" ", text)


def _phrase_to_regex(phrase: str, case_sensitive: bool = False, allow_inflection: bool = True) -> re.Pattern[str]:
    normalized = _normalize_apostrophes(phrase.strip())
    tokens = normalized.split()
    part_patterns: list[str] = []

    for tok in tokens:
        if "'" in tok:
            prefix, rest = tok.split("'", 1)
            suffix = r"(?:es|s)?" if (allow_inflection and len(rest) >= 4) else ""
            part_patterns.append(rf"{re.escape(prefix)}'{re.escape(rest)}{suffix}")
        elif "-" in tok:
            subparts = tok.split("-")
            sub_patterns = []
            for idx, sub in enumerate(subparts):
                is_last = idx == len(subparts) - 1
                suffix = r"(?:es|s)?" if (allow_inflection and is_last and len(sub) >= 4) else ""
                sub_patterns.append(rf"{re.escape(sub)}{suffix}")
            part_patterns.append(r"[-\s]+".join(sub_patterns))
        else:
            if allow_inflection and tok.lower() not in _INVARIANT_FUNCTION_WORDS and len(tok) >= 4:
                part_patterns.append(rf"{re.escape(tok)}(?:es|s)?")
            else:
                part_patterns.append(re.escape(tok))

    joined = r"\s+".join(part_patterns)
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(rf"{_LEFT_BOUNDARY}{joined}{_RIGHT_BOUNDARY}", flags)


class GlossaryEngine:
    """Detects source terms, validates target translations, and builds prompt rules."""

    def __init__(self, glossary: Glossary) -> None:
        self.glossary = glossary

    @classmethod
    def from_file(cls, path: Path) -> "GlossaryEngine":
        """Create a GlossaryEngine directly from a JSON glossary path."""
        return cls(load_glossary(path))

    def detect_source_terms(self, masked_source: str) -> list[GlossaryTerm]:
        """Identify glossary terms occurring in translatable English prose."""
        prose = _normalize_apostrophes(_strip_protected_tokens(masked_source))
        detected: list[GlossaryTerm] = []

        for term in self.glossary.terms:
            candidates = [term.en, *term.en_aliases]
            for candidate in candidates:
                pattern = _phrase_to_regex(
                    candidate, case_sensitive=term.case_sensitive, allow_inflection=True
                )
                if pattern.search(prose):
                    detected.append(term)
                    break

        return detected

    def term_present_in_text(
        self,
        phrase: str,
        text: str,
        case_sensitive: bool = False,
        strip_tokens: bool = True,
    ) -> bool:
        """Check whether a target or forbidden phrase appears in text outside protected tokens."""
        cleaned = _strip_protected_tokens(text) if strip_tokens else text
        normalized = _normalize_apostrophes(cleaned)
        pattern = _phrase_to_regex(phrase, case_sensitive=case_sensitive, allow_inflection=True)
        return pattern.search(normalized) is not None

    def find_forbidden_terms(
        self,
        masked_translation: str,
        target_language: TargetLanguage,
    ) -> list[tuple[GlossaryTerm, str]]:
        """Return all forbidden terminology occurrences found in the translation."""
        prose = _normalize_apostrophes(_strip_protected_tokens(masked_translation))
        findings: list[tuple[GlossaryTerm, str]] = []

        for term in self.glossary.terms:
            for forbidden in term.forbidden_terms(target_language):
                pattern = _phrase_to_regex(
                    forbidden, case_sensitive=term.case_sensitive, allow_inflection=True
                )
                match = pattern.search(prose)
                if match:
                    findings.append((term, match.group(0)))

        return findings

    def build_prompt_rules(
        self,
        target_language: TargetLanguage,
        relevant_terms: list[GlossaryTerm] | None = None,
    ) -> str:
        """Format mandatory and forbidden corporate glossary rules for LLM injection."""
        terms = relevant_terms if relevant_terms is not None else self.glossary.terms
        lang_label = "French (fr)" if target_language == TargetLanguage.FR else "Spanish (es)"
        lines = [
            f"Corporate Terminology Rules ({self.glossary.domain} -> {lang_label}):",
            "You MUST translate each English term using the exact mandatory target term and NEVER use any forbidden variant.",
        ]

        for term in terms:
            mandatory = term.target_term(target_language)
            forbidden = ", ".join(f'"{f}"' for f in term.forbidden_terms(target_language))
            lines.append(
                f'- [{term.id}] "{term.en}" => MANDATORY: "{mandatory}" | FORBIDDEN: {forbidden}'
            )

        return "\n".join(lines)
