"""Unit tests for single-pass DocumentRebuilder and integrity checks."""

from __future__ import annotations

from pathlib import Path
import pytest

from src.models import BlockKind, ProtectedBlock, TargetLanguage
from src.parser import MarkdownProtectedParser
from src.rebuilder import DocumentRebuilder, TokenIntegrityError
from src.glossary import GlossaryEngine
from src.swarm_translator import LocalizationSwarm


def test_single_pass_prevents_recursive_token_expansion(
    rebuilder: DocumentRebuilder,
) -> None:
    blocks = [
        ProtectedBlock(
            token="__PROTECTED_BLOCK_01__",
            index=1,
            kind=BlockKind.INLINE_CODE,
            original_content="`__PROTECTED_BLOCK_02__`",
            start_line=1,
            end_line=1,
        ),
        ProtectedBlock(
            token="__PROTECTED_BLOCK_02__",
            index=2,
            kind=BlockKind.INLINE_CODE,
            original_content="`SECOND_VALUE`",
            start_line=1,
            end_line=1,
        ),
    ]
    masked = "First __PROTECTED_BLOCK_01__ then __PROTECTED_BLOCK_02__."
    rebuilt = rebuilder.rebuild(masked, blocks, strict=True)

    assert rebuilt == "First `__PROTECTED_BLOCK_02__` then `SECOND_VALUE`."


def test_rebuild_strict_raises_on_missing_or_duplicated_tokens(
    parser: MarkdownProtectedParser,
    rebuilder: DocumentRebuilder,
) -> None:
    src = "Value `alpha` and formula $x + 1$."
    parsed = parser.parse(src)

    missing_masked = "Value __PROTECTED_BLOCK_01__ and formula."
    with pytest.raises(TokenIntegrityError):
        rebuilder.rebuild(missing_masked, parsed.blocks, strict=True)

    duplicated_masked = "Value __PROTECTED_BLOCK_01__ __PROTECTED_BLOCK_01__ and __PROTECTED_BLOCK_02__."
    with pytest.raises(TokenIntegrityError):
        rebuilder.rebuild(duplicated_masked, parsed.blocks, strict=True)


def test_verify_syntax_integrity_detects_leaked_tokens_or_corrupted_blocks(
    parser: MarkdownProtectedParser,
    rebuilder: DocumentRebuilder,
) -> None:
    parsed = parser.parse("Run `verify_crc32()` and $q'' = -k \\nabla T$.")
    assert rebuilder.verify_syntax_integrity(
        parsed.blocks, "Exécutez `verify_crc32()` et $q'' = -k \\nabla T$."
    )
    assert not rebuilder.verify_syntax_integrity(
        parsed.blocks, "Exécutez __PROTECTED_BLOCK_01__ et $q'' = -k \\nabla T$."
    )
    assert not rebuilder.verify_syntax_integrity(
        parsed.blocks, "Exécutez `verify_crc16()` et $q'' = -k \\nabla T$."
    )


def test_export_document_and_audit_report(
    tmp_path: Path,
    glossary_engine: GlossaryEngine,
) -> None:
    swarm = LocalizationSwarm(glossary_engine=glossary_engine)
    results = []
    for lang in (TargetLanguage.FR, TargetLanguage.ES):
        res = swarm.localize_text(
            "The **ring buffer** validates each **checksum** with `verify_crc32()`.",
            target_language=lang,
            source_path="inline.md",
        )
        out_path = tmp_path / f"doc_{lang.value}.md"
        swarm.rebuilder.export_document(res, out_path)
        res.output_path = str(out_path)
        results.append(res)
        assert out_path.exists()

    report_path = swarm.rebuilder.export_audit_report(results, tmp_path / "audit.json")
    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert '"target_language": "fr"' in content
    assert '"target_language": "es"' in content
