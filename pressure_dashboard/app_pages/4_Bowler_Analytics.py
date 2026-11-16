from __future__ import annotations

from collections import Counter, defaultdict

import plotly.graph_objects as go
import streamlit as st

from lib.metrics import economy_rate, share, shrink_to_baseline, wicket_rate
from lib.death_study import (
    INDIA_DEATH_MIN_INNINGS,
    INDIA_DEATH_MIN_LEGAL_BALLS,
    INDIA_DEATH_MIN_SEASONS,
    india_death_bowler_rankings,
    india_death_bowler_study,
)
from lib.pressure_reports import pressure_report
from lib.queries import (
    bowler_profile,
    bowler_stats,
)
from lib.ui import BLUE, GOLD, ORDINARY, PRESSURE, SLATE, chart, csv_download, fmt_or_na, markdown_table, page_header, pct, year_axis

filters = st.session_state.get("dashboard_filters", {})
page_header(
    "Bowler analytics",
    "Control, wicket threat, discipline, and late-chase bowling pressure.",
    ":material/sports:",
)

ranking_filters = dict(filters)
ranking_filters["pressure_only"] = False
raw = bowler_stats(ranking_filters)
minimum = max(int(filters.get("min_balls", 30)), 30)
ranking_minimum = minimum
eligible = [row for row in raw if int(row.get("legal_balls") or 0) >= ranking_minimum]
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
sort_by = st.selectbox(
    "Rank by",
    ["Adjusted wicket rate", "Credited wickets", "Adjusted economy", "Bowler-charged economy proxy"],
    key="bowler_rank_metric",
)
sort_key = {
    "Credited wickets": "credited_wickets",
    "Bowler-charged economy proxy": "economy",
    "Adjusted economy": "adjusted_economy",
    "Adjusted wicket rate": "adjusted_wicket_rate",
}[sort_by]
rank_candidates = eligible
if sort_by == "Adjusted wicket rate":
    rank_candidates = [row for row in eligible if int(row.get("credited_wickets") or 0) >= 3]
for row in raw:
    row["sample_status"] = "Eligible sample" if int(row.get("legal_balls") or 0) >= ranking_minimum else "Review sample"
    row["ranking_eligible"] = row in rank_candidates
if sort_by in {"Bowler-charged economy proxy", "Adjusted economy"}:
    ranked = sorted(
        rank_candidates,
        key=lambda row: (
            row.get(sort_key) is None,
            row.get(sort_key) if row.get(sort_key) is not None else float("inf"),
            row.get("player") or "",
            int(row.get("player_id") or -1),
        ),
    )
else:
    ranked = sorted(
        rank_candidates,
        key=lambda row: (
            row.get(sort_key) is None,
            -(row.get(sort_key) if row.get(sort_key) is not None else float("-inf")),
            row.get("player") or "",
            int(row.get("player_id") or -1),
        ),
    )
if len(rank_candidates) < 10:
    ranked = sorted(raw, key=lambda row: (row.get("player") or "", int(row.get("player_id") or -1)))

pressure_data = pressure_report()
pressure_candidates = [
    row for row in pressure_data.get("bowler_table", [])
    if row.get("state") == "Bowling pressure"
]
pressure_state = next(
    (row for row in pressure_data.get("state_table", []) if row.get("state") == "Bowling pressure"),
    {},
)
pressure_legal = int(pressure_state.get("legal_balls") or 0)
pressure_decided_chases = int(pressure_state.get("decided_chases") or 0)
pressure_run_proxy = sum(int(row.get("runs") or 0) for row in pressure_candidates)
pressure_wickets = sum(int(row.get("credited_wickets") or 0) for row in pressure_candidates)
pressure_dots = sum(int(row.get("dots") or 0) for row in pressure_candidates)
pressure_reportable = pressure_decided_chases >= 20
pressure_economy = economy_rate(pressure_run_proxy, pressure_legal) if pressure_reportable else None
pressure_wicket_rate = wicket_rate(pressure_wickets, pressure_legal) if pressure_reportable else None
pressure_minimum = 30
reliable_pressure_candidates = [
    row for row in pressure_candidates
    if pressure_reportable
    and int(row.get("sample_balls") or 0) >= pressure_minimum
    and int(row.get("credited_wickets") or 0) >= 3
    and row.get("active_2026_all_venues")
    and int(row.get("recent_innings") or 0) >= 10
]
pressure_match_count = int(pressure_state.get("matches") or 0)
pressure_match_samples = sum(int(row.get("matches") or 0) for row in pressure_candidates)

st.caption(
    f"{len(eligible):,} bowlers meet the {ranking_minimum}-legal-ball minimum. "
    "Rankings use the full selected format, season, and country cohort; the pressure-only switch applies to the player profile. "
    "Adjusted rates blend each player with the eligible-cohort baseline using 60 prior legal balls."
    " Rate rankings require 3 credited wickets; cohorts with fewer than 10 eligible players are listed without ranks."
)
metric_row = st.columns(5, border=True)
metric_row[0].metric("Bowlers in cohort", f"{len(raw):,}")
metric_row[1].metric("Bowling-pressure legal balls", f"{pressure_legal:,}")
metric_row[2].metric("Pressure economy proxy", fmt_or_na(pressure_economy) if pressure_reportable else "Count only", f"{pressure_decided_chases:,} decided chases; 20 required")
metric_row[3].metric("Pressure wickets / 100", fmt_or_na(pressure_wicket_rate) if pressure_reportable else "Count only")
metric_row[4].metric("Pressure dot share", fmt_or_na(share(pressure_dots, pressure_legal)) if pressure_reportable else "Count only")
st.caption(
    "The pressure report uses all-venue T20 chases and requires 2 or fewer wickets down, ≤30 legal balls remaining, current scoring rate ≥11 RPO, "
    "and required run rate ≥9 RPO. Use economy and dot share to compare containment; use credited wickets per "
    f"100 legal balls to compare quick-wicket threat. Current sample: {pressure_legal} legal balls across "
    f"{pressure_match_count} matches and {pressure_match_samples} bowler-match appearances. "
    f"The state-level rates are {'reportable' if pressure_reportable else 'count only'} with {pressure_decided_chases} decided chases; 20 are required."
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
                ("runs_proxy", "Bowler-charged runs proxy"),
                ("economy", "Bowler-charged economy"),
                ("adjusted_economy", "Adjusted economy"),
                ("credited_wickets", "Credited wickets"),
                ("wicket_rate_100", "Wickets / 100"),
                ("dot_share", "Zero-run share"),
                ("wides", "Wides"),
                ("no_balls", "No-balls"),
                ("sample_status", "Sample"),
                ("ranking_eligible", "Rank eligible"),
            ],
        )
        csv_download(ranked[:500], "Download filtered bowler rankings", "bowler_rankings.csv", "bowler_rank_csv")
with right:
    with st.container(border=True):
        st.markdown("**Adjusted economy and wicket rate**")
        chart_rows = [
            row
            for row in eligible
            if int(row.get("credited_wickets") or 0) >= 3
            and row.get("adjusted_economy") is not None and row.get("adjusted_wicket_rate") is not None
        ]
        fig = go.Figure(
            go.Scatter(
                x=[row["adjusted_economy"] for row in chart_rows],
                y=[row["adjusted_wicket_rate"] for row in chart_rows],
                mode="markers",
                marker=dict(
                    size=[max(8, min(28, 7 + (row["legal_balls"] or 0) ** 0.5 / 3)) for row in chart_rows],
                    color=BLUE,
                    opacity=0.78,
                    line=dict(color="white", width=1),
                ),
                text=[row["player"] for row in chart_rows],
                customdata=[[row["legal_balls"], row["credited_wickets"]] for row in chart_rows],
                hovertemplate="%{text}<br>Adjusted economy %{x:.2f}<br>Adjusted wickets / 100 %{y:.2f}<br>Legal balls %{customdata[0]}<br>Credited wickets %{customdata[1]}<extra></extra>",
            )
        )
        fig.update_layout(xaxis_title="Adjusted bowler-charged economy proxy", yaxis_title="Adjusted credited wickets / 100 balls")
        if len(chart_rows) >= 10:
            chart(fig, "Adjusted bowling economy against adjusted wicket rate, bubble size shows legal balls", height=460)
        else:
            st.info(f"Only {len(chart_rows)} bowlers meet the 3-wicket comparison minimum; the rate comparison requires 10 eligible players.")

st.subheader("Bowling-pressure player figures")
st.caption(
    "All-venue T20 chases only: 2 or fewer wickets down, 1–30 legal balls remaining, current rate ≥11, and required rate ≥9. "
    "Composite: 40% adjusted-economy percentile, 40% adjusted wickets-per-6 percentile, and 20% dot-share percentile. "
    "At least 30 legal balls, 3 credited wickets, 2026 activity, 10 recent chase innings, and 10 eligible players are required to rank."
)
if not pressure_reportable:
    st.info(
        f"No bowling-pressure ranking is published: the cohort has {pressure_decided_chases} decided chases, "
        f"below the {20}-chase reporting minimum. The current state has {pressure_legal} legal balls across "
        f"{pressure_match_count} matches and {pressure_match_samples} bowler-match appearances."
    )
elif len(reliable_pressure_candidates) < 10:
    st.info(
        f"No bowling-pressure ranking is published: {len(reliable_pressure_candidates)} bowlers pass all individual gates; "
        f"at least 10 eligible players are needed. The state contains {pressure_legal} legal balls across "
        f"{pressure_match_count} matches and {pressure_match_samples} bowler-match appearances."
    )
if pressure_candidates:
    st.caption(
        f"No performance ordering is shown for rows below {pressure_minimum} qualifying legal balls. "
        "Players are also unranked until they have 3 credited wickets and pass recent activity/form gates."
    )
    observation_rows = sorted(
        pressure_candidates,
        key=lambda row: (
            -int(row.get("sample_balls") or 0),
            -int(row.get("matches") or 0),
            row.get("player") or "",
            int(row.get("player_id") or -1),
        ),
    )
    markdown_table(
        [
            {
                "player": row.get("player"),
                "pressure_matches": row.get("matches"),
                "pressure_legal_balls": row.get("sample_balls"),
                "pressure_runs": row.get("runs"),
                "pressure_economy": row.get("economy"),
                "adjusted_economy": row.get("adjusted_economy"),
                "pressure_dot_share": row.get("dot_share"),
                "pressure_credited_wickets": row.get("credited_wickets"),
                "pressure_wicket_rate_6": row.get("wicket_rate_per_6"),
                "adjusted_wicket_rate_6": row.get("adjusted_wicket_rate_per_6"),
                "recent_innings": row.get("recent_innings"),
                "active": row.get("active_2026_all_venues"),
                "ranking_reasons": row.get("ranking_reasons"),
                "sample": "Review sample"
                if int(row.get("sample_balls") or 0) < pressure_minimum
                else "Review sample" if not row.get("ranking_eligible") else "Eligible",
            }
            for row in observation_rows
        ],
        [
            ("player", "Bowler"),
            ("pressure_matches", "Pressure matches"),
            ("pressure_legal_balls", "Legal balls"),
            ("pressure_runs", "Runs conceded"),
            ("pressure_economy", "Raw economy"),
            ("adjusted_economy", "Adjusted economy"),
            ("pressure_dot_share", "Dot share %"),
            ("pressure_credited_wickets", "Credited wickets"),
            ("pressure_wicket_rate_6", "Raw wickets / 6"),
            ("adjusted_wicket_rate_6", "Adjusted wickets / 6"),
            ("recent_innings", "Recent innings"),
            ("active", "Played in 2026"),
            ("ranking_reasons", "Ranking gate detail"),
            ("sample", "Sample status"),
        ],
    )
else:
    st.info("No delivery in this filtered cohort meets the bowling-pressure rule.")

st.divider()
st.subheader("Death-over study · Indian venues")
st.caption(
    "This separate death-over study uses every supplied T20/T20I match at venues recorded in India, independent of the sidebar filters. "
    f"Death overs are 16–20. A bowler must have at least {INDIA_DEATH_MIN_LEGAL_BALLS} legal death balls, "
    f"{INDIA_DEATH_MIN_INNINGS} death-over innings, and appearances in {INDIA_DEATH_MIN_SEASONS} seasons. "
    "The economy uses the bowler-charged proxy; the source omits many extra-run amounts, so this remains an estimate. Pitch-level measurements are not present in the data."
)

death_bowlers = india_death_bowler_study()
death_eligible = india_death_bowler_rankings(death_bowlers)
st.caption(
    f"Coverage: {len(death_bowlers):,} bowlers, "
    f"{sum(int(row.get('legal_balls') or 0) for row in death_bowlers):,} legal death balls, "
    f"{sum(int(row.get('credited_wickets') or 0) for row in death_bowlers):,} credited wickets, and "
    f"{sum(int(row.get('death_innings') or 0) for row in death_bowlers):,} bowler-innings."
)

if death_eligible:

    best_balanced = death_eligible[0]
    best_containment = min(death_eligible, key=lambda row: row["economy_proxy"])
    best_consistency = max(death_eligible, key=lambda row: row["wicket_innings_pct"])
    best_volume = max(death_eligible, key=lambda row: (row["credited_wickets"], row["legal_balls"]))
    quickest_wickets = min(
        (row for row in death_eligible if row.get("balls_per_wicket") is not None),
        key=lambda row: row["balls_per_wicket"],
    )
    insight_cards = st.columns(3, border=True)
    insight_cards[0].metric("Best balanced profile", best_balanced["player"])
    insight_cards[0].caption(
        f"{best_balanced['credited_wickets']} wickets · {best_balanced['balls_per_wicket']:.2f} balls/wicket · "
        f"{best_balanced['economy_proxy']:.2f} economy proxy"
    )
    insight_cards[1].metric("Most consistent wicket threat", best_consistency["player"])
    insight_cards[1].caption(
        f"{best_consistency['wicket_innings']}/{best_consistency['death_innings']} death innings with a wicket · "
        f"{best_consistency['balls_per_wicket']:.2f} balls/wicket · {best_consistency['economy_proxy']:.2f} economy proxy"
    )
    insight_cards[2].metric("Most death-over wickets", best_volume["player"])
    insight_cards[2].caption(
        f"{best_volume['credited_wickets']} wickets · {best_volume['death_matches']} matches · "
        f"{best_volume['wicket_innings_pct']:.1f}% of death-over innings with a wicket"
    )
    st.caption(
        f"Lowest economy: {best_containment['player']} at {best_containment['economy_proxy']:.2f}. "
        f"Fastest wickets: {quickest_wickets['player']} every {quickest_wickets['balls_per_wicket']:.2f} balls "
        f"(economy {quickest_wickets['economy_proxy']:.2f}), showing the containment-versus-wicket-speed tradeoff."
    )
    st.caption(
        f"Balanced rank gives equal weight to lower economy, fewer balls per credited wicket, and a higher share of "
        f"death-over innings with at least one credited wicket and a higher dot-ball share. "
        f"{len(death_eligible)} bowlers meet the evidence minimum."
    )

    with st.container(border=True):
        st.markdown("**Top 10 balanced death-over profiles**")
        markdown_table(
            [
                {
                    "rank": i,
                    "player": row["player"],
                    "death_matches": row["death_matches"],
                    "legal_balls": row["legal_balls"],
                    "credited_wickets": row["credited_wickets"],
                    "balls_per_wicket": row["balls_per_wicket"],
                    "economy_proxy": row["economy_proxy"],
                    "wicket_innings_pct": row["wicket_innings_pct"],
                    "dot_pct": row["dot_pct"],
                }
                for i, row in enumerate(death_eligible[:10], 1)
            ],
            [
                ("rank", "Rank"),
                ("player", "Bowler"),
                ("death_matches", "Matches"),
                ("legal_balls", "Legal death balls"),
                ("credited_wickets", "Wickets"),
                ("balls_per_wicket", "Balls / wicket"),
                ("economy_proxy", "Economy proxy"),
                ("wicket_innings_pct", "Wicket innings %"),
                ("dot_pct", "Dot-ball %"),
            ],
        )
    with st.container(border=True):
        fig = go.Figure(
                go.Scatter(
                    x=[row["economy_proxy"] for row in death_eligible],
                    y=[row["balls_per_wicket"] for row in death_eligible],
                    mode="markers",
                    marker=dict(
                        size=[max(8, min(28, 6 + row["legal_balls"] ** 0.5 / 3)) for row in death_eligible],
                        color=[row["wicket_innings_pct"] for row in death_eligible],
                        coloraxis="coloraxis",
                        line=dict(color="white", width=0.7),
                        opacity=0.82,
                    ),
                    text=[row["player"] for row in death_eligible],
                    customdata=[
                        [row["credited_wickets"], row["legal_balls"], row["death_matches"], row["wicket_innings_pct"]]
                        for row in death_eligible
                    ],
                    hovertemplate=(
                        "%{text}<br>Economy proxy %{x:.2f}<br>Balls per wicket %{y:.1f}"
                        "<br>Credited wickets %{customdata[0]}<br>Death balls %{customdata[1]}"
                        "<br>Matches %{customdata[2]}<br>Wicket innings %{customdata[3]:.1f}%<extra></extra>"
                    ),
                )
        )
        fig.update_layout(
                xaxis_title="Economy proxy · lower is better",
                yaxis_title="Balls per credited wicket · lower is quicker",
                coloraxis=dict(
                    colorscale=[[0, SLATE], [0.5, ORDINARY], [1, "#99F6E4"]],
                    cmin=0,
                    cmax=100,
                    colorbar=dict(title="Wicket innings %"),
                ),
        )
        chart(
            fig,
            "Indian-venue death-over economy against balls per credited wicket; marker color shows wicket consistency and size shows legal-ball sample",
            height=460,
        )
else:
    st.info("No Indian-venue bowler meets the death-over evidence minimum in the supplied match data.")

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
        by_over[over]["runs"] += int(row.get("bowler_runs_proxy") or 0)
        by_over[over]["legal"] += int(row.get("legal") or 0)
        by_over[over]["wickets"] += int(row.get("credited_wicket") or 0)
        match_date = str(row.get("match_date") or "")
        year = match_date[:4] if len(match_date) >= 4 else "Unknown"
        by_year[year]["runs"] += int(row.get("bowler_runs_proxy") or 0)
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
        item["runs_proxy"] += int(row.get("bowler_runs_proxy") or 0)
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
            st.markdown("**Bowler-charged economy proxy by over number**")
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
            name="Bowler-charged economy proxy",
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
                ("runs_proxy", "Bowler-charged runs proxy"),
                ("economy", "Economy"),
                ("credited_wickets", "Credited wickets"),
                ("result", "Result"),
            ],
        )
