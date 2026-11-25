"""End-to-end and quantitative evaluation tests."""

from __future__ import annotations

from pathlib import Path

from src.glossary import GlossaryEngine
from src.models import BlockKind
from src.parser import MarkdownProtectedParser
from src.pipeline import run_benchmark_comparison


def test_sample_engineering_doc_meets_complexity_and_glossary_coverage(
    sample_doc_text: str,
    glossary_engine: GlossaryEngine,
    parser: MarkdownProtectedParser,
) -> None:
    word_count = len(sample_doc_text.split())
    assert 720 <= word_count <= 900

    parsed = parser.parse(sample_doc_text)
    detected_terms = glossary_engine.detect_source_terms(parsed.masked_text)
    assert len(detected_terms) == 25

    assert parsed.ast_summary["tables"] == 2
    assert parsed.ast_summary["fenced_code_blocks"] == 2
    kinds = {b.kind for b in parsed.blocks}
    assert BlockKind.FENCED_CODE in kinds
    assert BlockKind.INLINE_CODE in kinds
    assert BlockKind.LATEX_DISPLAY in kinds
    assert BlockKind.LATEX_INLINE in kinds
    assert BlockKind.XML_BLOCK in kinds
    assert BlockKind.XML_TAG in kinds


def test_end_to_end_benchmark_improves_precision_and_eliminates_violations(
    tmp_path: Path,
    sample_doc_path: Path,
    glossary_path: Path,
    parser: MarkdownProtectedParser,
    sample_doc_text: str,
) -> None:
    comparisons = run_benchmark_comparison(
        input_path=sample_doc_path,
        glossary_path=glossary_path,
        output_dir=tmp_path,
    )
    assert len(comparisons) == 2

    parsed_src = parser.parse(sample_doc_text)

    for comp in comparisons:
        assert comp.terms_in_source == 25
        assert comp.before_score < 95.0
        assert comp.after_score >= 95.0
        assert comp.score_delta > 0.0
        assert comp.after_terminology_precision > comp.before_terminology_precision
        assert comp.after_terminology_precision == 100.0
        assert comp.before_forbidden_violations > 0
        assert comp.after_forbidden_violations == 0
        assert comp.after_token_integrity == 100.0
        assert comp.iterations_required >= 2

        out_md = tmp_path / f"sample_engineering_doc_{comp.language.value}.md"
        assert out_md.exists()
        rebuilt = out_md.read_text(encoding="utf-8")
        for block in parsed_src.blocks:
            assert block.original_content in rebuilt

    assert (tmp_path / "translation_audit_report.json").exists()
