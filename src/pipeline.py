"""Typer CLI entry point for the trilingual technical localization pipeline."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from src.backends import create_backend
from src.glossary import GlossaryEngine
from src.models import LanguageEvalComparison, TargetLanguage
from src.swarm_translator import (
    DomainTranslatorAgent,
    LocalizationSwarm,
    TerminologyCriticAgent,
)

app = typer.Typer(
    name="trilingual-localize",
    help="Multi-agent EN->FR/ES technical documentation localization & auditing pipeline.",
    add_completion=False,
)
console = Console()

DEFAULT_INPUT = Path("data/sample_engineering_doc_en.md")
DEFAULT_GLOSSARY = Path("data/glossary_en_fr_es.json")
DEFAULT_OUTPUT_DIR = Path("output")


def run_benchmark_comparison(
    input_path: Path = DEFAULT_INPUT,
    glossary_path: Path = DEFAULT_GLOSSARY,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    pass_threshold: float = 95.0,
) -> list[LanguageEvalComparison]:
    """Compare localization quality before vs. after TerminologyCriticAgent feedback loop."""
    source_text = input_path.read_text(encoding="utf-8")
    glossary_engine = GlossaryEngine.from_file(glossary_path)
    comparisons: list[LanguageEvalComparison] = []
    final_results = []

    for lang in (TargetLanguage.FR, TargetLanguage.ES):
        # Baseline (no critic correction loop: max_iterations=1)
        baseline_backend = create_backend(
            "deterministic",
            glossary_engine=glossary_engine,
            simulate_initial_drift=True,
        )
        baseline_swarm = LocalizationSwarm(
            glossary_engine=glossary_engine,
            translator=DomainTranslatorAgent(glossary_engine, backend=baseline_backend),
            critic=TerminologyCriticAgent(glossary_engine, pass_threshold=pass_threshold),
        )
        before_res = baseline_swarm.localize_text(
            source_text=source_text,
            target_language=lang,
            max_iterations=1,
            source_path=str(input_path),
        )
        before_rep = before_res.iterations[0].critic_report

        # Active Critic loop (auto-correction when score < 95.0)
        audited_backend = create_backend(
            "deterministic",
            glossary_engine=glossary_engine,
            simulate_initial_drift=True,
        )
        audited_swarm = LocalizationSwarm(
            glossary_engine=glossary_engine,
            translator=DomainTranslatorAgent(glossary_engine, backend=audited_backend),
            critic=TerminologyCriticAgent(glossary_engine, pass_threshold=pass_threshold),
        )
        after_res = audited_swarm.localize_text(
            source_text=source_text,
            target_language=lang,
            max_iterations=3,
            source_path=str(input_path),
        )
        after_rep = after_res.iterations[-1].critic_report

        stem = input_path.stem[:-3] if input_path.stem.endswith("_en") else input_path.stem
        out_path = output_dir / f"{stem}_{lang.value}.md"
        audited_swarm.rebuilder.export_document(after_res, out_path)
        after_res.output_path = str(out_path)
        final_results.append(after_res)

        comparisons.append(
            LanguageEvalComparison(
                language=lang,
                terms_in_source=after_rep.source_terms_detected,
                before_score=before_rep.score,
                after_score=after_rep.score,
                score_delta=round(after_rep.score - before_rep.score, 2),
                before_terminology_precision=before_rep.terminology_precision,
                after_terminology_precision=after_rep.terminology_precision,
                precision_delta=round(
                    after_rep.terminology_precision - before_rep.terminology_precision, 2
                ),
                before_forbidden_violations=before_rep.forbidden_terms_found,
                after_forbidden_violations=after_rep.forbidden_terms_found,
                before_token_integrity=before_rep.token_integrity_rate,
                after_token_integrity=after_rep.token_integrity_rate,
                iterations_required=len(after_res.iterations),
            )
        )

    if final_results:
        LocalizationSwarm(glossary_engine=glossary_engine).rebuilder.export_audit_report(
            final_results,
            output_dir / "translation_audit_report.json",
        )

    return comparisons


@app.command()
def translate(
    input_path: Path = typer.Option(DEFAULT_INPUT, "--input", "-i", help="Source English Markdown file."),
    glossary_path: Path = typer.Option(DEFAULT_GLOSSARY, "--glossary", "-g", help="Corporate glossary JSON."),
    output_dir: Path = typer.Option(DEFAULT_OUTPUT_DIR, "--output-dir", "-o", help="Export directory."),
    languages: list[TargetLanguage] = typer.Option(
        [TargetLanguage.FR, TargetLanguage.ES], "--lang", "-l", help="Target languages (fr, es)."
    ),
    backend: str = typer.Option("deterministic", "--backend", "-b", help="Backend: deterministic, openai, gemini, anthropic."),
    max_iterations: int = typer.Option(3, "--max-iterations", min=1, max=5),
    threshold: float = typer.Option(95.0, "--threshold", min=0.0, max=100.0),
) -> None:
    """Translate and audit a technical Markdown document into FR/ES."""
    glossary_engine = GlossaryEngine.from_file(glossary_path)
    llm_backend = create_backend(backend, glossary_engine=glossary_engine)
    swarm = LocalizationSwarm(
        glossary_engine=glossary_engine,
        translator=DomainTranslatorAgent(glossary_engine, backend=llm_backend),
        critic=TerminologyCriticAgent(glossary_engine, pass_threshold=threshold),
    )
    results = swarm.localize_file(
        input_path=input_path,
        target_languages=languages,
        output_dir=output_dir,
        max_iterations=max_iterations,
    )

    table = Table(title="Localization Results")
    table.add_column("Lang", style="cyan")
    table.add_column("Iterations", justify="right")
    table.add_column("Final Score", justify="right")
    table.add_column("Syntax Integrity", justify="center")
    table.add_column("Output Path")
    for res in results:
        table.add_row(
            res.target_language.value.upper(),
            str(len(res.iterations)),
            f"{res.final_score:.2f}",
            "100%" if res.syntax_integrity_verified else "FAILED",
            str(res.output_path),
        )
    console.print(table)


@app.command()
def evaluate(
    input_path: Path = typer.Option(DEFAULT_INPUT, "--input", "-i"),
    glossary_path: Path = typer.Option(DEFAULT_GLOSSARY, "--glossary", "-g"),
    output_dir: Path = typer.Option(DEFAULT_OUTPUT_DIR, "--output-dir", "-o"),
) -> None:
    """Run the before/after TerminologyCriticAgent benchmark."""
    comparisons = run_benchmark_comparison(
        input_path=input_path,
        glossary_path=glossary_path,
        output_dir=output_dir,
    )
    table = Table(title="TerminologyCriticAgent Before vs. After Benchmark")
    table.add_column("Lang", style="cyan")
    table.add_column("Terms", justify="right")
    table.add_column("Before Score", justify="right")
    table.add_column("After Score", justify="right")
    table.add_column("Before Precision", justify="right")
    table.add_column("After Precision", justify="right")
    table.add_column("Forbidden (Before->After)", justify="right")
    for comp in comparisons:
        table.add_row(
            comp.language.value.upper(),
            str(comp.terms_in_source),
            f"{comp.before_score:.1f}",
            f"{comp.after_score:.1f}",
            f"{comp.before_terminology_precision:.1f}%",
            f"{comp.after_terminology_precision:.1f}%",
            f"{comp.before_forbidden_violations} -> {comp.after_forbidden_violations}",
        )
    console.print(table)


if __name__ == "__main__":
    app()
