"""Evaluation benchmark comparing terminology precision before vs. after TerminologyCriticAgent."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.models import LanguageEvalComparison  # noqa: E402
from src.pipeline import run_benchmark_comparison  # noqa: E402


def format_markdown_table(comparisons: list[LanguageEvalComparison]) -> str:
    """Render a publication-ready Markdown table summarizing the eval results."""
    avg_before_score = sum(c.before_score for c in comparisons) / len(comparisons)
    avg_after_score = sum(c.after_score for c in comparisons) / len(comparisons)
    avg_before_prec = sum(c.before_terminology_precision for c in comparisons) / len(comparisons)
    avg_after_prec = sum(c.after_terminology_precision for c in comparisons) / len(comparisons)
    total_before_forb = sum(c.before_forbidden_violations for c in comparisons)
    total_after_forb = sum(c.after_forbidden_violations for c in comparisons)
    avg_before_tok = sum(c.before_token_integrity for c in comparisons) / len(comparisons)
    avg_after_tok = sum(c.after_token_integrity for c in comparisons) / len(comparisons)

    lines = [
        "| Target Language | Glossary Terms | Critic Score (Before -> After) | Terminology Precision (Before -> After) | Forbidden Terms (Before -> After) | Protected Token Integrity | Iterations |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for c in comparisons:
        lines.append(
            f"| **{c.language.value.upper()}** | {c.terms_in_source} | "
            f"{c.before_score:.1f} -> **{c.after_score:.1f}** (+{c.score_delta:.1f}) | "
            f"{c.before_terminology_precision:.1f}% -> **{c.after_terminology_precision:.1f}%** (+{c.precision_delta:.1f} pp) | "
            f"{c.before_forbidden_violations} -> **{c.after_forbidden_violations}** | "
            f"{c.before_token_integrity:.1f}% -> **{c.after_token_integrity:.1f}%** | "
            f"{c.iterations_required} |"
        )
    lines.append(
        f"| **Aggregate (FR + ES)** | {comparisons[0].terms_in_source} | "
        f"{avg_before_score:.1f} -> **{avg_after_score:.1f}** (+{avg_after_score - avg_before_score:.1f}) | "
        f"{avg_before_prec:.1f}% -> **{avg_after_prec:.1f}%** (+{avg_after_prec - avg_before_prec:.1f} pp) | "
        f"{total_before_forb} -> **{total_after_forb}** | "
        f"{avg_before_tok:.1f}% -> **{avg_after_tok:.1f}%** | "
        f"{max(c.iterations_required for c in comparisons)} |"
    )
    return "\n".join(lines)


def main() -> None:
    input_path = REPO_ROOT / "data" / "sample_engineering_doc_en.md"
    glossary_path = REPO_ROOT / "data" / "glossary_en_fr_es.json"
    output_dir = REPO_ROOT / "output"

    comparisons = run_benchmark_comparison(
        input_path=input_path,
        glossary_path=glossary_path,
        output_dir=output_dir,
    )

    eval_report_path = output_dir / "eval_benchmark_report.json"
    eval_payload = {
        "benchmark": "sample_engineering_doc_en.md",
        "glossary": "glossary_en_fr_es.json",
        "pass_threshold": 95.0,
        "languages": [c.model_dump(mode="json") for c in comparisons],
        "aggregate": {
            "avg_before_score": round(sum(c.before_score for c in comparisons) / len(comparisons), 2),
            "avg_after_score": round(sum(c.after_score for c in comparisons) / len(comparisons), 2),
            "avg_before_terminology_precision": round(
                sum(c.before_terminology_precision for c in comparisons) / len(comparisons), 2
            ),
            "avg_after_terminology_precision": round(
                sum(c.after_terminology_precision for c in comparisons) / len(comparisons), 2
            ),
            "total_before_forbidden_violations": sum(
                c.before_forbidden_violations for c in comparisons
            ),
            "total_after_forbidden_violations": sum(
                c.after_forbidden_violations for c in comparisons
            ),
        },
    }
    eval_report_path.write_text(
        json.dumps(eval_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    console = Console()
    table = Table(title="Trilingual Localization Eval: Before vs. After TerminologyCriticAgent")
    table.add_column("Language", style="cyan")
    table.add_column("Terms", justify="right")
    table.add_column("Score (Before -> After)", justify="right")
    table.add_column("Precision (Before -> After)", justify="right")
    table.add_column("Forbidden (Before -> After)", justify="right")
    table.add_column("Token Integrity", justify="right")
    table.add_column("Iterations", justify="right")

    for c in comparisons:
        table.add_row(
            c.language.value.upper(),
            str(c.terms_in_source),
            f"{c.before_score:.1f} -> {c.after_score:.1f} (+{c.score_delta:.1f})",
            f"{c.before_terminology_precision:.1f}% -> {c.after_terminology_precision:.1f}% (+{c.precision_delta:.1f} pp)",
            f"{c.before_forbidden_violations} -> {c.after_forbidden_violations}",
            f"{c.after_token_integrity:.1f}%",
            str(c.iterations_required),
        )
    console.print(table)
    console.print("\n[bold]Markdown Summary Table:[/bold]\n")
    print(format_markdown_table(comparisons))


if __name__ == "__main__":
    main()
