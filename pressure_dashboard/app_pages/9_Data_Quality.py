from __future__ import annotations

import streamlit as st

from lib.db import quality_report
from lib.ui import fmt_or_na, json_block, markdown_table, page_header

page_header(
    "Data quality",
    "Source coverage, reconstruction limits, and reproducibility details for the current local build.",
    ":material/fact_check:",
)

report = quality_report()
if not report:
    st.error("Validation report is missing. Rebuild the processed data.")
    st.stop()

scope = report.get("scope", {})
quality = report.get("quality", {})
processing = report.get("processing", {})
files = report.get("source_files", {})
definitions = report.get("definitions", {})

run_total = int(quality.get("source_run_margin_comparisons") or 0)
run_matches = int(quality.get("source_run_margin_matches") or 0)
run_mismatches = int(quality.get("source_run_margin_mismatches") or 0)
match_rate = (100 * run_matches / run_total) if run_total else None
unknown_events = int(quality.get("unknown_legality_events") or 0)
workbook_rows = int(quality.get("workbook_pressure_rows") or 0)
workbook_numeric = int(quality.get("workbook_pressure_count_comparisons") or 0)
workbook_matches = int(quality.get("workbook_pressure_count_matches") or 0)

cards = st.columns(5, border=True)
cards[0].metric("Raw delivery rows", f"{int(scope.get('delivery_rows') or 0):,}")
cards[1].metric("Processed delivery rows", f"{int(scope.get('processed_delivery_rows') or 0):,}")
cards[2].metric("Matches", f"{int(scope.get('matches') or 0):,}")
cards[3].metric("Unknown-legality events", f"{unknown_events:,}")
cards[4].metric(
    "Raw run-margin match rate",
    fmt_or_na(match_rate) + ("%" if match_rate is not None else ""),
    help=f"{run_matches:,} source-field run margins matched out of {run_total:,}.",
)

st.error(
    f"Raw source run fields matched only {run_matches:,} of {run_total:,} match-result run margins. "
    f"Only {int(quality.get('revised_target_matches') or 0):,} matches provide revised targets; "
    f"{int(quality.get('proxy_target_chases') or 0):,} chases use a first-innings score proxy. "
    "The raw extras fields do not contain enough information to recover every official total, so RRR and pressure "
    "states based on proxy targets must be read as estimates.",
    title="Score totals are not official-score reconciliations",
    icon=":material/report:",
)

left, right = st.columns(2)
with left:
    with st.container(border=True):
        st.markdown("**Delivery legality map**")
        extras = quality.get("extras_type_counts", {})
        extra_rows = [
            {
                "extras_type": kind,
                "events": count,
                "classification": (
                    "Known legal"
                    if kind.casefold() in {"none", "byes", "legbyes"}
                    else "Known illegal"
                    if kind.casefold() in {"wide", "overstep"}
                    else "Unknown legality"
                ),
            }
            for kind, count in sorted(extras.items(), key=lambda item: -item[1])
        ]
        markdown_table(
            extra_rows,
            [
                ("extras_type", "Source extras_type"),
                ("events", "Rows"),
                ("classification", "Dashboard classification"),
            ],
        )
        st.caption(
            "Unknown-legality rows are excluded from legal-ball denominators. "
            "They do not advance reconstructed legal balls, and later chase states are marked unknown."
        )
with right:
    with st.container(border=True):
        st.markdown("**Coverage and row checks**")
        format_rows = scope.get("formats", [])
        markdown_table(
            format_rows,
            [
                ("format", "Format"),
                ("matches", "Matches"),
                ("seasons", "Seasons"),
            ],
        )
        checks = [
            {"check": "Raw delivery rows preserved", "value": f"{scope.get('processed_delivery_rows', 0):,} / {scope.get('delivery_rows', 0):,}", "status": "Match" if scope.get("processed_delivery_rows") == scope.get("delivery_rows") else "Different"},
            {"check": "Workbook Match Pressure rows", "value": f"{workbook_rows:,}", "status": "Loaded" if workbook_rows else "Missing"},
            {"check": "Numeric workbook pressure counts", "value": f"{workbook_numeric:,}", "status": f"{workbook_matches:,} exact count matches"},
            {"check": "Revised target fields", "value": f"{quality.get('revised_target_matches', 0):,}", "status": "Available"},
            {"check": "Revised schedule fields", "value": f"{quality.get('revised_schedule_matches', 0):,}", "status": "Available"},
            {"check": "Extra innings excluded from standard views", "value": f"{scope.get('extra_innings_delivery_rows_excluded_from_standard_views', 0):,} rows", "status": "Documented"},
            {"check": "Ambiguous striker IDs with multiple names", "value": f"{quality.get('ambiguous_striker_ids_with_multiple_names', 0):,}", "status": "Reviewed"},
        ]
        markdown_table(checks, [("check", "Check"), ("value", "Value"), ("status", "Status")])

st.subheader("Definitions used in this build")
definition_rows = [{"definition": key.replace("_", " ").capitalize(), "value": value} for key, value in definitions.items()]
with st.expander("Open methodology and source conventions"):
    markdown_table(definition_rows, [("definition", "Item"), ("value", "Definition")])
    st.caption(
        "The dashboard does not calculate win probability, WPA, leverage, pitch/weather effects, or custom clutch scores."
    )

st.subheader("Source hashes")
st.caption(f"Last build: {report.get('built_at_utc', 'Unknown')} · SHA-256 values identify the exact inputs used.")
hash_rows = [
    {
        "file": name,
        "rows": info.get("row_count"),
        "bytes": info.get("byte_size"),
        "sha256": info.get("sha256"),
    }
    for name, info in files.items()
]
markdown_table(
    hash_rows,
    [
        ("file", "Source file"),
        ("rows", "Rows"),
        ("bytes", "Bytes"),
        ("sha256", "SHA-256"),
    ],
)

with st.expander("Full validation report"):
    json_block(report)
