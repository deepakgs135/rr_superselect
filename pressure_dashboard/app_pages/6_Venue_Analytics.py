from __future__ import annotations

from collections import defaultdict

import plotly.graph_objects as go
import streamlit as st

from lib.metrics import economy_rate, share, strike_rate, wicket_rate
from lib.queries import state_comparison, venue_innings, venue_state_aggregates
from lib.ui import ORDINARY, PRESSURE, chart, fmt_or_na, markdown_table, page_header, pct, year_axis

filters = st.session_state.get("dashboard_filters", {})
page_header(
    "Venue analytics",
    "Venue IDs are paired with country and format so score patterns are not presented as named grounds.",
    ":material/stadium:",
)
st.caption(
    "Batting pressure: RRR ≥15, ≤30 legal balls, and at least 3 wickets lost. Bowling pressure: exactly 2 wickets lost, "
    "≤30 legal balls, current scoring rate ≥11 RPO, and required rate ≥9 RPO."
)

innings_rows = venue_innings(filters)
state_rows = venue_state_aggregates(filters)
groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
for row in innings_rows:
    groups[(str(row.get("venue_id") or "Unknown"), row.get("venue_country") or "Unknown", row.get("match_format") or "Unknown")].append(row)
state_map = {
    (
        str(row.get("venue_id") or "Unknown"),
        row.get("venue_country") or "Unknown",
        row.get("match_format") or "Unknown",
    ): row
    for row in state_rows
}

venue_stats = []
for key, rows in groups.items():
    venue_id, country, format_name = key
    first_rows = [row for row in rows if int(row.get("innings") or 0) == 1]
    chase_rows = [row for row in rows if int(row.get("innings") or 0) == 2]
    match_ids = {int(row["match_id"]) for row in rows}
    decided = [row for row in chase_rows if row.get("chase_success") is not None]
    pressure_decided = [
        row for row in decided if int(row.get("pressure_legal_balls") or 0) > 0
    ]
    pressure_chases = [row for row in chase_rows if int(row.get("pressure_legal_balls") or 0) > 0]
    venue_state = state_map.get((venue_id, country, format_name), {})
    first_total = sum(int(row.get("total_runs_proxy") or 0) for row in first_rows)
    first_count = len(first_rows)
    second_total = sum(int(row.get("total_runs_proxy") or 0) for row in chase_rows)
    second_count = len(chase_rows)
    legal_balls = sum(int(row.get("known_legal_balls") or 0) for row in rows)
    unknown_events = sum(int(row.get("unknown_legality_events") or 0) for row in rows)
    wickets = sum(int(row.get("wicket_events") or 0) for row in rows)
    fours = sum(int(row.get("fours") or 0) for row in rows)
    sixes = sum(int(row.get("sixes") or 0) for row in rows)
    bowling_pressure_balls = int(venue_state.get("bowling_pressure_legal_balls") or 0)
    venue_stats.append(
        {
            "venue_id": venue_id,
            "country": country,
            "format": format_name,
            "matches": len(match_ids),
            "chases": len(chase_rows),
            "pressure_chases": len(pressure_chases),
            "pressure_share": share(len(pressure_chases), len(chase_rows)),
            "pressure_win_rate": share(
                sum(int(row.get("chase_success") or 0) for row in pressure_decided),
                len(pressure_decided),
            ),
            "all_chase_win_rate": share(
                sum(int(row.get("chase_success") or 0) for row in decided), len(decided)
            ),
            "mean_first_score": first_total / first_count if first_count else None,
            "mean_second_score": second_total / second_count if second_count else None,
            "pressure_sr": strike_rate(
                int(venue_state.get("batter_pressure_runs") or 0),
                int(venue_state.get("batter_pressure_balls") or 0),
            ),
            "ordinary_sr": strike_rate(
                int(venue_state.get("batter_ordinary_runs") or 0),
                int(venue_state.get("batter_ordinary_balls") or 0),
            ),
            "pressure_economy": economy_rate(
                int(venue_state.get("bowling_pressure_runs_proxy") or 0),
                bowling_pressure_balls,
            ),
            "pressure_wicket_rate": wicket_rate(
                int(venue_state.get("bowling_pressure_credited_wickets") or 0),
                bowling_pressure_balls,
            ),
            "legal_balls": legal_balls,
            "unknown_events": unknown_events,
            "wickets": wickets,
            "boundaries_per_100": share(fours + sixes, legal_balls),
        }
    )

venue_stats.sort(
    key=lambda row: (-row["matches"], row["country"], row["venue_id"], row["format"])
)

if not venue_stats:
    st.info("No venue data match the selected filters.")
else:
    st.caption(
        f"{len(venue_stats):,} venue-format cohorts. Summary scores and outcomes use the full innings; "
        "Batting pressure and bowling pressure use their separate chase-state rules. "
        "Score and economy fields remain raw proxies."
    )
    with st.container(border=True):
        st.markdown("**Venue comparison**")
        markdown_table(
            venue_stats[:40],
            [
                ("venue_id", "Venue ID"),
                ("country", "Country"),
                ("format", "Format"),
                ("matches", "Matches"),
                ("chases", "Chases"),
                ("pressure_chases", "Pressure chases"),
                ("pressure_share", "Pressure chase share", pct),
                ("pressure_win_rate", "Pressure chase win rate", pct),
                ("all_chase_win_rate", "All chase win rate", pct),
                ("mean_first_score", "Mean first score proxy"),
                ("mean_second_score", "Mean chase score proxy"),
                ("pressure_sr", "Pressure SR"),
                ("ordinary_sr", "Ordinary SR"),
                ("pressure_economy", "Bowling-pressure economy"),
                ("pressure_wicket_rate", "Bowling-pressure wickets / 100"),
            ],
        )

    labels = {
        f"Venue {row['venue_id']} · {row['country']} · {row['format']} ({row['matches']} matches)": (
            row["venue_id"],
            row["country"],
            row["format"],
        )
        for row in venue_stats
    }
    selected_label = st.selectbox("Select a venue cohort", list(labels), key="venue_cohort")
    selected_key = labels[selected_label]
    selected_summary = next(row for row in venue_stats if (row["venue_id"], row["country"], row["format"]) == selected_key)
    selected_rows = groups[selected_key]

    cards = st.columns(4, border=True)
    cards[0].metric("Matches", f"{selected_summary['matches']:,}")
    cards[1].metric("Mean first-innings score proxy", fmt_or_na(selected_summary["mean_first_score"]))
    cards[2].metric("Pressure chase win rate", pct(selected_summary["pressure_win_rate"]))
    cards[3].metric("Unknown-legality events", f"{selected_summary['unknown_events']:,}")

    by_year: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: {"first": [], "second": [], "pressure_chases": []}
    )
    for row in selected_rows:
        match_date = str(row.get("match_date") or "")
        year = match_date[:4] if len(match_date) >= 4 else "Unknown"
        if int(row.get("innings") or 0) == 1:
            by_year[year]["first"].append(int(row.get("total_runs_proxy") or 0))
        elif int(row.get("innings") or 0) == 2:
            by_year[year]["second"].append(int(row.get("total_runs_proxy") or 0))
            by_year[year]["pressure_chases"].append(
                int(int(row.get("pressure_legal_balls") or 0) > 0)
            )
    year_items = sorted(
        by_year.items(),
        key=lambda item: (int(item[0]) if item[0].isdigit() else 0, item[0]),
    )
    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.markdown("**Raw score proxy by year**")
            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=[year for year, _ in year_items],
                    y=[
                        (sum(value["first"]) / len(value["first"])) if value["first"] else None
                        for _, value in year_items
                    ],
                    name="First innings",
                    mode="lines+markers",
                    line=dict(color=ORDINARY, width=3),
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=[year for year, _ in year_items],
                    y=[
                        (sum(value["second"]) / len(value["second"])) if value["second"] else None
                        for _, value in year_items
                    ],
                    name="Second innings",
                    mode="lines+markers",
                    line=dict(color=PRESSURE, width=3),
                )
            )
            fig.update_layout(xaxis_title="Year", yaxis_title="Mean raw score proxy")
            year_axis(fig, [year for year, _ in year_items])
            chart(fig, "Mean first and second innings raw score proxies by calendar year at the selected venue", height=330)
    with right:
        with st.container(border=True):
            st.markdown("**Pressure chase share by year**")
            fig = go.Figure(
                go.Bar(
                    x=[year for year, _ in year_items],
                    y=[
                        share(sum(value["pressure_chases"]), len(value["pressure_chases"]))
                        for _, value in year_items
                    ],
                    marker_color=PRESSURE,
                    hovertemplate="%{x}<br>Pressure chase share %{y:.1f}%<extra></extra>",
                )
            )
            fig.update_layout(xaxis_title="Year", yaxis_title="Pressure chases (%)", yaxis_range=[0, 100])
            year_axis(fig, [year for year, _ in year_items])
            chart(fig, "Share of venue chases with batting pressure by calendar year", height=330)

    player_filters = dict(filters)
    player_filters["formats"] = [selected_key[2]]
    batter_state_rows = state_comparison(player_filters, "batter", selected_key[0])
    bowler_state_rows = state_comparison(player_filters, "bowler", selected_key[0])
    minimum = int(filters.get("min_balls", 30))

    def player_state_map(rows: list[dict]) -> dict[int, dict[int, dict]]:
        result: dict[int, dict[int, dict]] = defaultdict(dict)
        for row in rows:
            result[int(row["player_id"])][int(row["pressure"])] = row
        return result

    batter_states = player_state_map(batter_state_rows)
    bowler_states = player_state_map(bowler_state_rows)
    top_batters = []
    for player_id, states in batter_states.items():
        pressure = states.get(1, {})
        ordinary = states.get(0, {})
        balls = int(pressure.get("balls") or 0)
        sr = strike_rate(int(pressure.get("runs") or 0), balls)
        if sr is not None and balls >= minimum:
            top_batters.append(
                {
                    "player": pressure.get("player") or f"Player {player_id}",
                    "pressure_balls": balls,
                    "pressure_sr": sr,
                    "ordinary_sr": strike_rate(
                        int(ordinary.get("runs") or 0), int(ordinary.get("balls") or 0)
                    ),
                }
            )
    top_batters.sort(key=lambda row: (-row["pressure_sr"], -row["pressure_balls"]))
    top_bowlers = []
    for player_id, states in bowler_states.items():
        pressure = states.get(1, {})
        balls = int(pressure.get("legal_balls") or 0)
        economy = economy_rate(int(pressure.get("runs_proxy") or 0), balls)
        if economy is not None and balls > 0:
            top_bowlers.append(
                {
                    "player": pressure.get("player") or f"Player {player_id}",
                    "pressure_legal_balls": balls,
                    "pressure_economy": economy,
                    "credited_wickets": int(pressure.get("credited_wickets") or 0),
                    "wickets_per_100": wicket_rate(
                        int(pressure.get("credited_wickets") or 0), balls
                    ),
                }
            )
    top_bowlers.sort(
        key=lambda row: (
            -(row["wickets_per_100"] or 0),
            row["pressure_economy"],
            -row["pressure_legal_balls"],
        )
    )

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.markdown(f"**Top pressure batters · minimum {minimum} balls**")
            markdown_table(
                top_batters[:12],
                [
                    ("player", "Batter"),
                    ("pressure_balls", "Pressure balls"),
                    ("pressure_sr", "Pressure SR"),
                    ("ordinary_sr", "Ordinary SR"),
                ],
            )
    with right:
        with st.container(border=True):
            st.markdown("**Bowling-pressure leaders · quick-wicket rate first**")
            st.caption("Exact pressure scenarios can be uncommon; legal-ball counts show sample size.")
            markdown_table(
                top_bowlers[:12],
                [
                    ("player", "Bowler"),
                    ("pressure_legal_balls", "Bowling-pressure legal balls"),
                    ("wickets_per_100", "Wickets / 100"),
                    ("pressure_economy", "Economy proxy"),
                    ("credited_wickets", "Credited wickets"),
                ],
            )
