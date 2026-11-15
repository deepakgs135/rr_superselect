from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from lib.metrics import economy_rate, share, strike_rate
from lib.queries import overview, overview_by_year, state_comparison
from lib.ui import ORDINARY, PRESSURE, chart, fmt_or_na, metric_row, page_header, pct, year_axis

filters = st.session_state.get("dashboard_filters", {})
page_header(
    "Pressure overview",
    "A filtered view of second-innings states, player output, and chase outcomes.",
    ":material/space_dashboard:",
)

summary = overview(filters)
year_rows = overview_by_year(filters)
year_labels = [str(row["year"]) for row in year_rows]
chase_balls = int(summary.get("chase_legal_balls") or 0)
pressure_balls = int(summary.get("pressure_legal_balls") or 0)
pressure_chases = int(summary.get("pressure_chases") or 0)
decided_pressure_chases = int(summary.get("decided_pressure_chases") or 0)
pressure_wins = int(summary.get("pressure_chase_wins") or 0)
pressure_win_rate = share(pressure_wins, decided_pressure_chases)

metric_row(
    [
        ("Chase innings", fmt_or_na(summary.get("chase_innings"), 0), "Second innings in the selected cohort."),
        ("Batting-pressure legal balls", fmt_or_na(pressure_balls, 0), "Known-legal events meeting the batting-pressure rule."),
        ("Batting-pressure chases", fmt_or_na(pressure_chases, 0), "Chases with at least one batting-pressure legal ball."),
        ("Batting-pressure share", pct(share(pressure_balls, chase_balls)), "Uses known-legal second-innings balls."),
        ("Batting-pressure chase win rate", pct(pressure_win_rate), "Among decided chases with a batting-pressure phase."),
    ]
)

st.space("small")
left, right = st.columns(2)
with left:
    with st.container(border=True):
        st.subheader("Batting-pressure chases by year")
        fig = go.Figure(
            go.Bar(
                x=year_labels,
                y=[row.get("pressure_chases") or 0 for row in year_rows],
                marker_color=PRESSURE,
                hovertemplate="Year %{x}<br>Pressure chases %{y}<extra></extra>",
            )
        )
        fig.update_layout(xaxis_title="Year", yaxis_title="Chases")
        year_axis(fig, year_labels)
        chart(fig, "Batting-pressure chases by calendar year", height=330)

with right:
    with st.container(border=True):
        st.subheader("Batting-pressure share and chase success")
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=year_labels,
                y=[
                    share(row.get("pressure_legal_balls") or 0, row.get("chase_legal_balls") or 0)
                    for row in year_rows
                ],
                name="Pressure share of legal balls",
                mode="lines+markers",
                line=dict(color=PRESSURE, width=3),
                hovertemplate="Year %{x}<br>Pressure ball share %{y:.1f}%<extra></extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=year_labels,
                y=[share(row.get("pressure_wins") or 0, row.get("decided_pressure_chases") or 0) for row in year_rows],
                name="Pressure chase win rate",
                mode="lines+markers",
                line=dict(color=ORDINARY, width=3),
                hovertemplate="Year %{x}<br>Win rate %{y:.1f}%<extra></extra>",
            )
        )
        fig.update_layout(xaxis_title="Year", yaxis_title="Percent", yaxis_range=[0, 100])
        year_axis(fig, year_labels)
        chart(fig, "Batting-pressure share of chase balls and chase win rate by calendar year", height=330)

st.subheader("Batting and bowling output by pressure state")
st.caption(
    "Batting pressure uses RRR ≥15, the final 30 balls, and at least 3 wickets lost. "
    "Bowling pressure uses exactly 2 wickets down, the final 30 balls, current rate ≥11 RPO, and required rate ≥9 RPO."
)
batter_rows = state_comparison(filters, "batter")
bowler_rows = state_comparison(filters, "bowler")

def combined(rows, pressure_value: int, role: str) -> dict[str, int]:
    chosen = [row for row in rows if int(row.get("pressure") or 0) == pressure_value]
    keys = (
        ("runs", "balls", "dots", "fours", "sixes", "dismissals")
        if role == "batter"
        else ("runs_proxy", "legal_balls", "credited_wickets", "dots")
    )
    return {key: sum(int(row.get(key) or 0) for row in chosen) for key in keys}

overview_batter = []
overview_bowler = []
for pressure_value, label in ((1, "Pressure"), (0, "Other known chase states")):
    b = combined(batter_rows, pressure_value, "batter")
    w = combined(bowler_rows, pressure_value, "bowler")
    overview_batter.append(
        {
            "state": "Batting pressure" if pressure_value else label,
            "balls": b.get("balls", 0),
            "strike_rate": strike_rate(b.get("runs", 0), b.get("balls", 0)),
            "dot_share": share(b.get("dots", 0), b.get("balls", 0)),
            "boundary_share": share(b.get("fours", 0) + b.get("sixes", 0), b.get("balls", 0)),
        }
    )
    overview_bowler.append(
        {
            "state": "Bowling pressure" if pressure_value else label,
            "legal_balls": w.get("legal_balls", 0),
            "economy": economy_rate(w.get("runs_proxy", 0), w.get("legal_balls", 0)),
            "wickets_per_100": (
                round(100 * w.get("credited_wickets", 0) / w.get("legal_balls", 0), 2)
                if w.get("legal_balls", 0)
                else None
            ),
            "dot_share": share(w.get("dots", 0), w.get("legal_balls", 0)),
        }
    )

left, right = st.columns(2)
with left:
    with st.container(border=True):
        st.markdown("**Batting**")
        st.caption("Batter-attributed runs; balls exclude wides and unknown-legality rows.")
        from lib.ui import markdown_table
        markdown_table(
            overview_batter,
            [
                ("state", "State"),
                ("balls", "Balls"),
                ("strike_rate", "Strike rate"),
                ("boundary_share", "Boundary events / 100 balls"),
                ("dot_share", "Dot share", pct),
            ],
        )
with right:
    with st.container(border=True):
        st.markdown("**Bowling**")
        st.caption("Runs are a raw-field proxy; legal balls use the documented legality map.")
        from lib.ui import markdown_table
        markdown_table(
            overview_bowler,
            [
                ("state", "State"),
                ("legal_balls", "Legal balls"),
                ("economy", "Raw economy proxy"),
                ("wickets_per_100", "Credited wickets / 100 balls"),
                ("dot_share", "Team zero-run share", pct),
            ],
        )

st.info(
        "Pressure is classified from the pre-ball chase state using separate batting and bowling rules. The dashboard uses the raw "
    "runs + extras_2_runs fields for target reconstruction and labels resulting team "
    "run rates as proxies because the source fields do not consistently reconcile to match results.",
    title="How to read these numbers",
    icon=":material/info:",
)
