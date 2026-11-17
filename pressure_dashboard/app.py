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
    qualified = [row for row in rows if _int(row.get("balls")) >= MIN_SAMPLE_BALLS]
    volume_leader = max(rows, key=lambda row: _int(row.get("runs")))
    pace_leader = max(qualified, key=lambda row: float(row.get("strike_rate") or 0), default=None)
    average_candidates = [row for row in qualified if row.get("average") is not None]
    average_leader = max(average_candidates, key=lambda row: float(row.get("average") or 0), default=None)

    st.subheader("Batting leadership view")
    st.caption("Read the innings through three lenses: run volume, scoring pace, and where the runs arrive. All available formats and innings in the processed data are included.")
    metrics = st.columns(4)
    metrics[0].metric("Batters in data", f"{active:,}")
    metrics[1].metric("Runs", f"{total_runs:,}")
    metrics[2].metric("Balls faced", f"{total_balls:,}")
    metrics[3].metric("Overall strike rate", _fmt(mean_sr, 1))

    st.markdown("#### Leadership read")
    readout = st.columns(3)
    with readout[0].container(border=True):
        st.caption("Most runs in the full sample")
        st.markdown(f"### {_safe_name(volume_leader)}")
        st.write(f"{_int(volume_leader.get('runs')):,} runs · {_int(volume_leader.get('balls')):,} balls")
    with readout[1].container(border=True):
        st.caption("Fastest scorer · 30+ balls")
        if pace_leader:
            st.markdown(f"### {_safe_name(pace_leader)}")
            st.write(f"{_fmt(pace_leader.get('strike_rate'), 1)} strike rate · {_int(pace_leader.get('balls')):,} balls")
        else:
            st.write("No player has reached the 30-ball guide yet.")
    with readout[2].container(border=True):
        st.caption("Highest reported average · 30+ balls, 3+ dismissals")
        if average_leader:
            st.markdown(f"### {_safe_name(average_leader)}")
            st.write(f"{_fmt(average_leader.get('average'), 1)} runs per dismissal · {_int(average_leader.get('dismissals'))} dismissals")
        else:
            st.write("No player meets the average reporting guide yet.")

    run_leaders = sorted(rows, key=lambda row: (-_int(row.get("runs")), _safe_name(row)))[:10]
    phase_leaders = run_leaders[:8]

    st.markdown("#### Where batting impact comes from")
    st.caption("The first chart shows who supplies the runs; the second shows each leading scorer’s run mix by innings phase.")
    top_left, top_right = st.columns(2, gap="large")
    with top_left:
        _ranked_bar(run_leaders, "batter", "runs", "Run volume · top 10", "Runs", "Top 10 batters by raw runs")
    with top_right:
        st.markdown("**Run contribution by phase**")
        st.caption("Share of each batter’s recorded phase runs · top 8 run scorers")
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
                    customdata=[
                        [
                            _int(row.get(key)),
                            sum(_int(row.get(field)) for _, field, _ in phase_specs),
                            100 * _int(row.get(key)) / max(1, sum(_int(row.get(field)) for _, field, _ in phase_specs)),
                        ]
                        for row in phase_leaders
                    ],
                    hovertemplate=f"%{{y}}<br>{name}: %{{customdata[0]:,}} runs · %{{customdata[2]:.1f}}% of shown phases<extra></extra>",
                )
            )
        fig.update_layout(
            barmode="stack",
            barnorm="percent",
            xaxis_title="Phase run share (%)",
            yaxis_title="",
            xaxis=dict(range=[0, 100], ticksuffix="%"),
            yaxis=dict(categoryorder="array", categoryarray=[row["batter"] for row in phase_leaders][::-1]),
            legend_title_text="Innings phase",
            bargap=0.24,
        )
        chart(fig, "Share of powerplay, middle-over, and death-over runs for the top eight batters by total runs", height=390)

    st.markdown("#### Pace and scoring control")
    chart_left, chart_right = st.columns(2, gap="large")
    if qualified:
        pace_rows = sorted(qualified, key=lambda row: (-_int(row.get("runs")), _safe_name(row)))[:24]
        ball_values = sorted(_int(row.get("balls")) for row in pace_rows)
        sr_values = sorted(float(row.get("strike_rate") or 0) for row in pace_rows)
        median_balls = (ball_values[(len(ball_values) - 1) // 2] + ball_values[len(ball_values) // 2]) / 2
        median_sr = (sr_values[(len(sr_values) - 1) // 2] + sr_values[len(sr_values) // 2]) / 2
        with chart_left:
            st.markdown("**Scoring pace vs innings volume**")
            st.caption("Each bubble is a batter with 30+ balls; larger bubbles represent more runs. Hover for raw sample size.")
            pace_fig = go.Figure(go.Scatter(
                x=[_int(row.get("balls")) for row in pace_rows],
                y=[row.get("strike_rate") for row in pace_rows],
                mode="markers+text",
                text=[_safe_name(row) if i < 7 else "" for i, row in enumerate(pace_rows)],
                textposition="top center",
                marker=dict(
                    size=[max(10, min(34, 8 + _int(row.get("runs")) ** 0.5)) for row in pace_rows],
                    color=[PALETTE[i % len(PALETTE)] for i in range(len(pace_rows))],
                    opacity=0.82,
                    line=dict(color="#FFFFFF", width=1.2),
                ),
                customdata=[[_safe_name(row), _int(row.get("runs")), _int(row.get("dismissals")), row.get("average")] for row in pace_rows],
                hovertemplate=("%{customdata[0]}<br>Runs %{customdata[1]:,}<br>Balls %{x:,}"
                               "<br>Strike rate %{y:.1f}<br>Dismissals %{customdata[2]}"
                               "<br>Average %{customdata[3]}<extra></extra>"),
            ))
            pace_fig.add_vline(x=median_balls, line_dash="dot", line_color="#9AA8BA", annotation_text="Median balls")
            pace_fig.add_hline(y=median_sr, line_dash="dot", line_color="#9AA8BA", annotation_text="Median SR")
            pace_fig.update_layout(xaxis_title="Balls faced", yaxis_title="Strike rate", showlegend=False)
            chart(pace_fig, "Strike rate against balls faced for the top 24 run scorers with at least 30 balls; bubble size encodes runs and dotted lines show this chart's medians", height=420)
        with chart_right:
            st.markdown("**Boundary frequency vs dot-ball share**")
            st.caption("This view separates boundary pressure from risk of getting stuck; bubble size reflects balls faced.")
            control_rows = sorted(qualified, key=lambda row: (-_int(row.get("runs")), _safe_name(row)))[:40]
            control_fig = go.Figure(go.Scatter(
                x=[row.get("boundaries_per_100") or 0 for row in control_rows],
                y=[row.get("dot_share") or 0 for row in control_rows],
                mode="markers",
                marker=dict(
                    size=[max(9, min(28, 7 + _int(row.get("balls")) ** 0.5 / 2)) for row in control_rows],
                    color=[row.get("strike_rate") or 0 for row in control_rows],
                    colorscale="Tealrose",
                    showscale=True,
                    colorbar=dict(title="Strike rate", thickness=12),
                    opacity=0.84,
                    line=dict(color="#FFFFFF", width=1),
                ),
                text=[_safe_name(row) for row in control_rows],
                customdata=[[_int(row.get("runs")), _int(row.get("balls")), row.get("strike_rate")] for row in control_rows],
                hovertemplate=("%{text}<br>Boundaries / 100 balls %{x:.1f}<br>Dot-ball share %{y:.1f}%"
                               "<br>Runs %{customdata[0]:,} · %{customdata[1]:,} balls"
                               "<br>Strike rate %{customdata[2]:.1f}<extra></extra>"),
            ))
            control_fig.update_layout(xaxis_title="Boundaries per 100 balls", yaxis_title="Dot balls (%)")
            chart(control_fig, "Boundary frequency against dot-ball share for up to 40 batters with 30 or more balls; color shows strike rate and bubble size shows balls faced", height=420)
    else:
        with chart_left:
            st.info("No batting sample has reached the 30-ball guide for comparison charts.")

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
    total_economy = economy_rate(total_runs, total_balls)
    qualified = [row for row in rows if _int(row.get("legal_balls")) >= MIN_SAMPLE_BALLS]
    wicket_leaders = sorted(rows, key=lambda row: (-_int(row.get("credited_wickets")), _safe_name(row)))[:10]
    economy_leaders = sorted(
        [row for row in qualified if row.get("economy") is not None],
        key=lambda row: (float(row["economy"]), _safe_name(row)),
    )[:10]
    dot_leaders = sorted(
        [row for row in qualified if row.get("dot_share") is not None],
        key=lambda row: (-float(row["dot_share"]), _safe_name(row)),
    )[:10]
    best_economy = economy_leaders[0] if economy_leaders else None
    wicket_rate_candidates = [
        row for row in qualified
        if _int(row.get("credited_wickets")) >= 3 and row.get("wicket_rate_per_6") is not None
    ]
    best_wicket_rate = max(wicket_rate_candidates, key=lambda row: float(row.get("wicket_rate_per_6") or 0), default=None)
    st.subheader("Bowling leadership view")
    st.caption("Read bowling through wicket impact, run control, and dot-ball pressure. Rates use legal-ball samples from all available formats and innings.")
    metrics = st.columns(4)
    metrics[0].metric("Bowlers in data", f"{len(rows):,}")
    metrics[1].metric("Bowler runs", f"{total_runs:,}", help="Uses the processed source's bowler-run convention.")
    metrics[2].metric("Legal balls", f"{total_balls:,}")
    metrics[3].metric("Overall economy", _fmt(total_economy, 2), help=f"{total_wickets:,} credited wickets across the full sample.")

    st.markdown("#### Leadership read")
    readout = st.columns(3)
    with readout[0].container(border=True):
        if wicket_leaders:
            st.caption("Most credited wickets · full sample")
            st.markdown(f"### {_safe_name(wicket_leaders[0])}")
            st.write(f"{_int(wicket_leaders[0].get('credited_wickets')):,} wickets · {_int(wicket_leaders[0].get('legal_balls')):,} legal balls")
    with readout[1].container(border=True):
        st.caption("Tightest economy · 30+ legal balls")
        if best_economy:
            st.markdown(f"### {_safe_name(best_economy)}")
            st.write(f"{_fmt(best_economy.get('economy'), 2)} runs per over · {_int(best_economy.get('legal_balls')):,} legal balls")
        else:
            st.write("No bowler has reached the 30-ball guide yet.")
    with readout[2].container(border=True):
        st.caption("Highest wicket rate · 30+ balls, 3+ wickets")
        if best_wicket_rate:
            st.markdown(f"### {_safe_name(best_wicket_rate)}")
            st.write(f"{_fmt(best_wicket_rate.get('wicket_rate_per_6'), 2)} wickets per 6 balls · {_int(best_wicket_rate.get('credited_wickets'))} wickets")
        else:
            st.write("No player meets the wicket-rate guide yet.")

    st.markdown("#### Wickets, economy, and control")
    st.caption("Use the wicket chart for workload and the rate charts for efficiency. The sample guide is 30 legal balls; the scatter also requires 3 credited wickets.")
    top_left, top_right = st.columns(2, gap="large")
    with top_left:
        _ranked_bar(wicket_leaders, "bowler", "credited_wickets", "Credited wickets · top 10 full-sample totals", "Wickets", "Top 10 bowlers by credited wickets across the full sample")
    comparison_rows = [
        row for row in qualified
        if _int(row.get("credited_wickets")) >= 3
        and row.get("economy") is not None
        and row.get("wicket_rate_per_6") is not None
    ]
    with top_right:
        st.markdown("**Run control vs wicket threat**")
        st.caption("Best profile is toward the upper-left: lower economy with more wickets per six balls. Larger dots mean more legal balls.")
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

    rate_left, rate_right = st.columns(2, gap="large")
    with rate_left:
        if economy_leaders:
            _ranked_bar(
                economy_leaders, "bowler", "economy", "Tightest economy · qualified samples",
                "Runs per over", "Lowest economy among bowlers with at least 30 legal balls",
            )
            st.caption("Lower is better. This view is sample-gated at 30 legal balls.")
        else:
            st.info("No bowlers pass the 30-legal-ball guide for economy comparisons.")
    with rate_right:
        if dot_leaders:
            _ranked_bar(
                dot_leaders, "bowler", "dot_share", "Highest dot-ball share · qualified samples",
                "Dot balls / legal balls (%)", "Highest dot-ball share among bowlers with at least 30 legal balls",
            )
            st.caption("Higher dot-ball share means more legal deliveries with no bowler runs conceded.")
        else:
            st.info("No bowlers pass the 30-legal-ball guide for dot-ball comparisons.")

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


def render_trusted_death_bowlers(report: dict[str, Any]) -> None:
    st.subheader("Trusted death-over bowlers · Indian venues")
    if not report:
        st.warning("The raw death-over bowling report is missing. Rebuild the local raw-data reports to populate this section.")
        return

    counts = report.get("counts", {})
    scope = report.get("scope", "")
    minimums = report.get("minimums", {})
    top_ten = report.get("top_ten", [])
    validation = report.get("validation", {})
    st.caption(
        f"{scope} No chase-pressure state filter is used. Only death-over figures enter the score. "
        f"Ranking sample: each bowler's latest {minimums.get('death_innings', 10)} Indian death-over innings. "
        f"Eligibility: at least {minimums.get('death_legal_balls', 30)} legal balls and "
        f"{minimums.get('credited_wickets', 3)} credited wickets in that sample, a 2026 appearance at any venue, "
        f"and a latest Indian death-over appearance in {minimums.get('latest_india_death_appearance_year', '2026')}."
    )
    exclusions = report.get("user_exclusions", [])
    if exclusions:
        st.caption(
            "Removed from this top-ten selection at your request: "
            + ", ".join(item.get("player", "") for item in exclusions)
            + "."
        )

    metrics = st.columns(3)
    metrics[0].metric("Eligible bowlers", f"{_int(counts.get('eligible_players')):,}")
    metrics[1].metric("Recent death balls scored", f"{_int(counts.get('eligible_cohort_legal_balls')):,}")
    metrics[2].metric("Recent credited wickets", f"{_int(counts.get('eligible_cohort_credited_wickets')):,}")
    st.caption(
        "Score = 30% economy · 25% dot-ball rate · 20% wickets/100 balls · "
        "15% boundary concessions/100 balls · 10% balls yielding 1–2 team runs. "
        "Lower economy, boundary concessions, and 1–2 run balls are better. "
        "All five components use death-over deliveries only; percentiles are relative to eligible bowlers. "
        "Economy and wicket rate use a 60-ball prior in the score only; the table shows raw and adjusted rates."
    )
    if validation:
        if validation.get("all_passed"):
            st.success(
                f"Raw-data cross-check passed: {validation.get('checks_passed', 0):,}/"
                f"{validation.get('checks_total', 0):,} checks, including every ranked player's figures and rank."
            )
        else:
            st.error(
                f"Raw-data cross-check failed: {validation.get('checks_passed', 0):,}/"
                f"{validation.get('checks_total', 0):,} checks passed. Review the validation details before relying on this ranking."
            )
            failed = [check for check in validation.get("checks", []) if not check.get("passed")]
            if failed:
                with st.expander("Show failed raw-data checks", expanded=True):
                    markdown_table(failed, [
                        ("check", "Check"), ("computed", "Computed"), ("reference", "Expected"),
                    ], max_height=360)

    if not top_ten:
        st.info(report.get("ranking_status", "No death-over bowlers meet the ranking gates."))
    else:
        chart_col, heat_col = st.columns([1, 1.15])
        with chart_col:
            visual_rows = [
                {**row, "chart_name": f"{row.get('rank')}. {row.get('player')}"}
                for row in top_ten
            ]
            _ranked_bar(
                visual_rows,
                "chart_name",
                "composite_score",
                "Weighted score · top 10",
                "Score / 100",
                "Composite death-over bowling scores for the top ten raw-data bowlers",
            )
        with heat_col:
            st.markdown("**What drove the score**")
            component_fields = [
                ("adjusted_economy", "Economy"),
                ("ranking_dot_pct", "Dot balls"),
                ("adjusted_wickets_per_100", "Wickets / 100"),
                ("ranking_boundary_pct", "Boundary control"),
                ("ranking_singles_twos_pct", "1s / 2s control"),
            ]
            heatmap = go.Figure(
                go.Heatmap(
                    z=[
                        [float(row.get(f"{field}_percentile") or 0) for field, _ in component_fields]
                        for row in top_ten
                    ],
                    x=[label for _, label in component_fields],
                    y=[f"{row.get('rank')}. {row.get('player')}" for row in top_ten],
                    zmin=0,
                    zmax=100,
                    colorscale="RdYlGn",
                    colorbar=dict(title="Better", thickness=12),
                    hovertemplate="%{y}<br>%{x} percentile: %{z:.1f}<extra></extra>",
                )
            )
            heatmap.update_layout(xaxis_title="Weighted score component", yaxis_title="Bowler")
            chart(heatmap, "Heatmap of the five death-over component percentiles for each ranked bowler", height=390)

        st.markdown("**Top 10 · latest 10 Indian death-over innings**")
        st.caption("The score is a relative percentile composite across the eligible bowlers. Recent raw rates are shown below; each rate uses the legal balls in that bowler’s latest-ten sample.")
        markdown_table(
            top_ten,
            [
                ("rank", "Rank"), ("player", "Bowler"), ("ranking_innings", "Recent innings"),
                ("ranking_latest_date", "Latest sample date"),
                ("ranking_balls", "Legal balls"), ("ranking_runs", "Runs conceded"),
                ("ranking_economy", "Economy", lambda value: _fmt(value, 2)),
                ("adjusted_economy", "Adjusted economy", lambda value: _fmt(value, 2)),
                ("ranking_dot_balls", "Dot balls"),
                ("ranking_dot_pct", "Dot %", lambda value: _fmt(value, 1)),
                ("ranking_wickets", "Wickets"),
                ("ranking_wickets_per_100", "Wickets / 100", lambda value: _fmt(value, 2)),
                ("adjusted_wickets_per_100", "Adjusted W / 100", lambda value: _fmt(value, 2)),
                ("ranking_boundary_pct", "Boundaries / 100", lambda value: _fmt(value, 1)),
                ("ranking_singles_twos_pct", "1s / 2s per 100", lambda value: _fmt(value, 1)),
                ("composite_score", "Score / 100", lambda value: _fmt(value, 1)),
            ],
            max_height=510,
        )
        csv_download(top_ten, "Download top 10", "trusted_death_bowlers_top10.csv", "death_bowler_top10_csv")
        with st.expander("Career Indian death-over record for these 10", expanded=False):
            markdown_table(
                top_ten,
                [
                    ("rank", "Rank"), ("player", "Bowler"), ("death_matches", "Matches"),
                    ("death_innings", "Death innings"), ("legal_balls", "Legal balls"),
                    ("bowler_runs", "Runs conceded"),
                    ("economy", "Career economy", lambda value: _fmt(value, 2)),
                    ("credited_wickets", "Credited wickets"),
                    ("wickets_per_100", "Wickets / 100", lambda value: _fmt(value, 2)),
                ],
                max_height=420,
            )

    with st.expander("Check the 10 suggested names against the raw ranking", expanded=False):
        candidate_rows = report.get("suggested_candidate_audit", [])
        st.caption("These names are evaluated against the same raw death-over rules. A suggested name is not forced into the final top 10.")
        if candidate_rows:
            markdown_table(
                candidate_rows,
                [
                    ("suggested_bowler", "Suggested bowler"), ("rank", "Raw rank"),
                    ("ranking_status", "Eligibility"), ("ranking_innings", "Recent innings"),
                    ("ranking_balls", "Legal balls"),
                    ("ranking_economy", "Economy", lambda value: _fmt(value, 2)),
                    ("adjusted_economy", "Adjusted economy", lambda value: _fmt(value, 2)),
                    ("ranking_dot_pct", "Dot %", lambda value: _fmt(value, 1)),
                    ("ranking_wickets", "Wickets"),
                    ("ranking_wickets_per_100", "Wickets / 100", lambda value: _fmt(value, 2)),
                    ("adjusted_wickets_per_100", "Adjusted W / 100", lambda value: _fmt(value, 2)),
                    ("ranking_boundary_pct", "Boundaries / 100", lambda value: _fmt(value, 1)),
                    ("ranking_singles_twos_pct", "1s / 2s per 100", lambda value: _fmt(value, 1)),
                    ("composite_score", "Score", lambda value: _fmt(value, 1)),
                    ("ranking_reasons", "If not ranked"),
                ],
                max_height=460,
            )
            csv_download(candidate_rows, "Download suggested-name audit", "suggested_death_bowler_audit.csv", "death_bowler_candidate_csv")

    with st.expander("Full cohort, scoring details, and exclusions", expanded=False):
        st.markdown("**Scoring rules**")
        markdown_table(
            [
                {"measure": "Economy", "weight": "30%", "direction": "Lower is better", "sample": "Death-over bowler runs / legal balls × 6"},
                {"measure": "Dot-ball rate", "weight": "25%", "direction": "Higher is better", "sample": "Dot legal balls / legal balls × 100"},
                {"measure": "Wicket rate", "weight": "20%", "direction": "Higher is better", "sample": "Credited wickets / legal balls × 100"},
                {"measure": "Boundary-concession rate", "weight": "15%", "direction": "Lower is better", "sample": "Fours + sixes / legal balls × 100"},
                {"measure": "Singles/twos allowed", "weight": "10%", "direction": "Lower is better", "sample": "Legal balls with 1 or 2 team runs / legal balls × 100"},
            ],
            [("measure", "Measure"), ("weight", "Weight"), ("direction", "Better result"), ("sample", "Death-over formula")],
        )
        st.caption(report.get("definitions", {}).get("eligibility", "Eligibility details are included in the report."))
        st.caption(
            f"Raw Indian death-over rows: {_int(counts.get('raw_india_death_rows')):,}; "
            f"usable after unknown-state exclusions: {_int(counts.get('usable_india_death_rows')):,}. "
            f"Excluded unknown-legality rows: {_int(counts.get('unknown_legality_rows_in_cohort')):,}; "
            f"later deliveries from unknown-state innings: {_int(counts.get('death_rows_after_unknown_state_excluded')):,}."
        )
        player_rows = report.get("player_rows", [])
        csv_download(player_rows, "Download all bowlers and review samples", "india_death_bowler_rankings.csv", "all_death_bowler_csv")
        if report.get("excluded_player_ids"):
            st.caption(f"Unknown or multi-name IDs excluded from the death-over sample: {len(report['excluded_player_ids']):,}.")


def render_pressure(report: dict[str, Any], clutch: dict[str, Any], death_bowling: dict[str, Any]) -> None:
    if not report:
        st.warning("Pressure report is not available. Rebuild the raw-data report to populate this tab.")
        return

    state_rows = report.get("state_table", [])
    batting_state = next((row for row in state_rows if row.get("state") == "Batting pressure"), {})
    bowling_state = next((row for row in state_rows if row.get("state") == "Bowling pressure"), {})
    clutch_cohort = clutch.get("cohort", {}) if clutch else {}
    audit = clutch.get("entry_timing_audit", {}) if clutch else {}
    entry_rows = audit.get("summary", [])
    top_ten = clutch.get("final_batting_top_ten", []) if clutch else []
    phase_rankings = clutch.get("phase_candidate_rankings", []) if clutch else []
    clutch_validation = clutch.get("validation", {}) if clutch else {}

    st.subheader("Pressure leadership brief")
    st.caption("A leadership view of who has handled the clutch batting window, how the score is built, and which bowlers combine death-over control with wickets.")
    summary = st.columns(4)
    summary[0].metric("Indian clutch chases", f"{_int(clutch_cohort.get('anchor_chases')):,}")
    summary[1].metric("Final batting shortlist", f"{len(top_ten):,}")
    death_counts = death_bowling.get("counts", {}) if death_bowling else {}
    death_top_ten = death_bowling.get("top_ten", []) if death_bowling else []
    summary[2].metric("Death-over bowler shortlist", f"{len(death_top_ten):,}")
    if clutch_validation:
        summary[3].metric(
            "Raw batting checks",
            f"{_int(clutch_validation.get('checks_passed')):,}/{_int(clutch_validation.get('checks_total')):,}",
            help="Independent reconstruction from raw ball-by-ball, match, and competition files.",
        )
    else:
        summary[3].metric("Eligible death-over bowlers", f"{_int(death_counts.get('eligible_players')):,}")

    narrative = st.columns(2, gap="large")
    with narrative[0].container(border=True):
        if top_ten:
            lead_batter = top_ten[0]
            st.markdown("**Batting story · Indian clutch window**")
            st.markdown(f"### {lead_batter.get('player', '—')}")
            st.write(
                f"Leads the current top 10 with a phase score of {_fmt(lead_batter.get('phase_weighted_score'), 1)} / 100. "
                f"Middle-over SR {_fmt(lead_batter.get('middle_phase_strike_rate'), 1)} → death-over SR "
                f"{_fmt(lead_batter.get('death_phase_strike_rate'), 1)} across {_int(lead_batter.get('innings'))} pressure innings."
            )
        else:
            st.markdown("**Batting story · Indian clutch window**")
            st.write("The current raw-data batting shortlist is unavailable.")
    with narrative[1].container(border=True):
        if death_top_ten:
            lead_bowler = death_top_ten[0]
            st.markdown("**Bowling story · Indian death overs**")
            st.markdown(f"### {lead_bowler.get('player', '—')}")
            st.write(
                f"Ranked first on the death-over composite ({_fmt(lead_bowler.get('composite_score'), 1)} / 100): "
                f"{_fmt(lead_bowler.get('ranking_economy'), 2)} economy, "
                f"{_fmt(lead_bowler.get('ranking_dot_pct'), 1)}% dots, and "
                f"{_fmt(lead_bowler.get('ranking_wickets_per_100'), 1)} wickets per 100 balls "
                f"in {_int(lead_bowler.get('ranking_balls'))} recent balls."
            )
        else:
            st.markdown("**Bowling story · Indian death overs**")
            st.write("The current raw-data death-over shortlist is unavailable.")

    pressure_rows = [row for row in state_rows if row.get("state") in {"Batting pressure", "Bowling pressure"}]
    if pressure_rows:
        st.markdown("**How much pressure-state evidence is available?**")
        st.caption("Counts reflect the separately defined pressure states; the bowling sample is intentionally shown at its actual size.")
        state_fig = go.Figure(go.Bar(
            x=[_int(row.get("delivery_rows")) for row in pressure_rows],
            y=[row.get("state") for row in pressure_rows],
            orientation="h",
            marker_color=[PALETTE[1] if row.get("state") == "Batting pressure" else PALETTE[2] for row in pressure_rows],
            text=[f"{_int(row.get('delivery_rows')):,} deliveries · {_int(row.get('matches')):,} matches" for row in pressure_rows],
            textposition="outside",
            cliponaxis=False,
            customdata=[[_int(row.get("matches")), _int(row.get("legal_balls")), row.get("reporting_status", "")] for row in pressure_rows],
            hovertemplate=("%{y}<br>Pressure deliveries %{x:,}<br>Matches %{customdata[0]:,}"
                           "<br>Legal balls %{customdata[1]:,}<br>%{customdata[2]}<extra></extra>"),
        ))
        state_fig.update_layout(
            title=dict(text="Pressure sample size by scenario", x=0.02, xanchor="left"),
            xaxis=dict(title="Delivery rows", range=[0, max(_int(row.get("delivery_rows")) for row in pressure_rows) * 1.45]),
            yaxis=dict(categoryorder="array", categoryarray=[row.get("state") for row in pressure_rows][::-1]),
            showlegend=False,
        )
        chart(state_fig, "Pressure delivery counts and contributing matches for batting and bowling pressure scenarios", height=270)
        if bowling_state and str(bowling_state.get("reporting_status", "")).startswith("Count only"):
            st.info(
                f"Bowling pressure currently covers {_int(bowling_state.get('decided_chases')):,} decided chases, "
                "below the 20-chase cohort guide. The chart shows the observed volume; it does not publish a pressure-state bowler ranking."
            )

    st.subheader("Indian clutch-window batting")
    st.caption(
        clutch.get("definition", {}).get("scenario", "Raw ball-by-ball data joined to match and competition records.")
        + " The approved top seven are retained; the final three come from the remaining clutch-qualified batters using the phase-weighted score below. Match outcomes do not affect the score."
    )
    metrics = st.columns(3)
    metrics[0].metric("Players after reliability gates", f"{_int(clutch_cohort.get('players_remaining_after_user_exclusions')):,}")
    metrics[1].metric("Eligible for phase score", f"{_int(clutch_cohort.get('phase_eligible_players')):,}")
    if clutch_validation:
        metrics[2].metric(
            "Independent raw checks",
            f"{_int(clutch_validation.get('checks_passed'))}/{_int(clutch_validation.get('checks_total'))}",
        )
        if clutch_validation.get("all_passed"):
            st.success("The batting figures and ranks passed the independent raw-data recount.")
        else:
            st.error("The independent raw-data recount found differences. Check the validation report before using this list.")
    else:
        metrics[2].metric("Decided qualifying chases", f"{_int(clutch_cohort.get('decided_anchor_chases')):,}")

    if top_ten:
        score_col, phase_col = st.columns([1, 1])
        chart_rows = [
            {**row, "chart_name": f"{row.get('final_rank')}. {row.get('player')}"}
            for row in top_ten
        ]
        with score_col:
            _ranked_bar(
                chart_rows,
                "chart_name",
                "phase_weighted_score",
                "Phase-weighted score · final top 10",
                "Relative score / 100",
                "Phase-weighted batting score for the final top ten; scores are relative to eligible clutch candidates",
            )
        with phase_col:
            fig = go.Figure()
            approved_rows = [row for row in chart_rows if _int(row.get("final_rank")) <= 7]
            selected_rows = [row for row in chart_rows if _int(row.get("final_rank")) > 7]
            for subset, label, color in (
                (approved_rows, "Approved top seven", PALETTE[0]),
                (selected_rows, "Selected by phase score", PALETTE[2]),
            ):
                if not subset:
                    continue
                fig.add_trace(go.Scatter(
                    x=[row.get("middle_phase_strike_rate") for row in subset],
                    y=[row.get("death_phase_strike_rate") for row in subset],
                    mode="markers+text",
                    name=label,
                    text=[row.get("player") for row in subset],
                    textposition="top center",
                    marker=dict(size=13, color=color, line=dict(color="#FFFFFF", width=1.5)),
                    customdata=[[
                        row.get("middle_phase_balls"), row.get("death_phase_balls"),
                        row.get("middle_phase_adjusted_strike_rate"), row.get("death_phase_adjusted_strike_rate"),
                    ] for row in subset],
                    hovertemplate=(
                        "%{text}<br>Middle raw SR: %{x:.1f} (%{customdata[0]} balls)"
                        "<br>Death raw SR: %{y:.1f} (%{customdata[1]} balls)"
                        "<br>Middle adjusted SR: %{customdata[2]:.1f}"
                        "<br>Death adjusted SR: %{customdata[3]:.1f}<extra></extra>"
                    ),
                ))
            phase_min = min(
                float(row.get("middle_phase_strike_rate") or 0) for row in chart_rows
            )
            phase_max = max(
                float(row.get("death_phase_strike_rate") or 0) for row in chart_rows
            )
            fig.add_trace(go.Scatter(
                x=[phase_min, phase_max], y=[phase_min, phase_max],
                mode="lines", name="No change", line=dict(color="#A7B1C2", dash="dot"),
                hoverinfo="skip",
            ))
            fig.update_layout(
                title=dict(text="Middle-to-death strike-rate shift", x=0.02, xanchor="left"),
                xaxis_title="Middle overs 7–15 · raw strike rate",
                yaxis_title="Death overs 16–20 · raw strike rate",
                legend=dict(orientation="h", y=1.12),
                margin=dict(t=80),
            )
            chart(fig, "Raw middle-over strike rate plotted against death-over strike rate; sample balls and adjusted rates are shown on hover", height=420)

        st.caption(
            "Score formula: death-over SR 25%, middle-over SR 15%, adjusted SR acceleration 20%, "
            "runs across both phases 15%, boundary-rate acceleration 15%, and adjusted average 10%. "
            "Each component is a percentile within the clutch-qualified phase cohort. Middle overs are 7–15; death overs are 16–20. "
            "Ties break by death-over balls, then combined phase runs."
        )
        display_rows = []
        for row in top_ten:
            average_display = (
                f"{_fmt(row.get('phase_average_raw'), 1)} raw / {_fmt(row.get('phase_average_adjusted'), 1)} adjusted · "
                f"{_int(row.get('phase_total_dismissals'))} dismissals"
                if row.get("phase_average_raw") != "Not reported"
                else f"Not reported · {_int(row.get('phase_total_dismissals'))} dismissals"
            )
            display_rows.append({
                **row,
                "selection_label": "Approved" if _int(row.get("final_rank")) <= 7 else "Phase score",
                "middle_sr_sample": (
                    f"{_fmt(row.get('middle_phase_strike_rate'), 1)} raw / "
                    f"{_fmt(row.get('middle_phase_adjusted_strike_rate'), 1)} adj · "
                    f"{_int(row.get('middle_phase_balls'))} balls"
                ),
                "death_sr_sample": (
                    f"{_fmt(row.get('death_phase_strike_rate'), 1)} raw / "
                    f"{_fmt(row.get('death_phase_adjusted_strike_rate'), 1)} adj · "
                    f"{_int(row.get('death_phase_balls'))} balls"
                ),
                "average_sample": average_display,
            })
        st.markdown("**Top 10 batters under pressure · Indian T20 phase data**")
        markdown_table(
            display_rows,
            [
                ("final_rank", "Rank"), ("player", "Batter"), ("selection_label", "Selection"),
                ("innings", "Pressure innings"), ("balls", "Pressure balls"),
                ("middle_sr_sample", "Middle SR · raw / adjusted"),
                ("death_sr_sample", "Death SR · raw / adjusted"),
                ("phase_sr_acceleration", "Adjusted SR lift", lambda value: _fmt(value, 1)),
                ("phase_total_runs", "Middle + death runs"),
                ("phase_boundary_rate_acceleration", "Boundary lift / 100 balls", lambda value: _fmt(value, 1)),
                ("average_sample", "Phase average · raw / adjusted"),
                ("phase_weighted_score", "Score / 100", lambda value: _fmt(value, 1)),
            ],
            max_height=590,
        )
        csv_download(top_ten, "Download top 10", "indian_clutch_phase_weighted_top_10.csv", "clutch_phase_top10_csv")

        st.markdown("#### What drives the batting score")
        st.caption("Each stack shows the weighted percentile points supplied by that part of the formula.")
        score_components = [
            ("Death SR · 25%", "death_phase_adjusted_strike_rate_points", PALETTE[0]),
            ("Middle SR · 15%", "middle_phase_adjusted_strike_rate_points", PALETTE[1]),
            ("SR acceleration · 20%", "phase_sr_acceleration_points", PALETTE[2]),
            ("Total runs · 15%", "phase_total_runs_points", PALETTE[3]),
            ("Boundary acceleration · 15%", "phase_boundary_rate_acceleration_points", PALETTE[4]),
            ("Average · 10%", "phase_average_adjusted_points", PALETTE[5]),
        ]
        component_chart = go.Figure()
        rank_labels = [f"{row.get('final_rank')}. {row.get('player')}" for row in top_ten]
        for label, field, color in score_components:
            component_chart.add_trace(go.Bar(
                name=label,
                x=rank_labels,
                y=[row.get(field) or 0 for row in top_ten],
                marker_color=color,
                hovertemplate=f"%{{x}}<br>{label}: %{{y:.1f}} points<extra></extra>",
            ))
        component_chart.update_layout(
            title=dict(text="Weighted score contribution by component", x=0.02, xanchor="left"),
            barmode="stack",
            xaxis_title="Final list position",
            yaxis_title="Weighted percentile points",
            yaxis_range=[0, 100],
            legend=dict(orientation="h", y=1.2),
            margin=dict(t=105),
        )
        chart(component_chart, "Stacked weighted percentile points for each batter and score component", height=440)

        with st.expander("Detailed score components and alternatives", expanded=False):
            component_rows = []
            for row in top_ten:
                component_rows.append({
                    "Rank": row.get("final_rank"),
                    "Phase cohort rank": row.get("phase_weighted_rank"),
                    "Batter": row.get("player"),
                    "Death SR · 25%": row.get("death_phase_adjusted_strike_rate_points"),
                    "Middle SR · 15%": row.get("middle_phase_adjusted_strike_rate_points"),
                    "SR acceleration · 20%": row.get("phase_sr_acceleration_points"),
                    "Total runs · 15%": row.get("phase_total_runs_points"),
                    "Boundary acceleration · 15%": row.get("phase_boundary_rate_acceleration_points"),
                    "Average · 10%": row.get("phase_average_adjusted_points"),
                    "Total score": row.get("phase_weighted_score"),
                    "Middle balls": row.get("middle_phase_balls"),
                    "Death balls": row.get("death_phase_balls"),
                    "Middle boundaries / 100": row.get("middle_phase_boundary_rate"),
                    "Death boundaries / 100": row.get("death_phase_boundary_rate"),
                    "Phase dismissals": row.get("phase_total_dismissals"),
                })
            markdown_table(
                component_rows,
                [("Rank", "Final rank"), ("Phase cohort rank", "Phase rank"),
                 ("Batter", "Batter"), ("Death SR · 25%", "Death SR · 25%"),
                 ("Middle SR · 15%", "Middle SR · 15%"), ("SR acceleration · 20%", "SR acceleration · 20%"),
                 ("Total runs · 15%", "Total runs · 15%"),
                 ("Boundary acceleration · 15%", "Boundary acceleration · 15%"),
                 ("Average · 10%", "Average · 10%"), ("Total score", "Total score"),
                 ("Middle balls", "Middle balls"), ("Death balls", "Death balls"),
                 ("Middle boundaries / 100", "Middle boundaries / 100"),
                 ("Death boundaries / 100", "Death boundaries / 100"),
                 ("Phase dismissals", "Phase dismissals")],
                max_height=420,
            )
            selected_ids = {int(row["player_id"]) for row in top_ten}
            next_candidates = [row for row in phase_rankings if int(row["player_id"]) not in selected_ids]
            if next_candidates:
                st.markdown("**Next eligible alternatives by phase score**")
                markdown_table(
                    next_candidates[:10],
                    [("phase_weighted_rank", "Cohort rank"), ("player", "Batter"),
                     ("phase_weighted_score", "Score", lambda value: _fmt(value, 1)),
                     ("middle_phase_strike_rate", "Middle SR", lambda value: _fmt(value, 1)),
                     ("middle_phase_balls", "Middle balls"),
                     ("death_phase_strike_rate", "Death SR", lambda value: _fmt(value, 1)),
                     ("death_phase_balls", "Death balls"),
                     ("phase_total_runs", "Phase runs")],
                    max_height=340,
                )

        with st.expander("Latest 10 Indian-venue chase form · raw", expanded=False):
            markdown_table(
                top_ten,
                [
                    ("final_rank", "Rank"), ("player", "Batter"), ("recent_form_innings", "Innings"),
                    ("recent_form_window_start", "From"), ("recent_form_window_end", "To"),
                    ("recent_form_runs", "Runs"), ("recent_form_balls", "Balls"),
                    ("recent_form_strike_rate", "SR", lambda value: _fmt(value, 1)),
                    ("recent_form_average", "Average", lambda value: "Not reported" if value == "Not reported" else _fmt(value, 1)),
                    ("recent_form_boundary_share", "Boundary-run share %", lambda value: _fmt(value, 1)),
                    ("recent_form_dot_balls", "Dots"),
                    ("recent_form_dot_pct", "Dot %", lambda value: _fmt(value, 1)),
                ],
                max_height=420,
            )
        with st.expander("Review samples below the clutch ranking gates", expanded=False):
            review_rows = [row for row in clutch.get("player_rows", []) if row.get("rank") is None]
            if review_rows:
                markdown_table(
                    review_rows,
                    [("player", "Batter"), ("innings", "Pressure innings"),
                     ("balls", "Pressure balls"), ("runs", "Pressure runs"),
                     ("ranking_status", "Review reason"), ("user_excluded", "User excluded")],
                    max_height=360,
                )
    else:
        st.warning("The raw Indian clutch-window top-10 result is missing from the current report.")

    st.divider()
    render_trusted_death_bowlers(death_bowling)
    st.divider()

    with st.expander("Raw entry timing audit · supplied top 10", expanded=False):
        st.caption(
            f"Raw source scope: {_int(audit.get('anchor_chases'))} India-venue chases "
            f"({_int(audit.get('format_anchor_chases', {}).get('T20'))} T20 and "
            f"{_int(audit.get('format_anchor_chases', {}).get('T20I'))} T20I)."
        )
        if entry_rows:
            audit_chart_rows = [
                {**row, "label": f"{row.get('rank')}. {row.get('player')}"}
                for row in entry_rows
            ]
            audit_cols = st.columns([1.25, 1])
            with audit_cols[0]:
                fig = go.Figure(
                    go.Bar(
                        x=[row.get("raw_median_entry_over") for row in audit_chart_rows],
                        y=[row["label"] for row in audit_chart_rows],
                        orientation="h",
                        marker_color=[PALETTE[1] if row.get("status") == "DIFFERS" else PALETTE[2] for row in audit_chart_rows],
                        text=[_fmt(row.get("raw_median_entry_over"), 1) for row in audit_chart_rows],
                        textposition="outside",
                        cliponaxis=False,
                        hovertemplate="%{y}<br>Raw median entry over: %{x:.1f}<extra></extra>",
                    )
                )
                fig.update_layout(
                    xaxis_title="Median entry over",
                    yaxis=dict(categoryorder="array", categoryarray=[row["label"] for row in audit_chart_rows][::-1]),
                    showlegend=False,
                )
                chart(fig, "Raw median entry over for the supplied ten-player clutch list; highlighted bar marks a mismatch", height=400)
            with audit_cols[1]:
                st.metric(
                    "Rows matching supplied figures",
                    f"{_int(audit.get('reference_rows_matching'))}/{_int(audit.get('reference_rows_compared'))}",
                )
                for row in entry_rows:
                    if not row.get("matches_reference"):
                        st.warning(
                            f"{row.get('player')}: raw data has {row.get('raw_innings')} innings "
                            f"({row.get('raw_entry_overs')}; median {row.get('raw_median_entry_over')}); "
                            f"the supplied row has {row.get('reference_innings')} innings."
                        )
            markdown_table(
                entry_rows,
                [("rank", "Rank"), ("player", "Batter"), ("raw_entry_overs", "Raw entry overs"),
                 ("raw_median_entry_over", "Median"), ("raw_came_before_anchor", "Before anchor"),
                 ("status", "Check")],
                max_height=420,
            )
        else:
            st.warning("The entry-timing raw audit is missing from the current report.")

    with st.expander("All-venue T20 pressure-state detail", expanded=False):
        st.caption(
            "Separate from the Indian clutch-window ranking. Batting: second innings, 1–30 legal balls left, "
            "3+ wickets down, RRR ≥15. Bowling: second innings, 1–30 legal balls left, 2 or fewer wickets down, "
            "current rate ≥11, RRR ≥9."
        )
        if state_rows:
            state_cols = st.columns(2)
            names = [row.get("state", "") for row in state_rows]
            counts = [_int(row.get("delivery_rows")) for row in state_rows]
            fig = go.Figure(go.Bar(
                x=names,
                y=counts,
                marker_color=[PALETTE[i % len(PALETTE)] for i in range(len(names))],
                text=[f"{count:,}" for count in counts],
                textposition="outside",
                cliponaxis=False,
                hovertemplate="%{x}<br>Delivery rows %{y:,}<extra></extra>",
            ))
            fig.update_layout(xaxis_title="State", yaxis_title="Delivery rows", showlegend=False)
            with state_cols[0]:
                chart(fig, "Delivery counts for raw T20 pressure and ordinary chase states", height=360)
            with state_cols[1]:
                markdown_table(
                    state_rows,
                    [("state", "State"), ("delivery_rows", "Deliveries"), ("matches", "Matches"),
                     ("decided_chases", "Decided chases"), ("legal_balls", "Legal balls"),
                     ("players", "Players"), ("reporting_status", "Status")],
                )

        pressure_validation = report.get("validation", {})
        raw_counts = pressure_validation.get("raw_pressure_flag_totals", {})
        supplied = pressure_validation.get("supplied_pressure_flag_reference", {})
        if raw_counts and supplied and raw_counts != supplied:
            st.warning(
                f"Raw pressure recount: {_int(raw_counts.get('batting_pressure')):,} batting + "
                f"{_int(raw_counts.get('bowling_pressure')):,} bowling = "
                f"{_int(raw_counts.get('both_pressure_flags')):,} flags. Supplied reference: "
                f"{_int(supplied.get('both_pressure_flags')):,}; this difference is not reconciled."
            )

        pressure_batters = [
            row for row in report.get("batter_table", [])
            if row.get("state") == "Batting pressure" and row.get("ranking_eligible")
        ]
        pressure_batters.sort(key=lambda row: (row.get("rank") is None, row.get("rank") or 9999))
        bowling_rows = [row for row in report.get("bowler_table", []) if row.get("state") == "Bowling pressure"]

        st.markdown("**Batting-pressure leaders · separate all-venue T20 cohort**")
        if pressure_batters:
            markdown_table(
                pressure_batters[:10],
                [("rank", "Rank"), ("player", "Batter"), ("innings", "Innings"),
                 ("sample_balls", "Balls"), ("runs", "Runs"),
                 ("strike_rate", "Raw SR", lambda value: _fmt(value, 1)),
                 ("adjusted_strike_rate", "Adjusted SR", lambda value: _fmt(value, 1)),
                 ("dismissals", "Dismissals"),
                 ("average", "Raw average", lambda value: "Not reported" if value is None or value == "Not reported" else _fmt(value, 1)),
                 ("composite_score", "Score", lambda value: _fmt(value, 1))],
            )

        st.markdown("**Bowling-pressure observations · count only**")
        st.caption(
            f"{_int(bowling_state.get('legal_balls'))} legal balls in {_int(bowling_state.get('matches'))} matches; "
            f"{_int(bowling_state.get('decided_chases'))} decided chases. Fewer than 20 chases, so no ranking is published."
        )
        if bowling_rows:
            markdown_table(
                bowling_rows,
                [("player", "Bowler"), ("matches", "Matches"), ("sample_balls", "Legal balls"),
                 ("runs", "Runs"), ("economy", "Economy", lambda value: _fmt(value, 2)),
                 ("credited_wickets", "Credited wickets"), ("dots", "Dots")],
            )


if not database_ready():
    st.title("Cricket stats and pressure")
    st.error("Processed data is not built yet. Build the local data from the project folder first.")
    st.code("python build/build_data.py", language="powershell")
    st.stop()

batting_rows = _prepare_batters(queries.batter_stats({}))
bowling_rows = _prepare_bowlers(queries.bowler_stats({}))
pressure_data = pressure_reports.pressure_report()
clutch_data = pressure_reports.clutch_batting_report()
death_bowling_data = pressure_reports.death_bowling_report()

page_header(
    "Cricket performance",
    "Player records, bowling control, and the latest pressure read — all in one place.",
)

batting_tab, bowling_tab, pressure_tab = st.tabs(
    ["🏏 Batting stats", "🎯 Bowling stats", "⚡ Pressure stats"],
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
        render_pressure(pressure_data, clutch_data, death_bowling_data)
