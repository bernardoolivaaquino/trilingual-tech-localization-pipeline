"""Unit tests for the deterministic AST + regex Markdown preprocessor."""

from __future__ import annotations

from src.models import BlockKind
from src.parser import MarkdownProtectedParser, TOKEN_PATTERN
from src.rebuilder import DocumentRebuilder


def test_extracts_fenced_and_indented_code_blocks(
    parser: MarkdownProtectedParser,
    rebuilder: DocumentRebuilder,
) -> None:
    src = (
        "# Title\n\n"
        "Intro paragraph.\n\n"
        "```python\n"
        "def compute(x: float) -> float:\n"
        "    return x * 2.0  # $not_latex\n"
        "```\n\n"
        "Another paragraph.\n\n"
        "    indented_var = 42\n"
        "    print(indented_var)\n"
    )
    res = parser.parse(src)

    assert len(res.blocks) == 2
    assert res.blocks[0].kind == BlockKind.FENCED_CODE
    assert res.blocks[0].metadata.get("language") == "python"
    assert res.blocks[0].token == "__PROTECTED_BLOCK_01__"
    assert res.blocks[1].kind == BlockKind.INDENTED_CODE
    assert res.blocks[1].token == "__PROTECTED_BLOCK_02__"
    assert "$not_latex" not in res.masked_text
    assert rebuilder.rebuild(res.masked_text, res.blocks) == src


def test_inline_code_and_latex_precedence_and_currency_safety(
    parser: MarkdownProtectedParser,
    rebuilder: DocumentRebuilder,
) -> None:
    src = (
        "Use `config_var` and ``<xml-inline>`` with `$RAW_ENV`.\n"
        "Energy follows $E = mc^2$ and thermal flux follows:\n\n"
        "$$q'' = -k \\nabla T$$\n\n"
        "Budget is $50 and $75 or $100-$200 per unit, while $x < y$ and $a > b$.\n"
    )
    res = parser.parse(src)

    kinds = [b.kind for b in res.blocks]
    assert BlockKind.INLINE_CODE in kinds
    assert BlockKind.LATEX_INLINE in kinds
    assert BlockKind.LATEX_DISPLAY in kinds
    # Inline code containing <xml-inline> and $RAW_ENV must remain INLINE_CODE, not split.
    inline_codes = [b.original_content for b in res.blocks if b.kind == BlockKind.INLINE_CODE]
    assert "`config_var`" in inline_codes
    assert "``<xml-inline>``" in inline_codes
    assert "`$RAW_ENV`" in inline_codes

    # Currency amounts must remain untouched in prose.
    assert "$50 and $75" in res.masked_text
    assert "$100-$200" in res.masked_text
    assert rebuilder.rebuild(res.masked_text, res.blocks) == src


def test_xml_blocks_inline_tags_and_math_comparisons(
    parser: MarkdownProtectedParser,
    rebuilder: DocumentRebuilder,
) -> None:
    src = (
        "<callout severity=\"critical\">\n\n"
        "Check <sensor-ref id=\"TC-07\" /> when pressure a < b and x > 0.\n\n"
        "</callout>\n\n"
        "<telemetry-config version=\"2.4\">\n"
        "  <endpoint role=\"primary\" />\n"
        "</telemetry-config>\n"
    )
    res = parser.parse(src)

    assert "Check __PROTECTED_BLOCK_" in res.masked_text
    assert "when pressure a < b and x > 0." in res.masked_text
    xml_blocks = [b for b in res.blocks if b.kind == BlockKind.XML_BLOCK]
    xml_tags = [b for b in res.blocks if b.kind == BlockKind.XML_TAG]
    assert len(xml_blocks) == 1
    assert len(xml_tags) == 3
    assert rebuilder.rebuild(res.masked_text, res.blocks) == src


def test_reading_order_sequential_tokens_and_sample_doc_roundtrip(
    parser: MarkdownProtectedParser,
    rebuilder: DocumentRebuilder,
    sample_doc_text: str,
) -> None:
    res = parser.parse(sample_doc_text)
    found_tokens = [m.group(0) for m in TOKEN_PATTERN.finditer(res.masked_text)]
    expected_tokens = [f"__PROTECTED_BLOCK_{i:02d}__" for i in range(1, len(res.blocks) + 1)]

    assert found_tokens == expected_tokens
    assert res.ast_summary["tables"] == 2
    assert res.ast_summary["fenced_code_blocks"] == 2
    assert rebuilder.rebuild(res.masked_text, res.blocks) == sample_doc_text
