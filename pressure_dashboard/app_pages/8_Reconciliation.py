from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from lib.db import quality_report
from lib.queries import reconciliation
from lib.ui import ORDINARY, PRESSURE, chart, csv_download, markdown_table, page_header

filters = st.session_state.get("dashboard_filters", {})
page_header(
    "Reconciliation",
    "Compare the batting-pressure recount with the workbook’s Match Pressure sheet.",
    ":material/difference:",
)

rows = reconciliation(filters)
numeric_rows = [row for row in rows if row.get("workbook_pressure_count") is not None]
matches = [row for row in numeric_rows if row.get("pressure_count_status") == "Match"]
different = [row for row in numeric_rows if row.get("pressure_count_status") == "Different"]
no_count = [row for row in rows if row.get("workbook_pressure_count") is None]
target_comparable = [
    row
    for row in rows
    if row.get("workbook_target") is not None and row.get("app_target") is not None
]
target_matches = [
    row
    for row in target_comparable
    if int(row["workbook_target"]) == int(row["app_target"])
]

cards = st.columns(4, border=True)
cards[0].metric("Workbook rows in filter", f"{len(rows):,}")
cards[1].metric("Numeric pressure counts", f"{len(numeric_rows):,}")
cards[2].metric("Exact pressure-count matches", f"{len(matches):,}")
cards[3].metric("Different pressure counts", f"{len(different):,}")

if numeric_rows:
    with st.container(border=True):
        st.markdown("**Workbook pressure count versus current recount**")
        fig = go.Figure(
            go.Scatter(
                x=[row["workbook_pressure_count"] for row in numeric_rows],
                y=[row["app_pressure_legal_balls"] or 0 for row in numeric_rows],
                mode="markers",
                marker=dict(
                    color=[ORDINARY if row["pressure_count_status"] == "Match" else PRESSURE for row in numeric_rows],
                    size=8,
                    opacity=0.72,
                ),
                text=[f"Match {row['match_id']} · {row.get('match_date')}" for row in numeric_rows],
                customdata=[[row.get("app_pressure_event_rows"), row.get("unknown_legality_events")] for row in numeric_rows],
                hovertemplate="%{text}<br>Workbook count %{x}<br>App known-legal balls %{y}<br>App pressure event rows %{customdata[0]}<br>Unknown legality events %{customdata[1]}<extra></extra>",
            )
        )
        maximum = max(
            [int(row.get("workbook_pressure_count") or 0) for row in numeric_rows]
            + [int(row.get("app_pressure_legal_balls") or 0) for row in numeric_rows]
            + [1]
        )
        fig.add_trace(
            go.Scatter(
                x=[0, maximum],
                y=[0, maximum],
                mode="lines",
                line=dict(color="#94A3B8", dash="dash"),
                name="Equal count",
                hoverinfo="skip",
            )
        )
        fig.update_layout(xaxis_title="Workbook severe-pressure delivery count", yaxis_title="App severe-pressure known-legal balls")
        chart(fig, "Workbook versus app severe-pressure counts, with an equal-count reference line", height=380)

summary = quality_report()
definition = summary.get("definitions", {})
st.warning(
    "The app counts known-legal batting-pressure balls and stops reconstructing later RRR states after an "
    "unknown-legality event. The workbook stores a delivery-count value without carrying the same state-confidence "
    "flags, so equal numbers are useful checks while differences should be reviewed as a definition/reconstruction "
    "difference rather than a source-file corruption signal.",
    title="Read the comparison with the metric definitions",
    icon=":material/info:",
)

left, right = st.columns(2)
with left:
    with st.container(border=True):
        st.markdown("**Target convention**")
        st.markdown(
            f"Workbook and app targets both matched in **{len(target_matches):,} of {len(target_comparable):,}** "
            "rows where both values were numeric."
        )
        target_diffs = [
            {
                "match_id": row.get("match_id"),
                "date": row.get("match_date"),
                "workbook_target": row.get("workbook_target"),
                "app_target": row.get("app_target"),
                "app_target_source": row.get("target_source"),
                "result": row.get("result"),
            }
            for row in target_comparable
            if int(row["workbook_target"]) != int(row["app_target"])
        ]
        markdown_table(
            target_diffs[:15],
            [
                ("match_id", "Match"),
                ("date", "Date"),
                ("workbook_target", "Workbook target"),
                ("app_target", "App target"),
                ("app_target_source", "App source"),
                ("result", "Result"),
            ],
            empty_message="No numeric target differences in the selected cohort.",
        )
with right:
    with st.container(border=True):
        st.markdown("**Current state rules**")
        st.markdown(
            "- Pre-ball RRR uses remaining runs × 6 ÷ known legal balls remaining.\n"
            "- Pressure requires RRR ≥ 15, ≤ 30 legal balls remaining, and ≥ 3 wickets lost.\n"
            "- Targets use revised_target when supplied; otherwise first-innings raw fields + 1.\n"
            "- After an unknown-legality event, later legal-ball states are marked unknown."
        )
        st.caption(
            "RRR bands: Low < 8 · Medium 8–12 · High > 12–15 · Extreme > 15. "
            "No win probability or leverage model is fitted."
        )

st.subheader("Match-level count differences")
display = [
    row
    for row in rows
    if row.get("pressure_count_status") == "Different"
]
markdown_table(
    display[:50],
    [
        ("match_date", "Date"),
        ("match_id", "Match"),
        ("match_format", "Format"),
        ("venue_id", "Venue ID"),
        ("home_team", "Home"),
        ("away_team", "Away"),
        ("workbook_pressure_count", "Workbook count"),
        ("app_pressure_legal_balls", "App known-legal"),
        ("app_pressure_event_rows", "App event rows"),
        ("unknown_legality_events", "Unknown legality"),
        ("unknown_rrr_states", "Unknown RRR states"),
        ("pressure_count_status", "Status"),
    ],
    empty_message="No pressure-count differences in the selected cohort.",
)
if len(display) > 50:
    st.caption(f"Showing the 50 largest recent rows of {len(display):,} differences.")
csv_download(rows, "Download reconciliation rows", "pressure_reconciliation.csv", "reconciliation_csv")
