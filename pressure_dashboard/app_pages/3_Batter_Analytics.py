from __future__ import annotations

from collections import Counter, defaultdict

import plotly.graph_objects as go
import streamlit as st

from lib.metrics import batting_average, share, shrink_to_baseline, strike_rate
from lib.queries import batter_profile, batter_stats
from lib.ui import BLUE, GOLD, ORDINARY, PRESSURE, chart, csv_download, fmt_or_na, markdown_table, page_header, pct, year_axis

filters = st.session_state.get("dashboard_filters", {})
page_header(
    "Batter analytics",
    "Rankings, sample-adjusted rates, and player-level innings profiles.",
    ":material/sports_cricket:",
)

ranking_filters = dict(filters)
ranking_filters["pressure_only"] = False
raw = batter_stats(ranking_filters)
ranking_minimum = max(int(filters.get("min_balls", 30)), 30)
eligible = [row for row in raw if int(row.get("balls") or 0) >= ranking_minimum]
all_runs = sum(int(row.get("runs") or 0) for row in eligible)
all_balls = sum(int(row.get("balls") or 0) for row in eligible)
all_dismissals = sum(int(row.get("dismissals") or 0) for row in eligible)
base_sr = strike_rate(all_runs, all_balls)
base_average = batting_average(all_runs, all_dismissals)

for row in raw:
    runs = int(row.get("runs") or 0)
    balls = int(row.get("balls") or 0)
    dismissals = int(row.get("dismissals") or 0)
    sr = strike_rate(runs, balls)
    average = batting_average(runs, dismissals)
    average_for_adjustment = runs / dismissals if dismissals else None
    row["strike_rate"] = sr
    row["average"] = average
    row["boundary_events_per_100"] = share(
        int(row.get("fours") or 0) + int(row.get("sixes") or 0), balls
    )
    row["dot_share"] = share(int(row.get("dots") or 0), balls)
    row["adjusted_sr"] = shrink_to_baseline(sr, balls, base_sr, 60)
    row["adjusted_average"] = shrink_to_baseline(average_for_adjustment, dismissals, base_average, 3)
    pressure_balls = int(row.get("pressure_balls") or 0)
    row["pressure_sr"] = (
        strike_rate(int(row.get("pressure_runs") or 0), pressure_balls)
        if pressure_balls >= 30
        else None
    )

if st.session_state.get("batter_rank_metric") == "Pressure strike rate":
    st.session_state["batter_rank_metric"] = "Strike rate"

sort_by = st.selectbox(
    "Rank by",
    ["Runs", "Strike rate", "Batting average", "Adjusted strike rate"],
    key="batter_rank_metric",
)
sort_key = {
    "Runs": "runs",
    "Strike rate": "strike_rate",
    "Batting average": "average",
    "Adjusted strike rate": "adjusted_sr",
}[sort_by]
for row in raw:
    row["sample_status"] = "Eligible sample" if int(row.get("balls") or 0) >= ranking_minimum else "Review sample"
    row["pressure_sample_status"] = "Eligible sample" if int(row.get("pressure_balls") or 0) >= 30 else "Review sample"
    row["ranking_eligible"] = int(row.get("balls") or 0) >= ranking_minimum
    if sort_by == "Batting average":
        row["ranking_eligible"] = row["ranking_eligible"] and int(row.get("dismissals") or 0) >= 3
rank_eligible = [row for row in raw if row.get("ranking_eligible")]
review_rows = [row for row in raw if not row.get("ranking_eligible")]
ranked = sorted(rank_eligible, key=lambda row: (row.get(sort_key) is None, -(row.get(sort_key) or 0), row.get("player") or ""))
review_ranked = sorted(review_rows, key=lambda row: (row.get(sort_key) is None, -(row.get(sort_key) or 0), row.get("player") or ""))
ranked_display = ranked + review_ranked
ranked_csv = ranked_display[:500]

st.caption(
    f"{len(eligible):,} players meet the {ranking_minimum}-ball state minimum. "
    "Rankings use the full selected format, season, and country cohort; the pressure-only switch applies to the player profile. "
    "Adjusted strike rate blends with the filtered cohort baseline using 60 prior balls; adjusted average uses 3 prior dismissals. "
    "Raw batting average is shown only at 3 or more dismissals. Use the Pressure state player report for pressure rankings, which apply the confirmed recency gates and weighted composite."
)
col1, col2 = st.columns([1.2, 0.8])
with col1:
    with st.container(border=True):
        st.markdown("**Player leaderboard**")
        markdown_table(
            ranked_display[:30],
            [
                ("player", "Batter"),
                ("matches", "Matches"),
                ("innings", "Innings"),
                ("runs", "Raw runs"),
                ("balls", "Balls faced"),
                ("strike_rate", "SR"),
                ("average", "Average"),
                ("adjusted_sr", "Adjusted SR"),
                ("adjusted_average", "Adjusted average"),
                ("fours", "4s"),
                ("sixes", "6s"),
                ("dot_share", "Dot share"),
                ("sample_status", "Sample"),
            ],
        )
        csv_download(ranked_csv, "Download filtered batter rankings", "batter_rankings.csv", "batter_rank_csv")
with col2:
    with st.container(border=True):
        st.markdown("**Adjusted strike rate and average**")
        chart_rows = [
            row
            for row in eligible
            if row.get("adjusted_sr") is not None and row.get("adjusted_average") is not None
        ]
        fig = go.Figure(
            go.Scatter(
                x=[row["adjusted_sr"] for row in chart_rows],
                y=[row["adjusted_average"] for row in chart_rows],
                mode="markers",
                marker=dict(
                    size=[max(8, min(28, 7 + (row["balls"] or 0) ** 0.5 / 3)) for row in chart_rows],
                    color=[row["pressure_sr"] if row["pressure_sr"] is not None else row["adjusted_sr"] for row in chart_rows],
                    colorscale=[[0, BLUE], [0.6, ORDINARY], [1, PRESSURE]],
                    opacity=0.76,
                    line=dict(color="white", width=1),
                    colorbar=dict(title="Pressure SR"),
                ),
                text=[row["player"] for row in chart_rows],
                customdata=[[row["balls"], row["runs"], row["pressure_sr"]] for row in chart_rows],
                hovertemplate="%{text}<br>Adjusted SR %{x:.1f}<br>Adjusted average %{y:.1f}<br>Balls %{customdata[0]}<br>Runs %{customdata[1]}<br>Pressure SR %{customdata[2]:.1f}<extra></extra>",
            )
        )
        fig.update_layout(xaxis_title="Adjusted strike rate", yaxis_title="Adjusted batting average")
        chart(fig, "Adjusted batting strike rate against adjusted average, bubble size shows balls faced", height=460)

st.divider()
st.subheader("Player profile")
if not raw:
    st.info("No batter rows match the selected filters.")
else:
    player_options = sorted(raw, key=lambda row: (row.get("player") or "", int(row.get("player_id") or 0)))
    player_labels = {
        f"{row.get('player') or 'Unknown'} · ID {row['player_id']}": int(row["player_id"])
        for row in player_options
    }
    selected_label = st.selectbox("Select a batter", list(player_labels), key="batter_profile_player")
    player_id = player_labels[selected_label]
    profile = batter_profile(filters, player_id)
    scores: dict[tuple[int, int], dict] = {}
    dismissals = Counter()
    by_year: dict[str, dict[str, int]] = defaultdict(lambda: {"runs": 0, "balls": 0})
    by_remaining: dict[str, dict[str, int]] = defaultdict(lambda: {"runs": 0, "balls": 0})
    for row in profile:
        key = (int(row["match_id"]), int(row["innings"]))
        item = scores.setdefault(
            key,
            {
                "match_id": row["match_id"],
                "date": row.get("match_date") or "",
                "season": row.get("season") or "",
                "innings": row["innings"],
                "runs": 0,
                "balls": 0,
                "dismissals": 0,
                "venue": row.get("venue_id") or "",
                "result": row.get("result") or "",
            },
        )
        item["runs"] += int(row.get("runs") or 0)
        item["balls"] += int(row.get("faced_ball") or 0)
        item["dismissals"] += int(row.get("is_wicket") or 0) if row.get("dismissed_player_id") == player_id else 0
        if row.get("is_wicket") and row.get("dismissed_player_id") == player_id:
            kind = (row.get("dismissal_type") or "Unknown").strip() or "Unknown"
            dismissals[kind] += 1
        match_date = str(row.get("match_date") or "")
        year = match_date[:4] if len(match_date) >= 4 else "Unknown"
        by_year[year]["runs"] += int(row.get("runs") or 0)
        by_year[year]["balls"] += int(row.get("faced_ball") or 0)
        remaining = row.get("balls_remaining")
        if row.get("innings") == 2 and row.get("state_known") and remaining is not None:
            if remaining <= 6:
                band = "1–6 balls"
            elif remaining <= 12:
                band = "7–12 balls"
            elif remaining <= 18:
                band = "13–18 balls"
            elif remaining <= 30:
                band = "19–30 balls"
            elif remaining <= 60:
                band = "31–60 balls"
            else:
                band = "61+ balls"
            by_remaining[band]["runs"] += int(row.get("runs") or 0)
            by_remaining[band]["balls"] += int(row.get("faced_ball") or 0)

    innings_rows = sorted(scores.values(), key=lambda row: (row["date"], row["match_id"], row["innings"]))
    total_runs = sum(row["runs"] for row in innings_rows)
    total_balls = sum(row["balls"] for row in innings_rows)
    total_outs = sum(row["dismissals"] for row in innings_rows)
    pressure_runs = sum(
        int(row.get("runs") or 0) for row in profile if int(row.get("pressure") or 0) == 1
    )
    pressure_balls = sum(int(row.get("pressure") or 0) * int(row.get("faced_ball") or 0) for row in profile)

    metric_row = st.columns(5, border=True)
    metric_row[0].metric("Raw runs", f"{total_runs:,}")
    metric_row[1].metric("Balls faced", f"{total_balls:,}")
    metric_row[2].metric("Strike rate", fmt_or_na(strike_rate(total_runs, total_balls)))
    profile_average = batting_average(total_runs, total_outs)
    metric_row[3].metric("Average", "Not reported" if profile_average is None else fmt_or_na(profile_average))
    metric_row[4].metric("Pressure SR", fmt_or_na(strike_rate(pressure_runs, pressure_balls)))

    trend_col, phase_col = st.columns(2)
    with trend_col:
        with st.container(border=True):
            st.markdown("**Strike rate by year**")
            year_items = sorted(
                by_year.items(),
                key=lambda item: (int(item[0]) if item[0].isdigit() else 0, item[0]),
            )
            fig = go.Figure(
                go.Scatter(
                    x=[year for year, _ in year_items],
                    y=[strike_rate(value["runs"], value["balls"]) for _, value in year_items],
                    mode="lines+markers",
                    line=dict(color=ORDINARY, width=3),
                    customdata=[[value["runs"], value["balls"]] for _, value in year_items],
                    hovertemplate="Year %{x}<br>SR %{y:.1f}<br>Runs %{customdata[0]}<br>Balls %{customdata[1]}<extra></extra>",
                )
            )
            fig.update_layout(xaxis_title="Year", yaxis_title="Strike rate")
            year_axis(fig, [year for year, _ in year_items])
            chart(fig, "Batter strike rate by calendar year", height=320)
    with phase_col:
        with st.container(border=True):
            st.markdown("**Strike rate by balls remaining**")
            bands = ["61+ balls", "31–60 balls", "19–30 balls", "13–18 balls", "7–12 balls", "1–6 balls"]
            values = [by_remaining.get(band, {"runs": 0, "balls": 0}) for band in bands]
            fig = go.Figure(
                go.Bar(
                    x=bands,
                    y=[strike_rate(value["runs"], value["balls"]) for value in values],
                    marker_color=PRESSURE,
                    customdata=[[value["runs"], value["balls"]] for value in values],
                    hovertemplate="%{x}<br>SR %{y:.1f}<br>Runs %{customdata[0]}<br>Balls %{customdata[1]}<extra></extra>",
                )
            )
            fig.update_layout(xaxis_title="Legal balls remaining at pre-ball state", yaxis_title="Strike rate")
            chart(fig, "Batter strike rate across chase balls-remaining bands", height=320)

    dismissal_rows = [{"type": kind, "count": count} for kind, count in dismissals.most_common()]
    log_rows = [
        {
            "date": row["date"],
            "match_id": row["match_id"],
            "innings": row["innings"],
            "venue_id": row["venue"],
            "runs": row["runs"],
            "balls": row["balls"],
            "strike_rate": strike_rate(row["runs"], row["balls"]),
            "dismissals": row["dismissals"],
            "result": row["result"],
        }
        for row in reversed(innings_rows[-25:])
    ]
    profile_left, profile_right = st.columns([0.8, 1.2])
    with profile_left:
        with st.container(border=True):
            st.markdown("**Dismissal types**")
            fig = go.Figure(
                go.Bar(
                    x=[row["count"] for row in dismissal_rows],
                    y=[row["type"] for row in dismissal_rows],
                    orientation="h",
                    marker_color=GOLD,
                )
            )
            fig.update_layout(xaxis_title="Dismissals", yaxis_title="")
            chart(fig, "Batter dismissals by type", height=320)
    with profile_right:
        with st.container(border=True):
            st.markdown("**Recent innings**")
            markdown_table(
                log_rows,
                [
                    ("date", "Date"),
                    ("match_id", "Match"),
                    ("innings", "Inn."),
                    ("venue_id", "Venue ID"),
                    ("runs", "Raw runs"),
                    ("balls", "Balls"),
                    ("strike_rate", "SR"),
                    ("dismissals", "Out"),
                    ("result", "Result"),
                ],
            )
