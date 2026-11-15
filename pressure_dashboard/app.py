from __future__ import annotations

import streamlit as st

from lib.db import database_ready
from lib.queries import filter_options

st.set_page_config(
    page_title="Pressure Analytics",
    page_icon=":material/sports_cricket:",
    layout="wide",
    initial_sidebar_state="expanded",
)

if not database_ready():
    st.title(":material/sports_cricket: Pressure analytics")
    st.error(
        "Processed data is not built yet.",
        icon=":material/database_off:",
    )
    st.markdown("From the project folder, build the local database first:")
    st.code("python build/build_data.py\nstreamlit run app.py", language="powershell")
    st.stop()

options = filter_options()
formats = options["formats"]
seasons = options["seasons"]
countries = options["countries"]

with st.sidebar:
    st.markdown("## :material/sports_cricket: Pressure analytics")
    st.caption(
        f"{options.get('matches', 0):,} matches · "
        f"{options.get('deliveries', 0):,} delivery rows"
    )
    st.divider()

    selected_formats = st.multiselect(
        "Format",
        formats,
        default=formats,
        help="T20 and T20I are kept as separate format cohorts in the analytics.",
        key="global_formats",
    )
    if seasons:
        selected_range = st.select_slider(
            "Season range",
            options=seasons,
            value=(seasons[0], seasons[-1]),
            key="global_season_range",
        )
        start = seasons.index(selected_range[0])
        end = seasons.index(selected_range[1])
        selected_seasons = seasons[start : end + 1]
    else:
        selected_seasons = []

    country_options = ["All countries", *countries]
    selected_country = st.selectbox(
        "Venue country",
        country_options,
        index=0,
        key="global_country",
    )
    min_balls = st.number_input(
        "Minimum balls for rankings",
        min_value=0,
        max_value=600,
        value=30,
        step=10,
        help="Used to keep player rankings from over-weighting very small samples.",
        key="global_min_balls",
    )
    pressure_only = st.toggle(
        "Pressure-only delivery views",
        value=False,
        help=(
            "Limits batter profiles to batting-pressure deliveries and bowler profiles to "
            "bowling-pressure deliveries. Overview, match-list, and venue chase summaries "
            "continue to use batting pressure. Ordinary-versus-pressure and scenario "
            "comparisons keep both states."
        ),
        key="global_pressure_only",
    )
    st.divider()
    st.caption(
        "**Batting pressure:** pre-ball chase state with RRR ≥ 15, 30 or fewer known legal balls left, "
        "and at least 3 wickets lost."
    )
    st.caption(
        "**Bowling pressure:** exactly 2 wickets lost in the final 30 known-legal balls, with current scoring rate ≥ 11 RPO "
        "and required rate ≥ 9 RPO. Compare economy and dot share for containment, and credited wickets for quick-wicket threat."
    )
    st.caption("Venue labels use the supplied venue ID and country; no ground-name file was provided.")
    st.caption("All analytics run locally from the processed database.")

st.session_state["dashboard_filters"] = {
    "formats": list(selected_formats),
    "seasons": list(selected_seasons),
    "country": selected_country,
    "min_balls": int(min_balls),
    "pressure_only": bool(pressure_only),
}

pages = {
    "Explore": [
        st.Page("app_pages/1_Overview.py", title="Overview", icon=":material/space_dashboard:", default=True),
        st.Page("app_pages/2_Ordinary_vs_Pressure.py", title="Ordinary vs pressure", icon=":material/compare_arrows:"),
        st.Page("app_pages/7_Chase_Scenarios.py", title="Chase scenarios", icon=":material/grid_view:"),
    ],
    "Players": [
        st.Page("app_pages/3_Batter_Analytics.py", title="Batter analytics", icon=":material/sports_cricket:"),
        st.Page("app_pages/4_Bowler_Analytics.py", title="Bowler analytics", icon=":material/sports:"),
    ],
    "Matches & venues": [
        st.Page("app_pages/5_Match_Analytics.py", title="Match analytics", icon=":material/scoreboard:"),
        st.Page("app_pages/6_Venue_Analytics.py", title="Venue analytics", icon=":material/stadium:"),
    ],
    "Audit": [
        st.Page("app_pages/8_Reconciliation.py", title="Reconciliation", icon=":material/difference:"),
        st.Page("app_pages/9_Data_Quality.py", title="Data quality", icon=":material/fact_check:"),
        st.Page("app_pages/10_Leaderboard_Audit.py", title="Leaderboard audit", icon=":material/verified:")
    ],
}

navigation = st.navigation(pages, position="sidebar")
navigation.run()
