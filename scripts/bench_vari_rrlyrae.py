"""Ad-hoc benchmark reproducing the vari_rrlyrae (270k rows) processing cost.

The real Gaia ``vari_rrlyrae`` catalog is not part of the repository, so this
script synthesizes a representative 270k-row table with the same shape that
stresses the two hot spots fixed in this change:

* a unique ``source_id`` column (270k distinct values) that previously made
  ``_extract_top_values_from_frequency_metric`` build a ~270k entry list, and
* several float photometry columns (some strongly correlated) that previously
  caused pairwise correlations to be computed twice over the whole dataset.

It measures the end-to-end ``analyze_unit`` action time for the BEFORE (old
behaviour, faithfully reconstructed by toggling off the two fixes) and AFTER
(current code) variants on the same dataset and machine.
"""

from __future__ import annotations

import importlib.util
import math
import statistics
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (str(SRC), str(ROOT / "legacy"), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

SPEC = importlib.util.spec_from_file_location("orchestrator_module", ROOT / "legacy" / "orchestrator.py")
orchestrator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = orchestrator
sys.modules["orchestrator"] = orchestrator
SPEC.loader.exec_module(orchestrator)

ROW_COUNT = 270_000


def build_dataset(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE vari_rrlyrae (
            source_id INTEGER,
            pf REAL,
            p1_o REAL,
            epoch_g REAL,
            int_average_g REAL,
            int_average_bp REAL,
            int_average_rp REAL,
            peak_to_peak_g REAL,
            num_clean_epochs_g INTEGER
        )
        """
    )
    rows = []
    for i in range(ROW_COUNT):
        pf = 0.3 + (i % 9000) * 0.00007
        g = 14.0 + (i % 5000) * 0.0008
        rows.append(
            (
                1_000_000_000 + i,             # source_id: unique
                pf,                            # period
                pf * 0.74 + 0.01,              # p1_o: strongly correlated with pf
                55000.0 + (i % 4000) * 0.5,    # epoch_g
                g,                             # int_average_g
                g + 0.6 + (i % 311) * 0.0001,  # int_average_bp: correlated with g
                g - 0.5 - (i % 271) * 0.0001,  # int_average_rp: correlated with g
                0.2 + (i % 700) * 0.001,       # peak_to_peak_g
                int(20 + (i % 80)),            # num_clean_epochs_g
            )
        )
        if len(rows) >= 20_000:
            connection.executemany(
                "INSERT INTO vari_rrlyrae VALUES (?,?,?,?,?,?,?,?,?)", rows
            )
            rows.clear()
    if rows:
        connection.executemany("INSERT INTO vari_rrlyrae VALUES (?,?,?,?,?,?,?,?,?)", rows)
    connection.commit()
    connection.close()


# ---- Faithful reconstruction of the OLD (pre-fix) behaviour -----------------

def _old_extract_top_values_from_frequency_metric(self, frequency_metric):
    counts = None
    if isinstance(frequency_metric, dict):
        counts = frequency_metric.get("counts")
        if counts is None and isinstance(frequency_metric.get("top_values"), list):
            return [
                {"value": item.get("value"), "count": item.get("count")}
                for item in frequency_metric.get("top_values", [])
                if isinstance(item, dict) and "value" in item and "count" in item
            ]
    elif hasattr(frequency_metric, "counts"):
        counts = getattr(frequency_metric, "counts")
    if not isinstance(counts, dict) or not counts:
        return []
    ordered = sorted(counts.items(), key=lambda item: (-int(item[1]), str(item[0])))
    top_values = []
    for value, count in ordered:
        top_values.append({"value": value, "count": count})
    return top_values


def time_analyze(db_path: Path, *, old: bool) -> float:
    session = orchestrator.OrchestratorSession(str(db_path))
    if old:
        # Restore the uncapped top_values extractor (item 1 before fix).
        session._extract_top_values_from_frequency_metric = (
            lambda fm: _old_extract_top_values_from_frequency_metric(session, fm)
        )
        # Force the double full-dataset correlation pass (item 2 before fix):
        # returning None makes _build_operational_payload_for_unit compute its
        # own correlations AND summarize_unit_metrics recompute them.
        session._pairwise_correlations_for_analysis = lambda analysis: None
    start = time.perf_counter()
    session.execute_action({"action": "analyze_unit", "unit_name": "vari_rrlyrae"})
    return time.perf_counter() - start


def main() -> None:
    db_path = ROOT / "scripts" / "_bench_vari_rrlyrae.db"
    print(f"Building synthetic dataset ({ROW_COUNT} rows)...", flush=True)
    build_dataset(db_path)

    print("Timing BEFORE (old behaviour)...", flush=True)
    before = time_analyze(db_path, old=True)
    print("Timing AFTER (current code)...", flush=True)
    after = time_analyze(db_path, old=False)

    print("\n=== Results (analyze_unit on 270k-row vari_rrlyrae analogue) ===")
    print(f"BEFORE (old): {before:8.3f} s")
    print(f"AFTER  (new): {after:8.3f} s")
    if after > 0:
        print(f"Speedup     : {before / after:6.2f}x  ({before - after:.3f} s saved)")

    db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
