"""Deterministic AST + regex preprocessor for syntax-safe Markdown localization."""

from __future__ import annotations

import re
import uuid
from typing import Callable

from markdown_it import MarkdownIt

from src.models import BlockKind, ParseResult, ProtectedBlock

TOKEN_PREFIX = "__PROTECTED_BLOCK_"
TOKEN_SUFFIX = "__"
TOKEN_PATTERN = re.compile(r"__PROTECTED_BLOCK_(\d{2,})__")

# Regexes ordered by precedence after AST block extraction.
DISPLAY_LATEX_DOLLAR_RE = re.compile(r"(?<!\\)\$\$(.+?)(?<!\\)\$\$", re.DOTALL)
DISPLAY_LATEX_BRACKET_RE = re.compile(r"(?<!\\)\\\[(.+?)(?<!\\)\\\]", re.DOTALL)
INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)((?:(?!\n\n).)+?)(?<!`)\1(?!`)", re.DOTALL)
XML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
XML_PI_RE = re.compile(r"<\?[\s\S]*?\?>")
XML_TAG_RE = re.compile(
    r"</?[A-Za-z][A-Za-z0-9_:\-.]*"
    r"(?:\s+[A-Za-z_:][A-Za-z0-9_:\-.]*"
    r"(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s\"'=<>`]+))?)*"
    r"\s*/?>"
)
INLINE_LATEX_DOLLAR_RE = re.compile(
    r"(?<!\\)\$(?!\$)(?!\s)([^$\n]+?)(?<!\s)(?<!\\)\$(?!\$)(?!\d)"
)
INLINE_LATEX_PAREN_RE = re.compile(r"(?<!\\)\\\((.+?)(?<!\\)\\\)", re.DOTALL)

_TAG_NAME_RE = re.compile(r"^<\s*/?\s*([A-Za-z][A-Za-z0-9_:\-.]*)")
_HTML_OR_XML_START_RE = re.compile(r"^\s*(?:<!--|<\?|</?[A-Za-z][A-Za-z0-9_:\-.]*)")


def format_token(index: int) -> str:
    """Format a 1-based index into a canonical protected block token."""
    return f"{TOKEN_PREFIX}{index:02d}{TOKEN_SUFFIX}"


def _is_likely_inline_latex(inner: str) -> bool:
    """Filter out obvious currency false positives while keeping LaTeX math."""
    stripped = inner.strip()
    if not stripped:
        return False
    # Reject fragments ending with dash/slash right before another currency value.
    if re.fullmatch(r"\d[\d.,]*\s*[-–/]", stripped):
        return False
    # Reject plain number + English words without any LaTeX/math operators.
    if (
        re.match(r"^\d[\d.,]*\s+[A-Za-z]+", stripped)
        and "\\" not in stripped
        and not any(op in stripped for op in "=^_<>+*/{}")
    ):
        return False
    return True


class MarkdownProtectedParser:
    """Extracts and masks syntax-critical Markdown blocks using AST + regex."""

    def __init__(self) -> None:
        self._md = MarkdownIt("commonmark").enable("table")

    def parse(self, text: str) -> ParseResult:
        """Mask fenced/indented/inline code, XML, and LaTeX into immutable tokens."""
        sentinel_prefix = self._make_sentinel_prefix(text)
        temp_store: dict[str, tuple[BlockKind, str, dict[str, str]]] = {}
        counter = 0

        def register(kind: BlockKind, content: str, metadata: dict[str, str] | None = None) -> str:
            nonlocal counter
            counter += 1
            sentinel = f"{sentinel_prefix}{counter:06d}@@"
            temp_store[sentinel] = (kind, content, metadata or {})
            return sentinel

        # Stage 1: CommonMark + GFM-table AST extraction for block-level structures.
        tokens = self._md.parse(text)
        ast_summary = self._summarize_ast(tokens)
        masked = self._extract_ast_blocks(text, tokens, register)

        # Stage 2: Strict-precedence regex extraction on remaining prose.
        masked = self._mask_regex(
            masked,
            DISPLAY_LATEX_DOLLAR_RE,
            lambda m: register(BlockKind.LATEX_DISPLAY, m.group(0), {"delimiter": "$$"}),
            sentinel_prefix,
        )
        masked = self._mask_regex(
            masked,
            DISPLAY_LATEX_BRACKET_RE,
            lambda m: register(BlockKind.LATEX_DISPLAY, m.group(0), {"delimiter": "\\[\\]"}),
            sentinel_prefix,
        )
        masked = self._mask_regex(
            masked,
            INLINE_CODE_RE,
            lambda m: register(
                BlockKind.INLINE_CODE, m.group(0), {"backticks": str(len(m.group(1)))}
            ),
            sentinel_prefix,
        )
        masked = self._mask_regex(
            masked,
            XML_COMMENT_RE,
            lambda m: register(BlockKind.XML_TAG, m.group(0), {"tag_name": "!--"}),
            sentinel_prefix,
        )
        masked = self._mask_regex(
            masked,
            XML_PI_RE,
            lambda m: register(BlockKind.XML_TAG, m.group(0), {"tag_name": "?"}),
            sentinel_prefix,
        )
        masked = self._mask_regex(
            masked,
            XML_TAG_RE,
            lambda m: register(
                BlockKind.XML_TAG,
                m.group(0),
                {"tag_name": self._extract_tag_name(m.group(0))},
            ),
            sentinel_prefix,
        )
        masked = self._mask_regex(
            masked,
            INLINE_LATEX_DOLLAR_RE,
            lambda m: (
                register(BlockKind.LATEX_INLINE, m.group(0), {"delimiter": "$"})
                if _is_likely_inline_latex(m.group(1))
                else m.group(0)
            ),
            sentinel_prefix,
        )
        masked = self._mask_regex(
            masked,
            INLINE_LATEX_PAREN_RE,
            lambda m: register(BlockKind.LATEX_INLINE, m.group(0), {"delimiter": "\\(\\)"}),
            sentinel_prefix,
        )

        # Stage 3: Re-index in left-to-right reading order and compute exact line spans.
        sentinel_re = re.compile(rf"{re.escape(sentinel_prefix)}\d{{6}}@@")
        blocks: list[ProtectedBlock] = []
        final_parts: list[str] = []
        cursor = 0
        current_line = 1

        for idx, match in enumerate(sentinel_re.finditer(masked), start=1):
            preceding = masked[cursor : match.start()]
            final_parts.append(preceding)
            current_line += preceding.count("\n")

            kind, original_content, metadata = temp_store[match.group(0)]
            token = format_token(idx)
            end_line = current_line + original_content.count("\n")

            blocks.append(
                ProtectedBlock(
                    token=token,
                    index=idx,
                    kind=kind,
                    original_content=original_content,
                    start_line=current_line,
                    end_line=end_line,
                    metadata=metadata,
                )
            )
            final_parts.append(token)
            current_line = end_line
            cursor = match.end()

        final_parts.append(masked[cursor:])
        final_masked = "".join(final_parts)

        return ParseResult(
            original_text=text,
            masked_text=final_masked,
            blocks=blocks,
            ast_summary=ast_summary,
        )

    @staticmethod
    def _make_sentinel_prefix(text: str) -> str:
        while True:
            candidate = f"@@__PROT_TMP_{uuid.uuid4().hex[:12]}_"
            if candidate not in text:
                return candidate

    @staticmethod
    def _summarize_ast(tokens: list) -> dict[str, int]:
        return {
            "headings": sum(1 for t in tokens if t.type == "heading_open"),
            "tables": sum(1 for t in tokens if t.type == "table_open"),
            "fenced_code_blocks": sum(1 for t in tokens if t.type == "fence"),
            "indented_code_blocks": sum(1 for t in tokens if t.type == "code_block"),
            "html_blocks": sum(1 for t in tokens if t.type == "html_block"),
            "paragraphs": sum(1 for t in tokens if t.type == "paragraph_open"),
            "lists": sum(1 for t in tokens if t.type in ("bullet_list_open", "ordered_list_open")),
        }

    @staticmethod
    def _extract_tag_name(tag_text: str) -> str:
        match = _TAG_NAME_RE.match(tag_text)
        return match.group(1) if match else "xml"

    def _extract_ast_blocks(
        self,
        text: str,
        tokens: list,
        register: Callable[[BlockKind, str, dict[str, str] | None], str],
    ) -> str:
        lines = text.splitlines(keepends=True)
        if not lines:
            return text

        # Collect non-overlapping block spans identified by the Markdown AST.
        candidate_spans: list[tuple[int, int, BlockKind, dict[str, str]]] = []
        for tok in tokens:
            if not tok.map:
                continue
            start, end = tok.map
            if start >= end or end > len(lines):
                continue

            if tok.type == "fence":
                info = (tok.info or "").strip()
                meta = {"language": info} if info else {}
                candidate_spans.append((start, end, BlockKind.FENCED_CODE, meta))
            elif tok.type == "code_block":
                candidate_spans.append((start, end, BlockKind.INDENTED_CODE, {}))
            elif tok.type == "html_block":
                raw_slice = "".join(lines[start:end])
                if _HTML_OR_XML_START_RE.match(raw_slice):
                    stripped = raw_slice.strip()
                    # Single standalone opening/closing/self-closing tag lines become XML_TAG
                    # when not spanning multiple lines, keeping consistent block semantics.
                    is_single_tag = (
                        "\n" not in stripped
                        and XML_TAG_RE.fullmatch(stripped) is not None
                    )
                    kind = BlockKind.XML_TAG if is_single_tag else BlockKind.XML_BLOCK
                    meta = {"tag_name": self._extract_tag_name(stripped)}
                    candidate_spans.append((start, end, kind, meta))

        if not candidate_spans:
            return text

        candidate_spans.sort(key=lambda item: (item[0], item[1]))
        merged_spans: list[tuple[int, int, BlockKind, dict[str, str]]] = []
        last_end = -1
        for span in candidate_spans:
            if span[0] >= last_end:
                merged_spans.append(span)
                last_end = span[1]

        out_chunks: list[str] = []
        line_idx = 0
        for start, end, kind, meta in merged_spans:
            if line_idx < start:
                out_chunks.append("".join(lines[line_idx:start]))

            slice_text = "".join(lines[start:end])
            if slice_text.endswith("\r\n"):
                content, trailing = slice_text[:-2], "\r\n"
            elif slice_text.endswith("\n"):
                content, trailing = slice_text[:-1], "\n"
            else:
                content, trailing = slice_text, ""

            sentinel = register(kind, content, meta)
            out_chunks.append(sentinel + trailing)
            line_idx = end

        if line_idx < len(lines):
            out_chunks.append("".join(lines[line_idx:]))

        return "".join(out_chunks)

    @staticmethod
    def _mask_regex(
        text: str,
        pattern: re.Pattern[str],
        replacer: Callable[[re.Match[str]], str],
        sentinel_prefix: str,
    ) -> str:
        sentinel_re = re.compile(rf"{re.escape(sentinel_prefix)}\d{{6}}@@")
        # Split around existing sentinels so regexes never inspect inside protected tokens.
        parts: list[str] = []
        cursor = 0
        for s_match in sentinel_re.finditer(text):
            chunk = text[cursor : s_match.start()]
            parts.append(pattern.sub(replacer, chunk))
            parts.append(s_match.group(0))
            cursor = s_match.end()
        parts.append(pattern.sub(replacer, text[cursor:]))
        return "".join(parts)
