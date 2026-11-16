from __future__ import annotations

from collections import defaultdict

import plotly.graph_objects as go
import streamlit as st

from lib.metrics import economy_rate, share, strike_rate, wicket_rate
from lib.pressure_reports import pressure_report
from lib.queries import state_comparison, venue_innings, venue_state_aggregates
from lib.ui import ORDINARY, PRESSURE, chart, fmt_or_na, markdown_table, page_header, pct, year_axis

filters = st.session_state.get("dashboard_filters", {})
page_header(
    "Venue analytics",
    "Venue IDs are paired with country and format so score patterns are not presented as named grounds.",
    ":material/stadium:",
)
st.caption(
    "Pressure flags use all-venue T20 chases. Batting: final 30 balls, RRR ≥15, and at least 3 wickets down. "
    "Bowling: 2 or fewer wickets down in the final 30 balls, current rate ≥11 RPO, and required rate ≥9 RPO. "
    "Win rates require 10 venue matches; pressure-state rates also require 20 decided pressure chases."
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
        row for row in decided if int(row.get("pressure_delivery_rows") or 0) > 0
    ]
    pressure_chases = [row for row in chase_rows if int(row.get("pressure_delivery_rows") or 0) > 0]
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
    batting_pressure_decided = int(venue_state.get("batting_pressure_decided_chases") or 0)
    bowling_pressure_decided = int(venue_state.get("bowling_pressure_decided_chases") or 0)
    batting_ordinary_decided = int(venue_state.get("batting_ordinary_decided_chases") or 0)
    bowling_ordinary_decided = int(venue_state.get("bowling_ordinary_decided_chases") or 0)
    enough_matches = len(match_ids) >= 10
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
                int(venue_state.get("batting_pressure_wins") or 0),
                len(pressure_decided),
            ) if enough_matches and batting_pressure_decided >= 20 else None,
            "all_chase_win_rate": share(
                sum(int(row.get("chase_success") or 0) for row in decided), len(decided)
            ) if enough_matches else None,
            "decided_chases": len(decided),
            "decided_pressure_chases": batting_pressure_decided,
            "bowling_pressure_decided_chases": bowling_pressure_decided,
            "decided_batting_ordinary_chases": batting_ordinary_decided,
            "decided_bowling_ordinary_chases": bowling_ordinary_decided,
            "decided_ordinary_chases": len(decided),
            "mean_first_score": first_total / first_count if enough_matches and first_count else None,
            "mean_second_score": second_total / second_count if enough_matches and second_count else None,
            "pressure_sr": strike_rate(
                int(venue_state.get("batter_pressure_runs") or 0),
                int(venue_state.get("batter_pressure_balls") or 0),
            ) if batting_pressure_decided >= 20 else None,
            "ordinary_sr": strike_rate(
                int(venue_state.get("batter_ordinary_runs") or 0),
                int(venue_state.get("batter_ordinary_balls") or 0),
            ) if batting_ordinary_decided >= 20 else None,
            "pressure_economy": economy_rate(
                int(venue_state.get("bowling_pressure_runs_proxy") or 0),
                bowling_pressure_balls,
            ) if bowling_pressure_decided >= 20 else None,
            "pressure_reporting": (
                "Full pressure rates available"
                if batting_pressure_decided >= 20 and bowling_pressure_decided >= 20
                else f"Count only for pressure state (batting n={batting_pressure_decided}; bowling n={bowling_pressure_decided})"
            ),
            "pressure_wicket_rate": wicket_rate(
                int(venue_state.get("bowling_pressure_credited_wickets") or 0),
                bowling_pressure_balls,
            ) if bowling_pressure_decided >= 20 else None,
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
                ("decided_chases", "Decided chases"),
                ("decided_pressure_chases", "Decided batting-pressure chases"),
                ("bowling_pressure_decided_chases", "Decided bowling-pressure chases"),
                ("decided_batting_ordinary_chases", "Decided ordinary batting chases"),
                ("decided_bowling_ordinary_chases", "Decided ordinary bowling chases"),
                ("pressure_share", "Pressure chase share", pct),
                ("pressure_win_rate", "Pressure chase win rate", pct),
                ("all_chase_win_rate", "All chase win rate", pct),
                ("mean_first_score", "Mean first score proxy"),
                ("mean_second_score", "Mean chase score proxy"),
                ("pressure_sr", "Pressure SR"),
                ("ordinary_sr", "Ordinary SR"),
                ("pressure_economy", "Bowling-pressure economy"),
                ("pressure_wicket_rate", "Bowling-pressure wickets / 100"),
                ("pressure_reporting", "Pressure-state reporting"),
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
        lambda: {"first": [], "second": [], "pressure_chases": [], "matches": set(), "decided_pressure": 0, "pressure_wins": 0}
    )
    for row in selected_rows:
        match_date = str(row.get("match_date") or "")
        year = match_date[:4] if len(match_date) >= 4 else "Unknown"
        by_year[year]["matches"].add(int(row["match_id"]))
        if int(row.get("innings") or 0) == 1:
            by_year[year]["first"].append(int(row.get("total_runs_proxy") or 0))
        elif int(row.get("innings") or 0) == 2:
            by_year[year]["second"].append(int(row.get("total_runs_proxy") or 0))
            by_year[year]["pressure_chases"].append(
                int(int(row.get("pressure_delivery_rows") or 0) > 0)
            )
            if int(row.get("pressure_delivery_rows") or 0) > 0 and row.get("chase_success") is not None:
                by_year[year]["decided_pressure"] += 1
                by_year[year]["pressure_wins"] += int(row.get("chase_success") or 0)
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
                        (sum(value["first"]) / len(value["first"])) if value["first"] and len(value["matches"]) >= 10 else None
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
                        (sum(value["second"]) / len(value["second"])) if value["second"] and len(value["matches"]) >= 10 else None
                        for _, value in year_items
                    ],
                    name="Second innings",
                    mode="lines+markers",
                    line=dict(color=PRESSURE, width=3),
                )
            )
            fig.update_layout(xaxis_title="Year", yaxis_title="Mean raw score proxy")
            year_axis(fig, [year for year, _ in year_items])
            chart(fig, "Mean first and second innings raw score proxies by year (10 matches required)", height=330)
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

    year_sample_rows = [
        {
            "year": year,
            "matches": len(value["matches"]),
            "pressure_chases": sum(value["pressure_chases"]),
            "decided_pressure_chases": value["decided_pressure"],
            "pressure_win_rate": share(value["pressure_wins"], value["decided_pressure"])
            if len(value["matches"]) >= 10 and value["decided_pressure"] >= 20 else "Count only",
            "mean_first_score": sum(value["first"]) / len(value["first"])
            if value["first"] and len(value["matches"]) >= 10 else "Count only",
            "mean_second_score": sum(value["second"]) / len(value["second"])
            if value["second"] and len(value["matches"]) >= 10 else "Count only",
        }
        for year, value in year_items
    ]
    with st.expander("Year sample counts and reportability"):
        markdown_table(
            year_sample_rows,
            [
                ("year", "Year"),
                ("matches", "Matches"),
                ("pressure_chases", "Pressure chases"),
                ("decided_pressure_chases", "Decided pressure chases"),
                ("pressure_win_rate", "Pressure win rate"),
                ("mean_first_score", "Mean first score proxy"),
                ("mean_second_score", "Mean chase score proxy"),
            ],
        )

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
    pressure_data = pressure_report()
    recent_player_context = {
        (role, int(row["player_id"])): row
        for role, table in (
            ("batter", pressure_data.get("batter_table", [])),
            ("bowler", pressure_data.get("bowler_table", [])),
        )
        for row in table
        if row.get("state") == ("Batting pressure" if role == "batter" else "Bowling pressure")
    }
    batting_cell_decided = int(selected_summary.get("decided_pressure_chases") or 0)
    bowling_cell_decided = int(selected_summary.get("bowling_pressure_decided_chases") or 0)
    batting_cell_reportable = batting_cell_decided >= 20
    bowling_cell_reportable = bowling_cell_decided >= 20
    batting_ordinary_reportable = int(selected_summary.get("decided_batting_ordinary_chases") or 0) >= 20
    bowling_ordinary_reportable = int(selected_summary.get("decided_bowling_ordinary_chases") or 0) >= 20
    top_batters = []
    for player_id, states in batter_states.items():
        pressure = states.get(1, {})
        ordinary = states.get(0, {})
        balls = int(pressure.get("balls") or 0)
        ordinary_balls = int(ordinary.get("balls") or 0)
        sr = strike_rate(int(pressure.get("runs") or 0), balls)
        if pressure:
            context = recent_player_context.get(("batter", player_id), {})
            active_2026 = bool(context.get("active_2026_all_venues"))
            recent_innings = int(context.get("recent_innings") or 0)
            sample_ok = balls >= minimum
            activity_ok = active_2026
            form_ok = recent_innings >= 10
            ranking_eligible = batting_cell_reportable and sample_ok and activity_ok and form_ok
            comparison_reasons = []
            if not batting_cell_reportable or not batting_ordinary_reportable:
                comparison_status = "Count only"
            else:
                if balls < minimum:
                    comparison_reasons.append(f"pressure sample below {minimum} balls")
                if ordinary_balls < minimum:
                    comparison_reasons.append(f"ordinary sample below {minimum} balls")
                if not activity_ok:
                    comparison_reasons.append("no 2026 T20 appearance")
                if not form_ok:
                    comparison_reasons.append(f"{recent_innings} recent innings; 10 required")
                comparison_status = "Eligible comparison" if not comparison_reasons else "Review sample"
            ranking_reasons = []
            if not batting_cell_reportable:
                ranking_reasons.append(f"{batting_cell_decided} decided chases; 20 required")
            if not sample_ok:
                ranking_reasons.append(f"{balls} pressure balls; {minimum} required")
            if not activity_ok:
                ranking_reasons.append("no 2026 T20 appearance")
            if not form_ok:
                ranking_reasons.append(f"{recent_innings} recent innings; 10 required")
            top_batters.append(
                {
                    "player": pressure.get("player") or f"Player {player_id}",
                    "pressure_matches": int(pressure.get("matches") or 0),
                    "pressure_balls": balls,
                    "ordinary_matches": int(ordinary.get("matches") or 0),
                    "ordinary_balls": ordinary_balls,
                    "pressure_sr": sr if batting_cell_reportable and balls >= minimum else "Count only" if not batting_cell_reportable else "Not reported",
                    "ordinary_sr": strike_rate(int(ordinary.get("runs") or 0), ordinary_balls)
                    if batting_ordinary_reportable and ordinary_balls >= minimum else "Not compared",
                    "sample_status": "Eligible sample" if balls >= minimum else "Review sample",
                    "active_2026_all_venues": active_2026,
                    "recent_innings": recent_innings,
                    "recent_form_status": "Eligible form" if form_ok else "Review sample",
                    "ranking_eligible": ranking_eligible,
                    "ranking_reasons": "; ".join(ranking_reasons),
                    "comparison_status": comparison_status,
                    "comparison_reasons": "; ".join(comparison_reasons),
                }
            )
    eligible_batters = [row for row in top_batters if row["ranking_eligible"]]
    if batting_cell_reportable and len(eligible_batters) >= 10:
        top_batters.sort(key=lambda row: (row["sample_status"] != "Eligible sample", -(row["pressure_sr"] if isinstance(row["pressure_sr"], (int, float)) else -1), -row["pressure_balls"], row["player"]))
        rank = 0
        for row in top_batters:
            if row["sample_status"] == "Eligible sample":
                rank += 1
                row["rank"] = rank
            else:
                row["rank"] = None
    else:
        top_batters.sort(key=lambda row: row["player"])
        for row in top_batters:
            row["rank"] = None
    top_bowlers = []
    for player_id, states in bowler_states.items():
        pressure = states.get(1, {})
        balls = int(pressure.get("legal_balls") or 0)
        economy = economy_rate(int(pressure.get("runs_proxy") or 0), balls)
        wickets = int(pressure.get("credited_wickets") or 0)
        if pressure:
            context = recent_player_context.get(("bowler", player_id), {})
            active_2026 = bool(context.get("active_2026_all_venues"))
            recent_innings = int(context.get("recent_innings") or 0)
            sample_ok = balls >= minimum
            wicket_ok = wickets >= 3
            activity_ok = active_2026
            form_ok = recent_innings >= 10
            ranking_eligible = bowling_cell_reportable and sample_ok and wicket_ok and activity_ok and form_ok
            ranking_reasons = []
            if not bowling_cell_reportable:
                ranking_reasons.append(f"{bowling_cell_decided} decided chases; 20 required")
            if not sample_ok:
                ranking_reasons.append(f"{balls} pressure legal balls; {minimum} required")
            if not wicket_ok:
                ranking_reasons.append(f"{wickets} credited wickets; 3 required")
            if not activity_ok:
                ranking_reasons.append("no 2026 T20 appearance")
            if not form_ok:
                ranking_reasons.append(f"{recent_innings} recent innings; 10 required")
            top_bowlers.append(
                {
                    "player": pressure.get("player") or f"Player {player_id}",
                    "pressure_legal_balls": balls,
                    "pressure_economy": economy if bowling_cell_reportable and balls >= minimum else "Count only" if not bowling_cell_reportable else "Not reported",
                    "credited_wickets": wickets,
                    "wickets_per_100": wicket_rate(wickets, balls)
                    if bowling_cell_reportable and balls >= minimum and wickets >= 3 else "Not reported",
                    "sample_status": "Eligible sample" if balls >= minimum else "Review sample",
                    "wicket_rate_status": "Eligible" if wickets >= 3 else "Review sample",
                    "active_2026_all_venues": active_2026,
                    "recent_innings": recent_innings,
                    "recent_form_status": "Eligible form" if form_ok else "Review sample",
                    "ranking_eligible": ranking_eligible,
                    "ranking_reasons": "; ".join(ranking_reasons),
                }
            )
    eligible_bowlers = [row for row in top_bowlers if row["ranking_eligible"]]
    if bowling_cell_reportable and len(eligible_bowlers) >= 10:
        top_bowlers.sort(key=lambda row: (row not in eligible_bowlers, -(row["wickets_per_100"] if isinstance(row["wickets_per_100"], (int, float)) else -1), row["pressure_economy"] if isinstance(row["pressure_economy"], (int, float)) else float("inf"), -row["pressure_legal_balls"], row["player"]))
        rank = 0
        for row in top_bowlers:
            if row in eligible_bowlers:
                rank += 1
                row["rank"] = rank
            else:
                row["rank"] = None
    else:
        top_bowlers.sort(key=lambda row: row["player"])
        for row in top_bowlers:
            row["rank"] = None

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.markdown("**Batting-pressure observations**")
            st.caption(f"{len(eligible_batters):,} players pass the 30-ball, 2026 activity, and latest-10-innings gates. A ranking also needs 20 decided venue chases and at least 10 eligible players. A state comparison requires 30 balls in both states.")
            markdown_table(
                top_batters,
                [
                    ("rank", "Rank"),
                    ("player", "Batter"),
                    ("pressure_matches", "Pressure matches"),
                    ("pressure_balls", "Pressure balls"),
                    ("ordinary_matches", "Ordinary matches"),
                    ("ordinary_balls", "Ordinary balls"),
                    ("pressure_sr", "Pressure SR"),
                    ("ordinary_sr", "Ordinary SR"),
                    ("sample_status", "Pressure sample"),
                    ("comparison_status", "Comparison sample"),
                    ("recent_innings", "Recent innings"),
                    ("active_2026_all_venues", "Played in 2026"),
                    ("ranking_reasons", "Ranking gate detail"),
                    ("comparison_reasons", "Comparison gate detail"),
                ],
            )
    with right:
        with st.container(border=True):
            st.markdown("**Bowling-pressure observations**")
            st.caption(f"{len(eligible_bowlers):,} players pass the 30-ball, 3-wicket, 2026 activity, and latest-10-innings gates. A ranking also needs 20 decided venue chases and at least 10 eligible players. Economy charges one run per wide/no-ball row.")
            markdown_table(
                top_bowlers,
                [
                    ("rank", "Rank"),
                    ("player", "Bowler"),
                    ("pressure_legal_balls", "Bowling-pressure legal balls"),
                    ("wickets_per_100", "Wickets / 100"),
                    ("pressure_economy", "Economy proxy"),
                    ("credited_wickets", "Credited wickets"),
                    ("sample_status", "Ball sample"),
                    ("wicket_rate_status", "Wicket-rate sample"),
                    ("recent_innings", "Recent innings"),
                    ("active_2026_all_venues", "Played in 2026"),
                    ("ranking_reasons", "Ranking gate detail"),
                ],
            )
