from __future__ import annotations

import importlib
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from lib.db import database_ready
import lib.queries as queries
import lib.pressure_reports as pressure_reports
from lib.metrics import economy_rate, share, strike_rate
from lib.ui import chart, csv_download, markdown_table, page_header

# Refresh shared data modules so updated report helpers are picked up after edits.
queries = importlib.reload(queries)
pressure_reports = importlib.reload(pressure_reports)

st.set_page_config(
    page_title="Cricket Stats & Pressure",
    page_icon=":material/sports_cricket:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

PALETTE = [
    "#4F7DF3",
    "#F27A63",
    "#25A99A",
    "#F0B84B",
    "#9573D8",
    "#6FBF73",
    "#E477A8",
    "#F28E45",
    "#49A9D8",
    "#A5B83F",
]
MIN_SAMPLE_BALLS = 30


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_name(row: dict[str, Any]) -> str:
    return str(row.get("player") or row.get("source_player") or "Unknown")


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None or value == "":
        return "–"
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}" if isinstance(value, float) else f"{value:,}"
    return str(value)


def _prepare_batters(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        balls = _int(row.get("balls"))
        runs = _int(row.get("runs"))
        dismissals = _int(row.get("dismissals"))
        boundaries = _int(row.get("fours")) + _int(row.get("sixes"))
        row.update(
            batter=_safe_name(row),
            strike_rate=strike_rate(runs, balls),
            average=round(runs / dismissals, 2) if dismissals >= 3 else None,
            boundary_events=boundaries,
            boundaries_per_100=share(boundaries, balls),
            dot_share=share(_int(row.get("dots")), balls),
            powerplay_strike_rate=strike_rate(row.get("powerplay_runs", 0), row.get("powerplay_balls", 0)),
            middle_strike_rate=strike_rate(row.get("middle_runs", 0), row.get("middle_balls", 0)),
            death_strike_rate=strike_rate(row.get("death_runs", 0), row.get("death_balls", 0)),
            pressure_strike_rate=strike_rate(row.get("pressure_runs", 0), row.get("pressure_balls", 0)),
            sample_status="Eligible sample" if balls >= MIN_SAMPLE_BALLS else "Review sample",
        )
        prepared.append(row)
    return prepared


def _prepare_bowlers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        balls = _int(row.get("legal_balls"))
        runs = _int(row.get("runs_proxy"))
        wickets = _int(row.get("credited_wickets"))
        pressure_balls = _int(row.get("pressure_legal_balls"))
        pressure_runs = _int(row.get("pressure_runs_proxy"))
        pressure_wickets = _int(row.get("pressure_credited_wickets"))
        row.update(
            bowler=_safe_name(row),
            overs=round(balls / 6, 2),
            economy=economy_rate(runs, balls),
            balls_per_wicket=round(balls / wickets, 2) if wickets else None,
            wicket_rate_per_6=round(wickets * 6 / balls, 3) if balls else None,
            dot_share=share(_int(row.get("dots")), balls),
            boundaries_per_100=share(_int(row.get("boundary_events")), balls),
            pressure_economy=economy_rate(pressure_runs, pressure_balls),
            pressure_wicket_rate_per_6=round(pressure_wickets * 6 / pressure_balls, 3) if pressure_balls else None,
            pressure_dot_share=share(_int(row.get("pressure_dots")), pressure_balls),
            ordinary_chase_economy=economy_rate(
                _int(row.get("ordinary_chase_runs_proxy")),
                _int(row.get("ordinary_chase_legal_balls")),
            ),
            sample_status="Eligible sample" if balls >= MIN_SAMPLE_BALLS else "Review sample",
        )
        prepared.append(row)
    return prepared


def _ranked_bar(rows: list[dict[str, Any]], label_key: str, value_key: str, title: str, axis_title: str, alt: str) -> None:
    valid = [row for row in rows if row.get(value_key) is not None]
    if not valid:
        st.info("There are not enough values to draw this chart.")
        return
    fig = go.Figure(
        go.Bar(
            x=[row[value_key] for row in valid],
            y=[row[label_key] for row in valid],
            orientation="h",
            marker=dict(
                color=[PALETTE[i % len(PALETTE)] for i in range(len(valid))],
                line=dict(color="#FFFFFF", width=1),
            ),
            text=[_fmt(row[value_key], 1) for row in valid],
            textposition="outside",
            cliponaxis=False,
            hovertemplate=f"%{{y}}<br>{axis_title}: %{{x:.2f}}<extra></extra>",
        )
    )
    fig.update_layout(
        title=dict(text=title, x=0.02, xanchor="left"),
        xaxis_title=axis_title,
        yaxis=dict(categoryorder="array", categoryarray=[row[label_key] for row in valid][::-1]),
        showlegend=False,
        bargap=0.28,
    )
    chart(fig, alt, height=max(320, 30 * len(valid) + 80))


def _search_rows(rows: list[dict[str, Any]], query: str, name_key: str) -> list[dict[str, Any]]:
    needle = query.strip().casefold()
    if not needle:
        return rows
    return [
        row for row in rows
        if needle in str(row.get(name_key, "")).casefold()
        or needle in str(row.get("player_id", ""))
    ]


def render_batting(rows: list[dict[str, Any]]) -> None:
    if not rows:
        st.warning("No batting records are available in the processed source.")
        return

    total_runs = sum(_int(row.get("runs")) for row in rows)
    total_balls = sum(_int(row.get("balls")) for row in rows)
    active = sum(_int(row.get("matches")) > 0 for row in rows)
    mean_sr = strike_rate(total_runs, total_balls)

    st.subheader("Batting overview")
    st.caption("All available formats and innings in the processed data. Rates include their full player samples.")
    metrics = st.columns(4)
    metrics[0].metric("Batters in data", f"{active:,}")
    metrics[1].metric("Runs", f"{total_runs:,}")
    metrics[2].metric("Balls faced", f"{total_balls:,}")
    metrics[3].metric("Overall strike rate", _fmt(mean_sr, 1))

    run_leaders = sorted(rows, key=lambda row: (-_int(row.get("runs")), _safe_name(row)))[:10]
    phase_leaders = run_leaders[:8]

    top_left, top_right = st.columns(2)
    with top_left:
        _ranked_bar(run_leaders, "batter", "runs", "Runs scored · top 10", "Runs", "Top 10 batters by raw runs")
    with top_right:
        st.markdown("**Where the runs came from**")
        st.caption("Powerplay, middle overs, and death overs · top 8 run scorers")
        fig = go.Figure()
        phase_specs = [
            ("Powerplay", "powerplay_runs", PALETTE[0]),
            ("Middle overs", "middle_runs", PALETTE[2]),
            ("Death overs", "death_runs", PALETTE[1]),
        ]
        for name, key, color in phase_specs:
            fig.add_trace(
                go.Bar(
                    name=name,
                    x=[_int(row.get(key)) for row in phase_leaders],
                    y=[row["batter"] for row in phase_leaders],
                    orientation="h",
                    marker_color=color,
                    hovertemplate=f"%{{y}}<br>{name}: %{{x:,}} runs<extra></extra>",
                )
            )
        fig.update_layout(
            barmode="stack",
            xaxis_title="Runs",
            yaxis_title="",
            yaxis=dict(categoryorder="array", categoryarray=[row["batter"] for row in phase_leaders][::-1]),
            legend_title_text="Innings phase",
            bargap=0.24,
        )
        chart(fig, "Runs by powerplay, middle overs, and death overs for the top eight batters", height=380)

    st.subheader("Player records")
    st.caption("Averages are reported only after three dismissals. Players under 30 balls are marked as review samples.")
    with st.expander("Open complete batting tables", expanded=False):
        search = st.text_input("Find batter by name or player ID", key="batting_player_search", placeholder="e.g. Virat Kohli")
        visible = _search_rows(rows, search, "batter")
        st.caption(f"Showing {len(visible):,} of {len(rows):,} batters. Download includes every player.")
        csv_download(rows, "Download all batting stats", "all_batting_stats.csv", "all_batting_csv")
        st.markdown("**Batting totals and outcomes**")
        markdown_table(
            visible,
            [
                ("player_id", "ID"), ("batter", "Batter"), ("matches", "Matches"),
                ("innings", "Innings"), ("runs", "Runs"), ("balls", "Balls"),
                ("strike_rate", "Strike rate", lambda value: _fmt(value, 2)),
                ("dismissals", "Dismissals"), ("average", "Average", lambda value: "Not reported" if value is None else _fmt(value, 2)),
                ("fours", "4s"), ("sixes", "6s"), ("boundary_events", "Boundaries"),
                ("boundaries_per_100", "Boundaries / 100 balls", lambda value: _fmt(value, 2)),
                ("dots", "Dot balls"), ("dot_share", "Dot %", lambda value: _fmt(value, 2)),
                ("sample_status", "Sample"),
            ],
            max_height=450,
        )
        st.markdown("**Phase and pressure splits**")
        markdown_table(
            visible,
            [
                ("player_id", "ID"), ("batter", "Batter"),
                ("powerplay_runs", "Powerplay runs"), ("powerplay_balls", "Powerplay balls"),
                ("powerplay_strike_rate", "Powerplay SR", lambda value: _fmt(value, 2)),
                ("middle_runs", "Middle-over runs"), ("middle_balls", "Middle-over balls"),
                ("middle_strike_rate", "Middle-over SR", lambda value: _fmt(value, 2)),
                ("death_runs", "Death-over runs"), ("death_balls", "Death-over balls"),
                ("death_strike_rate", "Death-over SR", lambda value: _fmt(value, 2)),
                ("pressure_runs", "Pressure runs"), ("pressure_balls", "Pressure balls"),
                ("pressure_strike_rate", "Pressure SR", lambda value: _fmt(value, 2)),
                ("pressure_dismissals", "Pressure dismissals"), ("pressure_matches", "Pressure matches"),
            ],
            max_height=450,
        )


def render_bowling(rows: list[dict[str, Any]]) -> None:
    if not rows:
        st.warning("No bowling records are available in the processed source.")
        return

    total_runs = sum(_int(row.get("runs_proxy")) for row in rows)
    total_balls = sum(_int(row.get("legal_balls")) for row in rows)
    total_wickets = sum(_int(row.get("credited_wickets")) for row in rows)
    st.subheader("Bowling overview")
    st.caption("All available formats and innings. Economy and wicket frequency are shown with legal-ball samples.")
    metrics = st.columns(4)
    metrics[0].metric("Bowlers in data", f"{len(rows):,}")
    metrics[1].metric("Bowler runs", f"{total_runs:,}", help="Uses the processed source's bowler-run convention.")
    metrics[2].metric("Legal balls", f"{total_balls:,}")
    metrics[3].metric("Credited wickets", f"{total_wickets:,}")

    wicket_leaders = sorted(rows, key=lambda row: (-_int(row.get("credited_wickets")), _safe_name(row)))[:10]
    qualified = [row for row in rows if _int(row.get("legal_balls")) >= MIN_SAMPLE_BALLS]
    st.subheader("Wickets and control")
    top_left, top_right = st.columns(2)
    with top_left:
        _ranked_bar(wicket_leaders, "bowler", "credited_wickets", "Credited wickets · top 10", "Wickets", "Top 10 bowlers by credited wickets")
    comparison_rows = [
        row for row in qualified
        if _int(row.get("credited_wickets")) >= 3
        and row.get("economy") is not None
        and row.get("wicket_rate_per_6") is not None
    ]
    with top_right:
        st.markdown("**Economy vs wicket rate**")
        st.caption("Each dot is a bowler · larger dots mean more legal balls")
        if comparison_rows:
            fig = go.Figure(
                go.Scatter(
                    x=[row["economy"] for row in comparison_rows],
                    y=[row["wicket_rate_per_6"] for row in comparison_rows],
                    mode="markers",
                    marker=dict(
                        size=[max(9, min(28, 7 + _int(row.get("legal_balls")) ** 0.5 / 3)) for row in comparison_rows],
                        color=[row["economy"] for row in comparison_rows],
                        colorscale="Turbo",
                        reversescale=True,
                        showscale=True,
                        colorbar=dict(title="Economy", thickness=12),
                        opacity=0.82,
                        line=dict(color="#FFFFFF", width=1.1),
                    ),
                    text=[row["bowler"] for row in comparison_rows],
                    customdata=[[row["legal_balls"], row["credited_wickets"], row["dot_share"]] for row in comparison_rows],
                    hovertemplate=(
                        "%{text}<br>Economy %{x:.2f}<br>Wickets / 6 %{y:.3f}"
                        "<br>Legal balls %{customdata[0]}<br>Credited wickets %{customdata[1]}"
                        "<br>Dot share %{customdata[2]:.1f}%<extra></extra>"
                    ),
                )
            )
            fig.update_layout(xaxis_title="Economy · lower is tighter", yaxis_title="Credited wickets / 6 balls")
            chart(fig, "Economy compared with credited wicket rate among bowlers with at least 30 legal balls and three wickets", height=380)
        else:
            st.info("No bowlers pass both minimum sample guides for this comparison.")

    st.subheader("Player records")
    st.caption("The full record is split into performance totals and pressure or phase detail for easier reading.")
    with st.expander("Open complete bowling tables", expanded=False):
        search = st.text_input("Find bowler by name or player ID", key="bowling_player_search", placeholder="e.g. Jasprit Bumrah")
        visible = _search_rows(rows, search, "bowler")
        st.caption(f"Showing {len(visible):,} of {len(rows):,} bowlers. Download includes every player.")
        csv_download(rows, "Download all bowling stats", "all_bowling_stats.csv", "all_bowling_csv")
        st.markdown("**Bowling totals and discipline**")
        markdown_table(
            visible,
            [
                ("player_id", "ID"), ("bowler", "Bowler"), ("matches", "Matches"),
                ("innings", "Innings"), ("event_rows", "Deliveries"), ("legal_balls", "Legal balls"),
                ("overs", "Overs", lambda value: _fmt(value, 2)), ("runs_proxy", "Bowler runs"),
                ("economy", "Economy", lambda value: _fmt(value, 2)), ("wicket_events", "Wicket events"),
                ("credited_wickets", "Credited wickets"),
                ("balls_per_wicket", "Balls / wicket", lambda value: _fmt(value, 2)),
                ("wicket_rate_per_6", "Wickets / 6 balls", lambda value: _fmt(value, 3)),
                ("dots", "Dot balls"), ("dot_share", "Dot %", lambda value: _fmt(value, 2)),
                ("boundary_events", "Boundaries conceded"),
                ("boundaries_per_100", "Boundaries / 100 balls", lambda value: _fmt(value, 2)),
                ("wides", "Wides"), ("no_balls", "No-balls"), ("sample_status", "Sample"),
            ],
            max_height=450,
        )
        st.markdown("**Phase and pressure splits**")
        markdown_table(
            visible,
            [
                ("player_id", "ID"), ("bowler", "Bowler"),
                ("pace_events", "Pace events"), ("spin_events", "Spin events"),
                ("pressure_runs_proxy", "Pressure runs"), ("pressure_legal_balls", "Pressure legal balls"),
                ("pressure_economy", "Pressure economy", lambda value: _fmt(value, 2)),
                ("pressure_credited_wickets", "Pressure wickets"),
                ("pressure_wicket_rate_per_6", "Pressure wickets / 6", lambda value: _fmt(value, 3)),
                ("pressure_dots", "Pressure dots"),
                ("pressure_dot_share", "Pressure dot %", lambda value: _fmt(value, 2)),
                ("pressure_matches", "Pressure matches"),
                ("ordinary_chase_runs_proxy", "Ordinary chase runs"),
                ("ordinary_chase_legal_balls", "Ordinary chase balls"),
                ("ordinary_chase_economy", "Ordinary chase economy", lambda value: _fmt(value, 2)),
            ],
            max_height=450,
        )


def render_pressure(report: dict[str, Any], clutch: dict[str, Any]) -> None:
    if not report:
        st.warning("Pressure report is not available. Rebuild the raw-data report to populate this tab.")
        return

    state_rows = report.get("state_table", [])
    batting_state = next((row for row in state_rows if row.get("state") == "Batting pressure"), {})
    bowling_state = next((row for row in state_rows if row.get("state") == "Bowling pressure"), {})
    clutch_cohort = clutch.get("cohort", {}) if clutch else {}
    audit = clutch.get("entry_timing_audit", {}) if clutch else {}
    entry_rows = audit.get("summary", [])

    metrics = st.columns(4, border=True)
    metrics[0].metric("Indian clutch anchor chases", f"{_int(clutch_cohort.get('anchor_chases')):,}")
    metrics[1].metric("Batting-pressure deliveries", f"{_int(batting_state.get('delivery_rows')):,}")
    metrics[2].metric("Bowling-pressure legal balls", f"{_int(bowling_state.get('legal_balls')):,}")
    metrics[3].metric("Entry audit match rate", f"{_int(audit.get('reference_rows_matching'))}/{_int(audit.get('reference_rows_compared'))}")

    st.info(
        "The pressure tab combines two distinct raw-data views: the Indian clutch window (40 T20 anchor chases "
        "for the player result) and the all-venue T20 chase pressure states. Counts are kept separate so their "
        "different conditions are not blended."
    )

    with st.container(border=True):
        st.markdown("**Latest Indian clutch-window result · top 20**")
        st.caption(
            clutch.get("definition", {}).get("scenario", "Raw ball-by-ball data joined to match and competition records.")
            + " Ranking uses the raw-data composite: 50% adjusted strike-rate percentile, 30% adjusted-average percentile, and 20% boundary-share percentile. The score is relative to this cohort; displayed figures are recomputed from the raw source."
        )
        top_twenty = clutch.get("computed_top_twenty", [])
        if top_twenty:
            score_rows = top_twenty[:10]
            _ranked_bar(score_rows, "player", "composite_score", "Top 10 composite scores", "Relative score", "Top ten Indian clutch-window composite scores")
            csv_download(top_twenty, "Download clutch-window top 20", "indian_clutch_window_top_20.csv", "clutch_top20_csv")
            markdown_table(
                top_twenty,
                [
                    ("rank", "Rank"), ("player", "Batter"), ("player_id", "Player ID"),
                    ("innings", "Innings"), ("balls", "Balls"), ("runs", "Runs"),
                    ("strike_rate", "Raw SR", lambda value: _fmt(value, 1)),
                    ("average", "Raw average", lambda value: "Not reported" if value is None or value == "Not reported" else _fmt(value, 1)),
                    ("adjusted_strike_rate", "Adjusted SR", lambda value: _fmt(value, 1)),
                    ("adjusted_average", "Adjusted average", lambda value: "Not reported" if value is None or value == "Not reported" else _fmt(value, 1)),
                    ("boundary_share", "Boundaries / 100 balls", lambda value: _fmt(value, 1)),
                    ("dots", "Dot balls"), ("composite_score", "Relative score", lambda value: _fmt(value, 2)),
                    ("ranking_eligible", "Eligible"),
                ],
                max_height=600,
            )
        else:
            st.warning("The raw clutch-window top-20 result is missing from the current report.")

    entry_audit_col, entry_notes_col = st.columns([1.25, 1])
    with entry_audit_col:
        with st.container(border=True):
            st.markdown("**Raw entry timing audit · requested top 10**")
            if entry_rows:
                audit_chart_rows = [
                    {**row, "label": f"{row.get('rank')}. {row.get('player')}"}
                    for row in entry_rows
                ]
                fig = go.Figure(
                    go.Bar(
                        x=[row.get("raw_median_entry_over") for row in audit_chart_rows],
                        y=[row["label"] for row in audit_chart_rows],
                        orientation="h",
                        marker=dict(
                            color=[PALETTE[1] if row.get("status") == "DIFFERS" else PALETTE[2] for row in audit_chart_rows],
                            line=dict(color="#FFFFFF", width=1),
                        ),
                        text=[_fmt(row.get("raw_median_entry_over"), 1) for row in audit_chart_rows],
                        textposition="outside",
                        cliponaxis=False,
                        customdata=[[row.get("raw_entry_overs"), row.get("raw_came_before_anchor"), row.get("status")] for row in audit_chart_rows],
                        hovertemplate=("%{y}<br>Raw entry overs: %{customdata[0]}<br>Median: %{x:.1f}"
                                       "<br>Before anchor: %{customdata[1]}<br>Reference: %{customdata[2]}<extra></extra>"),
                    )
                )
                fig.update_layout(
                    xaxis_title="Median entry over",
                    yaxis=dict(categoryorder="array", categoryarray=[row["label"] for row in audit_chart_rows][::-1]),
                    showlegend=False,
                )
                chart(fig, "Raw median entry over for the requested clutch-window batter list; coral marks a mismatch against the supplied row", height=440)
                markdown_table(
                    entry_rows,
                    [
                        ("rank", "Rank"), ("player", "Batter"), ("raw_entry_overs", "Raw entry overs"),
                        ("raw_median_entry_over", "Raw median"), ("raw_came_before_anchor", "Before anchor"),
                        ("status", "Reference check"),
                    ],
                    max_height=420,
                )
            else:
                st.warning("The entry-timing raw audit is missing from the current report.")
    with entry_notes_col:
        with st.container(border=True):
            st.markdown("**Cohort and raw-source checks**")
            st.metric(
                "Entry timing scope",
                f"{_int(audit.get('anchor_chases'))} chases",
                f"{_int(audit.get('format_anchor_chases', {}).get('T20'))} T20 · {_int(audit.get('format_anchor_chases', {}).get('T20I'))} T20I",
            )
            st.caption("Entry timing is independently rebuilt from ball-by-ball, match, and competition source files.")
            mismatches = [row for row in entry_rows if not row.get("matches_reference")]
            for row in mismatches:
                st.warning(
                    f"{row.get('player')}: raw entries {row.get('raw_entry_overs')} "
                    f"({row.get('raw_innings')} innings; median {row.get('raw_median_entry_over')}) "
                    f"do not match the supplied row {row.get('reference_entry_overs')} "
                    f"({row.get('reference_innings')} innings; median {row.get('reference_median_entry_over')})."
                )

    with st.container(border=True):
        st.markdown("**Pressure-state coverage · all-venue T20 chases**")
        if state_rows:
            names = [row.get("state", "") for row in state_rows]
            counts = [_int(row.get("delivery_rows")) for row in state_rows]
            fig = go.Figure(
                go.Bar(
                    x=names,
                    y=counts,
                    marker_color=[PALETTE[i % len(PALETTE)] for i in range(len(names))],
                    text=[f"{count:,}" for count in counts],
                    textposition="outside",
                    cliponaxis=False,
                    customdata=[[
                        _int(row.get("matches")),
                        _int(row.get("decided_chases")),
                        _int(row.get("legal_balls")),
                        _int(row.get("players")),
                    ] for row in state_rows],
                    hovertemplate=("%{x}<br>Delivery rows %{y:,}<br>Matches %{customdata[0]}"
                                   "<br>Decided chases %{customdata[1]}<br>Legal balls %{customdata[2]}"
                                   "<br>Players %{customdata[3]}<extra></extra>"),
                )
            )
            fig.update_layout(xaxis_title="State", yaxis_title="Delivery rows", showlegend=False)
            chart(fig, "Delivery counts for the four raw pressure and ordinary chase states", height=390)
            markdown_table(
                state_rows,
                [("state", "State"), ("delivery_rows", "Delivery rows"), ("matches", "Matches"),
                 ("decided_chases", "Decided chases"), ("legal_balls", "Legal balls"),
                 ("players", "Players"), ("reporting_status", "Reporting status")],
            )

        st.caption(
            "Batting pressure: T20 second innings, 1–30 legal balls left, at least 3 wickets down, RRR ≥15. "
            "Bowling pressure: T20 second innings, 1–30 legal balls left, 2 or fewer wickets down, current rate ≥11, RRR ≥9."
        )

    pressure_validation = report.get("validation", {})
    raw_counts = pressure_validation.get("raw_pressure_flag_totals", {})
    supplied = pressure_validation.get("supplied_pressure_flag_reference", {})
    if raw_counts and supplied and raw_counts != supplied:
        st.warning(
            f"Pressure-count reference remains unreconciled: raw recount is "
            f"{_int(raw_counts.get('batting_pressure')):,} batting + {_int(raw_counts.get('bowling_pressure')):,} bowling "
            f"= {_int(raw_counts.get('both_pressure_flags')):,} flags; the supplied reference is "
            f"{_int(supplied.get('both_pressure_flags')):,}. This dashboard shows the raw recount and labels the difference."
        )

    pressure_batters = [
        row for row in report.get("batter_table", [])
        if row.get("state") == "Batting pressure" and row.get("ranking_eligible")
    ]
    pressure_batters.sort(key=lambda row: (row.get("rank") is None, row.get("rank") or 9999))
    bowling_rows = [
        row for row in report.get("bowler_table", [])
        if row.get("state") == "Bowling pressure"
    ]

    with st.container(border=True):
        st.markdown("**Separate T20 batting-pressure player figures**")
        st.caption("All-venue T20 chase state; composite weights: adjusted strike rate 50%, adjusted average 30%, boundary share 20%.")
        if pressure_batters:
            pressure_top = pressure_batters[:10]
            markdown_table(
                pressure_top,
                [("rank", "Rank"), ("player", "Batter"), ("player_id", "Player ID"),
                 ("innings", "Innings"), ("sample_balls", "Balls"), ("runs", "Runs"),
                 ("strike_rate", "Raw SR", lambda value: _fmt(value, 1)),
                 ("adjusted_strike_rate", "Adjusted SR", lambda value: _fmt(value, 1)),
                 ("dismissals", "Dismissals"),
                 ("average", "Raw average", lambda value: "Not reported" if value is None or value == "Not reported" else _fmt(value, 1)),
                 ("boundary_share", "Boundary share", lambda value: _fmt(value, 1)),
                 ("recent_innings", "Recent innings"), ("composite_score", "Relative score", lambda value: _fmt(value, 1))],
            )
        else:
            st.info("No batting-pressure player rows are eligible for display.")

    with st.container(border=True):
        st.markdown("**Bowling-pressure observations · exploratory sample**")
        st.caption(
            f"{_int(bowling_state.get('legal_balls'))} qualifying legal balls across "
            f"{_int(bowling_state.get('matches'))} matches and {_int(bowling_state.get('decided_chases'))} decided chases. "
            "The cohort is below the 20-decided-chase reporting minimum, so these are observations, not a ranking."
        )
        if bowling_rows:
            markdown_table(
                bowling_rows,
                [("player", "Bowler"), ("player_id", "Player ID"), ("matches", "Matches"),
                 ("sample_balls", "Legal balls"), ("runs", "Bowler runs"),
                 ("economy", "Economy", lambda value: _fmt(value, 2)),
                 ("credited_wickets", "Credited wickets"), ("dots", "Dot balls"),
                 ("dot_share", "Dot %", lambda value: _fmt(value, 1)),
                 ("ranking_status", "Status")],
            )
        else:
            st.info("No bowling-pressure observations matched the confirmed state conditions.")


if not database_ready():
    st.title("Cricket stats and pressure")
    st.error("Processed data is not built yet. Build the local data from the project folder first.")
    st.code("python build/build_data.py", language="powershell")
    st.stop()

batting_rows = _prepare_batters(queries.batter_stats({}))
bowling_rows = _prepare_bowlers(queries.bowler_stats({}))
pressure_data = pressure_reports.pressure_report()
clutch_data = pressure_reports.clutch_batting_report()

page_header(
    "Cricket analytics",
    "Batting, bowling, and pressure performance from the available raw-data reports.",
)

batting_tab, bowling_tab, pressure_tab = st.tabs(
    ["Batting stats", "Bowling stats", "Pressure stats"],
    on_change="rerun",
    key="main_dashboard_tabs",
)

if batting_tab.open:
    with batting_tab:
        render_batting(batting_rows)

if bowling_tab.open:
    with bowling_tab:
        render_bowling(bowling_rows)

if pressure_tab.open:
    with pressure_tab:
        render_pressure(pressure_data, clutch_data)
