from __future__ import annotations

from collections import defaultdict

import plotly.graph_objects as go
import streamlit as st

from lib.metrics import economy_rate, strike_rate, wicket_rate
from lib.queries import chase_events, match_deliveries, match_innings, match_list
from lib.scorecards import build_innings_scorecard
from lib.ui import BLUE, GOLD, ORDINARY, PRESSURE, chart, csv_download, fmt_or_na, markdown_table, page_header, pct

filters = st.session_state.get("dashboard_filters", {})
page_header(
    "Match analytics",
    "Compare both innings by over, inspect batting and bowling figures, and track every pressure event.",
    ":material/scoreboard:",
)

matches = match_list(filters)
search = st.text_input(
    "Find a match by team, competition, venue, or match ID",
    placeholder="For example, India or 13511",
    key="match_search",
)
if search.strip():
    needle = search.strip().casefold()
    matches = [
        row
        for row in matches
        if needle
        in " ".join(
            str(row.get(key) or "")
            for key in ("match_id", "home_team", "away_team", "comp_name", "venue_id", "venue_country")
        ).casefold()
    ]

with st.container(border=True):
    st.markdown("**Filtered chase matches**")
    markdown_table(
        matches[:40],
        [
            ("match_date", "Date"),
            ("match_id", "Match"),
            ("comp_name", "Competition"),
            ("match_format", "Format"),
            ("home_team", "Home"),
            ("away_team", "Away"),
            ("venue_id", "Venue ID"),
            ("venue_country", "Country"),
            ("target", "Target"),
            ("chase_runs_proxy", "Chase runs proxy"),
            ("pressure_legal_balls", "Batting-pressure legal balls"),
            ("result", "Result"),
        ],
    )
    csv_download(matches, "Download filtered match list", "match_analytics.csv", "match_list_csv")

if not matches:
    st.info("No chase matches match the current filters or search.")
else:
    match_labels = {
        (
            f"{row.get('match_date') or 'Unknown date'} · "
            f"{row.get('home_team') or 'Team'} vs {row.get('away_team') or 'Team'} "
            f"· ID {row['match_id']}"
        ): int(row["match_id"])
        for row in matches
    }
    match_options = list(match_labels)
    match_by_id = {int(row["match_id"]): row for row in matches}
    first_pressure_match = next(
        (
            index
            for index, label in enumerate(match_options)
            if int(match_by_id[match_labels[label]].get("pressure_legal_balls") or 0) > 0
        ),
        0,
    )
    selected_label = st.selectbox(
        "Select a match",
        match_options,
        index=first_pressure_match,
        key="selected_match",
    )
    match_id = match_labels[selected_label]
    innings = match_innings(filters, match_id)
    chase = next((row for row in innings if int(row.get("innings") or 0) == 2), {})
    first = next((row for row in innings if int(row.get("innings") or 0) == 1), {})
    chase_log = chase_events(match_id)
    match_events = match_deliveries(match_id)
    metadata = next((row for row in matches if int(row["match_id"]) == match_id), {})

    st.divider()
    st.subheader(
        f"{metadata.get('home_team') or 'Team'} vs {metadata.get('away_team') or 'Team'}"
    )
    st.caption(
        f"{metadata.get('match_date') or 'Unknown date'} · {metadata.get('match_format') or 'Unknown format'} "
        f"· Season {metadata.get('season') or 'Unknown'} · Match ID {match_id} · "
        f"{metadata.get('result') or 'Result unavailable'}"
    )
    score_metrics = st.columns(5, border=True)
    score_metrics[0].metric(
        f"{first.get('batting_team') or 'First innings'} score proxy",
        fmt_or_na(first.get("total_runs_proxy"), 0),
    )
    score_metrics[1].metric("Chase target", fmt_or_na(chase.get("target"), 0))
    score_metrics[2].metric(
        f"{chase.get('batting_team') or 'Chase'} score proxy",
        fmt_or_na(chase.get("total_runs_proxy"), 0),
    )
    score_metrics[3].metric(
        "Batting-pressure legal balls", fmt_or_na(chase.get("pressure_legal_balls"), 0)
    )
    score_metrics[4].metric(
        "Chase outcome",
        "Win" if chase.get("chase_success") == 1 else (
            "Loss" if chase.get("chase_success") == 0 else "Undecided"
        ),
    )
    st.caption(
        f"Target source: {chase.get('target_source') or 'Unknown'} · "
        f"Schedule: {chase.get('scheduled_balls') or 'Unknown'} balls "
        f"({chase.get('schedule_source') or 'Unknown'}) · "
        f"{int(chase.get('unknown_legality_events') or 0)} unknown-legality events. "
        "Scores use the raw runs + extras_2_runs proxy."
    )

    over_rows: dict[int, dict[int, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"runs": 0, "wickets": 0})
    )
    for event in match_events:
        innings_no = int(event.get("innings") or 0)
        over_no = int(event.get("over_no") or 0)
        over_rows[innings_no][over_no]["runs"] += int(event.get("total_runs_proxy") or 0)
        over_rows[innings_no][over_no]["wickets"] += int(event.get("is_wicket") or 0)

    fig = go.Figure()
    innings_labels: dict[int, str] = {}
    cumulative_by_innings: dict[int, dict[int, int]] = {}
    for innings_no, summary in ((1, first), (2, chase)):
        over_values = over_rows.get(innings_no, {})
        cumulative = 0
        cumulative_by_innings[innings_no] = {}
        x_values = []
        y_values = []
        customdata = []
        for over_no in sorted(over_values):
            values = over_values[over_no]
            cumulative += values["runs"]
            cumulative_by_innings[innings_no][over_no] = cumulative
            x_values.append(over_no)
            y_values.append(cumulative)
            customdata.append([values["runs"], values["wickets"]])
        if not x_values:
            continue
        team = summary.get("batting_team") or f"Innings {innings_no}"
        innings_labels[innings_no] = team
        color = BLUE if innings_no == 1 else ORDINARY
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=y_values,
                customdata=customdata,
                mode="lines+markers",
                name=f"{team} · innings {innings_no}",
                line=dict(color=color, width=3),
                marker=dict(size=7),
                hovertemplate=(
                    "Over %{x}<br>Cumulative score proxy %{y}"
                    "<br>Runs this over %{customdata[0]}"
                    "<br>Wicket events this over %{customdata[1]}<extra></extra>"
                ),
            )
        )

    batting_pressure_by_over: dict[int, dict[str, Any]] = {}
    for event in chase_log:
        if not event.get("pressure") or not event.get("state_known"):
            continue
        over_no = int(event.get("over_no") or 0)
        item = batting_pressure_by_over.setdefault(
            over_no,
            {"events": 0, "peak_rrr": None, "min_balls": None, "max_wickets": 0},
        )
        item["events"] += 1
        rrr = event.get("rrr")
        if rrr is not None:
            item["peak_rrr"] = max(float(rrr), item["peak_rrr"] or float(rrr))
        balls_left = event.get("balls_remaining")
        if balls_left is not None:
            if item["min_balls"] is None or int(balls_left) < item["min_balls"]:
                item["min_balls"] = int(balls_left)
        item["max_wickets"] = max(
            item["max_wickets"], int(event.get("wickets_lost") or 0)
        )

    pressure_points = [
        over_no
        for over_no in sorted(batting_pressure_by_over)
        if over_no in cumulative_by_innings.get(2, {})
    ]
    if pressure_points:
        fig.add_trace(
            go.Scatter(
                x=pressure_points,
                y=[cumulative_by_innings[2][over_no] for over_no in pressure_points],
                customdata=[
                    [
                        batting_pressure_by_over[over_no]["events"],
                        batting_pressure_by_over[over_no]["peak_rrr"],
                        batting_pressure_by_over[over_no]["min_balls"],
                        batting_pressure_by_over[over_no]["max_wickets"],
                    ]
                    for over_no in pressure_points
                ],
                mode="markers",
                name="Batting-pressure over",
                marker=dict(color=PRESSURE, size=13, symbol="diamond", line=dict(color="#FFFFFF", width=1)),
                hovertemplate=(
                    "Batting-pressure state occurred in over %{x}"
                    "<br>Chase score at over end %{y}"
                    "<br>Pressure deliveries %{customdata[0]}"
                    "<br>Peak RRR in over %{customdata[1]:.2f}"
                    "<br>Fewest balls left %{customdata[2]}"
                    "<br>Most wickets down %{customdata[3]}<extra></extra>"
                ),
            )
        )
    fig.update_layout(
        xaxis_title="Over completed",
        yaxis_title="Cumulative raw score proxy",
        xaxis=dict(type="linear", dtick=1, tick0=1),
        yaxis=dict(rangemode="tozero"),
    )
    chart(
        fig,
        "Cumulative raw score by over for both innings, with batting-pressure overs marked",
        height=420,
    )
    st.caption(
        f"Team A: {innings_labels.get(1, first.get('batting_team') or 'Innings 1')} · "
        f"Team B: {innings_labels.get(2, chase.get('batting_team') or 'Innings 2')}. "
        "Pressure diamonds mark overs with at least one batting-pressure pre-ball state."
    )

    pressure_peak_rrr_values = [
        float(row["rrr"])
        for row in chase_log
        if row.get("pressure") and row.get("state_known") and row.get("rrr") is not None
    ]
    pressure_metrics = st.columns(4, border=True)
    pressure_metrics[0].metric(
        "Batting-pressure legal balls", fmt_or_na(chase.get("pressure_legal_balls"), 0)
    )
    pressure_metrics[1].metric(
        "Runs during pressure (proxy)", fmt_or_na(chase.get("pressure_raw_runs_proxy"), 0)
    )
    pressure_metrics[2].metric(
        "Wicket events during pressure", fmt_or_na(chase.get("pressure_wicket_events"), 0)
    )
    pressure_metrics[3].metric(
        "Peak batting-pressure RRR",
        fmt_or_na(max(pressure_peak_rrr_values), 2) if pressure_peak_rrr_values else "N/A",
    )
    st.caption(
        "Batting pressure is measured before the ball: required run rate ≥ 15, "
        "30 or fewer known legal balls remaining, and at least 3 wickets lost."
    )

    bowling_pressure_rows = [row for row in chase_log if row.get("bowling_pressure")]
    bowling_pressure_legal = sum(int(row.get("legal") or 0) for row in bowling_pressure_rows)
    bowling_pressure_runs = sum(
        int(row.get("total_runs_proxy") or 0) for row in bowling_pressure_rows
    )
    bowling_pressure_wickets = sum(
        int(row.get("credited_wicket") or 0) for row in bowling_pressure_rows
    )
    bowling_pressure_current_rates = [
        float(row["current_rpo"])
        for row in bowling_pressure_rows
        if row.get("current_rpo") is not None
    ]
    st.subheader("Bowling-pressure status")
    if bowling_pressure_legal:
        st.success(
            f"Reached in {bowling_pressure_legal} legal ball(s): exactly 2 wickets down, "
            "30 or fewer legal balls left, current scoring rate ≥11 RPO, and required rate ≥9 RPO.",
            title="Bowling pressure reached",
        )
    else:
        st.info(
            "This chase did not reach the defined bowling-pressure state: exactly 2 wickets down, "
            "30 or fewer legal balls left, current scoring rate ≥11 RPO, and required rate ≥9 RPO.",
            title="Bowling pressure not reached",
        )
    bowling_pressure_metrics = st.columns(4, border=True)
    bowling_pressure_metrics[0].metric("Qualifying legal balls", f"{bowling_pressure_legal:,}")
    bowling_pressure_metrics[1].metric(
        "Runs conceded / over (proxy)",
        fmt_or_na(economy_rate(bowling_pressure_runs, bowling_pressure_legal)),
    )
    bowling_pressure_metrics[2].metric("Credited wickets", f"{bowling_pressure_wickets:,}")
    bowling_pressure_metrics[3].metric(
        "Wickets / 100 legal balls",
        fmt_or_na(wicket_rate(bowling_pressure_wickets, bowling_pressure_legal)),
    )
    if bowling_pressure_current_rates:
        st.caption(
            f"Peak current scoring-rate proxy in the qualifying state: "
            f"{max(bowling_pressure_current_rates):.2f} RPO. Economy and rate values use the supplied raw score fields."
        )
    st.caption(
        "Bowling plan signal: use the containment table to identify low-economy, dot-ball options and the quick-wicket "
        "table to find bowlers with credited dismissals in this exact type of chase. These are historical dataset rates, "
        "so compare the qualifying-ball counts before ranking players."
    )

    st.subheader("Innings scorecards")
    st.caption(
        "Batter runs and balls come from the raw delivery rows. Team totals and bowling run totals use "
        "the supplied runs + extras_2_runs proxy. Fielder names are not present in the source."
    )
    scorecards = [
        (
            row,
            build_innings_scorecard(
                [event for event in match_events if int(event.get("innings") or 0) == int(row.get("innings") or 0)],
                row,
            ),
        )
        for row in innings
    ]
    score_tabs = st.tabs(
        [
            f"Innings {int(row.get('innings') or 0)} · {row.get('batting_team') or 'Team'}"
            for row, _ in scorecards
        ]
    )
    for tab, (row, card) in zip(score_tabs, scorecards):
        with tab:
            team_name = row.get("batting_team") or "Unknown batting team"
            batter_runs = sum(int(item.get("runs") or 0) for item in card["batting"])
            extras_proxy = int(card["runs_proxy"]) - batter_runs
            st.subheader(
                f"{team_name} · {card['runs_proxy']}/{card['wickets']} "
                f"({card['overs']} known-legal overs)"
            )
            summary_metrics = st.columns(4, border=True)
            summary_metrics[0].metric("Total score proxy", f"{card['runs_proxy']:,}")
            summary_metrics[1].metric("Batter runs", f"{batter_runs:,}")
            summary_metrics[2].metric("Extras proxy", f"{extras_proxy:,}")
            summary_metrics[3].metric("Wicket events", f"{card['wickets']:,}")
            if int(row.get("unknown_legality_events") or 0):
                st.caption(
                    f"Overs show {card['legal_balls']} known-legal balls; "
                    f"{int(row.get('unknown_legality_events') or 0)} events have unknown legality."
                )
            st.markdown("**Batting**")
            markdown_table(
                card["batting"],
                [
                    ("batter", "Batter"),
                    ("dismissal", "Dismissal"),
                    ("runs", "R"),
                    ("balls", "B"),
                    ("fours", "4s"),
                    ("sixes", "6s"),
                    ("strike_rate", "SR"),
                ],
            )
            csv_download(
                card["batting"],
                f"Download {team_name} batting card",
                f"match_{match_id}_innings_{row.get('innings')}_batting.csv",
                f"batting_card_{match_id}_{row.get('innings')}",
            )
            st.markdown("**Bowling**")
            markdown_table(
                card["bowling"],
                [
                    ("bowler", "Bowler"),
                    ("overs", "O"),
                    ("legal_balls", "Legal balls"),
                    ("team_runs_proxy", "Team runs proxy"),
                    ("credited_wickets", "Wkts"),
                    ("economy_proxy", "Eco. proxy"),
                    ("dot_balls", "Dots"),
                ],
            )
            st.markdown("**Fall of wickets**")
            if card["fall_of_wickets"]:
                markdown_table(
                    card["fall_of_wickets"],
                    [
                        ("wicket", "Wkt"),
                        ("score_proxy", "Score proxy"),
                        ("over_ball", "Over.ball"),
                        ("batter", "Batter out"),
                        ("dismissal", "Dismissal"),
                        ("bowler_credit", "Bowler credited"),
                    ],
                )
            else:
                st.info("No wicket events are recorded for this innings.")
            if card["missing_dismissed_ids"]:
                st.warning(
                    f"{card['missing_dismissed_ids']} wicket event(s) have no dismissed-player ID in the source; "
                    "the fall-of-wickets entry is retained with an unknown batter label, and affected batting "
                    "statuses are marked unconfirmed.",
                    title="Incomplete wicket attribution",
                )
            csv_download(
                card["fall_of_wickets"],
                f"Download {team_name} fall of wickets",
                f"match_{match_id}_innings_{row.get('innings')}_wickets.csv",
                f"wicket_card_{match_id}_{row.get('innings')}",
            )

    st.divider()
    known = [row for row in chase_log if row.get("state_known") and row.get("rrr") is not None]
    if known:
        fig = go.Figure(
            go.Scatter(
                x=[row["seq"] for row in known],
                y=[row["rrr"] for row in known],
                mode="lines",
                name="Required run rate",
                line=dict(color=BLUE, width=2.5),
                customdata=[[row["balls_remaining"], row["wickets_lost"], row["score_before"]] for row in known],
                hovertemplate="Delivery %{x}<br>RRR %{y:.2f}<br>Balls left %{customdata[0]}<br>Wickets down %{customdata[1]}<br>Score before %{customdata[2]}<extra></extra>",
            )
        )
        pressure_rows = [row for row in known if row.get("pressure")]
        fig.add_trace(
            go.Scatter(
                x=[row["seq"] for row in pressure_rows],
                y=[row["rrr"] for row in pressure_rows],
                mode="markers",
                name="Batting pressure",
                marker=dict(color=PRESSURE, size=9, symbol="diamond"),
                hovertemplate="Batting-pressure delivery %{x}<br>RRR %{y:.2f}<extra></extra>",
            )
        )
        bowling_rows = [row for row in known if row.get("bowling_pressure")]
        if bowling_rows:
            fig.add_trace(
                go.Scatter(
                    x=[row["seq"] for row in bowling_rows],
                    y=[row["rrr"] for row in bowling_rows],
                    mode="markers",
                    name="Bowling-pressure status",
                    marker=dict(color=GOLD, size=10, symbol="triangle-up", line=dict(color="#FFFFFF", width=1)),
                    customdata=[[row.get("current_rpo"), row.get("wickets_lost")] for row in bowling_rows],
                    hovertemplate="Bowling-pressure delivery %{x}<br>Required rate %{y:.2f}<br>Current rate %{customdata[0]:.2f}<br>Wickets down %{customdata[1]}<extra></extra>",
                )
            )
        fig.add_hline(y=15, line_dash="dash", line_color=PRESSURE, annotation_text="Batting-pressure RRR 15")
        fig.add_hline(y=9, line_dash="dot", line_color=GOLD, annotation_text="Bowling-pressure RRR 9")
        fig.update_layout(xaxis_title="Delivery event sequence", yaxis_title="Required run rate")
        chart(fig, "Required run rate through the chase with batting- and bowling-pressure balls highlighted", height=380)
    else:
        st.warning("No known RRR states are available for this chase.", title="State data unavailable")

    st.subheader("Chase delivery log")
    st.caption("Score, wickets, balls remaining, RRR, and pressure describe the moment before each delivery.")
    log_rows = []
    for event in chase_log:
        if event.get("is_wicket"):
            outcome = f"Wicket · {event.get('dismissal_type') or 'type unknown'}"
        else:
            runs = int(event.get("total_runs_proxy") or 0)
            outcome = f"{runs} raw runs"
            if event.get("extras_type") and event.get("extras_type") not in {"None", ""}:
                outcome += f" · {event['extras_type']}"
        log_rows.append(
            {
                "seq": event["seq"],
                "over": f"{event.get('over_no')}.{event.get('over_ball_num')}",
                "batter": event.get("striker_name"),
                "bowler": event.get("bowler_name"),
                "score_before": event.get("score_before"),
                "target": event.get("target"),
                "balls_remaining": event.get("balls_remaining"),
                "wickets_lost": event.get("wickets_lost"),
                "rrr": event.get("rrr"),
                "current_rpo": event.get("current_rpo"),
                "outcome": outcome,
                "batting_pressure": "Yes" if event.get("pressure") else "No",
                "bowling_pressure": "Yes" if event.get("bowling_pressure") else "No",
                "state": "Known" if event.get("state_known") else "Unknown",
            }
        )
    markdown_table(
        log_rows[:50],
        [
            ("seq", "Seq."),
            ("over", "Over.ball"),
            ("batter", "Batter"),
            ("bowler", "Bowler"),
            ("score_before", "Score before"),
            ("target", "Target"),
            ("balls_remaining", "Balls left"),
            ("wickets_lost", "Wickets down"),
            ("rrr", "RRR"),
            ("current_rpo", "Current RPO"),
            ("outcome", "Outcome"),
            ("batting_pressure", "Batting pressure"),
            ("bowling_pressure", "Bowling pressure"),
            ("state", "State"),
        ],
    )
    csv_download(log_rows, "Download full chase delivery log", f"chase_{match_id}_deliveries.csv", f"chase_log_{match_id}")

    pressure_matches = [row for row in matches if int(row.get("pressure_legal_balls") or 0) > 0]
    with st.container(border=True):
        st.markdown("**Target versus chase total in pressure matches**")
        fig = go.Figure(
            go.Scatter(
                x=[row.get("target") for row in pressure_matches],
                y=[row.get("chase_runs_proxy") for row in pressure_matches],
                mode="markers",
                marker=dict(
                    color=[ORDINARY if row.get("chase_success") == 1 else PRESSURE for row in pressure_matches],
                    size=9,
                    opacity=0.72,
                ),
                text=[f"{row.get('home_team')} vs {row.get('away_team')} · {row.get('match_id')}" for row in pressure_matches],
                customdata=[[row.get("result"), row.get("pressure_legal_balls")] for row in pressure_matches],
                hovertemplate="%{text}<br>Target %{x}<br>Chase total proxy %{y}<br>%{customdata[0]}<br>Pressure balls %{customdata[1]}<extra></extra>",
            )
        )
        maximum = max(
            [int(row.get("target") or 0) for row in pressure_matches]
            + [int(row.get("chase_runs_proxy") or 0) for row in pressure_matches]
            + [1]
        )
        fig.add_trace(
            go.Scatter(
                x=[0, maximum],
                y=[0, maximum],
                mode="lines",
                name="Target line",
                line=dict(color="#94A3B8", dash="dash"),
                hoverinfo="skip",
            )
        )
        fig.update_layout(xaxis_title="Target", yaxis_title="Chase raw score proxy")
        chart(fig, "Target and raw chase score proxies for matches with batting pressure", height=360)
