"""Trilingual technical documentation localization and auditing pipeline."""

from src.parser import MarkdownProtectedParser
from src.rebuilder import DocumentRebuilder, TokenIntegrityError
from src.swarm_translator import (
    DomainTranslatorAgent,
    LocalizationSwarm,
    TerminologyCriticAgent,
)

__version__ = "1.0.0"

__all__ = [
    "__version__",
    "MarkdownProtectedParser",
    "DocumentRebuilder",
    "TokenIntegrityError",
    "DomainTranslatorAgent",
    "TerminologyCriticAgent",
    "LocalizationSwarm",
]
