from __future__ import annotations

from lib.metrics import economy_rate, strike_rate, wicket_rate
from lib.db import quality_report
from lib.player_names import PLAYER_DISPLAY_OVERRIDES, PLAYER_REFERENCE_URLS, PLAYER_SOURCE_LABELS
from lib.queries import batter_stats, bowler_stats, source_batter_stats, source_bowler_stats
from lib.ui import PRESSURE, chart, markdown_table, metric_row, page_header
import streamlit as st
import plotly.graph_objects as go

filters = st.session_state.get("dashboard_filters", {})
page_header(
    "Leaderboard and raw-record audit",
    "Top players, their role-specific pressure values, and a check against independent raw CSV aggregates.",
    ":material/fact_check:",
)

# The audit always compares complete batting and bowling records for the selected
# format, season, and country cohort. The pressure-only toggle is a delivery view.
audit_filters = dict(filters)
audit_filters["pressure_only"] = False
minimum = int(filters.get("min_balls", 30))

batter_rows = batter_stats(audit_filters)
bowler_rows = bowler_stats(audit_filters)
source_batters = {int(row["player_id"]): row for row in source_batter_stats(audit_filters)}
source_bowlers = {int(row["player_id"]): row for row in source_bowler_stats(audit_filters)}

eligible_batters = [row for row in batter_rows if int(row.get("balls") or 0) >= minimum]
eligible_bowlers = [row for row in bowler_rows if int(row.get("legal_balls") or 0) >= minimum]


def verified_batters() -> list[dict]:
    top = sorted(
        eligible_batters,
        key=lambda row: (-int(row.get("runs") or 0), row.get("player") or "", int(row.get("player_id") or -1)),
    )[:10]
    output = []
    for rank, row in enumerate(top, 1):
        source = source_batters.get(int(row["player_id"]), {})
        checked_fields = ("matches", "runs", "balls", "dismissals", "fours", "sixes")
        matches_raw = all(int(row.get(key) or 0) == int(source.get(key) or 0) for key in checked_fields)
        variants = int(source.get("source_name_variants") or 0)
        name_ok = variants == 1 and str(row.get("source_player") or "") == str(source.get("source_name") or "")
        output.append(
            {
                "rank": rank,
                "player": row.get("player"),
                "player_id": row.get("player_id"),
                "raw_source_name": source.get("source_names") or row.get("source_player"),
                "matches": row.get("matches"),
                "dashboard_runs": row.get("runs"),
                "raw_runs": source.get("runs"),
                "dashboard_balls": row.get("balls"),
                "raw_balls": source.get("balls"),
                "pressure_runs": row.get("pressure_runs"),
                "pressure_balls": row.get("pressure_balls"),
                "pressure_sr": strike_rate(int(row.get("pressure_runs") or 0), int(row.get("pressure_balls") or 0)),
                "check": "PASS" if matches_raw and name_ok else "REVIEW",
            }
        )
    return output


def verified_bowlers() -> list[dict]:
    top = sorted(
        eligible_bowlers,
        key=lambda row: (-int(row.get("credited_wickets") or 0), row.get("player") or "", int(row.get("player_id") or -1)),
    )[:10]
    output = []
    for rank, row in enumerate(top, 1):
        source = source_bowlers.get(int(row["player_id"]), {})
        checked_fields = ("matches", "runs_proxy", "legal_balls", "wicket_events", "credited_wickets")
        matches_raw = all(int(row.get(key) or 0) == int(source.get(key) or 0) for key in checked_fields)
        variants = int(source.get("source_name_variants") or 0)
        name_ok = variants == 1 and str(row.get("source_player") or "") == str(source.get("source_name") or "")
        output.append(
            {
                "rank": rank,
                "player": row.get("player"),
                "player_id": row.get("player_id"),
                "raw_source_name": source.get("source_names") or row.get("source_player"),
                "matches": row.get("matches"),
                "dashboard_wickets": row.get("credited_wickets"),
                "raw_wickets": source.get("credited_wickets"),
                "dashboard_legal_balls": row.get("legal_balls"),
                "raw_legal_balls": source.get("legal_balls"),
                "pressure_wickets": row.get("pressure_credited_wickets"),
                "pressure_legal_balls": row.get("pressure_legal_balls"),
                "pressure_economy_proxy": economy_rate(
                    int(row.get("pressure_runs_proxy") or 0),
                    int(row.get("pressure_legal_balls") or 0),
                ),
                "check": "PASS" if matches_raw and name_ok else "REVIEW",
            }
        )
    return output

batter_audit = verified_batters()
bowler_audit = verified_bowlers()
batter_pass = sum(row["check"] == "PASS" for row in batter_audit)
bowler_pass = sum(row["check"] == "PASS" for row in bowler_audit)
metric_row(
    [
        ("Top batters checked", f"{batter_pass}/{len(batter_audit)}", "Dashboard runs, balls, dismissals, boundaries, matches, and source name."),
        ("Top bowlers checked", f"{bowler_pass}/{len(bowler_audit)}", "Dashboard wickets, legal balls, run proxy, matches, and source name."),
        ("Minimum sample", f"{minimum} balls", "Applied to the overall top 10 qualification."),
        ("Name display corrections", f"{len(PLAYER_DISPLAY_OVERRIDES)}", "Raw source names remain visible in the audit tables."),
    ]
)

st.caption(
    "The audit re-aggregates the raw ball_by_ball.csv independently, keyed by match, innings, and player ID. "
    "This checks the supplied dataset; it does not compare the selected partial seasons with complete career totals. "
    "Format, season, and country filters apply. The pressure-only toggle does not narrow this audit."
)
quality = quality_report().get("quality", {})
pressure_matches = int(quality.get("workbook_pressure_count_matches") or 0)
pressure_comparisons = int(quality.get("workbook_pressure_count_comparisons") or 0)
st.info(
    f"Batter leaders use the batting-pressure rule and bowler leaders use the separate bowling-pressure rule. "
    f"Workbook reconciliation checks batting-pressure counts: {pressure_matches:,} of "
    f"{pressure_comparisons:,} comparable match counts match exactly; review the Reconciliation page for details.",
    title="Pressure counts need reconciliation",
)

left, right = st.columns(2)
with left:
    with st.container(border=True):
        st.subheader("Top 10 batters by runs")
        markdown_table(
            batter_audit,
            [
                ("rank", "#"),
                ("player", "Batter"),
                ("player_id", "Source ID"),
                ("raw_source_name", "Raw source name"),
                ("matches", "Matches"),
                ("dashboard_runs", "Dashboard runs"),
                ("raw_runs", "Raw CSV runs"),
                ("dashboard_balls", "Dashboard balls"),
                ("raw_balls", "Raw CSV balls"),
                ("pressure_runs", "Pressure runs"),
                ("pressure_balls", "Pressure balls"),
                ("pressure_sr", "Pressure SR"),
                ("check", "Audit"),
            ],
        )
with right:
    with st.container(border=True):
        st.subheader("Top 10 bowlers by credited wickets")
        markdown_table(
            bowler_audit,
            [
                ("rank", "#"),
                ("player", "Bowler"),
                ("player_id", "Source ID"),
                ("raw_source_name", "Raw source name"),
                ("matches", "Matches"),
                ("dashboard_wickets", "Dashboard wickets"),
                ("raw_wickets", "Raw CSV wickets"),
                ("dashboard_legal_balls", "Dashboard legal balls"),
                ("raw_legal_balls", "Raw CSV legal balls"),
                ("pressure_wickets", "Bowling-pressure wickets"),
                ("pressure_legal_balls", "Bowling-pressure legal balls"),
                ("pressure_economy_proxy", "Bowling-pressure economy proxy"),
                ("check", "Audit"),
            ],
        )

st.subheader("Pressure leaders · role-specific pressure states")
st.caption(
    f"Batters need at least {minimum} batting-pressure balls. Bowling-pressure leaders include every bowler "
    "with a qualifying legal ball because the exact chase scenario is uncommon. Bowling wickets count only "
    "caught, bowled, LBW, stumped, and hit-wicket dismissals."
)
pressure_batters = [row for row in batter_rows if int(row.get("pressure_balls") or 0) >= minimum]
pressure_batters.sort(
    key=lambda row: (-int(row.get("pressure_runs") or 0), row.get("player") or "", int(row.get("player_id") or -1))
)
pressure_batter_table = [
    {
        "player": row.get("player"),
        "player_id": row.get("player_id"),
        "raw_source_name": row.get("source_player"),
        "matches": row.get("matches"),
        "pressure_runs": row.get("pressure_runs"),
        "pressure_balls": row.get("pressure_balls"),
        "pressure_sr": strike_rate(int(row.get("pressure_runs") or 0), int(row.get("pressure_balls") or 0)),
        "pressure_wicket_events": row.get("pressure_wicket_events"),
    }
    for row in pressure_batters[:10]
]
pressure_bowlers = [row for row in bowler_rows if int(row.get("pressure_legal_balls") or 0) > 0]
pressure_bowlers.sort(
    key=lambda row: (
        -float(wicket_rate(
            int(row.get("pressure_credited_wickets") or 0),
            int(row.get("pressure_legal_balls") or 0),
        ) or 0),
        float(economy_rate(
            int(row.get("pressure_runs_proxy") or 0),
            int(row.get("pressure_legal_balls") or 0),
        ) or float("inf")),
        -int(row.get("pressure_legal_balls") or 0),
        row.get("player") or "",
    )
)
pressure_bowler_table = [
    {
        "player": row.get("player"),
        "player_id": row.get("player_id"),
        "raw_source_name": row.get("source_player"),
        "matches": row.get("matches"),
        "pressure_wickets": row.get("pressure_credited_wickets"),
        "pressure_legal_balls": row.get("pressure_legal_balls"),
        "wickets_per_100": wicket_rate(
            int(row.get("pressure_credited_wickets") or 0),
            int(row.get("pressure_legal_balls") or 0),
        ),
        "pressure_economy_proxy": economy_rate(
            int(row.get("pressure_runs_proxy") or 0),
            int(row.get("pressure_legal_balls") or 0),
        ),
        "sample": "Review sample" if int(row.get("pressure_legal_balls") or 0) < minimum else "Eligible",
    }
    for row in pressure_bowlers[:10]
]

left, right = st.columns(2)
with left:
    with st.container(border=True):
        st.markdown("**Pressure runs by batter**")
        fig = go.Figure(
            go.Bar(
                x=[row["pressure_runs"] for row in pressure_batter_table],
                y=[row["player"] for row in pressure_batter_table],
                orientation="h",
                customdata=[[row["pressure_balls"]] for row in pressure_batter_table],
                marker_color=PRESSURE,
                hovertemplate="%{y}<br>Pressure runs %{x}<br>Pressure balls %{customdata[0]}<extra></extra>",
            )
        )
        fig.update_layout(xaxis_title="Runs in batting pressure", yaxis_title="", yaxis=dict(autorange="reversed"))
        chart(fig, "Top batters by runs scored during batting pressure", height=340)
with right:
    with st.container(border=True):
        st.markdown("**Pressure wickets by bowler**")
        fig = go.Figure(
            go.Bar(
                x=[row["pressure_wickets"] for row in pressure_bowler_table],
                y=[row["player"] for row in pressure_bowler_table],
                orientation="h",
                customdata=[[row["pressure_legal_balls"]] for row in pressure_bowler_table],
                marker_color=PRESSURE,
                hovertemplate="%{y}<br>Credited bowling-pressure wickets %{x}<br>Bowling-pressure legal balls %{customdata[0]}<extra></extra>",
            )
        )
        fig.update_layout(xaxis_title="Credited wickets in bowling pressure", yaxis_title="", yaxis=dict(autorange="reversed"))
        chart(fig, "Top bowlers by credited wickets during bowling pressure", height=340)

left, right = st.columns(2)
with left:
    with st.container(border=True):
        st.markdown("**Top pressure batters by pressure runs**")
        markdown_table(
            pressure_batter_table,
            [
                ("player", "Batter"),
                ("player_id", "Source ID"),
                ("raw_source_name", "Raw source name"),
                ("matches", "Matches"),
                ("pressure_runs", "Runs"),
                ("pressure_balls", "Balls"),
                ("pressure_sr", "Pressure SR"),
                ("pressure_wicket_events", "Dismissals"),
            ],
        )
with right:
    with st.container(border=True):
        st.markdown("**Top pressure bowlers by credited wickets**")
        markdown_table(
            pressure_bowler_table,
            [
                ("player", "Bowler"),
                ("player_id", "Source ID"),
                ("raw_source_name", "Raw source name"),
                ("matches", "Matches"),
                ("pressure_wickets", "Wkts"),
                ("pressure_legal_balls", "Legal balls"),
                ("wickets_per_100", "Wkts / 100"),
                ("pressure_economy_proxy", "Economy proxy"),
                ("sample", "Sample"),
            ],
        )

st.subheader("Player-name references")
reference_rows = []
for player_id, standard_name in PLAYER_DISPLAY_OVERRIDES.items():
    source_name = next(
        (
            row.get("source_player")
            for row in batter_rows + bowler_rows
            if int(row.get("player_id") or -1) == player_id
        ),
        PLAYER_SOURCE_LABELS.get(player_id, ""),
    )
    reference_rows.append(
        {
            "player_id": player_id,
            "raw_source_name": source_name,
            "dashboard_display_name": standard_name,
            "official_reference": f"[Official profile]({PLAYER_REFERENCE_URLS[player_id]})",
        }
    )
markdown_table(
    reference_rows,
    [
        ("player_id", "Source ID"),
        ("raw_source_name", "Raw label"),
        ("dashboard_display_name", "Dashboard name"),
        ("official_reference", "Name reference"),
    ],
)
st.caption(
    "Tilak Varma and MS Dhoni use common cricket display names in dashboards; "
    "their supplied source labels are retained above and in the raw data."
)

if batter_audit and batter_pass < len(batter_audit) or bowler_audit and bowler_pass < len(bowler_audit):
    st.warning("One or more leaderboard rows need review against the raw source aggregation.", title="Record mismatch")
else:
    st.success("The displayed overall top-player aggregates match the independent raw CSV aggregation.", title="Raw record check passed")
