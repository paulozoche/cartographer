from __future__ import annotations

from dataclasses import asdict

from agnostic.application.ports.canonical_result_store import CanonicalResultStore
from agnostic.application.use_cases.analyze_tabular_unit import TabularUnitAnalysis


def persist_canonical_result(
    kind: str,
    analysis: TabularUnitAnalysis,
    store: CanonicalResultStore,
    summary: str,
) -> str:
    payload = asdict(analysis)
    payload["summary"] = summary
    persisted_path = store.save(kind, analysis.unit_name, payload)
    return str(persisted_path)
