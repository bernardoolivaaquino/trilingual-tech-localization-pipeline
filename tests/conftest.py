"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path
import pytest

from src.glossary import GlossaryEngine, load_glossary
from src.models import Glossary
from src.parser import MarkdownProtectedParser
from src.rebuilder import DocumentRebuilder

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def glossary_path(repo_root: Path) -> Path:
    return repo_root / "data" / "glossary_en_fr_es.json"


@pytest.fixture(scope="session")
def sample_doc_path(repo_root: Path) -> Path:
    return repo_root / "data" / "sample_engineering_doc_en.md"


@pytest.fixture(scope="session")
def glossary(glossary_path: Path) -> Glossary:
    return load_glossary(glossary_path)


@pytest.fixture(scope="session")
def glossary_engine(glossary: Glossary) -> GlossaryEngine:
    return GlossaryEngine(glossary)


@pytest.fixture(scope="session")
def sample_doc_text(sample_doc_path: Path) -> str:
    return sample_doc_path.read_text(encoding="utf-8")


@pytest.fixture
def parser() -> MarkdownProtectedParser:
    return MarkdownProtectedParser()


@pytest.fixture
def rebuilder() -> DocumentRebuilder:
    return DocumentRebuilder()
