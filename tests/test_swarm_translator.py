"""Unit tests for GlossaryEngine, DomainTranslatorAgent, TerminologyCriticAgent, and LocalizationSwarm."""

from __future__ import annotations

from src.backends import DeterministicLocalizationBackend
from src.glossary import GlossaryEngine
from src.models import CriticReport, Glossary, TargetLanguage
from src.parser import MarkdownProtectedParser
from src.swarm_translator import (
    DomainTranslatorAgent,
    LocalizationSwarm,
    TerminologyCriticAgent,
)


def test_glossary_has_25_unique_terms_with_mandatory_and_forbidden_rules(
    glossary: Glossary,
) -> None:
    assert len(glossary.terms) == 25
    assert len({t.id for t in glossary.terms}) == 25
    for term in glossary.terms:
        assert term.en.strip()
        assert term.fr.strip()
        assert term.es.strip()
        assert len(term.forbidden_fr) >= 1
        assert len(term.forbidden_es) >= 1


def test_translator_prompt_dynamically_injects_glossary_rules(
    glossary_engine: GlossaryEngine,
    parser: MarkdownProtectedParser,
) -> None:
    agent = DomainTranslatorAgent(glossary_engine=glossary_engine)
    parsed = parser.parse("Avoid **thermal runaway** in the **telemetry pipeline** using `pid_step()`.")
    terms = glossary_engine.detect_source_terms(parsed.masked_text)

    fr_prompt = agent.build_system_prompt(TargetLanguage.FR, relevant_terms=terms)
    es_prompt = agent.build_system_prompt(TargetLanguage.ES, relevant_terms=terms)

    assert "emballement thermique" in fr_prompt
    assert "fuite thermique" in fr_prompt
    assert "embalamiento térmico" in es_prompt
    assert "fuga térmica" in es_prompt
    assert "__PROTECTED_BLOCK_XX__" in fr_prompt


def test_critic_scores_compliant_vs_violating_and_corrupted_translations(
    glossary_engine: GlossaryEngine,
    parser: MarkdownProtectedParser,
) -> None:
    critic = TerminologyCriticAgent(glossary_engine=glossary_engine, pass_threshold=95.0)
    parsed = parser.parse(
        "The **telemetry pipeline** prevents **thermal runaway** using `pid_step()`."
    )

    compliant = (
        "La **chaîne de télémétrie** prévient l'**emballement thermique** avec __PROTECTED_BLOCK_01__."
    )
    good_report = critic.audit(parsed, compliant, TargetLanguage.FR, iteration=1)
    assert good_report.score == 100.0
    assert good_report.passed is True
    assert good_report.token_integrity_rate == 100.0
    assert good_report.terminology_precision == 100.0

    forbidden = (
        "La **chaîne de télémétrie** prévient la **fuite thermique** avec __PROTECTED_BLOCK_01__."
    )
    bad_term_report = critic.audit(parsed, forbidden, TargetLanguage.FR, iteration=1)
    assert bad_term_report.score < 95.0
    assert bad_term_report.passed is False
    assert bad_term_report.forbidden_terms_found == 1
    assert any(o.code == "FORBIDDEN_TERM_USED" for o in bad_term_report.observations)

    broken_token = (
        "La **chaîne de télémétrie** prévient l'**emballement thermique** avec _PROTECTED_BLOCK_1_."
    )
    bad_tok_report = critic.audit(parsed, broken_token, TargetLanguage.FR, iteration=1)
    assert bad_tok_report.score < 95.0
    assert bad_tok_report.passed is False
    assert bad_tok_report.token_integrity_rate == 0.0
    assert any(o.code == "TOKEN_MISSING" for o in bad_tok_report.observations)
    assert any(o.code == "TOKEN_CORRUPTED" for o in bad_tok_report.observations)


def test_swarm_auto_corrects_when_score_below_95_and_honors_max_iterations(
    glossary_engine: GlossaryEngine,
) -> None:
    backend = DeterministicLocalizationBackend(
        glossary_engine=glossary_engine,
        simulate_initial_drift=True,
    )
    swarm = LocalizationSwarm(
        glossary_engine=glossary_engine,
        translator=DomainTranslatorAgent(glossary_engine, backend=backend),
        critic=TerminologyCriticAgent(glossary_engine, pass_threshold=95.0),
    )

    sample = (
        "Prevent **thermal runaway** and **deadlock** in the **ring buffer** "
        "by tripping the **circuit breaker** with `verify_crc32()`."
    )
    res = swarm.localize_text(sample, TargetLanguage.ES, max_iterations=3)

    assert len(res.iterations) == 2
    assert res.iterations[0].critic_report.score < 95.0
    assert res.iterations[0].critic_report.passed is False
    assert res.iterations[1].correction_prompt_used is not None
    assert res.iterations[1].critic_report.score >= 95.0
    assert res.passed is True
    assert res.syntax_integrity_verified is True

    # Stubborn backend that refuses to fix errors must stop cleanly at max_iterations.
    class StubbornBackend:
        def translate(
            self,
            masked_source: str,
            target_language: TargetLanguage,
            system_prompt: str,
            correction_prompt: str | None = None,
            previous_draft: str | None = None,
            critic_report: CriticReport | None = None,
        ) -> str:
            return "Éviter la fuite thermique sans __PROTECTED_BLOCK_01__."

    stubborn_swarm = LocalizationSwarm(
        glossary_engine=glossary_engine,
        translator=DomainTranslatorAgent(glossary_engine, backend=StubbornBackend()),
        critic=TerminologyCriticAgent(glossary_engine, pass_threshold=95.0),
    )
    stubborn_res = stubborn_swarm.localize_text(sample, TargetLanguage.FR, max_iterations=2)
    assert len(stubborn_res.iterations) == 2
    assert stubborn_res.passed is False
    assert stubborn_res.final_score < 95.0
    assert stubborn_res.syntax_integrity_verified is True

    # Stubborn backend that drops the protected token must report syntax_integrity_verified=False.
    class BrokenTokenBackend:
        def translate(
            self,
            masked_source: str,
            target_language: TargetLanguage,
            system_prompt: str,
            correction_prompt: str | None = None,
            previous_draft: str | None = None,
            critic_report: CriticReport | None = None,
        ) -> str:
            return "Éviter l'emballement thermique sans jeton."

    broken_swarm = LocalizationSwarm(
        glossary_engine=glossary_engine,
        translator=DomainTranslatorAgent(glossary_engine, backend=BrokenTokenBackend()),
        critic=TerminologyCriticAgent(glossary_engine, pass_threshold=95.0),
    )
    broken_res = broken_swarm.localize_text(sample, TargetLanguage.FR, max_iterations=2)
    assert len(broken_res.iterations) == 2
    assert broken_res.passed is False
    assert broken_res.syntax_integrity_verified is False
