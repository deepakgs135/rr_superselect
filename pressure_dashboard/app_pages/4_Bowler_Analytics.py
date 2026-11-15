from __future__ import annotations

from collections import Counter, defaultdict

import plotly.graph_objects as go
import streamlit as st

from lib.metrics import economy_rate, share, shrink_to_baseline, wicket_rate
from lib.queries import bowler_profile, bowler_stats
from lib.ui import BLUE, GOLD, ORDINARY, PRESSURE, chart, csv_download, fmt_or_na, markdown_table, page_header, pct, year_axis

filters = st.session_state.get("dashboard_filters", {})
page_header(
    "Bowler analytics",
    "Control, wicket threat, discipline, and late-chase bowling pressure.",
    ":material/sports:",
)

raw = bowler_stats(filters)
minimum = int(filters.get("min_balls", 30))
eligible = [row for row in raw if int(row.get("legal_balls") or 0) >= minimum]
cohort_runs = sum(int(row.get("runs_proxy") or 0) for row in eligible)
cohort_balls = sum(int(row.get("legal_balls") or 0) for row in eligible)
cohort_wickets = sum(int(row.get("credited_wickets") or 0) for row in eligible)
base_economy = economy_rate(cohort_runs, cohort_balls)
base_wicket_rate = wicket_rate(cohort_wickets, cohort_balls)

for row in raw:
    legal_balls = int(row.get("legal_balls") or 0)
    runs = int(row.get("runs_proxy") or 0)
    wickets = int(row.get("credited_wickets") or 0)
    row["economy"] = economy_rate(runs, legal_balls)
    row["wicket_rate_100"] = wicket_rate(wickets, legal_balls)
    row["wicket_strike_rate"] = round(legal_balls / wickets, 2) if wickets else None
    row["dot_share"] = share(int(row.get("dots") or 0), legal_balls)
    row["boundary_events_per_100"] = share(int(row.get("boundary_events") or 0), legal_balls)
    row["adjusted_economy"] = shrink_to_baseline(row["economy"], legal_balls, base_economy, 60)
    row["adjusted_wicket_rate"] = shrink_to_baseline(
        row["wicket_rate_100"], legal_balls, base_wicket_rate, 60
    )
    pressure_balls = int(row.get("pressure_legal_balls") or 0)
    row["pressure_economy"] = economy_rate(
        int(row.get("pressure_runs_proxy") or 0), pressure_balls
    )
    row["pressure_wicket_rate_100"] = wicket_rate(
        int(row.get("pressure_credited_wickets") or 0), pressure_balls
    )
    row["pressure_dot_share"] = share(
        int(row.get("pressure_dots") or 0), pressure_balls
    )
    ind_balls = int(row.get("india_legal_balls") or 0)
    ind_runs = int(row.get("india_runs_proxy") or 0)
    ind_wkts = int(row.get("india_credited_wickets") or 0)
    ind_inns = int(row.get("india_innings") or 0)
    ind_p_balls = int(row.get("india_pressure_legal_balls") or 0)
    ind_p_runs = int(row.get("india_pressure_runs_proxy") or 0)
    ind_p_wkts = int(row.get("india_pressure_credited_wickets") or 0)
    ind_p_dots = int(row.get("india_pressure_dots") or 0)
    row["india_economy"] = economy_rate(ind_runs, ind_balls)
    row["india_pressure_economy"] = economy_rate(ind_p_runs, ind_p_balls)
    row["india_pressure_wicket_rate_100"] = wicket_rate(ind_p_wkts, ind_p_balls)
    row["india_pressure_dot_share"] = share(ind_p_dots, ind_p_balls)
    row["is_eligible_india_performer"] = (
        ind_inns >= 15
        and ind_balls >= 240
        and (row["india_economy"] is not None and row["india_economy"] <= 8.65)
        and ind_p_balls >= 24
        and ind_p_wkts >= 2
        and (row["india_pressure_economy"] is not None and row["india_pressure_economy"] <= 9.60)
    )

ctrl_c1, ctrl_c2 = st.columns([1.4, 1])
with ctrl_c1:
    only_india_eligible = st.toggle(
        "Only eligible bowlers who performed well on Indian pitches (≥ 15 India innings · India Econ ≤ 8.65 · ≥ 24 India pressure balls · ≥ 2 India pressure wickets)",
        value=True,
        key="bowler_only_india_eligible",
    )
with ctrl_c2:
    sort_by = st.selectbox(
        "Rank by",
        ["Credited wickets", "Raw economy proxy", "Adjusted economy", "Adjusted wicket rate"],
        key="bowler_rank_metric",
    )

active_pool = [
    row for row in eligible
    if (row.get("is_eligible_india_performer") if only_india_eligible else True)
]
sort_key = {
    "Credited wickets": "credited_wickets",
    "Raw economy proxy": "economy",
    "Adjusted economy": "adjusted_economy",
    "Adjusted wicket rate": "adjusted_wicket_rate",
}[sort_by]
if sort_by in {"Raw economy proxy", "Adjusted economy"}:
    ranked = sorted(active_pool, key=lambda row: (row.get(sort_key) is None, row.get(sort_key) or 0, row.get("player") or ""))
else:
    ranked = sorted(active_pool, key=lambda row: (row.get(sort_key) is None, -(row.get(sort_key) or 0), row.get("player") or ""))

pressure_legal = sum(int(row.get("pressure_legal_balls") or 0) for row in raw)
pressure_run_proxy = sum(int(row.get("pressure_runs_proxy") or 0) for row in raw)
pressure_wickets = sum(int(row.get("pressure_credited_wickets") or 0) for row in raw)
pressure_dots = sum(int(row.get("pressure_dots") or 0) for row in raw)
pressure_economy = economy_rate(pressure_run_proxy, pressure_legal)
pressure_wicket_rate = wicket_rate(pressure_wickets, pressure_legal)

st.caption(
    f"{len(eligible):,} bowlers meet the {minimum}-legal-ball minimum. "
    "Adjusted rates blend each player with the filtered cohort baseline using 60 prior legal balls."
)
metric_row = st.columns(5, border=True)
metric_row[0].metric("Bowlers in cohort", f"{len(raw):,}")
metric_row[1].metric("Bowling-pressure legal balls", f"{pressure_legal:,}")
metric_row[2].metric("Pressure economy proxy", fmt_or_na(pressure_economy))
metric_row[3].metric("Pressure wickets / 100", fmt_or_na(pressure_wicket_rate))
metric_row[4].metric("Pressure dot share", fmt_or_na(share(pressure_dots, pressure_legal)))
st.caption(
    "Bowling pressure requires exactly 2 wickets lost, ≤30 legal balls remaining, current scoring rate ≥11 RPO, "
    "and required run rate ≥9 RPO. Use economy and dot share to compare containment; use credited wickets per "
    "100 legal balls to compare quick-wicket threat. The event sample is small, so check each bowler's ball count."
)

left, right = st.columns([1.25, 1])
with left:
    with st.container(border=True):
        st.markdown("**Bowler leaderboard**")
        markdown_table(
            ranked[:30],
            [
                ("player", "Bowler"),
                ("matches", "Matches"),
                ("innings", "Innings"),
                ("legal_balls", "Legal balls"),
                ("runs_proxy", "Raw runs proxy"),
                ("economy", "Raw economy"),
                ("adjusted_economy", "Adjusted economy"),
                ("credited_wickets", "Credited wickets"),
                ("wicket_rate_100", "Wickets / 100"),
                ("dot_share", "Zero-run share"),
                ("wides", "Wides"),
                ("no_balls", "No-balls"),
            ],
        )
        csv_download(ranked[:500], "Download filtered bowler rankings", "bowler_rankings.csv", "bowler_rank_csv")
with right:
    with st.container(border=True):
        st.markdown("**Adjusted economy and wicket rate**")
        chart_rows = [
            row
            for row in eligible
            if row.get("adjusted_economy") is not None and row.get("adjusted_wicket_rate") is not None
        ]
        fig = go.Figure(
            go.Scatter(
                x=[row["adjusted_economy"] for row in chart_rows],
                y=[row["adjusted_wicket_rate"] for row in chart_rows],
                mode="markers",
                marker=dict(
                    size=[max(8, min(28, 7 + (row["legal_balls"] or 0) ** 0.5 / 3)) for row in chart_rows],
                    color=[row["pressure_economy"] if row["pressure_economy"] is not None else row["adjusted_economy"] for row in chart_rows],
                    colorscale=[[0, ORDINARY], [0.6, BLUE], [1, PRESSURE]],
                    opacity=0.78,
                    line=dict(color="white", width=1),
                    colorbar=dict(title="Pressure econ."),
                ),
                text=[row["player"] for row in chart_rows],
                customdata=[[row["legal_balls"], row["credited_wickets"], row["pressure_economy"]] for row in chart_rows],
                hovertemplate="%{text}<br>Adjusted economy %{x:.2f}<br>Adjusted wickets / 100 %{y:.2f}<br>Legal balls %{customdata[0]}<br>Credited wickets %{customdata[1]}<br>Pressure economy %{customdata[2]:.2f}<extra></extra>",
            )
        )
        fig.update_layout(xaxis_title="Adjusted raw economy proxy", yaxis_title="Adjusted credited wickets / 100 balls")
        chart(fig, "Adjusted bowling economy against adjusted wicket rate, bubble size shows legal balls", height=460)

st.subheader("Pressure economy distribution")
pressure_rates = [
    row["pressure_economy"]
    for row in raw
    if row.get("pressure_economy") is not None
    and int(row.get("pressure_legal_balls") or 0) > 0
]
fig = go.Figure(
    go.Histogram(
        x=pressure_rates,
        nbinsx=24,
        marker_color=PRESSURE,
        opacity=0.8,
        name="Bowlers",
        hovertemplate="Pressure economy %{x:.2f}<br>Bowlers %{y}<extra></extra>",
    )
)
if base_economy is not None:
    fig.add_vline(
        x=base_economy,
        line_dash="dash",
        line_color=ORDINARY,
        annotation_text=f"All-state baseline {base_economy:.2f}",
    )
fig.update_layout(xaxis_title="Pressure raw economy proxy", yaxis_title="Bowlers")
chart(fig, "Distribution of bowler pressure economy compared with the cohort baseline", height=330)
st.caption(
    f"Shows all bowlers with at least one qualifying ball ({len(pressure_rates)} bowlers); "
    f"the general {minimum}-ball minimum is not applied to this rare scenario."
)

st.subheader("Bowling-pressure recommendations")
pressure_leaders = [row for row in raw if int(row.get("pressure_legal_balls") or 0) > 0]
containment_leaders = sorted(
    pressure_leaders,
    key=lambda row: (
        row.get("pressure_economy") if row.get("pressure_economy") is not None else float("inf"),
        -(row.get("pressure_dot_share") or 0),
        -int(row.get("pressure_legal_balls") or 0),
        row.get("player") or "",
    ),
)
wicket_leaders = sorted(
    pressure_leaders,
    key=lambda row: (
        -(row.get("pressure_wicket_rate_100") or 0),
        row.get("pressure_economy") if row.get("pressure_economy") is not None else float("inf"),
        -int(row.get("pressure_legal_balls") or 0),
        row.get("player") or "",
    ),
)
if pressure_leaders:
    st.caption(
        "Historical signals for the exact bowling-pressure state. Containment ranks lower economy then more dots; "
        "quick wickets ranks credited-wicket rate. Ball counts are shown because these samples are small."
    )
    contain_col, wicket_col = st.columns(2)
    with contain_col:
        with st.container(border=True):
            st.markdown("**Containment · economy then dots**")
            markdown_table(
                [
                    {
                        "player": row.get("player"),
                        "pressure_legal_balls": row.get("pressure_legal_balls"),
                        "pressure_economy": row.get("pressure_economy"),
                        "pressure_dot_share": row.get("pressure_dot_share"),
                    }
                    for row in containment_leaders[:10]
                ],
                [
                    ("player", "Bowler"),
                    ("pressure_legal_balls", "Legal balls"),
                    ("pressure_economy", "Economy proxy"),
                    ("pressure_dot_share", "Dot share %"),
                ],
            )
    with wicket_col:
        with st.container(border=True):
            st.markdown("**Quick wickets · credited-wicket rate**")
            markdown_table(
                [
                    {
                        "player": row.get("player"),
                        "pressure_legal_balls": row.get("pressure_legal_balls"),
                        "pressure_credited_wickets": row.get("pressure_credited_wickets"),
                        "pressure_wicket_rate_100": row.get("pressure_wicket_rate_100"),
                        "pressure_economy": row.get("pressure_economy"),
                    }
                    for row in wicket_leaders[:10]
                ],
                [
                    ("player", "Bowler"),
                    ("pressure_legal_balls", "Legal balls"),
                    ("pressure_credited_wickets", "Credited wickets"),
                    ("pressure_wicket_rate_100", "Wickets / 100"),
                    ("pressure_economy", "Economy proxy"),
                ],
            )
else:
    st.info("No bowler has qualifying deliveries under the bowling-pressure rule in this filtered cohort.")

st.divider()
st.subheader("Bowler profile")
if not raw:
    st.info("No bowler rows match the selected filters.")
else:
    player_options = sorted(raw, key=lambda row: (row.get("player") or "", int(row.get("player_id") or 0)))
    labels = {
        f"{row.get('player') or 'Unknown'} · ID {row['player_id']}": int(row["player_id"])
        for row in player_options
    }
    selected_label = st.selectbox("Select a bowler", list(labels), key="bowler_profile_player")
    player_id = labels[selected_label]
    profile = bowler_profile(filters, player_id)
    wicket_types = Counter()
    by_over: dict[int, dict[str, int]] = defaultdict(lambda: {"runs": 0, "legal": 0, "wickets": 0})
    by_year: dict[str, dict[str, int]] = defaultdict(lambda: {"runs": 0, "legal": 0, "wickets": 0})
    by_match: dict[tuple[int, int], dict[str, Any]] = {}
    wides = 0
    no_balls = 0
    unknown = 0
    for row in profile:
        extra = (row.get("extras_type") or "").casefold()
        wides += int(extra == "wide")
        no_balls += int(extra == "overstep")
        unknown += int(row.get("unknown_legality") or 0)
        if row.get("credited_wicket"):
            wicket_types[(row.get("dismissal_type") or "Unknown").strip() or "Unknown"] += 1
        over = int(row.get("over_no") or 0)
        by_over[over]["runs"] += int(row.get("total_runs_proxy") or 0)
        by_over[over]["legal"] += int(row.get("legal") or 0)
        by_over[over]["wickets"] += int(row.get("credited_wicket") or 0)
        match_date = str(row.get("match_date") or "")
        year = match_date[:4] if len(match_date) >= 4 else "Unknown"
        by_year[year]["runs"] += int(row.get("total_runs_proxy") or 0)
        by_year[year]["legal"] += int(row.get("legal") or 0)
        by_year[year]["wickets"] += int(row.get("credited_wicket") or 0)
        key = (int(row["match_id"]), int(row["innings"]))
        item = by_match.setdefault(
            key,
            {
                "match_id": row["match_id"],
                "date": row.get("match_date") or "",
                "innings": row["innings"],
                "venue_id": row.get("venue_id") or "",
                "runs_proxy": 0,
                "legal_balls": 0,
                "credited_wickets": 0,
                "result": row.get("result") or "",
            },
        )
        item["runs_proxy"] += int(row.get("total_runs_proxy") or 0)
        item["legal_balls"] += int(row.get("legal") or 0)
        item["credited_wickets"] += int(row.get("credited_wicket") or 0)

    profile_left, profile_right = st.columns(2)
    with profile_left:
        with st.container(border=True):
            st.markdown("**Credited wickets by dismissal type**")
            kinds = wicket_types.most_common()
            fig = go.Figure(
                go.Bar(
                    x=[count for _, count in kinds],
                    y=[kind for kind, _ in kinds],
                    orientation="h",
                    marker_color=GOLD,
                )
            )
            fig.update_layout(xaxis_title="Credited wickets", yaxis_title="")
            chart(fig, "Bowler wickets by credited dismissal type", height=320)
    with profile_right:
        with st.container(border=True):
            st.markdown("**Raw economy proxy by over number**")
            overs = sorted(by_over.items())
            fig = go.Figure(
                go.Scatter(
                    x=[over for over, _ in overs],
                    y=[economy_rate(value["runs"], value["legal"]) for _, value in overs],
                    mode="lines+markers",
                    line=dict(color=BLUE, width=3),
                    customdata=[[value["legal"], value["wickets"]] for _, value in overs],
                    hovertemplate="Over %{x}<br>Economy %{y:.2f}<br>Known legal balls %{customdata[0]}<br>Credited wickets %{customdata[1]}<extra></extra>",
                )
            )
            fig.update_layout(xaxis_title="Over number", yaxis_title="Economy proxy")
            chart(fig, "Bowler economy proxy by over number", height=320)

    year_items = sorted(
        by_year.items(),
        key=lambda item: (int(item[0]) if item[0].isdigit() else 0, item[0]),
    )
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[year for year, _ in year_items],
            y=[economy_rate(value["runs"], value["legal"]) for _, value in year_items],
            name="Raw economy proxy",
            mode="lines+markers",
            line=dict(color=ORDINARY, width=3),
        )
    )
    fig.update_layout(xaxis_title="Year", yaxis_title="Economy proxy")
    year_axis(fig, [year for year, _ in year_items])
    chart(fig, "Bowler economy proxy trend by calendar year", height=300)

    st.markdown(
        f"**Discipline and coverage:** {wides:,} wides · {no_balls:,} Overstep/no-ball rows · "
        f"{unknown:,} unknown-legality rows."
    )
    match_rows = []
    for row in sorted(by_match.values(), key=lambda item: (item["date"], item["match_id"]), reverse=True)[:25]:
        match_rows.append(
            {
                **row,
                "economy": economy_rate(row["runs_proxy"], row["legal_balls"]),
            }
        )
    with st.container(border=True):
        st.markdown("**Recent match log**")
        markdown_table(
            match_rows,
            [
                ("date", "Date"),
                ("match_id", "Match"),
                ("innings", "Inn."),
                ("venue_id", "Venue ID"),
                ("legal_balls", "Legal balls"),
                ("runs_proxy", "Raw runs proxy"),
                ("economy", "Economy"),
                ("credited_wickets", "Credited wickets"),
                ("result", "Result"),
            ],
        )
