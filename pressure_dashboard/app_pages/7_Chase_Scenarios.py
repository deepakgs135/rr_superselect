from __future__ import annotations

from collections import defaultdict

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from lib.queries import scenario_cells
from lib.ui import chart, markdown_table, page_header

filters = st.session_state.get("dashboard_filters", {})
page_header(
    "Chase scenarios",
    "Compare historical chase outcomes across balls remaining, wickets lost, and required-rate bands.",
    ":material/grid_view:",
)
st.caption(
    "Each match is counted once per state cell. Cells with fewer than 20 decided chases are grey and show only their sample count. "
    "This view always uses all eligible chase states, regardless of the pressure-only delivery toggle."
)

cells = scenario_cells(filters)
rrr_bands = ["Low", "Medium", "High", "Extreme"]
balls_bands = ["61+", "31–60", "19–30", "13–18", "7–12", "1–6"]
wicket_counts = list(range(11))
lookup = {
    (row["rrr_band"], row["balls_band"], int(row["wickets_lost"])): row
    for row in cells
}

selected_rows = [row for row in cells if int(row.get("chase_matches") or 0) >= 20]
metric_cols = st.columns(3, border=True)
metric_cols[0].metric("Eligible state cells", f"{len(selected_rows):,}")
metric_cols[1].metric("Minimum sample", "20 chases")
metric_cols[2].metric(
    "Largest cell",
    f"{max((int(row.get('chase_matches') or 0) for row in cells), default=0):,} chases",
)

fig = make_subplots(
    rows=2,
    cols=2,
    subplot_titles=["RRR below 8", "RRR 8–12", "RRR above 12 to 15", "RRR above 15"],
    horizontal_spacing=0.10,
    vertical_spacing=0.18,
)
colorscale = [
    [0.0, "#CBD5E1"],
    [0.30, "#CBD5E1"],
    [0.3001, "#F0FDFA"],
    [0.55, "#99F6E4"],
    [0.78, "#2DD4BF"],
    [1.0, "#0F766E"],
]
for index, band in enumerate(rrr_bands):
    row_num = index // 2 + 1
    col_num = index % 2 + 1
    z = []
    text = []
    custom = []
    for wickets in wicket_counts:
        z_row = []
        text_row = []
        custom_row = []
        for balls in balls_bands:
            value = lookup.get((band, balls, wickets), {})
            n = int(value.get("chase_matches") or 0)
            wins = int(value.get("chase_wins") or 0)
            rate = value.get("win_rate")
            z_row.append(float(rate) if n >= 20 and rate is not None else -100.0)
            text_row.append(f"{rate:.0f}% · {n}" if n >= 20 and rate is not None else (f"n={n}" if n else ""))
            custom_row.append([n, wins, rate])
        z.append(z_row)
        text.append(text_row)
        custom.append(custom_row)
    fig.add_trace(
        go.Heatmap(
            z=z,
            x=balls_bands,
            y=[str(value) for value in wicket_counts],
            text=text,
            texttemplate="%{text}",
            customdata=custom,
            colorscale=colorscale,
            zmin=-100,
            zmax=100,
            showscale=index == 3,
            colorbar=dict(title="Win rate", ticksuffix="%") if index == 3 else None,
            hovertemplate=(
                "RRR band "
                + band
                + "<br>Wickets down %{y}<br>Balls remaining %{x}<br>Win rate %{customdata[2]:.1f}%"
                + "<br>Chase matches %{customdata[0]}<br>Wins %{customdata[1]}<extra></extra>"
            ),
            xgap=2,
            ygap=2,
        ),
        row=row_num,
        col=col_num,
    )

fig.update_xaxes(title_text="Legal balls remaining", side="bottom")
fig.update_yaxes(title_text="Wickets lost", autorange="reversed")
chart(fig, "Chasing win rate by wickets lost, balls remaining, and required-rate band", height=780)

with st.expander("State cell details"):
    display_rows = sorted(
        cells,
        key=lambda row: (
            rrr_bands.index(row["rrr_band"]),
            balls_bands.index(row["balls_band"]),
            int(row["wickets_lost"]),
        ),
    )
    markdown_table(
        display_rows[:100],
        [
            ("rrr_band", "Required-rate band"),
            ("balls_band", "Balls left"),
            ("wickets_lost", "Wickets lost"),
            ("chase_matches", "Decided chases"),
            ("chase_wins", "Chasing wins"),
            ("win_rate", "Win rate"),
        ],
    )
    if len(display_rows) > 100:
        st.caption(f"Showing 100 of {len(display_rows):,} state cells.")
