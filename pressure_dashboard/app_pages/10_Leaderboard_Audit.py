from __future__ import annotations

import streamlit as st

from lib.pressure_reports import pressure_report
from lib.ui import csv_download, metric_row, page_header

report = pressure_report()
page_header(
    "Pressure data audit",
    "Independent raw-file recounts, sample-row checks, and source-data exceptions.",
    ":material/fact_check:",
)

if not report:
    st.error("No pressure report is available. Build the processed data and pressure report first.")
    st.code("python build/build_data.py", language="powershell")
    st.stop()

validation = report.get("validation", {})
raw = validation.get("raw_totals", report.get("raw_totals", {}))
processed = validation.get("database_totals", {})
metric_row(
    [
        ("Independent validation", validation.get("overall_status", "Not run"), f"Core raw-data checks plus {int(validation.get('source_run_margin_reconciliation', {}).get('mismatched_rows') or 0):,} unreproduced source run margins."),
        ("Raw delivery rows", f"{int(raw.get('delivery_rows') or 0):,}", f"Database: {int(processed.get('delivery_rows') or 0):,}."),
        ("Raw runs column sum", f"{int(raw.get('runs') or 0):,}", f"Database: {int(processed.get('runs') or 0):,}."),
        ("Known legal balls", f"{int(raw.get('legal_balls') or 0):,}", f"Database: {int(processed.get('known_legal_balls') or 0):,}."),
        ("Pressure flag mismatches", f"{int(validation.get('pressure_flag_mismatches') or 0):,}", f"Checked {int(validation.get('pressure_flag_rows_checked') or 0):,} chase deliveries."),
    ]
)

st.subheader("Validation log")
log_rows = validation.get("validation_log", [])
st.dataframe(log_rows, hide_index=True, width="stretch")
csv_download(log_rows, "Download validation log", "pressure_validation_log.csv", "pressure_audit_log_download")

st.subheader("Random player-row recomputation")
st.caption(
    f"The separate raw-CSV script used seed {validation.get('random_seed')} and checked "
    f"{int(validation.get('random_player_rows_checked') or 0)} player-state rows. It recalculates totals and counts without importing the dashboard state functions."
)
sample_rows = [
    {"player_id": row.get("player_id"), "role": row.get("role"), "state": row.get("state"), "status": row.get("status"), "mismatches": row.get("mismatches") or "None"}
    for row in validation.get("random_player_row_checks", [])
]
st.dataframe(sample_rows, hide_index=True, width="stretch")

st.subheader("Unreconciled source values")
margin = validation.get("source_run_margin_reconciliation", {})
unreproducible = margin.get("unreproducible_rows", [])
if unreproducible:
    st.warning(
        f"The count-based score formula does not reproduce {len(unreproducible):,} run-margin results recorded in matches.csv. "
        "No figures were adjusted to force agreement. These rows are listed below."
    )
    st.dataframe(unreproducible[:100], hide_index=True, width="stretch")
    csv_download(unreproducible, "Download run-margin exceptions", "pressure_reproduction_exceptions.csv", "pressure_margin_exception_download")
else:
    st.success("The count-based score formula reproduced every supplied run-margin result in this check.")

flag_examples = validation.get("flag_mismatch_examples", [])
if flag_examples:
    st.error("Independent pressure flags differ from the processed database. Inspect these delivery rows before relying on player rankings.")
    st.dataframe(flag_examples, hide_index=True, width="stretch")

st.subheader("Excluded player mappings")
excluded = report.get("excluded_player_ids", {})
st.write(
    f"Excluded {len(excluded.get('multiple_source_names', [])):,} IDs with multiple source names and "
    f"{len(excluded.get('unknown_or_blank_name', [])):,} IDs with unknown/blank names."
)
if excluded.get("multiple_source_names") or excluded.get("unknown_or_blank_name"):
    st.json(excluded)

with st.expander("Validation method"):
    st.markdown(
        "The raw recount joins match rows to competitions through `comp_id`, then orders each innings by "
        "over, innings-ball number, delivery-ball number, and source row. It reconstructs the first-innings "
        "count-based total, target, pre-ball legal-ball count, wicket count, required rate, and current rate. "
        "The database pressure flags and a deterministic sample of player-state aggregates are compared with that independent result."
    )
    st.json(validation, expanded=False)
