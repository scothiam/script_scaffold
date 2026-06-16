"""Generic entity lookup and validation interface.

Provides a common contract for validating and enriching named entities
(GPU models, stock tickers, etc.) before they are persisted.

Apps subclass EntityLookup and implement lookup(). The base class supplies
the normalization and scoring utilities needed to build local-database or
API-backed implementations.
"""

import re
from dataclasses import dataclass, field


@dataclass
class LookupResult:
    """Result of a single entity lookup.

    found=True  — canonical_name and data are populated; may include suggestions
                  for close-but-not-exact inputs (e.g. name casing was corrected).
    found=False — entity not recognized; suggestions contains close matches.
    """

    found: bool
    canonical_name: str | None = None
    data: dict = field(default_factory=dict)
    suggestions: list["LookupResult"] = field(default_factory=list)


class EntityLookup:
    """Base class for entity validation and spec enrichment.

    Subclass and implement lookup(). The static helpers here are shared
    utilities for building normalization-based matching logic.
    """

    def lookup(self, query: str) -> LookupResult:
        """Validate query and return a LookupResult.

        Implementations should:
          - Return found=True with canonical_name and data when the entity
            is unambiguously identified.
          - Return found=False with a populated suggestions list when the
            query is close but not exact.
          - Return found=False with an empty suggestions list when the
            query is completely unknown.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Shared normalization utilities
    # ------------------------------------------------------------------

    @staticmethod
    def normalize(text: str) -> str:
        """Lowercase and collapse whitespace. Preserves word boundaries."""
        return re.sub(r"\s+", " ", text.lower().strip())

    @staticmethod
    def fingerprint(text: str) -> str:
        """Remove all non-alphanumeric characters and lowercase.

        Lets "RTX3060Ti", "RTX 3060 Ti", and "rtx-3060-ti" all map to
        the same string ("rtx3060ti") for robust matching.
        """
        return re.sub(r"[^a-z0-9]", "", text.lower())

    @staticmethod
    def token_similarity(text_a: str, text_b: str) -> float:
        """Jaccard similarity of whitespace-delimited tokens (0.0 – 1.0)."""
        tokens_a = set(EntityLookup.normalize(text_a).split())
        tokens_b = set(EntityLookup.normalize(text_b).split())
        if not tokens_a or not tokens_b:
            return 0.0
        return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
