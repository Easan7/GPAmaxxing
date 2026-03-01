"""Run state storage abstraction.

TODO: Replace InMemoryRunStore with a Supabase-backed table implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import lru_cache


class RunStore(ABC):
    """Interface for persisting coach run state across requests."""

    @abstractmethod
    def save_run(self, run_id: str, state: dict) -> None:
        """Persist run state."""

    @abstractmethod
    def load_run(self, run_id: str) -> dict | None:
        """Load run state if present."""

    @abstractmethod
    def delete_run(self, run_id: str) -> None:
        """Delete persisted run state."""


_RUN_STATE: dict[str, dict] = {}


class InMemoryRunStore(RunStore):
    """Minimal in-process run store for development."""

    def save_run(self, run_id: str, state: dict) -> None:
        _RUN_STATE[run_id] = state

    def load_run(self, run_id: str) -> dict | None:
        return _RUN_STATE.get(run_id)

    def delete_run(self, run_id: str) -> None:
        _RUN_STATE.pop(run_id, None)


@lru_cache(maxsize=1)
def get_run_store() -> RunStore:
    """Return singleton run store instance."""
    return InMemoryRunStore()
