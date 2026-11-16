from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from lib.pressure_reports import pressure_report
from lib.ui import PRESSURE, chart, csv_download, metric_row, page_header

report = pressure_report()
page_header(
    "Pressure state player report",
    "Raw ball-by-ball figures for batting pressure, bowling pressure, and their ordinary chase controls.",
    ":material/compare_arrows:",
)

if not report:
    st.error("The pressure report has not been built yet. Rebuild the dashboard data to generate it.")
    st.code("python build/build_data.py", language="powershell")
    st.stop()

states = report.get("state_table", [])
batters = report.get("batter_table", [])
bowlers = report.get("bowler_table", [])
comparisons = report.get("comparison_table", [])
state_names = {row["state"]: row for row in states}
bp = state_names.get("Batting pressure", {})
wp = state_names.get("Bowling pressure", {})
bat_eligible = sum(row.get("ranking_eligible", False) for row in batters if row.get("state") == "Batting pressure")
bowl_eligible = sum(row.get("ranking_eligible", False) for row in bowlers if row.get("state") == "Bowling pressure")

metric_row(
    [
        ("Batting-pressure deliveries", f"{int(bp.get('delivery_rows') or 0):,}", f"{int(bp.get('matches') or 0):,} matches; {int(bp.get('decided_chases') or 0):,} decided chases."),
        ("Batting-pressure batters", f"{sum(row.get('state') == 'Batting pressure' for row in batters):,}", f"{bat_eligible:,} pass state sample, 2026 activity, and recent-form gates."),
        ("Bowling-pressure deliveries", f"{int(wp.get('delivery_rows') or 0):,}", f"{int(wp.get('matches') or 0):,} matches; {int(wp.get('decided_chases') or 0):,} decided chases."),
        ("Bowling-pressure bowlers", f"{sum(row.get('state') == 'Bowling pressure' for row in bowlers):,}", f"{bowl_eligible:,} pass 30 balls, 3 credited wickets, activity, and form gates."),
    ]
)

st.caption(report.get("cohort", ""))
st.subheader("State coverage")
st.caption("State summaries report counts. A state with fewer than 20 decided chases is count-only; no cohort rate is published for it.")
st.dataframe(
    states,
    hide_index=True,
    width="stretch",
    column_config={
        "state": "State",
        "delivery_rows": st.column_config.NumberColumn("Delivery rows", format="%d"),
        "matches": st.column_config.NumberColumn("Matches", format="%d"),
        "decided_chases": st.column_config.NumberColumn("Decided chases", format="%d"),
        "legal_balls": st.column_config.NumberColumn("Known legal balls", format="%d"),
        "players": st.column_config.NumberColumn("Players", format="%d"),
        "reporting_status": "Cohort reporting status",
    },
)

tab_bat, tab_bowl, tab_comp, tab_method = st.tabs(["Batting", "Bowling", "Pressure comparisons", "Rules & validation"])

with tab_bat:
    st.subheader("Batting-pressure players")
    st.caption(
        "Rows below a state minimum remain visible as “Review sample.” A rank appears only when at least 10 players meet all ranking gates. "
        "Composite: 50% adjusted strike-rate percentile, 30% adjusted-average percentile, 20% boundary-share percentile. "
        "Displayed raw rates remain alongside adjusted rates; batting average is not reported below 3 dismissals."
    )
    pressure_batters = [row for row in batters if row.get("state") == "Batting pressure"]
    ranked_batters = sorted(
        (row for row in pressure_batters if row.get("rank") is not None),
        key=lambda row: int(row["rank"]),
    )
    if ranked_batters:
        left, right = st.columns([1.05, 1.25])
        with left:
            st.markdown("**Composite leaders**")
            st.dataframe(
                ranked_batters[:10],
                hide_index=True,
                width="stretch",
                column_order=["rank", "player", "sample_balls", "runs", "strike_rate", "adjusted_strike_rate", "dismissals", "average", "adjusted_average", "boundary_share", "composite_score"],
                column_config={
                    "rank": "Rank",
                    "player": "Batter",
                    "sample_balls": "Balls faced",
                    "runs": "Runs",
                    "strike_rate": st.column_config.NumberColumn("Raw SR", format="%.2f"),
                    "adjusted_strike_rate": st.column_config.NumberColumn("Adjusted SR", format="%.2f"),
                    "average": "Raw average",
                    "adjusted_average": "Adjusted average",
                    "boundary_share": st.column_config.NumberColumn("Boundary share %", format="%.2f"),
                    "composite_score": st.column_config.NumberColumn("Composite / 100", format="%.2f"),
                },
            )
        with right:
            fig = go.Figure(
                go.Bar(
                    x=[row["composite_score"] for row in reversed(ranked_batters[:10])],
                    y=[row["player"] for row in reversed(ranked_batters[:10])],
                    orientation="h",
                    marker_color=PRESSURE,
                    customdata=[[row["sample_balls"], row["strike_rate"], row["adjusted_strike_rate"]] for row in reversed(ranked_batters[:10])],
                    hovertemplate="%{y}<br>Composite %{x:.1f}/100<br>Balls %{customdata[0]}<br>Raw SR %{customdata[1]:.1f}<br>Adjusted SR %{customdata[2]:.1f}<extra></extra>",
                )
            )
            fig.update_layout(xaxis_title="Weighted composite score · 0–100", yaxis_title="")
            chart(fig, "Batting-pressure weighted composite leaders", height=390)
    else:
        st.info(report.get("ranking_status", {}).get("Batting pressure", "No player is rank-eligible under the current gates."))

    with st.expander("All batting-pressure player figures", expanded=True):
        st.dataframe(
            pressure_batters,
            hide_index=True,
            width="stretch",
            column_order=["rank", "player", "player_id", "matches", "deliveries", "runs", "sample_balls", "strike_rate", "adjusted_strike_rate", "dismissals", "average", "adjusted_average", "fours", "sixes", "boundary_share", "dots", "dot_share", "recent_innings", "recent_runs", "recent_balls", "recent_strike_rate", "recent_dismissals", "recent_average", "active_2026_all_venues", "sample_status", "recent_form_status", "ranking_reasons", "ranking_status"],
            column_config={
                "rank": "Rank",
                "player": "Batter",
                "player_id": "Source ID",
                "matches": "Pressure matches",
                "deliveries": "State deliveries",
                "runs": "Raw runs",
                "sample_balls": "Balls faced",
                "strike_rate": st.column_config.NumberColumn("Raw SR", format="%.2f"),
                "adjusted_strike_rate": st.column_config.NumberColumn("Adjusted SR", format="%.2f"),
                "dismissals": "Dismissals",
                "average": "Raw avg · 3+ outs",
                "adjusted_average": st.column_config.NumberColumn("Adjusted avg", format="%.2f"),
                "fours": "4s",
                "sixes": "6s",
                "boundary_share": st.column_config.NumberColumn("Boundary share %", format="%.2f"),
                "dots": "Dot balls",
                "dot_share": st.column_config.NumberColumn("Dot share %", format="%.2f"),
                "recent_innings": "Recent innings",
                "recent_runs": "Recent runs",
                "recent_balls": "Recent balls",
                "recent_strike_rate": st.column_config.NumberColumn("Recent SR", format="%.2f"),
                "recent_dismissals": "Recent outs",
                "recent_average": "Recent avg · 3+ outs",
                "active_2026_all_venues": "Played in 2026",
                "sample_status": "Sample flag",
                "recent_form_status": "Recent-form sample",
                "ranking_reasons": "Ranking gate detail",
                "ranking_status": "Ranking status",
            },
        )
    csv_download(pressure_batters, "Download batting-pressure figures", "batter_pressure_figures.csv", "pressure_batter_download")

    st.subheader("Ordinary batting chase control")
    ordinary_batters = [row for row in batters if row.get("state") == "Ordinary batting chase"]
    st.dataframe(
        ordinary_batters,
        hide_index=True,
        width="stretch",
        column_order=["rank", "player", "matches", "runs", "sample_balls", "strike_rate", "adjusted_strike_rate", "dismissals", "average", "adjusted_average", "boundary_share", "sample_status", "recent_form_status", "ranking_reasons", "ranking_status"],
        column_config={
            "rank": "Rank",
            "player": "Batter",
            "matches": "Ordinary matches",
            "runs": "Raw runs",
            "sample_balls": "Balls faced",
            "strike_rate": st.column_config.NumberColumn("Raw SR", format="%.2f"),
            "adjusted_strike_rate": st.column_config.NumberColumn("Adjusted SR", format="%.2f"),
            "dismissals": "Dismissals",
            "average": "Raw avg · 3+ outs",
            "adjusted_average": st.column_config.NumberColumn("Adjusted avg", format="%.2f"),
            "boundary_share": st.column_config.NumberColumn("Boundary share %", format="%.2f"),
            "sample_status": "Sample flag",
            "recent_form_status": "Recent-form sample",
            "ranking_reasons": "Ranking gate detail",
            "ranking_status": "Ranking status",
        },
    )
    csv_download(ordinary_batters, "Download ordinary batting figures", "ordinary_batting_figures.csv", "ordinary_batter_download")

with tab_bowl:
    st.subheader("Bowling-pressure players")
    st.caption(
        "Bowling rank eligibility also requires at least 3 credited wickets and 30 legal balls in the state. "
        "Composite: 40% adjusted-economy percentile (lower is better), 40% adjusted wickets-per-6 percentile, 20% dot-share percentile. "
        "With fewer than 10 eligible players, observations stay unranked."
    )
    pressure_bowlers = [row for row in bowlers if row.get("state") == "Bowling pressure"]
    ranked_bowlers = sorted(
        (row for row in pressure_bowlers if row.get("rank") is not None),
        key=lambda row: int(row["rank"]),
    )
    if ranked_bowlers:
        st.dataframe(
            ranked_bowlers[:10],
            hide_index=True,
            width="stretch",
            column_order=["rank", "player", "sample_balls", "runs", "economy", "adjusted_economy", "credited_wickets", "wicket_rate_per_6", "adjusted_wicket_rate_per_6", "dot_share", "composite_score"],
        )
    else:
        st.info(report.get("ranking_status", {}).get("Bowling pressure", "No player is rank-eligible under the current gates."))
    st.dataframe(
        pressure_bowlers,
        hide_index=True,
        width="stretch",
        column_order=["rank", "player", "player_id", "matches", "deliveries", "runs", "sample_balls", "economy", "adjusted_economy", "credited_wickets", "balls_per_wicket", "wicket_rate_per_6", "adjusted_wicket_rate_per_6", "dots", "dot_share", "boundaries_conceded", "recent_innings", "recent_runs", "recent_balls", "recent_economy", "recent_wickets", "active_2026_all_venues", "sample_status", "wicket_rate_status", "recent_form_status", "ranking_reasons", "ranking_status"],
        column_config={
            "rank": "Rank",
            "player": "Bowler",
            "player_id": "Source ID",
            "matches": "Pressure matches",
            "deliveries": "State deliveries",
            "runs": "Charged runs",
            "sample_balls": "Legal balls",
            "economy": st.column_config.NumberColumn("Raw econ", format="%.2f"),
            "adjusted_economy": st.column_config.NumberColumn("Adjusted econ", format="%.2f"),
            "credited_wickets": "Credited wkts",
            "balls_per_wicket": "Balls / wicket",
            "wicket_rate_per_6": st.column_config.NumberColumn("Raw wkts / 6", format="%.3f"),
            "adjusted_wicket_rate_per_6": st.column_config.NumberColumn("Adjusted wkts / 6", format="%.3f"),
            "dots": "Dot balls",
            "dot_share": st.column_config.NumberColumn("Dot share %", format="%.2f"),
            "boundaries_conceded": "4s + 6s conceded",
            "recent_innings": "Recent innings",
            "recent_runs": "Recent runs conceded",
            "recent_balls": "Recent legal balls",
            "recent_economy": st.column_config.NumberColumn("Recent econ", format="%.2f"),
            "recent_wickets": "Recent wkts",
            "active_2026_all_venues": "Played in 2026",
            "sample_status": "Sample flag",
            "wicket_rate_status": "Wicket-rate sample",
            "recent_form_status": "Recent-form sample",
            "ranking_reasons": "Ranking gate detail",
            "ranking_status": "Ranking status",
        },
    )
    csv_download(pressure_bowlers, "Download bowling-pressure figures", "bowler_pressure_figures.csv", "pressure_bowler_download")

    st.subheader("Ordinary bowling chase control")
    ordinary_bowlers = [row for row in bowlers if row.get("state") == "Ordinary bowling chase"]
    st.dataframe(
        ordinary_bowlers,
        hide_index=True,
        width="stretch",
        column_order=["rank", "player", "matches", "runs", "sample_balls", "economy", "adjusted_economy", "credited_wickets", "balls_per_wicket", "wicket_rate_per_6", "adjusted_wicket_rate_per_6", "dot_share", "boundaries_conceded", "sample_status", "ranking_status"],
    )
    csv_download(ordinary_bowlers, "Download ordinary bowling figures", "ordinary_bowling_figures.csv", "ordinary_bowler_download")

with tab_comp:
    st.subheader("Matched-state comparisons")
    st.caption(
        "A comparison requires at least 30 balls in both states, a T20 appearance in 2026, and 10 known recent chase innings. "
        "State cells with fewer than 20 decided chases show counts only; rows missing any player gate remain visible for review."
    )
    batter_comparisons = [row for row in comparisons if row.get("role") == "Batter"]
    bowler_comparisons = [row for row in comparisons if row.get("role") == "Bowler"]
    comp_bat, comp_bowl = st.tabs(["Batting", "Bowling"])
    with comp_bat:
        st.dataframe(
            batter_comparisons,
            hide_index=True,
            width="stretch",
            column_order=["player", "pressure_matches", "pressure_balls", "ordinary_matches", "ordinary_balls", "pressure_runs", "ordinary_runs", "pressure_sr", "ordinary_sr", "sr_uplift", "pressure_average", "ordinary_average", "average_change", "boundary_share_change", "comparison_reasons", "cohort_note", "comparison_status"],
        )
        csv_download(batter_comparisons, "Download batting comparisons", "batting_pressure_comparisons.csv", "batting_comparison_download")
    with comp_bowl:
        st.dataframe(
            bowler_comparisons,
            hide_index=True,
            width="stretch",
            column_order=["player", "pressure_matches", "pressure_balls", "pressure_wickets", "ordinary_matches", "ordinary_balls", "ordinary_wickets", "pressure_economy", "ordinary_economy", "economy_change", "pressure_wicket_rate_per_6", "ordinary_wicket_rate_per_6", "wicket_rate_change_per_6", "dot_share_change", "comparison_reasons", "cohort_note", "comparison_status"],
        )
        csv_download(bowler_comparisons, "Download bowling comparisons", "bowling_pressure_comparisons.csv", "bowling_comparison_download")

with tab_method:
    st.subheader("Confirmed rules and formulas")
    st.json(report.get("confirmed_choices", {}), expanded=True)
    st.json(report.get("definitions", {}), expanded=True)
    validation = report.get("validation", {})
    if validation:
        st.markdown("**Validation status**")
        st.write(validation.get("overall_status", "Not run"))
        log_rows = validation.get("validation_log", [])
        st.dataframe(log_rows, hide_index=True, width="stretch")
        csv_download(log_rows, "Download validation log", "pressure_validation_log.csv", "pressure_validation_download")
