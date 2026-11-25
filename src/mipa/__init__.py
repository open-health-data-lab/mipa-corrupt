"""Downstream evaluation of corrupted corpora.

The corruption engine says what changed and by how much. This package says what
it *cost* — running a real phenotyping protocol over the corrupted notes and
reporting the F1 degradation against the clean baseline.

Nothing here is imported by the core package. A robustness result depends on a
model, an API and a prompt; the operator suite depends on none of those and must
stay runnable without them.
"""

from __future__ import annotations

__all__: list[str] = []
