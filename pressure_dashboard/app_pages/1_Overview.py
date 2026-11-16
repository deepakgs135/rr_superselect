from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from lib.metrics import economy_rate, share, strike_rate
from lib.queries import overview, overview_by_year, state_comparison, venue_state_aggregates
from lib.ui import ORDINARY, PRESSURE, chart, fmt_or_na, metric_row, page_header, pct, year_axis

filters = st.session_state.get("dashboard_filters", {})
pressure_filters = {**filters, "formats": ["T20"]}
page_header(
    "Pressure overview",
    "A filtered view of second-innings states, player output, and chase outcomes.",
    ":material/space_dashboard:",
)

summary = overview(pressure_filters)
year_rows = overview_by_year(pressure_filters)
year_labels = [str(row["year"]) for row in year_rows]
pressure_cohort_balls = int(summary.get("pressure_cohort_chase_legal_balls") or 0)
pressure_balls = int(summary.get("pressure_legal_balls") or 0)
pressure_chases = int(summary.get("pressure_chases") or 0)
decided_pressure_chases = int(summary.get("decided_pressure_chases") or 0)
pressure_wins = int(summary.get("pressure_chase_wins") or 0)
pressure_win_rate = (
    share(pressure_wins, decided_pressure_chases)
    if int(summary.get("t20_matches") or 0) >= 10 and decided_pressure_chases >= 20
    else None
)

metric_row(
    [
        ("Chase innings", fmt_or_na(summary.get("chase_innings"), 0), "Second innings in the selected cohort."),
        ("Batting-pressure legal balls", fmt_or_na(pressure_balls, 0), "Known-legal events meeting the batting-pressure rule."),
        ("Batting-pressure chases", fmt_or_na(pressure_chases, 0), "Chases with at least one batting-pressure legal ball."),
        ("Batting-pressure share", pct(share(pressure_balls, pressure_cohort_balls)), "Known-legal balls in the filtered T20 chase cohort."),
        ("Batting-pressure chase win rate", pct(pressure_win_rate), f"{decided_pressure_chases:,} decided pressure chases across {int(summary.get('t20_matches') or 0):,} T20 matches; 20 chases and 10 matches required."),
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
                    share(row.get("pressure_legal_balls") or 0, row.get("pressure_cohort_chase_legal_balls") or 0)
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
                y=[
                    share(row.get("pressure_wins") or 0, row.get("decided_pressure_chases") or 0)
                    if int(row.get("t20_matches") or 0) >= 10 and int(row.get("decided_pressure_chases") or 0) >= 20
                    else None
                    for row in year_rows
                ],
                customdata=[[int(row.get("t20_matches") or 0), int(row.get("decided_pressure_chases") or 0)] for row in year_rows],
                name="Pressure chase win rate",
                mode="lines+markers",
                line=dict(color=ORDINARY, width=3),
                hovertemplate="Year %{x}<br>Win rate %{y:.1f}%<br>T20 matches %{customdata[0]}<br>Decided pressure chases %{customdata[1]}<extra></extra>",
            )
        )
        fig.update_layout(xaxis_title="Year", yaxis_title="Percent", yaxis_range=[0, 100])
        year_axis(fig, year_labels)
        chart(fig, "Batting-pressure share of chase balls and chase win rate by calendar year", height=330)

st.subheader("Batting and bowling output by pressure state")
st.caption(
    "Pressure comparisons use selected-venue T20 chases only. Batting: the final 30 balls, RRR ≥15, and at least 3 wickets lost. "
    "Bowling: 2 or fewer wickets down in the final 30 balls, current rate ≥11 RPO, and required rate ≥9 RPO. "
    "The observed chase win rate is descriptive only and is not used to score or rank players."
)
batter_rows = state_comparison(pressure_filters, "batter")
bowler_rows = state_comparison(pressure_filters, "bowler")
cohort_counts = venue_state_aggregates(pressure_filters)
state_decided = {
    "batting_pressure": sum(int(row.get("batting_pressure_decided_chases") or 0) for row in cohort_counts),
    "batting_ordinary": sum(int(row.get("batting_ordinary_decided_chases") or 0) for row in cohort_counts),
    "bowling_pressure": sum(int(row.get("bowling_pressure_decided_chases") or 0) for row in cohort_counts),
    "bowling_ordinary": sum(int(row.get("bowling_ordinary_decided_chases") or 0) for row in cohort_counts),
}

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
    batting_sample = state_decided["batting_pressure" if pressure_value else "batting_ordinary"]
    bowling_sample = state_decided["bowling_pressure" if pressure_value else "bowling_ordinary"]
    batting_reportable = batting_sample >= 20
    bowling_reportable = bowling_sample >= 20
    overview_batter.append(
        {
            "state": "Batting pressure" if pressure_value else label,
            "balls": b.get("balls", 0),
            "decided_chases": batting_sample,
            "strike_rate": strike_rate(b.get("runs", 0), b.get("balls", 0)) if batting_reportable else "Count only",
            "dot_share": pct(share(b.get("dots", 0), b.get("balls", 0))) if batting_reportable else "Count only",
            "boundary_share": pct(share(b.get("fours", 0) + b.get("sixes", 0), b.get("balls", 0))) if batting_reportable else "Count only",
        }
    )
    overview_bowler.append(
        {
            "state": "Bowling pressure" if pressure_value else label,
            "legal_balls": w.get("legal_balls", 0),
            "decided_chases": bowling_sample,
            "economy": economy_rate(w.get("runs_proxy", 0), w.get("legal_balls", 0)) if bowling_reportable else "Count only",
            "wickets_per_100": (
                round(100 * w.get("credited_wickets", 0) / w.get("legal_balls", 0), 2)
                if bowling_reportable and w.get("legal_balls", 0) else "Count only" if not bowling_reportable else None
            ),
            "dot_share": pct(share(w.get("dots", 0), w.get("legal_balls", 0))) if bowling_reportable else "Count only",
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
                ("decided_chases", "Decided chases"),
                ("balls", "Balls"),
                ("strike_rate", "Strike rate"),
                ("boundary_share", "Boundary events / 100 balls"),
                ("dot_share", "Dot share"),
            ],
        )
with right:
    with st.container(border=True):
        st.markdown("**Bowling**")
        st.caption("Runs use the bowler-charged proxy, adding one run per wide/no-ball; recorded extra amounts are incomplete.")
        from lib.ui import markdown_table
        markdown_table(
            overview_bowler,
            [
                ("state", "State"),
                ("decided_chases", "Decided chases"),
                ("legal_balls", "Legal balls"),
                ("economy", "Bowler-charged economy proxy"),
                ("wickets_per_100", "Credited wickets / 100 balls"),
                ("dot_share", "Team zero-run share"),
            ],
        )

st.info(
        "Pressure is classified from the pre-ball chase state using separate batting and bowling rules. "
    "Fallback targets use the existing raw-analysis team-score proxy; source run totals do not consistently reconcile "
    "to match results, so required run rates based on fallback targets are estimates.",
    title="How to read these numbers",
    icon=":material/info:",
)
