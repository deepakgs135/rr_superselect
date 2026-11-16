from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from lib.pressure_reports import clutch_batting_report, pressure_report
from lib.ui import PRESSURE, chart, csv_download, markdown_table, metric_row, page_header

report = pressure_report()
clutch_report = clutch_batting_report()
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

COLUMN_LABELS = {
    "state": "State", "delivery_rows": "Delivery rows", "matches": "Matches", "decided_chases": "Decided chases",
    "legal_balls": "Known legal balls", "players": "Players", "reporting_status": "Cohort reporting status",
    "rank": "Rank", "player": "Player", "player_id": "Source ID", "source_player": "Source name",
    "runs": "Runs", "sample_balls": "Balls", "strike_rate": "Raw SR", "adjusted_strike_rate": "Adjusted SR",
    "dismissals": "Dismissals", "average": "Raw average", "adjusted_average": "Adjusted average",
    "fours": "Fours", "sixes": "Sixes", "boundary_share": "Boundary share %", "dots": "Dot balls",
    "dot_share": "Dot share %", "recent_innings": "Recent innings", "recent_runs": "Recent runs",
    "recent_balls": "Recent balls", "recent_strike_rate": "Recent SR", "recent_dismissals": "Recent outs",
    "recent_average": "Recent average", "active_2026_all_venues": "Played in 2026", "sample_status": "Sample status",
    "recent_form_status": "Recent form", "ranking_reasons": "Ranking gate detail", "ranking_status": "Ranking status",
    "composite_score": "Composite / 100", "innings": "Innings", "deliveries": "State deliveries",
    "economy": "Raw economy", "adjusted_economy": "Adjusted economy", "credited_wickets": "Credited wickets",
    "balls_per_wicket": "Balls / wicket", "wicket_rate_per_6": "Raw wickets / 6", "adjusted_wicket_rate_per_6": "Adjusted wickets / 6",
    "boundaries_conceded": "Boundaries conceded", "recent_economy": "Recent economy", "recent_wickets": "Recent wickets",
    "wicket_rate_status": "Wicket-rate sample", "pressure_matches": "Pressure matches", "pressure_balls": "Pressure balls",
    "ordinary_matches": "Ordinary matches", "ordinary_balls": "Ordinary balls", "pressure_runs": "Pressure runs",
    "ordinary_runs": "Ordinary runs", "pressure_sr": "Pressure SR", "ordinary_sr": "Ordinary SR",
    "sr_uplift": "SR uplift", "pressure_average": "Pressure average", "ordinary_average": "Ordinary average",
    "average_change": "Average change", "boundary_share_change": "Boundary-share change", "cohort_note": "Cohort note",
    "comparison_status": "Comparison status", "comparison_reasons": "Comparison gate detail", "pressure_wickets": "Pressure wickets",
    "ordinary_wickets": "Ordinary wickets", "pressure_economy": "Pressure economy", "ordinary_economy": "Ordinary economy",
    "economy_change": "Economy change", "pressure_wicket_rate_per_6": "Pressure wickets / 6",
    "ordinary_wicket_rate_per_6": "Ordinary wickets / 6", "wicket_rate_change_per_6": "Wicket-rate change / 6",
    "dot_share_change": "Dot-share change", "check": "Check", "raw": "Raw", "processed": "Processed", "status": "Status",
    "source_player_id": "Source ID", "reference_status": "Source check", "all_reference_figures_match": "All figures match",
    "reference_innings": "List innings", "source_innings": "Raw innings", "reference_balls": "List balls", "source_balls": "Raw balls",
    "reference_runs": "List runs", "source_runs": "Raw runs", "reference_strike_rate": "List SR", "source_strike_rate": "Raw SR",
    "reference_balls_per_innings": "List balls / innings", "source_balls_per_innings": "Raw balls / innings",
    "reference_boundaries_per_100": "List boundaries / 100", "source_boundaries_per_100": "Raw boundaries / 100",
    "reference_dot_pct": "List dot %", "source_dot_pct": "Raw dot %",
    "reference_stayed_to_16": "List stayed to 16", "source_stayed_to_16": "Raw stayed to 16",
    "sample_status": "Sample status", "matches": "Matches", "innings": "Innings", "balls": "Balls",
    "strike_rate": "Strike rate", "balls_per_innings": "Balls / innings", "boundaries_per_100": "Boundaries / 100 balls",
    "dot_pct": "Dot %", "stayed_to_16": "Stayed through 16 overs", "dismissals": "Dismissals",
    "source_active_2026_all_venues": "Active in 2026", "source_recent_chase_innings": "Known chase innings",
    "selection_gate_status": "Earlier selection gates", "active_2026_all_venues": "Active in 2026",
    "recent_chase_innings": "Known chase innings", "boundaries": "Boundaries",
    "base_eligible": "Passes data gates", "user_excluded": "Excluded by review", "exclusion_reason": "Exclusion reason",
    "adjusted_sr_percentile": "SR percentile", "adjusted_average_percentile": "Average percentile",
    "boundary_share_percentile": "Boundary percentile", "weighted_sr_points": "SR points",
    "weighted_average_points": "Average points", "weighted_boundary_points": "Boundary points",
    "entry_legal_balls_bowled": "Entry after legal balls", "entry_over": "Entry over",
    "anchor_legal_balls": "Anchor after legal balls", "anchor_wickets_down": "Anchor wickets down",
    "anchor_required_rate": "Anchor required rate", "batting_order": "Batting position",
    "fours": "Fours", "sixes": "Sixes", "dismissal_types": "Dismissal",
    "raw_entry_overs": "Raw entry overs", "reference_entry_overs": "Supplied entry overs",
    "raw_innings": "Raw chase entries", "reference_innings": "Supplied entries",
    "raw_median_entry_over": "Raw median entry over", "reference_median_entry_over": "Supplied median",
    "raw_came_before_anchor": "Raw came in before anchor", "reference_came_before_anchor": "Supplied came in before anchor",
    "identity_status": "Player ID check", "matches_reference": "Matches supplied row",
    "match_format": "Format", "match_date": "Match date",
    "competition": "Competition", "match_id": "Match ID", "anchor_over": "Anchor over",
    "came_in_before_anchor": "Entered before anchor",
}


def pressure_table(rows, columns, *, max_height=560):
    markdown_table(
        rows,
        [(key, COLUMN_LABELS.get(key, key.replace("_", " ").title())) for key in columns],
        max_height=max_height,
    )

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
pressure_table(
    states,
    ["state", "delivery_rows", "matches", "decided_chases", "legal_balls", "players", "reporting_status"],
    max_height=None,
)

tab_bat, tab_clutch, tab_bowl, tab_comp, tab_method = st.tabs(["Batting", "Clutch batting", "Bowling", "Pressure comparisons", "Rules & validation"])

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
            pressure_table(
                ranked_batters[:10],
                ["rank", "player", "sample_balls", "runs", "strike_rate", "adjusted_strike_rate", "dismissals", "average", "adjusted_average", "boundary_share", "composite_score"],
                max_height=None,
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
        pressure_table(
            pressure_batters,
            ["rank", "player", "player_id", "matches", "deliveries", "runs", "sample_balls", "strike_rate", "adjusted_strike_rate", "dismissals", "average", "adjusted_average", "fours", "sixes", "boundary_share", "dots", "dot_share", "recent_innings", "recent_runs", "recent_balls", "recent_strike_rate", "recent_dismissals", "recent_average", "active_2026_all_venues", "sample_status", "recent_form_status", "ranking_reasons", "ranking_status"],
            max_height=560,
        )
    csv_download(pressure_batters, "Download batting-pressure figures", "batter_pressure_figures.csv", "pressure_batter_download")

    st.subheader("Ordinary batting chase control")
    ordinary_batters = [row for row in batters if row.get("state") == "Ordinary batting chase"]
    pressure_table(
        ordinary_batters,
        ["rank", "player", "matches", "runs", "sample_balls", "strike_rate", "adjusted_strike_rate", "dismissals", "average", "adjusted_average", "boundary_share", "sample_status", "recent_form_status", "ranking_reasons", "ranking_status"],
        max_height=560,
    )
    csv_download(ordinary_batters, "Download ordinary batting figures", "ordinary_batting_figures.csv", "ordinary_batter_download")

with tab_clutch:
    st.subheader("Indian-venue clutch batting window")
    st.caption(
        "Second-innings chases only. The anchor is the first known delivery with 2–4 wickets down, "
        "18–42 legal balls already bowled, required rate 12–20, and runs still needed. Batter figures start on the anchor delivery."
    )
    if not clutch_report:
        st.info("The clutch report has not been built yet. Run the dashboard data build to create it.")
    else:
        cohort = clutch_report.get("cohort", {})
        audit_summary = clutch_report.get("reference_audit", {})
        metric_row(
            [
                ("Qualifying anchor chases", f"{int(cohort.get('anchor_chases') or 0):,}", f"{int(cohort.get('decided_anchor_chases') or 0):,} decided."),
                ("Players with 30+ balls", f"{int(cohort.get('players_meeting_30_ball_minimum') or 0):,}", "Minimum applied to the anchor-to-innings sample."),
                ("Players passing prior activity gates", f"{int(cohort.get('players_meeting_30_ball_2026_activity_and_10_recent_chase_gates') or 0):,}", "30+ balls, a 2026 T20 appearance, and 10+ known chase innings."),
                ("Supplied rows reproduced", f"{int(audit_summary.get('rows_matching_all_figures') or 0)}/{int(audit_summary.get('rows_compared') or 0)}", "Every displayed source figure is checked against the raw CSVs."),
            ]
        )
        excluded_names = ", ".join(row["player"] for row in clutch_report.get("user_excluded_players", []))
        if excluded_names:
            st.caption(f"Excluded from the final ranking at your request: {excluded_names}. Their raw figures remain in the full audit.")
        if audit_summary.get("status") != "MATCH":
            st.warning(
                "The figures in the supplied Top 10 table do not reproduce from the current raw CSVs. "
                "The table below keeps your requested player order but displays raw-recomputed values alongside your reference values."
            )
        entry_audit = clutch_report.get("entry_timing_audit", {})
        entry_summary = entry_audit.get("summary", [])
        if entry_summary:
            st.subheader("Raw entry-over check against your supplied batter list")
            st.caption(entry_audit.get("scope", "Entry details rebuilt from the raw source files."))
            format_counts = entry_audit.get("format_anchor_chases", {})
            metric_row(
                [
                    ("Qualifying raw anchor chases", f"{int(entry_audit.get('anchor_chases') or 0):,}",
                     f"T20: {int(format_counts.get('T20') or 0):,}; T20I: {int(format_counts.get('T20I') or 0):,}."),
                    ("Entry rows matching supplied values",
                     f"{int(entry_audit.get('reference_rows_matching') or 0)}/{int(entry_audit.get('reference_rows_compared') or 0)}",
                     "Raw entries are compared by sequence, median entry over, and came-before-anchor count."),
                ]
            )
            pressure_table(
                entry_summary,
                [
                    "rank", "player", "player_id", "raw_entry_overs", "reference_entry_overs",
                    "raw_median_entry_over", "reference_median_entry_over", "raw_came_before_anchor",
                    "reference_came_before_anchor", "identity_status", "status",
                ],
                max_height=500,
            )
            csv_download(
                entry_summary,
                "Download raw entry-over comparison",
                "raw_clutch_entry_over_comparison.csv",
                "raw_entry_over_comparison_download",
            )
            with st.expander("Match-by-match raw entry and anchor evidence", expanded=False):
                entry_innings = entry_audit.get("innings", [])
                pressure_table(
                    entry_innings,
                    [
                        "player", "player_id", "match_date", "competition", "match_format", "match_id",
                        "entry_over", "anchor_over", "anchor_legal_balls", "anchor_wickets_down",
                        "anchor_required_rate", "came_in_before_anchor",
                    ],
                    max_height=560,
                )
                csv_download(
                    entry_innings,
                    "Download raw match-by-match entry details",
                    "raw_clutch_entry_over_innings.csv",
                    "raw_entry_over_innings_download",
                )
        st.subheader("Raw-data ranks 1–20 by the confirmed batting composite")
        st.caption(clutch_report.get("definition", {}).get("composite_formula", ""))
        computed_top_twenty = clutch_report.get("computed_top_twenty", clutch_report.get("computed_top_ten", []))
        if computed_top_twenty:
            pressure_table(
                computed_top_twenty,
                [
                    "rank", "player", "player_id", "innings", "balls", "runs", "strike_rate", "adjusted_strike_rate",
                    "average", "adjusted_average", "fours", "sixes", "boundaries_per_100", "dots", "dot_pct",
                    "stayed_to_16", "composite_score",
                ],
                max_height=620,
            )
            fig = go.Figure(
                go.Bar(
                    x=[row["composite_score"] for row in reversed(computed_top_twenty)],
                    y=[row["player"] for row in reversed(computed_top_twenty)],
                    orientation="h",
                    marker_color=PRESSURE,
                    customdata=[[row["balls"], row["runs"], row["strike_rate"]] for row in reversed(computed_top_twenty)],
                    hovertemplate="%{y}<br>Composite %{x:.1f}/100<br>Balls %{customdata[0]}<br>Runs %{customdata[1]}<br>Raw SR %{customdata[2]:.1f}<extra></extra>",
                )
            )
            fig.update_layout(xaxis_title="Weighted composite score · 0–100", yaxis_title="")
            chart(fig, "Top 20 clutch batters by the confirmed weighted batting composite", height=620)
            csv_download(computed_top_twenty, "Download raw-data clutch ranks 1–20", "clutch_batting_top20.csv", "clutch_batting_top20_download")
        else:
            st.info(clutch_report.get("ranking_status", "No clutch ranking is available."))

        st.subheader("Candidate checks under the exact anchor rule")
        st.caption(clutch_report.get("definition", {}).get("unweighted_diagnostics", ""))
        player_rows_by_name = {row.get("player"): row for row in clutch_report.get("player_rows", [])}
        investigation_names = [
            "Tilak Varma", "Namboori Tilak Varma", "Marcus Stoinis", "Hardik Pandya", "Nicholas Pooran",
            "Tim David", "Rinku Singh", "Rajat Patidar", "Ayush Badoni", "Sanju Samson", "Nitish Rana",
            "David Miller", "Aiden Markram", "Liam Livingstone", "Sherfane Rutherford",
        ]
        investigation_rows = []
        used_ids = set()
        for player_name in investigation_names:
            row = player_rows_by_name.get(player_name)
            if row and row.get("player_id") not in used_ids:
                investigation_rows.append(row)
                used_ids.add(row.get("player_id"))
        pressure_table(
            investigation_rows,
            [
                "rank", "player_id", "player", "sample_status", "innings", "balls", "runs", "strike_rate",
                "average", "adjusted_strike_rate", "adjusted_sr_percentile", "adjusted_average_percentile",
                "boundary_share_percentile", "boundaries_per_100", "dots", "dot_pct", "stayed_to_16", "composite_score",
            ],
            max_height=500,
        )
        csv_download(investigation_rows, "Download candidate comparison", "clutch_candidate_comparison.csv", "clutch_candidate_comparison_download")
        with st.expander("Candidate innings by match", expanded=False):
            innings_audit = clutch_report.get("candidate_innings_audit", [])
            pressure_table(
                innings_audit,
                [
                    "player", "player_id", "match_date", "match_id", "batting_order", "anchor_legal_balls",
                    "anchor_wickets_down", "anchor_required_rate", "entry_over", "balls", "runs", "strike_rate",
                    "fours", "sixes", "dots", "dot_pct", "dismissals", "dismissal_types",
                ],
                max_height=560,
            )
            csv_download(innings_audit, "Download candidate innings audit", "clutch_candidate_innings_audit.csv", "clutch_candidate_innings_download")

        st.markdown("**Requested ten players: supplied figures vs raw-data figures**")
        audit_rows = clutch_report.get("reference_audit_rows", [])
        pressure_table(
            audit_rows,
            [
                "rank", "player", "source_player_id", "reference_status", "reference_innings", "source_innings",
                "reference_balls", "source_balls", "reference_runs", "source_runs", "reference_strike_rate", "source_strike_rate",
                "reference_balls_per_innings", "source_balls_per_innings", "reference_boundaries_per_100", "source_boundaries_per_100",
                "reference_dot_pct", "source_dot_pct", "reference_stayed_to_16", "source_stayed_to_16",
                "source_active_2026_all_venues", "source_recent_chase_innings", "selection_gate_status", "all_reference_figures_match",
            ],
            max_height=560,
        )
        chart_rows = [row for row in audit_rows if row.get("source_strike_rate") is not None]
        if chart_rows:
            fig = go.Figure()
            fig.add_bar(
                name="Supplied SR",
                x=[row["reference_strike_rate"] for row in chart_rows],
                y=[row["player"] for row in chart_rows],
                orientation="h",
                marker_color=PRESSURE,
            )
            fig.add_bar(
                name="Raw-data SR",
                x=[row["source_strike_rate"] for row in chart_rows],
                y=[row["player"] for row in chart_rows],
                orientation="h",
                marker_color="#3A8078",
            )
            fig.update_layout(barmode="group", xaxis_title="Strike rate", yaxis_title="", yaxis={"categoryorder": "array", "categoryarray": [row["player"] for row in reversed(chart_rows)]})
            chart(fig, "Supplied and raw-data strike rates for the ten requested clutch batters", height=430)
        csv_download(audit_rows, "Download supplied-list audit", "clutch_batter_reference_audit.csv", "clutch_reference_audit_download")

        with st.expander("All batters in the clutch window", expanded=False):
            player_rows = clutch_report.get("player_rows", [])
            pressure_table(
                player_rows,
                ["rank", "player_id", "player", "sample_status", "base_eligible", "user_excluded", "exclusion_reason", "active_2026_all_venues", "recent_chase_innings", "selection_gate_status", "innings", "matches", "balls", "runs", "strike_rate", "adjusted_strike_rate", "average", "adjusted_average", "balls_per_innings", "boundaries", "boundaries_per_100", "dots", "dot_pct", "dismissals", "stayed_to_16", "composite_score", "ranking_status"],
                max_height=560,
            )
            csv_download(player_rows, "Download all clutch-window batter figures", "clutch_batter_figures.csv", "clutch_batter_figures_download")

        with st.expander("Anchor matches and state details", expanded=False):
            pressure_table(
                clutch_report.get("anchor_matches", []),
                ["match_id", "match_date", "competition", "legal_balls_bowled", "anchor_over", "wickets_down", "target", "score_before", "runs_needed", "required_rate", "decided_chase"],
                max_height=560,
            )
            csv_download(clutch_report.get("anchor_matches", []), "Download anchor-match details", "clutch_anchor_chases.csv", "clutch_anchor_download")

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
        pressure_table(
            ranked_bowlers[:10],
            ["rank", "player", "sample_balls", "runs", "economy", "adjusted_economy", "credited_wickets", "wicket_rate_per_6", "adjusted_wicket_rate_per_6", "dot_share", "composite_score"],
            max_height=None,
        )
    else:
        st.info(report.get("ranking_status", {}).get("Bowling pressure", "No player is rank-eligible under the current gates."))
    pressure_table(
        pressure_bowlers,
        ["rank", "player", "player_id", "matches", "deliveries", "runs", "sample_balls", "economy", "adjusted_economy", "credited_wickets", "balls_per_wicket", "wicket_rate_per_6", "adjusted_wicket_rate_per_6", "dots", "dot_share", "boundaries_conceded", "recent_innings", "recent_runs", "recent_balls", "recent_economy", "recent_wickets", "active_2026_all_venues", "sample_status", "wicket_rate_status", "recent_form_status", "ranking_reasons", "ranking_status"],
        max_height=560,
    )
    csv_download(pressure_bowlers, "Download bowling-pressure figures", "bowler_pressure_figures.csv", "pressure_bowler_download")

    st.subheader("Ordinary bowling chase control")
    ordinary_bowlers = [row for row in bowlers if row.get("state") == "Ordinary bowling chase"]
    pressure_table(
        ordinary_bowlers,
        ["rank", "player", "matches", "runs", "sample_balls", "economy", "adjusted_economy", "credited_wickets", "balls_per_wicket", "wicket_rate_per_6", "adjusted_wicket_rate_per_6", "dot_share", "boundaries_conceded", "sample_status", "ranking_status"],
        max_height=560,
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
        pressure_table(
            batter_comparisons,
            ["player", "pressure_matches", "pressure_balls", "ordinary_matches", "ordinary_balls", "pressure_runs", "ordinary_runs", "pressure_sr", "ordinary_sr", "sr_uplift", "pressure_average", "ordinary_average", "average_change", "boundary_share_change", "comparison_reasons", "cohort_note", "comparison_status"],
            max_height=520,
        )
        csv_download(batter_comparisons, "Download batting comparisons", "batting_pressure_comparisons.csv", "batting_comparison_download")
    with comp_bowl:
        pressure_table(
            bowler_comparisons,
            ["player", "pressure_matches", "pressure_balls", "pressure_wickets", "ordinary_matches", "ordinary_balls", "ordinary_wickets", "pressure_economy", "ordinary_economy", "economy_change", "pressure_wicket_rate_per_6", "ordinary_wicket_rate_per_6", "wicket_rate_change_per_6", "dot_share_change", "comparison_reasons", "cohort_note", "comparison_status"],
            max_height=520,
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
        pressure_table(log_rows, ["check", "raw", "processed", "status"], max_height=None)
        csv_download(log_rows, "Download validation log", "pressure_validation_log.csv", "pressure_validation_download")
