"""Loader for the frozen v3 Phase A confirmatory pilot."""

from __future__ import annotations

from pathlib import Path

from benchmarks.knowledge_state_search.confirmatory_schema import ConfirmatorySchema

DEFAULT_PILOT_DATASET = Path("benchmarks/data/knowledge_state_search_confirmatory_v3_pilot")


def load_confirmatory_pilot(
    directory: str | Path = DEFAULT_PILOT_DATASET,
) -> ConfirmatorySchema:
    """Load and validate the frozen Phase A pilot dataset."""

    schema = ConfirmatorySchema.load(directory)
    schema.validate_pilot_contract()
    return schema
