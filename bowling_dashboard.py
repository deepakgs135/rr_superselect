"""Consolidated Bowling Analytics Dashboard for IPL (T20) & T20 Internationals (T20I)."""

from __future__ import annotations

from html import escape
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from pure_engine import DataFrame, np, pd, px

TEAL = "#0f766e"
AMBER = "#d97706"
NAVY = "#0f172a"
SLATE = "#334155"
INK = "#0f172a"
MUTED_TEXT = "#334155"

SCALE = [[0.0, "#14b8a6"], [0.5, "#0284c7"], [1.0, "#1e3a8a"]]
CATEGORY = ["#0f766e", "#d97706", "#2563eb", "#7c3aed", "#db2777", "#059669", "#dc2626", "#4f46e5"]
PLAYER_COLOURS = [TEAL, AMBER]

MIN_VENUE_BALLS = 30
MIN_INNINGS_COMPARE = 10

DISMISSAL_LABELS = {
    "Bowled": "Bowled",
    "Caught": "Caught",
    "Hit Wicket": "Hit wicket",
    "Hit wicket": "Hit wicket",
    "LBW": "LBW",
    "Stump": "Stumped",
    "Stumped": "Stumped",
}


def fmt_overs(balls: float | int) -> str:
    b = int(round(float(balls or 0)))
    return f"{b // 6}.{b % 6}"


@st.cache_data(show_spinner="Loading bowling innings…")
def load_bowling_innings(path: Path) -> DataFrame:
    df = pd.read_csv(path, low_memory=False)
    df["innings"] = pd.to_numeric(df["innings"], errors="coerce")
    df = df[df["innings"] <= 2].copy()

    num_cols = [
        "balls_bowled", "runs_conceded", "wickets", "maidens", "dots",
        "fours_conceded", "sixes_conceded", "boundary_runs_conceded",
        "wides", "noballs", "pp_balls", "pp_runs", "pp_wickets", "pp_dots",
        "mid_balls", "mid_runs", "mid_wickets", "mid_dots",
        "death_balls", "death_runs", "death_wickets", "death_dots",
    ]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["date"] = pd.to_datetime(df["match_date"], errors="coerce", dayfirst=True)
    df["year"] = df["year"].fillna(df["date"].dt.year).astype(int)
    df["season"] = df["year"].astype(str)

    df["match_format"] = df["match_format"].fillna("T20I").astype(str).str.strip()
    df["is_ipl"] = df["match_format"].eq("T20")
    df["bowling_team_won"] = df["bowling_team_won"].astype(str).str.lower().eq("true")
    df["bowling_type"] = df["bowling_type"].fillna("Unknown").astype(str)
    df["pace_or_spin"] = df["pace_or_spin"].fillna("Unknown").astype(str)
    df["overs"] = [fmt_overs(b) for b in df["balls_bowled"]]

    df["venue"] = "Venue " + df["venue_id"].astype(str)
    if "venue_country" in df.columns:
        df["venue_country"] = df["venue_country"].fillna("Unknown").astype(str)
        df["pitch_region"] = np.where(
            df["venue_country"].str.strip().str.lower().eq("india"),
            "Indian venue",
            "Overseas venue",
        )
    else:
        df["venue_country"] = "Unknown"
        df["pitch_region"] = "Unknown"
    return df


@st.cache_data
def load_bowling_wickets(path: Path) -> DataFrame | None:
    if not path.exists():
        return None
    d = pd.read_csv(path)
    if {"player_id", "dismissal_type", "wicket_count"}.issubset(d.columns):
        d["player_id"] = pd.to_numeric(d["player_id"], errors="coerce")
        d["wicket_count"] = pd.to_numeric(d["wicket_count"], errors="coerce").fillna(0).astype(int)
        d = d[d["dismissal_type"].notna() & (d["dismissal_type"].astype(str).str.strip() != "")].copy()
        d["dismissal_type"] = d["dismissal_type"].map(DISMISSAL_LABELS).fillna(d["dismissal_type"])
        return d
    return None


@st.cache_data(show_spinner="Loading bowling pressure matrix…")
def load_bowling_pressure(path: Path) -> DataFrame | None:
    if not path.exists():
        return None
    p = pd.read_csv(path)
    for col in p.columns:
        if col.endswith(("_balls", "_runs", "_wickets", "_dots", "_boundaries", "_matches", "_wins")):
            p[col] = pd.to_numeric(p[col], errors="coerce").fillna(0).astype(int)
        elif col.endswith(("_econ", "_sr", "_avg", "_dot_pct", "_boundary_pct", "_win_pct")):
            p[col] = pd.to_numeric(p[col], errors="coerce")
    return p


def bowling_totals(df: DataFrame) -> dict:
    balls = float(df["balls_bowled"].sum())
    runs = float(df["runs_conceded"].sum())
    wickets = int(df["wickets"].sum())
    dots = float(df["dots"].sum())
    maidens = int(df["maidens"].sum())
    bnd_runs = float(df["boundary_runs_conceded"].sum())
    return {
        "innings": len(df),
        "matches": df["match_id"].nunique(),
        "bowlers": df["bowler_id"].nunique(),
        "balls": int(balls),
        "overs_str": fmt_overs(balls),
        "runs": int(runs),
        "wickets": wickets,
        "maidens": maidens,
        "average": runs / wickets if wickets > 0 else np.nan,
        "economy": 6.0 * runs / balls if balls > 0 else np.nan,
        "strike_rate": balls / wickets if wickets > 0 else np.nan,
        "dot_pct": 100.0 * dots / balls if balls > 0 else np.nan,
        "boundary_pct": 100.0 * bnd_runs / runs if runs > 0 else np.nan,
        "three_w": int((df["wickets"] >= 3).sum()),
        "four_w": int((df["wickets"] == 4).sum()),
        "five_w": int((df["wickets"] >= 5).sum()),
    }


def bowler_table(df: DataFrame) -> DataFrame:
    df_work = df.assign(
        is_3w=(df["wickets"] >= 3).astype(int),
        is_4w=(df["wickets"] == 4).astype(int),
        is_5w=(df["wickets"] >= 5).astype(int),
    )
    g = df_work.groupby(["bowler_id", "bowler_name"], as_index=False).agg(
        innings=("wickets", "size"),
        balls=("balls_bowled", "sum"),
        runs=("runs_conceded", "sum"),
        wickets=("wickets", "sum"),
        maidens=("maidens", "sum"),
        dots=("dots", "sum"),
        boundary_runs=("boundary_runs_conceded", "sum"),
        three_w=("is_3w", "sum"),
        four_w=("is_4w", "sum"),
        five_w=("is_5w", "sum"),
    )

    best_map = {}
    type_map = {}
    ps_map = {}
    for b_name, sub in df_work.groupby("bowler_name", sort=False):
        if len(sub) > 0:
            r0 = sub.iloc[0]
            type_map[b_name] = str(r0.get("bowling_type", "Unknown") or "Unknown")
            ps_map[b_name] = str(r0.get("pace_or_spin", "Unknown") or "Unknown")
            s_best = sub.sort_values(["wickets", "runs_conceded", "balls_bowled"], ascending=[False, True, False]).iloc[0]
            best_map[b_name] = f"{int(s_best['wickets'])}/{int(s_best['runs_conceded'])}"
        else:
            type_map[b_name] = "Unknown"
            ps_map[b_name] = "Unknown"
            best_map[b_name] = "0/0"

    g["bowling_type"] = g["bowler_name"].map(type_map)
    g["pace_or_spin"] = g["bowler_name"].map(ps_map)
    g["best_bowling"] = g["bowler_name"].map(best_map)
    g["overs"] = [fmt_overs(b) for b in g["balls"]]
    g["average"] = np.where(g["wickets"] > 0, g["runs"] / g["wickets"].replace(0, np.nan), np.nan)
    g["economy"] = np.where(g["balls"] > 0, 6.0 * g["runs"] / g["balls"].replace(0, np.nan), np.nan)
    g["strike_rate"] = np.where(g["wickets"] > 0, g["balls"] / g["wickets"].replace(0, np.nan), np.nan)
    g["dot_pct"] = np.where(g["balls"] > 0, 100.0 * g["dots"] / g["balls"].replace(0, np.nan), np.nan)
    g["boundary_pct"] = np.where(g["runs"] > 0, 100.0 * g["boundary_runs"] / g["runs"].replace(0, np.nan), np.nan)
    return g


def render_bowling_dashboard(
    bowling_file: Path,
    wicket_file: Path,
    style_fn,
    kpi_fn,
    fmt_fn,
    html_table_fn,
    pressure_file: Path | None = None,
):
    if not bowling_file.exists():
        st.error(f"Missing consolidated bowling file: {bowling_file}")
        st.stop()

    if pressure_file is None:
        pressure_file = bowling_file.parent / "pressure_bowler_summary.csv"

    raw_b = load_bowling_innings(bowling_file)
    wickets_raw = load_bowling_wickets(wicket_file)
    bowl_pressure_raw = load_bowling_pressure(pressure_file)

    with st.sidebar:
        st.markdown("### Bowling filters")
        formats = sorted(raw_b["match_format"].dropna().astype(str).unique())
        sel_formats = st.multiselect(
            "Match format (T20 = IPL · T20I = Intl)",
            formats,
            default=formats,
            key="bowl_formats",
        )

        years = sorted(raw_b["year"].dropna().astype(int).unique())
        y0, y1 = st.select_slider("Years", options=years, value=(years[0], years[-1]), key="bowl_years")

        ps_opts = sorted([x for x in raw_b["pace_or_spin"].dropna().unique() if x and x != "Unknown"])
        sel_ps = st.multiselect("Pace or Spin", ps_opts, default=ps_opts, key="bowl_ps")

        teams = sorted(raw_b["bowling_team"].dropna().unique())
        sel_teams = st.multiselect("Bowling team (optional)", teams, key="bowl_teams")

        st.markdown("---")
        st.caption(
            "Super overs excluded. Legal balls exclude wides & no-balls. "
            "Bowler runs exclude byes & leg-byes. T20 = IPL · T20I = T20 Internationals."
        )

    fb = raw_b[raw_b["match_format"].isin(sel_formats) & raw_b["year"].between(y0, y1)]
    if sel_ps:
        fb = fb[fb["pace_or_spin"].isin(sel_ps)]
    if sel_teams:
        fb = fb[fb["bowling_team"].isin(sel_teams)]

    if fb.empty:
        st.warning("No bowling spells match these filters. Widen the years, formats, or bowling types.")
        st.stop()

    tb_all = bowling_totals(fb)
    st.markdown(
        "<div class='hero'><h1>Bowling insights</h1>"
        f"<p>{tb_all['innings']:,} bowling innings · {tb_all['matches']:,} matches · "
        f"{tb_all['bowlers']:,} bowlers · {tb_all['wickets']:,} wickets · "
        f"{tb_all['overs_str']} overs in the selected view</p></div>",
        unsafe_allow_html=True,
    )

    bt_all = bowler_table(fb)
    bowlers_by_wkts = bt_all.sort_values(["wickets", "balls"], ascending=[False, False])["bowler_name"].tolist()
    bowlers_eligible = (
        bt_all[bt_all["innings"] >= MIN_INNINGS_COMPARE]
        .sort_values(["wickets", "balls"], ascending=[False, False])["bowler_name"]
        .tolist()
    )

    tab_over, tab_profile, tab_innings, tab_h2h, tab_board, tab_venue, tab_pressure, tab_about = st.tabs(
        [
            "Overview",
            "Bowler profile",
            "Innings",
            "Bowler vs bowler",
            "Player leaderboard",
            "Venue fit",
            "Pressure",
            "About",
        ]
    )

    # ------------------------------------------------------------------------
    # 1. Overview
    # ------------------------------------------------------------------------
    with tab_over:
        st.markdown("#### Headline bowling numbers")
        cols = st.columns(6)
        with cols[0]:
            kpi_fn("Wickets", f"{tb_all['wickets']:,}")
        with cols[1]:
            kpi_fn("Bowling innings", f"{tb_all['innings']:,}")
        with cols[2]:
            kpi_fn("Bowling average", fmt_fn(tb_all["average"]))
        with cols[3]:
            kpi_fn("Economy rate", fmt_fn(tb_all["economy"], 2))
        with cols[4]:
            kpi_fn("Bowling strike rate", fmt_fn(tb_all["strike_rate"]))
        with cols[5]:
            kpi_fn("Dot ball % · 3W+ hauls", f"{fmt_fn(tb_all['dot_pct'])}% · {tb_all['three_w']:,}")

        st.markdown("")
        left, right = st.columns([1.4, 1])
        with left:
            season = fb.groupby(["year", "season"], as_index=False).agg(
                wickets=("wickets", "sum"),
                runs=("runs_conceded", "sum"),
                balls=("balls_bowled", "sum"),
                innings=("wickets", "size"),
            )
            season["economy"] = 6.0 * season["runs"] / season["balls"].replace(0, np.nan)
            season = season.sort_values("year")
            fig = go.Figure()
            fig.add_bar(
                x=season["season"],
                y=season["wickets"],
                name="Wickets",
                marker_color=TEAL,
                customdata=season[["innings", "economy", "runs"]],
                hovertemplate=(
                    "<b>Season %{x}</b><br>"
                    "Wickets: <b>%{y:,}</b><br>"
                    "Economy rate: <b>%{customdata[1]:.2f}</b><br>"
                    "Runs conceded: <b>%{customdata[2]:,}</b> (%{customdata[0]:,} spells)<extra></extra>"
                ),
            )
            fig.add_scatter(
                x=season["season"],
                y=season["economy"],
                name="Economy rate",
                mode="lines+markers",
                yaxis="y2",
                line=dict(color=AMBER, width=3.5),
                marker=dict(size=8, color=AMBER, line=dict(width=1.5, color="#ffffff")),
                customdata=season[["wickets", "innings"]],
                hovertemplate=(
                    "<b>Season %{x}</b><br>"
                    "Economy rate: <b>%{y:.2f}</b><br>"
                    "Wickets: <b>%{customdata[0]:,}</b> (%{customdata[1]:,} spells)<extra></extra>"
                ),
            )
            fig.update_layout(
                xaxis=dict(type="category", title="Year"),
                yaxis=dict(title="Wickets"),
                yaxis2=dict(title="Economy rate", overlaying="y", side="right", showgrid=False),
                legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"),
            )
            st.plotly_chart(style_fn(fig, "Wickets and economy rate by season"), width="stretch", theme=None)

        with right:
            top10 = bt_all.sort_values(["wickets", "economy"], ascending=[False, True]).head(10).sort_values("wickets")
            fig = px.bar(
                top10,
                x="wickets",
                y="bowler_name",
                orientation="h",
                color="economy",
                color_continuous_scale=SCALE,
                text="wickets",
                custom_data=["innings", "average", "economy", "strike_rate", "best_bowling"],
                labels={"wickets": "Wickets", "bowler_name": "", "economy": "Economy"},
            )
            fig.update_traces(
                texttemplate="%{text:,}",
                textposition="inside",
                insidetextanchor="end",
                textfont=dict(color="#ffffff", size=11),
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "Wickets: <b>%{x:,}</b> (Best: <b>%{customdata[4]}</b>)<br>"
                    "Economy: <b>%{customdata[2]:.2f}</b> · Average: <b>%{customdata[1]:.1f}</b><br>"
                    "Strike rate: <b>%{customdata[3]:.1f}</b> · Innings: <b>%{customdata[0]:,}</b><extra></extra>"
                ),
            )
            fig.update_layout(coloraxis_colorbar_title="Econ")
            st.plotly_chart(style_fn(fig, "Top 10 wicket takers (colour = economy rate)"), width="stretch", theme=None)

        left, right = st.columns(2)
        with left:
            phase_rows = [
                {
                    "Phase": "Powerplay (1–6)",
                    "Balls": int(fb["pp_balls"].sum()),
                    "Runs": int(fb["pp_runs"].sum()),
                    "Wickets": int(fb["pp_wickets"].sum()),
                },
                {
                    "Phase": "Middle (7–15)",
                    "Balls": int(fb["mid_balls"].sum()),
                    "Runs": int(fb["mid_runs"].sum()),
                    "Wickets": int(fb["mid_wickets"].sum()),
                },
                {
                    "Phase": "Death (16–20)",
                    "Balls": int(fb["death_balls"].sum()),
                    "Runs": int(fb["death_runs"].sum()),
                    "Wickets": int(fb["death_wickets"].sum()),
                },
            ]
            for pr_item in phase_rows:
                b_cnt = pr_item["Balls"]
                w_cnt = pr_item["Wickets"]
                pr_item["Economy"] = 6.0 * pr_item["Runs"] / b_cnt if b_cnt > 0 else 0.0
                pr_item["Strike rate"] = b_cnt / w_cnt if w_cnt > 0 else 0.0
            ph_df = pd.DataFrame(phase_rows)

            fig_ph = go.Figure()
            fig_ph.add_bar(
                x=ph_df["Phase"],
                y=ph_df["Wickets"],
                name="Wickets",
                marker_color=TEAL,
                customdata=ph_df[["Economy", "Strike rate", "Runs", "Balls"]],
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "Wickets: <b>%{y:,}</b><br>"
                    "Economy: <b>%{customdata[0]:.2f}</b> · Bowling SR: <b>%{customdata[1]:.1f}</b><br>"
                    "Runs: <b>%{customdata[2]:,}</b> off %{customdata[3]:,} balls<extra></extra>"
                ),
            )
            fig_ph.add_scatter(
                x=ph_df["Phase"],
                y=ph_df["Economy"],
                name="Economy rate",
                mode="lines+markers",
                yaxis="y2",
                line=dict(color=AMBER, width=3.5),
                marker=dict(size=9, color=AMBER, line=dict(width=1.5, color="#ffffff")),
                hovertemplate="<b>%{x}</b><br>Economy rate: <b>%{y:.2f}</b><extra></extra>",
            )
            fig_ph.update_layout(
                yaxis=dict(title="Wickets"),
                yaxis2=dict(title="Economy rate", overlaying="y", side="right", showgrid=False),
                legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"),
            )
            st.plotly_chart(style_fn(fig_ph, "Wickets and economy rate by match phase", height=360), width="stretch", theme=None)

        with right:
            bstyle = (
                fb[fb["bowling_type"] != "Unknown"]
                .groupby("bowling_type", as_index=False)
                .agg(wickets=("wickets", "sum"), runs=("runs_conceded", "sum"), balls=("balls_bowled", "sum"))
                .sort_values("wickets", ascending=False)
            )
            fig_pie = px.pie(
                bstyle,
                names="bowling_type",
                values="wickets",
                hole=0.52,
                color_discrete_sequence=CATEGORY,
            )
            fig_pie.update_traces(
                textposition="inside",
                textinfo="percent",
                insidetextorientation="horizontal",
                textfont=dict(color="#ffffff", size=11),
                marker=dict(line=dict(color="#ffffff", width=1.5)),
                hovertemplate=(
                    "<b>%{label}</b><br>"
                    "Wickets: <b>%{value:,}</b><br>"
                    "Share of total wickets: <b>%{percent}</b><extra></extra>"
                ),
            )
            fig_pie.update_layout(legend=dict(orientation="v", y=0.5, yanchor="middle", x=1.02))
            st.plotly_chart(style_fn(fig_pie, "Where the wickets come from (bowling style)", height=360), width="stretch", theme=None)

        st.markdown("#### Runs conceded mix by season (boundary runs vs non-boundary runs)")
        mix = (
            fb.groupby(["year", "season"], as_index=False)
            .agg(runs=("runs_conceded", "sum"), boundary_runs=("boundary_runs_conceded", "sum"))
            .sort_values("year")
        )
        mix["Boundary runs conceded"] = mix["boundary_runs"]
        mix["Non-boundary runs (1s, 2s, 3s, extras)"] = mix["runs"] - mix["boundary_runs"]
        mix = mix.melt(
            id_vars=["year", "season", "runs"],
            value_vars=["Boundary runs conceded", "Non-boundary runs (1s, 2s, 3s, extras)"],
            var_name="type",
            value_name="value",
        )
        mix["share_pct"] = 100.0 * mix["value"] / mix["runs"].replace(0, np.nan)
        fig_mix = px.bar(
            mix,
            x="season",
            y="value",
            color="type",
            barmode="stack",
            custom_data=["share_pct", "runs"],
            color_discrete_map={
                "Boundary runs conceded": AMBER,
                "Non-boundary runs (1s, 2s, 3s, extras)": TEAL,
            },
            labels={"season": "Season", "value": "Runs conceded", "type": ""},
        )
        fig_mix.update_traces(
            hovertemplate=(
                "<b>Season %{x}</b> · %{fullData.name}<br>"
                "Runs: <b>%{y:,}</b> (<b>%{customdata[0]:.1f}%</b> of %{customdata[1]:,})<extra></extra>"
            )
        )
        fig_mix.update_layout(
            xaxis=dict(type="category"),
            legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"),
        )
        st.plotly_chart(
            style_fn(fig_mix, "Boundary runs against non-boundary runs conceded, by season", height=340),
            width="stretch",
            theme=None,
        )

    # ------------------------------------------------------------------------
    # 2. Bowler profile
    # ------------------------------------------------------------------------
    with tab_profile:
        bowler = st.selectbox("Choose a bowler", bowlers_by_wkts, index=0, key="profile_bowler")
        pb = fb[fb["bowler_name"] == bowler].sort_values(["date", "match_id", "innings"])
        tpb = bowling_totals(pb)
        b_row = bt_all[bt_all["bowler_name"] == bowler].iloc[0]
        b_style_str = f"{b_row['bowling_type']} ({b_row['pace_or_spin']})"

        st.markdown(
            f"<div class='note'><b>{escape(bowler)}</b> · Style: <b>{escape(b_style_str)}</b> · "
            f"Best figures in view: <b>{escape(str(b_row['best_bowling']))}</b> · "
            f"Maidens: <b>{tpb['maidens']}</b></div>",
            unsafe_allow_html=True,
        )

        cols = st.columns(6)
        with cols[0]:
            kpi_fn("Innings (Overs)", f"{tpb['innings']:,} ({tpb['overs_str']})")
        with cols[1]:
            kpi_fn("Wickets (Best)", f"{tpb['wickets']:,} ({b_row['best_bowling']})")
        with cols[2]:
            kpi_fn("Bowling average", fmt_fn(tpb["average"]))
        with cols[3]:
            kpi_fn("Economy rate", fmt_fn(tpb["economy"], 2))
        with cols[4]:
            kpi_fn("Bowling strike rate", fmt_fn(tpb["strike_rate"]))
        with cols[5]:
            kpi_fn("Dot % · 3W+ hauls", f"{fmt_fn(tpb['dot_pct'])}% · {tpb['three_w']}")

        st.markdown("")
        left, right = st.columns(2)
        with left:
            cum = pb.assign(cum_wickets=pb["wickets"].cumsum())
            fig = px.line(
                cum,
                x="date",
                y="cum_wickets",
                custom_data=["wickets", "runs_conceded", "overs", "opposition"],
                labels={"date": "Date", "cum_wickets": "Cumulative wickets"},
            )
            fig.update_traces(
                line_color=TEAL,
                line_width=3,
                hovertemplate=(
                    "<b>%{x|%d %b %Y}</b><br>"
                    "Cumulative total: <b>%{y:,} wickets</b><br>"
                    "Spell: <b>%{customdata[0]:.0f}/%{customdata[1]:.0f}</b> (%{customdata[2]} ov) vs %{customdata[3]}<extra></extra>"
                ),
            )
            st.plotly_chart(style_fn(fig, f"{bowler}: cumulative wickets over time", height=340), width="stretch", theme=None)

        with right:
            pb_econ = 6.0 * pb["runs_conceded"] / pb["balls_bowled"].replace(0, np.nan)
            form = pb.assign(spell_econ=pb_econ, rolling_econ=pb_econ.rolling(10, min_periods=3).mean())
            fig = go.Figure()
            fig.add_bar(
                x=form["date"],
                y=form["wickets"],
                name="Wickets in spell",
                marker_color=TEAL,
                customdata=form[["runs_conceded", "overs", "opposition", "spell_econ"]],
                hovertemplate=(
                    "<b>%{x|%d %b %Y}</b><br>"
                    "Figures: <b>%{y:.0f}/%{customdata[0]:.0f}</b> (%{customdata[1]} ov · Econ %{customdata[3]:.2f})<br>"
                    "Opposition: <b>%{customdata[2]}</b><extra></extra>"
                ),
            )
            fig.add_scatter(
                x=form["date"],
                y=form["rolling_econ"],
                name="10-innings rolling economy",
                mode="lines",
                yaxis="y2",
                line=dict(color=AMBER, width=3),
                hovertemplate="<b>%{x|%d %b %Y}</b><br>10-innings rolling economy: <b>%{y:.2f}</b><extra></extra>",
            )
            fig.update_layout(
                yaxis=dict(title="Wickets"),
                yaxis2=dict(title="Economy rate", overlaying="y", side="right", showgrid=False),
                legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"),
            )
            st.plotly_chart(
                style_fn(fig, f"{bowler}: wickets & 10-innings rolling economy", height=340),
                width="stretch",
                theme=None,
            )

        left, right = st.columns(2)
        with left:
            scat = pb.assign(
                outcome=np.where(pb["bowling_team_won"], "Match Won", "Match Lost / NR"),
                spell_econ=6.0 * pb["runs_conceded"] / pb["balls_bowled"].replace(0, np.nan),
            )
            fig = px.scatter(
                scat,
                x="runs_conceded",
                y="wickets",
                size="dots",
                color="outcome",
                color_discrete_map={"Match Won": TEAL, "Match Lost / NR": AMBER},
                custom_data=["match_date", "opposition", "overs", "spell_econ", "dots"],
                labels={"runs_conceded": "Runs conceded in spell", "wickets": "Wickets taken", "outcome": ""},
            )
            fig.update_traces(
                marker=dict(line=dict(width=1, color="#ffffff")),
                hovertemplate=(
                    "<b>%{y:.0f}/%{x:.0f}</b> (%{customdata[2]} overs · Econ <b>%{customdata[3]:.2f}</b>)<br>"
                    "Dot balls: <b>%{customdata[4]:.0f}</b><br>"
                    "vs <b>%{customdata[1]}</b> · %{customdata[0]}<extra></extra>"
                ),
            )
            fig.update_layout(legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"))
            st.plotly_chart(
                style_fn(fig, f"{bowler}: wickets against runs conceded (size = dot balls)", height=350),
                width="stretch",
                theme=None,
            )

        with right:
            if wickets_raw is not None and len(pb):
                bid = pb["bowler_id"].iloc[0]
                wd = wickets_raw[(wickets_raw["player_id"] == bid) | (wickets_raw["player_name"] == bowler)]
                wd = wd.groupby("dismissal_type", as_index=False)["wicket_count"].sum()
                wd = wd[wd["wicket_count"] > 0]
                if wd.empty:
                    st.info("No wickets recorded for this bowler in the dismissal file.")
                else:
                    fig = px.pie(
                        wd,
                        names="dismissal_type",
                        values="wicket_count",
                        hole=0.52,
                        color_discrete_sequence=CATEGORY,
                    )
                    fig.update_traces(
                        textposition="inside",
                        textinfo="percent+label",
                        textfont=dict(color="#ffffff", size=11),
                        marker=dict(line=dict(color="#ffffff", width=1.5)),
                        hovertemplate=(
                            "<b>%{label}</b><br>"
                            "Wickets: <b>%{value:,}</b><br>"
                            "Share: <b>%{percent}</b><extra></extra>"
                        ),
                    )
                    st.plotly_chart(
                        style_fn(fig, f"{bowler}: how they took wickets", height=350),
                        width="stretch",
                        theme=None,
                    )
            else:
                st.info("Add cleaned_data/bowling_wicket_types.csv to show how this bowler took wickets.")

        left, right = st.columns(2)
        with left:
            opp = (
                pb.groupby("opposition", as_index=False)
                .agg(
                    wickets=("wickets", "sum"),
                    runs=("runs_conceded", "sum"),
                    balls=("balls_bowled", "sum"),
                    innings=("wickets", "size"),
                )
            )
            opp["economy"] = 6.0 * opp["runs"] / opp["balls"].replace(0, np.nan)
            opp = opp.sort_values(["wickets", "balls"], ascending=[False, False]).head(10).sort_values("wickets")
            fig = px.bar(
                opp,
                x="wickets",
                y="opposition",
                orientation="h",
                color="economy",
                color_continuous_scale=SCALE,
                custom_data=["innings", "economy", "runs", "balls"],
                labels={"wickets": "Wickets", "opposition": "", "economy": "Economy"},
            )
            fig.update_traces(
                hovertemplate=(
                    "<b>vs %{y}</b><br>"
                    "Wickets: <b>%{x:,}</b> (%{customdata[2]:,} runs off %{customdata[3]:,} balls)<br>"
                    "Economy: <b>%{customdata[1]:.2f}</b> · Spells: <b>%{customdata[0]:,}</b><extra></extra>"
                )
            )
            st.plotly_chart(
                style_fn(fig, f"{bowler}: wickets by opposition (colour = economy)", height=350),
                width="stretch",
                theme=None,
            )

        with right:
            b_ph = pd.DataFrame([
                {
                    "Phase": "Powerplay (1–6)",
                    "Balls": int(pb["pp_balls"].sum()),
                    "Runs": int(pb["pp_runs"].sum()),
                    "Wickets": int(pb["pp_wickets"].sum()),
                },
                {
                    "Phase": "Middle (7–15)",
                    "Balls": int(pb["mid_balls"].sum()),
                    "Runs": int(pb["mid_runs"].sum()),
                    "Wickets": int(pb["mid_wickets"].sum()),
                },
                {
                    "Phase": "Death (16–20)",
                    "Balls": int(pb["death_balls"].sum()),
                    "Runs": int(pb["death_runs"].sum()),
                    "Wickets": int(pb["death_wickets"].sum()),
                },
            ])
            b_ph["Economy"] = np.where(b_ph["Balls"] > 0, 6.0 * b_ph["Runs"] / b_ph["Balls"].replace(0, np.nan), 0.0)
            fig_bph = go.Figure()
            fig_bph.add_bar(
                x=b_ph["Phase"],
                y=b_ph["Wickets"],
                name="Wickets",
                marker_color=TEAL,
                customdata=b_ph[["Economy", "Runs", "Balls"]],
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "Wickets: <b>%{y:,}</b><br>"
                    "Economy: <b>%{customdata[0]:.2f}</b> (%{customdata[1]:,} runs off %{customdata[2]:,} balls)<extra></extra>"
                ),
            )
            fig_bph.add_scatter(
                x=b_ph["Phase"],
                y=b_ph["Economy"],
                name="Economy rate",
                mode="lines+markers",
                yaxis="y2",
                line=dict(color=AMBER, width=3.5),
                marker=dict(size=9, color=AMBER, line=dict(width=1.5, color="#ffffff")),
                hovertemplate="<b>%{x}</b><br>Economy: <b>%{y:.2f}</b><extra></extra>",
            )
            fig_bph.update_layout(
                yaxis=dict(title="Wickets"),
                yaxis2=dict(title="Economy rate", overlaying="y", side="right", showgrid=False),
                legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"),
            )
            st.plotly_chart(
                style_fn(fig_bph, f"{bowler}: wickets & economy by phase", height=350),
                width="stretch",
                theme=None,
            )

    # ------------------------------------------------------------------------
    # 3. Innings (Top Bowling Spells Explorer & Visuals)
    # ------------------------------------------------------------------------
    with tab_innings:
        st.markdown("#### Bowling innings & spell explorer")
        ic1, ic2, ic3 = st.columns([1, 1.2, 1.2])
        with ic1:
            min_spell_balls = st.slider(
                "Minimum balls bowled in spell",
                min_value=6,
                max_value=24,
                value=12,
                step=6,
                key="min_spell_balls",
            )
        with ic2:
            spell_sort = st.selectbox(
                "Rank bowling innings by",
                options=[
                    "Best figures (most wickets, fewest runs)",
                    "Lowest economy rate (min 12 balls)",
                    "Most dot balls in a spell",
                ],
                index=0,
                key="spell_sort",
            )
        with ic3:
            spell_bowler_filter = st.selectbox(
                "Filter by bowler (optional)",
                options=["All bowlers"] + bowlers_by_wkts,
                index=0,
                key="spell_bowler_filter",
            )

        spells_df = fb[fb["balls_bowled"] >= min_spell_balls].copy()
        if spell_bowler_filter != "All bowlers":
            spells_df = spells_df[spells_df["bowler_name"] == spell_bowler_filter].copy()

        if spells_df.empty:
            st.info("No bowling spells match these filters. Lower the minimum balls threshold.")
        else:
            spells_df["econ_calc"] = 6.0 * spells_df["runs_conceded"] / spells_df["balls_bowled"].replace(0, np.nan)
            spells_df["dot_pct_calc"] = 100.0 * spells_df["dots"] / spells_df["balls_bowled"].replace(0, np.nan)
            spells_df["figures"] = [
                f"{int(w)}/{int(r)}" for w, r in zip(spells_df["wickets"], spells_df["runs_conceded"])
            ]

            if spell_sort == "Best figures (most wickets, fewest runs)":
                spells_sorted = spells_df.sort_values(
                    ["wickets", "runs_conceded", "balls_bowled"], ascending=[False, True, False]
                )
            elif spell_sort == "Lowest economy rate (min 12 balls)":
                spells_sorted = spells_df.sort_values(["econ_calc", "wickets"], ascending=[True, False])
            else:
                spells_sorted = spells_df.sort_values(
                    ["dots", "wickets", "runs_conceded"], ascending=[False, False, True]
                )

            best_row = spells_df.sort_values(
                ["wickets", "runs_conceded", "balls_bowled"], ascending=[False, True, False]
            ).iloc[0]
            scols = st.columns(4)
            with scols[0]:
                kpi_fn("Qualified spells", f"{len(spells_df):,}")
            with scols[1]:
                kpi_fn("Best figures in view", f"{best_row['figures']} ({best_row['bowler_name']})")
            with scols[2]:
                kpi_fn(
                    "3W+ · 4W+ · 5W+ hauls",
                    f"{int((spells_df['wickets'] >= 3).sum()):,} · "
                    f"{int((spells_df['wickets'] >= 4).sum()):,} · "
                    f"{int((spells_df['wickets'] >= 5).sum()):,}",
                )
            with scols[3]:
                kpi_fn("Maiden overs bowled", f"{int(spells_df['maidens'].sum()):,}")

            st.markdown("")
            vis_l, vis_r = st.columns([1.15, 1])
            with vis_l:
                top12_sp = spells_sorted.head(12).copy()
                top12_sp["spell_label"] = [
                    f"{r['bowler_name']} ({r['figures']} vs {r['opposition']}, {str(r['match_date'])[:4]})"
                    for _, r in top12_sp.iterrows()
                ]
                top12_sp = top12_sp.iloc[::-1]
                metric_col = "dots" if spell_sort == "Most dot balls in a spell" else "wickets"
                metric_title = "Dot balls" if metric_col == "dots" else "Wickets"
                fig_sp = px.bar(
                    top12_sp,
                    x=metric_col,
                    y="spell_label",
                    orientation="h",
                    color="econ_calc",
                    color_continuous_scale=SCALE,
                    text="figures",
                    custom_data=["bowler_name", "figures", "overs", "econ_calc", "dots", "dot_pct_calc", "opposition", "match_date"],
                    labels={metric_col: metric_title, "spell_label": "", "econ_calc": "Econ"},
                )
                fig_sp.update_traces(
                    textposition="inside",
                    insidetextanchor="end",
                    textfont=dict(color="#ffffff", size=11),
                    hovertemplate=(
                        "<b>%{customdata[0]}</b> vs %{customdata[6]} (%{customdata[7]})<br>"
                        "Figures: <b>%{customdata[1]}</b> (%{customdata[2]} overs · Econ <b>%{customdata[3]:.2f}</b>)<br>"
                        "Dots: <b>%{customdata[4]:.0f}</b> (<b>%{customdata[5]:.1f}%</b>)<extra></extra>"
                    ),
                )
                fig_sp.update_layout(coloraxis_colorbar_title="Econ")
                st.plotly_chart(
                    style_fn(fig_sp, "Top 12 spells in current selection (colour = economy rate)", height=390),
                    width="stretch",
                    theme=None,
                )

            with vis_r:
                sample_sp = spells_sorted.head(250).copy()
                sample_sp["Result_Label"] = np.where(sample_sp["bowling_team_won"], "Match Won", "Match Lost / NR")
                fig_sc = px.scatter(
                    sample_sp,
                    x="runs_conceded",
                    y="wickets",
                    size="dots",
                    color="Result_Label",
                    color_discrete_map={"Match Won": TEAL, "Match Lost / NR": AMBER},
                    custom_data=["bowler_name", "figures", "overs", "econ_calc", "dots", "opposition", "match_date"],
                    labels={"runs_conceded": "Runs conceded in spell", "wickets": "Wickets taken", "Result_Label": ""},
                )
                fig_sc.update_traces(
                    marker=dict(line=dict(width=0.9, color="#ffffff"), opacity=0.88),
                    hovertemplate=(
                        "<b>%{customdata[0]}</b> · <b>%{customdata[1]}</b> (%{customdata[2]} ov)<br>"
                        "Economy: <b>%{customdata[3]:.2f}</b> · Dots: <b>%{customdata[4]:.0f}</b><br>"
                        "vs <b>%{customdata[5]}</b> (%{customdata[6]})<extra></extra>"
                    ),
                )
                fig_sc.update_layout(legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"))
                st.plotly_chart(
                    style_fn(fig_sc, "Spell impact map: wickets vs runs conceded (size = dot balls)", height=390),
                    width="stretch",
                    theme=None,
                )

            st.markdown("#### Top 25 bowling spells table")
            top_spells = spells_sorted.head(25).copy()
            top_spells["Mdns_int"] = top_spells["maidens"].astype(int)
            top_spells["Runs_int"] = top_spells["runs_conceded"].astype(int)
            top_spells["Wkts_int"] = top_spells["wickets"].astype(int)
            top_spells["Dots_str"] = [
                f"{int(d)} ({dp:.1f}%)" for d, dp in zip(top_spells["dots"], top_spells["dot_pct_calc"])
            ]
            top_spells["Matchup"] = [
                f"{t} vs {o}" for t, o in zip(top_spells["bowling_team"], top_spells["opposition"])
            ]
            top_spells["Format"] = np.where(
                top_spells["match_format"].eq("T20"),
                "<span class='pill ok'>IPL (T20)</span>",
                "<span class='pill overseas'>T20I</span>",
            )
            top_spells["Result"] = np.where(
                top_spells["bowling_team_won"],
                "<span class='pill ok'>Won</span>",
                "<span class='pill warn'>Lost / NR</span>",
            )

            spells_display = top_spells[[
                "bowler_name", "figures", "overs", "Mdns_int", "Runs_int", "Wkts_int",
                "econ_calc", "Dots_str", "Matchup", "Format", "match_date", "Result",
            ]].rename(columns={
                "bowler_name": "Bowler",
                "figures": "Figures",
                "overs": "Overs",
                "Mdns_int": "Mdns",
                "Runs_int": "Runs",
                "Wkts_int": "Wkts",
                "econ_calc": "Economy",
                "Dots_str": "Dots (Dot %)",
                "match_date": "Date",
            })
            html_table_fn(
                spells_display,
                formats={"Economy": "{:.2f}"},
                bar_cols={"Wkts": float(max(1, top_spells["Wkts_int"].max()))},
                num_cols=["Figures", "Overs", "Mdns", "Runs", "Wkts", "Economy", "Dots (Dot %)", "Date"],
            )

    # ------------------------------------------------------------------------
    # 4. Bowler vs bowler head-to-head comparison
    # ------------------------------------------------------------------------
    with tab_h2h:
        if len(bowlers_eligible) < 2:
            st.info("Not enough bowlers with at least 10 innings in this view. Widen the filters.")
        else:
            c1, c2 = st.columns(2)
            with c1:
                ba = st.selectbox("Bowler A", bowlers_eligible, index=0, key="cmp_bowl_a")
            with c2:
                bb = st.selectbox("Bowler B", bowlers_eligible, index=1, key="cmp_bowl_b")

            if ba == bb:
                st.info("Choose two different bowlers to compare.")
            else:
                row_a = bt_all[bt_all["bowler_name"] == ba].iloc[0]
                row_b = bt_all[bt_all["bowler_name"] == bb].iloc[0]

                ca, cb = st.columns(2)
                for col, name, row, colour in [(ca, ba, row_a, PLAYER_COLOURS[0]), (cb, bb, row_b, PLAYER_COLOURS[1])]:
                    with col:
                        st.markdown(
                            f"<h4 style='color:{colour} !important;margin-bottom:.4rem'>{escape(name)}</h4>",
                            unsafe_allow_html=True,
                        )
                        k = st.columns(4)
                        with k[0]:
                            kpi_fn("Wickets", f"{int(row.wickets):,}")
                        with k[1]:
                            kpi_fn("Economy", fmt_fn(row.economy, 2))
                        with k[2]:
                            kpi_fn("Average", fmt_fn(row.average))
                        with k[3]:
                            kpi_fn("Strike rate", fmt_fn(row.strike_rate))

                pool = bt_all[bt_all["innings"] >= MIN_INNINGS_COMPARE]
                radar_Specs = [
                    ("Wickets", "wickets", True),
                    ("Economy (control)", "economy", False),
                    ("Bowling Avg", "average", False),
                    ("Bowling SR", "strike_rate", False),
                    ("Dot ball %", "dot_pct", True),
                    ("Boundary control", "boundary_pct", False),
                ]
                axes = [s[0] for s in radar_Specs]

                def bowl_pct_rank(col_name: str, name: str, higher_better: bool) -> float:
                    val = bt_all.loc[bt_all["bowler_name"] == name, col_name].iloc[0]
                    if pd.isna(val):
                        return 0.0
                    series = pool[col_name].dropna()
                    if series.empty:
                        return 0.0
                    if higher_better:
                        return 100.0 * (series < val).mean()
                    return 100.0 * (series > val).mean()

                fig_rad = go.Figure()
                for name, colour in [(ba, PLAYER_COLOURS[0]), (bb, PLAYER_COLOURS[1])]:
                    vals = [bowl_pct_rank(col_c, name, hb) for _, col_c, hb in radar_Specs]
                    raw_vals = [float(bt_all.loc[bt_all["bowler_name"] == name, col_c].iloc[0]) for _, col_c, _ in radar_Specs]
                    fig_rad.add_trace(
                        go.Scatterpolar(
                            r=vals + vals[:1],
                            theta=axes + axes[:1],
                            customdata=raw_vals + raw_vals[:1],
                            name=name,
                            fill="toself",
                            line=dict(color=colour, width=2.5),
                            opacity=0.6,
                            hovertemplate=(
                                f"<b>{escape(name)}</b><br>"
                                "%{theta}: <b>%{customdata:,.2f}</b><br>"
                                "Percentile: <b>%{r:.0f}th</b><extra></extra>"
                            ),
                        )
                    )
                fig_rad.update_layout(
                    polar=dict(
                        bgcolor="#f8fafc",
                        radialaxis=dict(range=[0, 100], showticklabels=False, gridcolor="#cbd5e1"),
                        angularaxis=dict(tickfont=dict(color=INK, size=12), gridcolor="#cbd5e1"),
                    ),
                    legend=dict(orientation="h", y=-0.12, x=0.2),
                )

                left, right = st.columns([1, 1.2])
                with left:
                    st.plotly_chart(
                        style_fn(fig_rad, "Bowler profile shape (outer edge = better percentile)", height=420),
                        width="stretch",
                        theme=None,
                    )
                with right:
                    st.markdown("#### Side by side")
                    comp = pd.DataFrame({
                        "Metric": [
                            "Bowling style", "Innings", "Overs bowled", "Wickets (Best)", "Economy rate",
                            "Bowling average", "Bowling strike rate", "Dot ball %", "Boundary % conceded", "3W+ hauls",
                        ],
                        ba: [
                            f"{row_a.bowling_type} ({row_a.pace_or_spin})",
                            f"{int(row_a.innings):,}",
                            str(row_a.overs),
                            f"{int(row_a.wickets):,} ({row_a.best_bowling})",
                            fmt_fn(row_a.economy, 2),
                            fmt_fn(row_a.average, 1),
                            fmt_fn(row_a.strike_rate, 1),
                            f"{fmt_fn(row_a.dot_pct, 1)}%",
                            f"{fmt_fn(row_a.boundary_pct, 1)}%",
                            f"{int(row_a.three_w):,}",
                        ],
                        bb: [
                            f"{row_b.bowling_type} ({row_b.pace_or_spin})",
                            f"{int(row_b.innings):,}",
                            str(row_b.overs),
                            f"{int(row_b.wickets):,} ({row_b.best_bowling})",
                            fmt_fn(row_b.economy, 2),
                            fmt_fn(row_b.average, 1),
                            fmt_fn(row_b.strike_rate, 1),
                            f"{fmt_fn(row_b.dot_pct, 1)}%",
                            f"{fmt_fn(row_b.boundary_pct, 1)}%",
                            f"{int(row_b.three_w):,}",
                        ],
                    })
                    html_table_fn(comp, num_cols=[ba, bb])
                    st.markdown(
                        "<div class='note'>On the radar, Economy, Average, Strike Rate, and Boundary % are inverted "
                        "so that a larger polygon always indicates stronger bowling performance.</div>",
                        unsafe_allow_html=True,
                    )

                left, right = st.columns(2)
                with left:
                    yr_h2h = (
                        fb[fb["bowler_name"].isin([ba, bb])]
                        .groupby(["year", "season", "bowler_name"], as_index=False)
                        .agg(wickets=("wickets", "sum"), runs=("runs_conceded", "sum"), balls=("balls_bowled", "sum"), innings=("wickets", "size"))
                        .sort_values("year")
                    )
                    yr_h2h["economy"] = 6.0 * yr_h2h["runs"] / yr_h2h["balls"].replace(0, np.nan)
                    fig_yr = px.line(
                        yr_h2h,
                        x="season",
                        y="wickets",
                        color="bowler_name",
                        markers=True,
                        custom_data=["innings", "economy", "runs"],
                        color_discrete_map={ba: PLAYER_COLOURS[0], bb: PLAYER_COLOURS[1]},
                        labels={"season": "Season", "wickets": "Wickets", "bowler_name": ""},
                    )
                    fig_yr.update_traces(
                        line_width=3,
                        marker_size=8,
                        hovertemplate=(
                            "<b>%{fullData.name} · %{x}</b><br>"
                            "Wickets: <b>%{y:,}</b> (%{customdata[0]:,} inns)<br>"
                            "Economy: <b>%{customdata[1]:.2f}</b> (%{customdata[2]:,} runs)<extra></extra>"
                        ),
                    )
                    fig_yr.update_layout(
                        xaxis=dict(type="category"),
                        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"),
                    )
                    st.plotly_chart(style_fn(fig_yr, "Wickets by season (head-to-head)", height=350), width="stretch", theme=None)

                with right:
                    v_h2h = (
                        fb[fb["bowler_name"].isin([ba, bb])]
                        .groupby(["venue", "bowler_name"], as_index=False)
                        .agg(runs=("runs_conceded", "sum"), balls=("balls_bowled", "sum"), wickets=("wickets", "sum"))
                    )
                    v_h2h["economy"] = 6.0 * v_h2h["runs"] / v_h2h["balls"].replace(0, np.nan)
                    v_ok = v_h2h[v_h2h["balls"] >= MIN_VENUE_BALLS]
                    va_set = set(v_ok[v_ok["bowler_name"] == ba]["venue"].tolist())
                    vb_set = set(v_ok[v_ok["bowler_name"] == bb]["venue"].tolist())
                    shared_venues = sorted(va_set & vb_set)
                    if not shared_venues:
                        st.info(f"No shared venue where both bowlers have bowled at least {MIN_VENUE_BALLS} legal balls.")
                    else:
                        sv_df = v_ok[v_ok["venue"].isin(shared_venues)].copy()
                        fig_sv = px.bar(
                            sv_df,
                            x="venue",
                            y="economy",
                            color="bowler_name",
                            barmode="group",
                            custom_data=["wickets", "runs", "balls"],
                            color_discrete_map={ba: PLAYER_COLOURS[0], bb: PLAYER_COLOURS[1]},
                            labels={"venue": "Venue", "economy": "Economy rate", "bowler_name": ""},
                        )
                        fig_sv.update_traces(
                            hovertemplate=(
                                "<b>%{fullData.name} · %{x}</b><br>"
                                "Economy: <b>%{y:.2f}</b><br>"
                                "Wickets: <b>%{customdata[0]:,.0f}</b> (%{customdata[1]:,.0f} runs off %{customdata[2]:,.0f} balls)<extra></extra>"
                            )
                        )
                        fig_sv.update_layout(legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"))
                        st.plotly_chart(
                            style_fn(fig_sv, f"Economy rate at shared venues (min {MIN_VENUE_BALLS} balls)", height=350),
                            width="stretch",
                            theme=None,
                        )

    # ------------------------------------------------------------------------
    # 5. Player leaderboard
    # ------------------------------------------------------------------------
    with tab_board:
        lb_c1, lb_c2, lb_c3 = st.columns([1.2, 1, 1])
        with lb_c1:
            lb_pitch_mode = st.selectbox(
                "Pitch / venue filter",
                options=[
                    "Indian pitches only (Eligible Indian-pitch performers)",
                    "All venues (Indian + Overseas)",
                    "Overseas pitches only",
                ],
                index=0,
                key="bowl_lb_pitch_mode",
            )
        with lb_c2:
            min_inn_b = st.slider(
                "Minimum bowling innings (eligibility)",
                1,
                50,
                15,
                help="Eligible bowlers must meet this minimum innings count to avoid small-sample flukes.",
                key="bowl_min_inn",
            )
        with lb_c3:
            max_econ_b = st.slider(
                "Maximum economy rate (performed well)",
                6.5,
                12.0,
                8.65,
                step=0.05,
                help="Filter for bowlers who kept their economy at or below this threshold.",
                key="bowl_max_econ",
            )

        if lb_pitch_mode.startswith("Indian"):
            fb_lb_src = fb[fb["pitch_region"] == "Indian venue"]
            bt_lb = bowler_table(fb_lb_src)
        elif lb_pitch_mode.startswith("Overseas"):
            fb_lb_src = fb[fb["pitch_region"] == "Overseas venue"]
            bt_lb = bowler_table(fb_lb_src)
        else:
            bt_lb = bt_all

        board_b = bt_lb[
            (bt_lb["innings"] >= min_inn_b) & (bt_lb["economy"] <= max_econ_b)
        ].sort_values(
            ["wickets", "economy"], ascending=[False, True]
        )

        if board_b.empty:
            st.info("No bowlers meet this minimum innings and economy threshold. Adjust the sliders above.")
        else:
            board_plot = board_b[board_b["wickets"] > 0].copy()
            fig = px.scatter(
                board_plot,
                x="economy",
                y="strike_rate",
                size="wickets",
                color="dot_pct",
                color_continuous_scale=SCALE,
                hover_name="bowler_name",
                custom_data=["innings", "wickets", "average", "dot_pct", "best_bowling"],
                labels={
                    "economy": "Economy rate (runs per over — lower is better)",
                    "strike_rate": "Bowling strike rate (balls per wicket — lower is better)",
                    "dot_pct": "Dot ball %",
                },
            )
            fig.update_traces(
                marker=dict(line=dict(width=0.8, color=NAVY), opacity=0.88),
                hovertemplate=(
                    "<b>%{hovertext}</b><br>"
                    "Wickets: <b>%{customdata[1]:,.0f}</b> (%{customdata[0]:,.0f} inns · Best <b>%{customdata[4]}</b>)<br>"
                    "Economy: <b>%{x:.2f}</b> · Strike rate: <b>%{y:.1f}</b> · Average: <b>%{customdata[2]:.1f}</b><br>"
                    "Dot ball share: <b>%{customdata[3]:.1f}%</b><extra></extra>"
                ),
            )
            st.plotly_chart(
                style_fn(fig, "Eligible bowlers: Economy rate vs bowling strike rate (bubble = wickets, colour = dot ball %)", height=460),
                width="stretch",
                theme=None,
            )

            st.markdown(
                f"<div class='note'><b>{len(board_b):,} eligible bowlers</b> ({escape(lb_pitch_mode)}) with at least "
                f"<b>{min_inn_b} innings</b> and economy <b>≤ {max_econ_b:.2f}</b>. Sorted by wickets taken, then economy.</div>",
                unsafe_allow_html=True,
            )
            tbl_b = board_b[[
                "bowler_name", "bowling_type", "innings", "overs", "maidens", "runs",
                "wickets", "best_bowling", "average", "economy", "strike_rate",
                "dot_pct", "boundary_pct", "three_w", "four_w", "five_w",
            ]].rename(columns={
                "bowler_name": "Bowler",
                "bowling_type": "Style",
                "innings": "Inns",
                "overs": "Overs",
                "maidens": "Mdns",
                "runs": "Runs",
                "wickets": "Wickets",
                "best_bowling": "Best",
                "average": "Average",
                "economy": "Economy",
                "strike_rate": "Strike rate",
                "dot_pct": "Dot %",
                "boundary_pct": "Boundary %",
                "three_w": "3W+",
                "four_w": "4W",
                "five_w": "5W",
            })
            html_table_fn(
                tbl_b,
                formats={
                    "Runs": "{:,.0f}",
                    "Average": "{:.1f}",
                    "Economy": "{:.2f}",
                    "Strike rate": "{:.1f}",
                    "Dot %": "{:.1f}",
                    "Boundary %": "{:.1f}",
                },
                bar_cols={"Wickets": float(board_b["wickets"].max())},
                num_cols=[
                    "Inns", "Overs", "Mdns", "Runs", "Wickets", "Best",
                    "Average", "Economy", "Strike rate", "Dot %", "Boundary %", "3W+", "4W", "5W",
                ],
            )

    # ------------------------------------------------------------------------
    # 6. Venue fit
    # ------------------------------------------------------------------------
    with tab_venue:
        st.markdown(
            "<div class='note'>A bowler's economy rate at each venue is compared with the average economy rate of all bowlers "
            "at that ground in the same view. Negative difference means the bowler conceded fewer runs per over than the venue average. "
            f"The chart shows venues with at least {MIN_VENUE_BALLS} legal balls bowled.</div>",
            unsafe_allow_html=True,
        )
        player_bv = st.selectbox("Choose a bowler", bowlers_by_wkts, index=0, key="venue_bowler")
        pfb_v = fb[fb["bowler_name"] == player_bv]

        region_pool = (
            fb.groupby(["bowler_name", "pitch_region"], as_index=False)
            .agg(
                runs=("runs_conceded", "sum"),
                balls=("balls_bowled", "sum"),
                wickets=("wickets", "sum"),
                dots=("dots", "sum"),
                innings=("wickets", "size"),
            )
        )
        region_pool = region_pool[region_pool["balls"] >= MIN_VENUE_BALLS].copy()
        region_pool["econ"] = 6.0 * region_pool["runs"] / region_pool["balls"].replace(0, np.nan)
        region_pool["sr"] = np.where(region_pool["wickets"] > 0, region_pool["balls"] / region_pool["wickets"].replace(0, np.nan), np.nan)

        def bowl_region_rating(region_name: str, econ_val: float, sr_val: float) -> float:
            sub = region_pool[region_pool["pitch_region"] == region_name]
            if sub.empty or pd.isna(econ_val):
                return np.nan
            econ_pct = 100.0 * (sub["econ"].dropna() > econ_val).mean()
            if pd.isna(sr_val) or sub["sr"].dropna().empty:
                return econ_pct
            sr_pct = 100.0 * (sub["sr"].dropna() > sr_val).mean()
            return 0.55 * econ_pct + 0.45 * sr_pct

        reg_rows = []
        reg_econ_map = {}
        for reg_label in ["Indian venue", "Overseas venue"]:
            sub_p = pfb_v[pfb_v["pitch_region"] == reg_label]
            r_runs = float(sub_p["runs_conceded"].sum())
            r_balls = float(sub_p["balls_bowled"].sum())
            r_wkts = int(sub_p["wickets"].sum())
            r_inns = int(len(sub_p))
            r_dots = float(sub_p["dots"].sum())
            r_econ = 6.0 * r_runs / r_balls if r_balls > 0 else np.nan
            r_avg = r_runs / r_wkts if r_wkts > 0 else np.nan
            r_sr = r_balls / r_wkts if r_wkts > 0 else np.nan
            r_dpct = 100.0 * r_dots / r_balls if r_balls > 0 else np.nan
            r_rate = bowl_region_rating(reg_label, r_econ, r_sr) if r_balls > 0 else np.nan
            reg_econ_map[reg_label] = r_econ
            reg_rows.append({
                "Pitch / Venue Type": (
                    "<span class='pill ok'>Indian venues</span>"
                    if reg_label == "Indian venue"
                    else "<span class='pill overseas'>Overseas venues</span>"
                ),
                "Inns": r_inns,
                "Overs": fmt_overs(r_balls),
                "Runs": r_runs,
                "Wickets": r_wkts,
                "Average": r_avg,
                "Economy": r_econ,
                "Strike rate": r_sr,
                "Dot %": r_dpct,
                "Pitch Rating (0–100)": r_rate,
            })

        ind_econ = reg_econ_map.get("Indian venue", np.nan)
        ovr_econ = reg_econ_map.get("Overseas venue", np.nan)
        if pd.notna(ind_econ) and pd.notna(ovr_econ):
            better_badge = (
                f"<span class='pill ok'>Indian pitches (-{ovr_econ - ind_econ:.2f} Econ)</span>"
                if ind_econ <= ovr_econ
                else f"<span class='pill overseas'>Overseas pitches (-{ind_econ - ovr_econ:.2f} Econ)</span>"
            )
        elif pd.notna(ind_econ):
            better_badge = "<span class='pill ok'>Indian pitches only</span>"
        elif pd.notna(ovr_econ):
            better_badge = "<span class='pill overseas'>Overseas pitches only</span>"
        else:
            better_badge = "–"

        st.markdown(
            f"#### Indian venues vs Overseas venues — {escape(player_bv)} "
            f"&nbsp; <span style='font-size:0.9rem;font-weight:500'>Performed better on: {better_badge}</span>",
            unsafe_allow_html=True,
        )
        reg_df = pd.DataFrame(reg_rows)
        html_table_fn(
            reg_df,
            formats={
                "Runs": "{:,.0f}",
                "Average": "{:.1f}",
                "Economy": "{:.2f}",
                "Strike rate": "{:.1f}",
                "Dot %": "{:.1f}",
                "Pitch Rating (0–100)": "{:.1f}",
            },
            bar_cols={"Pitch Rating (0–100)": 100.0},
            num_cols=[
                "Inns", "Overs", "Runs", "Wickets", "Average",
                "Economy", "Strike rate", "Dot %", "Pitch Rating (0–100)",
            ],
        )

        venue_avg = fb.groupby(["venue", "venue_country", "pitch_region"], as_index=False).agg(
            venue_runs=("runs_conceded", "sum"), venue_balls=("balls_bowled", "sum")
        )
        venue_avg["venue_econ"] = 6.0 * venue_avg["venue_runs"] / venue_avg["venue_balls"].replace(0, np.nan)

        pv = (
            pfb_v.groupby("venue", as_index=False)
            .agg(
                runs=("runs_conceded", "sum"),
                balls=("balls_bowled", "sum"),
                wickets=("wickets", "sum"),
                innings=("wickets", "size"),
            )
        )
        pv["overs"] = [fmt_overs(b) for b in pv["balls"]]
        pv["econ"] = 6.0 * pv["runs"] / pv["balls"].replace(0, np.nan)
        pv = pv.merge(venue_avg[["venue", "venue_country", "pitch_region", "venue_econ"]], on="venue", how="left")
        pv["vs_venue_econ"] = pv["econ"] - pv["venue_econ"]

        reliable = pv[pv["balls"] >= MIN_VENUE_BALLS].sort_values("vs_venue_econ", ascending=False)
        if reliable.empty:
            st.info(f"{player_bv} has no venue with at least {MIN_VENUE_BALLS} balls in this view.")
        else:
            fig = px.bar(
                reliable,
                x="vs_venue_econ",
                y="venue",
                orientation="h",
                color=np.where(reliable["vs_venue_econ"] <= 0, "More economical than venue avg", "More expensive than venue avg"),
                color_discrete_map={"More economical than venue avg": TEAL, "More expensive than venue avg": AMBER},
                custom_data=["overs", "innings", "econ", "venue_econ", "wickets", "runs", "venue_country", "pitch_region"],
                labels={"vs_venue_econ": "Bowler economy minus venue average economy (negative = better)", "venue": "", "color": ""},
            )
            fig.update_traces(
                hovertemplate=(
                    "<b>%{y}</b> (%{customdata[6]} · %{customdata[7]})<br>"
                    "Economy difference: <b>%{x:+.2f} rpo</b><br>"
                    "Bowler Econ: <b>%{customdata[2]:.2f}</b> · Venue avg Econ: <b>%{customdata[3]:.2f}</b><br>"
                    "Record: <b>%{customdata[4]:,.0f} wkts</b> for %{customdata[5]:,.0f} runs (%{customdata[0]} ov, %{customdata[1]:,.0f} inns)<extra></extra>"
                )
            )
            fig.add_vline(x=0, line_color=NAVY, line_width=1.5)
            fig.update_layout(legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"))
            st.plotly_chart(
                style_fn(
                    fig,
                    f"{player_bv}: economy rate against the venue average (negative = better)",
                    height=max(320, 40 * len(reliable) + 120),
                ),
                width="stretch",
                theme=None,
            )

        st.markdown("#### All venues for this bowler")
        vt = pv.sort_values(["wickets", "balls"], ascending=[False, False]).copy()
        vt["Pitch"] = np.where(
            vt["pitch_region"].eq("Indian venue"),
            "<span class='pill ok'>India</span>",
            "<span class='pill overseas'>" + vt["venue_country"].astype(str) + " (Overseas)</span>",
        )
        vt = vt[["venue", "Pitch", "innings", "overs", "runs", "wickets", "econ", "venue_econ", "vs_venue_econ"]].rename(
            columns={
                "venue": "Venue",
                "innings": "Inns",
                "overs": "Overs",
                "runs": "Runs",
                "wickets": "Wickets",
                "econ": "Economy",
                "venue_econ": "Venue avg Econ",
                "vs_venue_econ": "Difference",
            }
        )
        html_table_fn(
            vt,
            formats={"Economy": "{:.2f}", "Venue avg Econ": "{:.2f}", "Difference": "{:+.2f}"},
            num_cols=["Inns", "Overs", "Runs", "Wickets", "Economy", "Venue avg Econ", "Difference"],
        )

    # ------------------------------------------------------------------------
    # 7. Pressure (Complete Bowling Pressure Analytics & IPL Scouting)
    # ------------------------------------------------------------------------
    with tab_pressure:
        st.markdown(
            "<div class='note'><b>Bowling Pressure Matrix & IPL Containment / Strike Scouting:</b><br>"
            "• <b>Condition 1 — Death-Overs Containment Pressure:</b> <b>Only ≤ 2 wickets have fallen</b> (8+ wickets in hand) · "
            "<b>Last 5 overs (≤ 30 legal balls remaining)</b> · <b>~9+ runs per over</b> — bowler must <b>contain set batters and win the match</b>.<br>"
            "• <b>Condition 2 — Quick Wickets Needed Pressure:</b> <b>Current Run Rate &gt; 11.0</b> with <b>≤ 2 wickets down</b> — "
            "batters are flying at &gt;11 RPO and <b>quick wickets are needed</b> along with dot-ball containment.</div>",
            unsafe_allow_html=True,
        )

        if bowl_pressure_raw is None or bowl_pressure_raw.empty:
            st.info("Missing `cleaned_data/pressure_bowler_summary.csv`. Run the bowling pressure builder script.")
        else:
            bp_c1, bp_c2, bp_c3 = st.columns([1.25, 1.1, 1])
            with bp_c1:
                scenario_mode = st.selectbox(
                    "Bowling pressure scenario lens",
                    options=[
                        "Combined Bowling Pressure (Death Containment + Current RR > 11)",
                        "Death-Overs Containment (Last 5 Overs · ≤ 2 Wkts Down · ~9 RPO)",
                        "Quick Wickets Needed (Current RR > 11.0 · Partnership Breaker)",
                    ],
                    index=0,
                    key="bowl_press_scenario",
                )
            with bp_c2:
                cluster_mode = st.selectbox(
                    "Competition / Pitch cluster lens",
                    options=[
                        "Indian Venues vs Overseas Venues",
                        "IPL (T20) vs T20 Internationals (T20I)",
                    ],
                    index=0,
                    key="bowl_press_cluster",
                )
            with bp_c3:
                min_bp_balls = st.slider(
                    "Minimum pressure legal balls",
                    min_value=12,
                    max_value=60,
                    value=24,
                    step=6,
                    help="Default 24 legal balls (4 overs) bowled under pressure.",
                    key="bowl_press_min_balls",
                )

            only_elig_india = st.checkbox(
                "Only eligible bowlers who performed well on Indian pitches (≥ 15 India innings · ≥ 240 India balls · India Economy ≤ 8.65 · ≥ 24 India pressure balls · ≥ 2 India pressure wickets · India Pressure Economy ≤ 9.60)",
                value=True,
                key="bowl_press_only_elig_india",
            )

            use_ipl_b = cluster_mode.startswith("IPL")
            bp = bowl_pressure_raw.copy()
            if sel_ps:
                bp = bp[bp["pace_or_spin"].isin(sel_ps)].copy()
            if only_elig_india and "is_eligible_india" in bp.columns:
                bp = bp[bp["is_eligible_india"] >= 1].copy()

            if scenario_mode.startswith("Death-Overs"):
                scen_prefix = "contain"
                scen_label = "Death Containment (≤30b left, ≤2 wkts)"
            elif scenario_mode.startswith("Quick Wickets"):
                scen_prefix = "quick_wkt"
                scen_label = "Quick Wickets Needed (CRR > 11)"
            else:
                scen_prefix = "pressure"
                scen_label = "Combined Pressure"

            bp["active_balls"] = bp[f"{scen_prefix}_balls"]
            bp["active_runs"] = bp[f"{scen_prefix}_runs"]
            bp["active_wickets"] = bp[f"{scen_prefix}_wickets"]
            bp["active_dots"] = bp[f"{scen_prefix}_dots"]
            bp["active_econ"] = bp[f"{scen_prefix}_econ"]
            bp["active_sr"] = bp[f"{scen_prefix}_sr"]
            bp["active_dot_pct"] = bp[f"{scen_prefix}_dot_pct"]
            bp["active_win_pct"] = bp[f"{scen_prefix}_win_pct"]

            if use_ipl_b:
                prim_prefix = "ipl_pressure"
                prim_ord_prefix = "ipl_ordinary"
                sec_prefix = "t20i_pressure"
                lens_name = "IPL"
                alt_name = "T20I"
            else:
                prim_prefix = "india_pressure"
                prim_ord_prefix = "india_ordinary"
                sec_prefix = "overseas_pressure"
                lens_name = "India"
                alt_name = "Overseas"

            bp_qual = bp[bp["active_balls"] >= min_bp_balls].copy()
            bp_qual["econ_delta"] = bp_qual["active_econ"] - bp_qual["ordinary_econ"]
            bp_qual["prim_econ_delta"] = bp_qual[f"{prim_prefix}_econ"] - bp_qual[f"{prim_ord_prefix}_econ"]
            bp_qual["cluster_econ_diff"] = bp_qual[f"{prim_prefix}_econ"] - bp_qual[f"{sec_prefix}_econ"]
            bp_qual["prim_ball_share"] = (
                100.0 * bp_qual[f"{prim_prefix}_balls"] / bp_qual["pressure_balls"].replace(0, np.nan)
            )

            # Compute composite Bowling Pressure Fit Score (0-100):
            # 45% Containment (Lower Economy), 35% Quick-Wicket Threat (Lower SR / Higher Wickets), 20% Dot% + Win%
            econ_pool = bp_qual["active_econ"].dropna()
            sr_pool = bp_qual["active_sr"].dropna()
            dot_pool = bp_qual["active_dot_pct"].dropna()
            win_pool = bp_qual["active_win_pct"].dropna()

            def inv_pct(series, val):
                if pd.isna(val) or series.empty:
                    return 50.0
                return 100.0 * (series > val).mean()

            def pos_pct(series, val):
                if pd.isna(val) or series.empty:
                    return 50.0
                return 100.0 * (series < val).mean()

            fit_scores = []
            for _, r in bp_qual.iterrows():
                p_econ = inv_pct(econ_pool, r["active_econ"])
                p_sr = inv_pct(sr_pool, r["active_sr"]) if pd.notna(r["active_sr"]) and r["active_wickets"] > 0 else 15.0
                p_dot = pos_pct(dot_pool, r["active_dot_pct"])
                p_win = pos_pct(win_pool, r["active_win_pct"])
                fit_scores.append(0.45 * p_econ + 0.35 * p_sr + 0.10 * p_dot + 0.10 * p_win)
            bp_qual["pressure_fit_score"] = fit_scores

            # Also compute IPL / India specific Fit Score for Top 10 picks
            prim_cands = bp_qual[
                (bp_qual[f"{prim_prefix}_balls"] >= min_bp_balls)
                & (bp_qual[f"{prim_prefix}_wickets"] >= 2)
            ].copy()
            if prim_cands.empty:
                prim_cands = bp_qual[bp_qual["active_wickets"] >= 1].copy()

            p_econ_s = prim_cands[f"{prim_prefix}_econ"].dropna()
            p_sr_s = prim_cands[f"{prim_prefix}_sr"].dropna()
            p_dot_s = prim_cands[f"{prim_prefix}_dot_pct"].dropna()
            p_win_s = prim_cands[f"{prim_prefix}_win_pct"].dropna()

            prim_fit = []
            for _, r in prim_cands.iterrows():
                sc_e = inv_pct(p_econ_s, r[f"{prim_prefix}_econ"])
                sc_sr = inv_pct(p_sr_s, r[f"{prim_prefix}_sr"]) if pd.notna(r[f"{prim_prefix}_sr"]) else 20.0
                sc_dt = pos_pct(p_dot_s, r[f"{prim_prefix}_dot_pct"])
                sc_wn = pos_pct(p_win_s, r[f"{prim_prefix}_win_pct"])
                prim_fit.append(0.45 * sc_e + 0.35 * sc_sr + 0.10 * sc_dt + 0.10 * sc_wn)
            prim_cands["prim_fit_score"] = prim_fit

            top10_bowl = prim_cands.sort_values(
                ["prim_fit_score", f"{prim_prefix}_econ", f"{prim_prefix}_wickets"],
                ascending=[False, True, False],
            ).head(10).copy()
            top10_bowl["rank"] = range(1, len(top10_bowl) + 1)
            top10_b_names = set(top10_bowl["bowler_name"].tolist())

            alt_stars = bp_qual[
                (~bp_qual["bowler_name"].isin(top10_b_names))
                & (bp_qual[f"{sec_prefix}_balls"] >= 18)
                & (bp_qual[f"{sec_prefix}_econ"] <= 9.5)
            ].sort_values([f"{sec_prefix}_econ", f"{sec_prefix}_wickets"], ascending=[True, False]).copy()

            # ----------------------------------------------------------------
            # 1. Headline Bowling Pressure KPIs
            # ----------------------------------------------------------------
            st.markdown(f"#### 1 · Bowling pressure landscape ({scen_label} · {lens_name} vs {alt_name})")
            tot_p_balls = int(bp_qual["active_balls"].sum())
            tot_p_runs = int(bp_qual["active_runs"].sum())
            tot_p_wkts = int(bp_qual["active_wickets"].sum())
            tot_p_dots = int(bp_qual["active_dots"].sum())
            overall_p_econ = 6.0 * tot_p_runs / tot_p_balls if tot_p_balls > 0 else np.nan
            overall_p_sr = tot_p_balls / tot_p_wkts if tot_p_wkts > 0 else np.nan
            overall_p_dot_pct = 100.0 * tot_p_dots / tot_p_balls if tot_p_balls > 0 else np.nan

            prim_balls_tot = int(bp_qual[f"{prim_prefix}_balls"].sum())
            sec_balls_tot = int(bp_qual[f"{sec_prefix}_balls"].sum())
            top1_b_name = top10_bowl.iloc[0]["bowler_name"] if not top10_bowl.empty else "–"
            top1_b_econ = top10_bowl.iloc[0][f"{prim_prefix}_econ"] if not top10_bowl.empty else np.nan

            bk = st.columns(6)
            with bk[0]:
                kpi_fn("Qualified bowlers", f"{len(bp_qual):,}")
            with bk[1]:
                kpi_fn(f"Pressure balls ({lens_name} / {alt_name})", f"{prim_balls_tot:,} / {sec_balls_tot:,}")
            with bk[2]:
                kpi_fn("Pressure economy", fmt_fn(overall_p_econ, 2))
            with bk[3]:
                kpi_fn("Quick wickets (Pressure SR)", f"{tot_p_wkts:,} ({fmt_fn(overall_p_sr, 1)})")
            with bk[4]:
                kpi_fn("Pressure dot ball %", f"{fmt_fn(overall_p_dot_pct, 1)}%")
            with bk[5]:
                kpi_fn(f"#1 {lens_name} pressure pick", f"{top1_b_name} ({fmt_fn(top1_b_econ, 2)})")

            st.markdown("")

            # ----------------------------------------------------------------
            # 2. Top 10 Bowling Picks Under Pressure (Containment + Quick Wickets)
            # ----------------------------------------------------------------
            st.markdown(
                f"#### 2 · Top 10 {lens_name} bowling picks under pressure (Containment + Quick Wickets + Match Wins) "
                f"<span style='font-size:0.88rem;font-weight:500;color:#475569'>"
                f"(≥ {min_bp_balls} {lens_name} pressure balls &amp; ≥ 2 pressure wickets)</span>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div class='note'><b>How the Top 10 Bowling Picks are ranked:</b> When only <b>≤ 2 wickets have fallen</b> "
                f"and the opposition is either in the <b>last 5 overs needing ~9 RPO</b> or <b>cruising at Current RR &gt; 11.0</b>, "
                f"an IPL / Indian-conditions bowler must do two things simultaneously: <b>contain the run rate below 9 RPO</b> and "
                f"<b>strike with quick wickets</b>. The <b>{lens_name} Fit Score (0–100)</b> weights <b>45% Containment Economy</b>, "
                f"<b>35% Quick-Wicket Strike Rate</b>, <b>10% Dot Ball %</b>, and <b>10% Match Win %</b>.</div>",
                unsafe_allow_html=True,
            )

            if top10_bowl.empty:
                st.info("No bowlers meet the current minimum pressure balls threshold. Lower the slider above.")
            else:
                b_left, b_right = st.columns([1.15, 1])
                with b_left:
                    t10_b_plot = top10_bowl.sort_values("prim_fit_score", ascending=True).copy()
                    fig_bt10 = go.Figure()
                    fig_bt10.add_bar(
                        x=t10_b_plot[f"{prim_prefix}_econ"],
                        y=t10_b_plot["bowler_name"],
                        orientation="h",
                        name=f"{lens_name} Pressure Economy (lower = better)",
                        marker_color=TEAL,
                        text=[
                            f"{e:.2f} Econ · {int(w)}W ({int(b)}b)"
                            for e, w, b in zip(
                                t10_b_plot[f"{prim_prefix}_econ"],
                                t10_b_plot[f"{prim_prefix}_wickets"],
                                t10_b_plot[f"{prim_prefix}_balls"],
                            )
                        ],
                        textposition="inside",
                        insidetextanchor="end",
                        textfont=dict(color="#ffffff", size=11),
                        customdata=t10_b_plot[[
                            f"{prim_prefix}_balls", f"{prim_prefix}_runs", f"{prim_prefix}_wickets",
                            f"{prim_prefix}_sr", f"{prim_prefix}_dot_pct", "prim_fit_score",
                        ]],
                        hovertemplate=(
                            "<b>%{y}</b><br>"
                            f"{lens_name} Pressure Economy: <b>%{{x:.2f}}</b> (%{{customdata[2]:,.0f}}W / %{{customdata[1]:,.0f}}R off %{{customdata[0]:,.0f}}b)<br>"
                            "Quick-Wicket SR: <b>%{customdata[3]:.1f}</b> · Dot ball %: <b>%{customdata[4]:.1f}%</b><br>"
                            f"{lens_name} Fit Score: <b>%{{customdata[5]:.1f}} / 100</b><extra></extra>"
                        ),
                    )
                    fig_bt10.add_scatter(
                        x=t10_b_plot[f"{prim_ord_prefix}_econ"],
                        y=t10_b_plot["bowler_name"],
                        mode="markers",
                        name=f"Ordinary {lens_name} Economy (non-pressure)",
                        marker=dict(size=11, color=AMBER, symbol="diamond", line=dict(width=1.5, color="#ffffff")),
                        customdata=t10_b_plot[[f"{prim_ord_prefix}_balls", f"{prim_ord_prefix}_runs", "prim_econ_delta"]],
                        hovertemplate=(
                            "<b>%{y}</b><br>"
                            f"Ordinary {lens_name} Economy: <b>%{{x:.2f}}</b> (%{{customdata[1]:,.0f}}R off %{{customdata[0]:,.0f}}b)<br>"
                            "Pressure vs Ordinary Econ Δ: <b>%{customdata[2]:+.2f} rpo</b><extra></extra>"
                        ),
                    )
                    fig_bt10.add_vline(x=9.0, line_dash="dash", line_color="#dc2626", line_width=1.4)
                    fig_bt10.update_layout(
                        xaxis_title=f"Economy rate in {lens_name} (dashed line = 9.0 RPO containment target)",
                        yaxis_title="",
                        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"),
                    )
                    st.plotly_chart(
                        style_fn(
                            fig_bt10,
                            f"Top 10 {lens_name} pressure picks: Pressure Econ (bars) vs Ordinary Econ (diamonds)",
                            height=440,
                        ),
                        width="stretch",
                        theme=None,
                    )

                with b_right:
                    fig_bbub = px.scatter(
                        top10_bowl,
                        x=f"{prim_prefix}_econ",
                        y=f"{prim_prefix}_sr",
                        size=f"{prim_prefix}_wickets",
                        color="prim_fit_score",
                        text="bowler_name",
                        color_continuous_scale=SCALE,
                        size_max=34,
                        custom_data=[
                            f"{prim_prefix}_wickets", f"{prim_prefix}_balls",
                            f"{prim_prefix}_dot_pct", f"{prim_prefix}_win_pct", "prim_fit_score",
                        ],
                        labels={
                            f"{prim_prefix}_econ": f"{lens_name} Pressure Economy (lower = better containment)",
                            f"{prim_prefix}_sr": f"{lens_name} Pressure Bowling SR (lower = quicker wickets)",
                            "prim_fit_score": "Fit Score",
                        },
                    )
                    fig_bbub.update_traces(
                        textposition="top center",
                        textfont=dict(color=INK, size=11),
                        marker=dict(line=dict(width=1.5, color=NAVY), opacity=0.9),
                        hovertemplate=(
                            "<b>%{text}</b><br>"
                            f"{lens_name} Pressure Econ: <b>%{{x:.2f}}</b> · Bowling SR: <b>%{{y:.1f}}</b><br>"
                            "Quick Wickets: <b>%{customdata[0]:,.0f}W</b> in %{customdata[1]:,.0f} balls · Dot %: <b>%{customdata[2]:.1f}%</b><br>"
                            "Match Win %: <b>%{customdata[3]:.1f}%</b> · Fit Score: <b>%{customdata[4]:.1f}/100</b><extra></extra>"
                        ),
                    )
                    fig_bbub.add_vline(x=9.0, line_dash="dash", line_color="#64748b", line_width=1.2)
                    fig_bbub.update_layout(coloraxis_colorbar_title="Fit")
                    st.plotly_chart(
                        style_fn(
                            fig_bbub,
                            f"Top 10 {lens_name} picks: Containment Econ vs Quick-Wicket SR (bubble = wickets)",
                            height=440,
                        ),
                        width="stretch",
                        theme=None,
                    )

                t10_b_tbl = top10_bowl.copy()
                t10_b_tbl["Rank"] = [f"<span class='pill ok'>#{r} {lens_name} Pick</span>" for r in t10_b_tbl["rank"]]
                t10_b_tbl["India Overall (Inns · Wkts · Econ)"] = [
                    f"{int(inn)} inns · {int(wk)}W · {ec:.2f}" if pd.notna(ec) and inn > 0 else "–"
                    for inn, wk, ec in zip(
                        t10_b_tbl.get("india_innings", pd.Series([0] * len(t10_b_tbl))),
                        t10_b_tbl.get("india_wickets", pd.Series([0] * len(t10_b_tbl))),
                        t10_b_tbl.get("india_econ", pd.Series([np.nan] * len(t10_b_tbl))),
                    )
                ]
                t10_b_tbl["Death Contain (≤30b, ≤2W)"] = [
                    f"{int(w)}W/{int(ru)}R ({int(b)}b · {ec:.2f})" if b > 0 and pd.notna(ec) else "0b"
                    for w, ru, b, ec in zip(
                        t10_b_tbl["contain_wickets"], t10_b_tbl["contain_runs"],
                        t10_b_tbl["contain_balls"], t10_b_tbl["contain_econ"],
                    )
                ]
                t10_b_tbl["Quick Wkts (CRR > 11)"] = [
                    f"{int(w)}W/{int(ru)}R ({int(b)}b · {ec:.2f})" if b > 0 and pd.notna(ec) else "0b"
                    for w, ru, b, ec in zip(
                        t10_b_tbl["quick_wkt_wickets"], t10_b_tbl["quick_wkt_runs"],
                        t10_b_tbl["quick_wkt_balls"], t10_b_tbl["quick_wkt_econ"],
                    )
                ]
                t10_b_tbl[f"{lens_name} Pressure Record"] = [
                    f"{int(w)}W/{int(ru)}R ({int(b)}b)"
                    for w, ru, b in zip(
                        t10_b_tbl[f"{prim_prefix}_wickets"],
                        t10_b_tbl[f"{prim_prefix}_runs"],
                        t10_b_tbl[f"{prim_prefix}_balls"],
                    )
                ]
                t10_b_tbl[f"{alt_name} Pressure Record"] = [
                    f"{int(w)}W/{int(ru)}R ({int(b)}b · {ec:.2f})" if b > 0 and pd.notna(ec) else "0b"
                    for w, ru, b, ec in zip(
                        t10_b_tbl[f"{sec_prefix}_wickets"],
                        t10_b_tbl[f"{sec_prefix}_runs"],
                        t10_b_tbl[f"{sec_prefix}_balls"],
                        t10_b_tbl[f"{sec_prefix}_econ"],
                    )
                ]

                t10_b_disp = t10_b_tbl[[
                    "Rank", "bowler_name", "bowling_type", "prim_fit_score",
                    "India Overall (Inns · Wkts · Econ)",
                    f"{lens_name} Pressure Record", f"{prim_prefix}_econ", f"{prim_ord_prefix}_econ",
                    f"{prim_prefix}_sr", f"{prim_prefix}_dot_pct",
                    "Death Contain (≤30b, ≤2W)", "Quick Wkts (CRR > 11)",
                    f"{alt_name} Pressure Record", f"{prim_prefix}_win_pct",
                ]].rename(columns={
                    "bowler_name": "Bowler",
                    "bowling_type": "Style",
                    "prim_fit_score": f"{lens_name} Fit (0–100)",
                    f"{prim_prefix}_econ": f"{lens_name} Press Econ",
                    f"{prim_ord_prefix}_econ": f"{lens_name} Ord Econ",
                    f"{prim_prefix}_sr": "Quick-Wkt SR",
                    f"{prim_prefix}_dot_pct": "Dot %",
                    f"{prim_prefix}_win_pct": "Match Win %",
                })
                html_table_fn(
                    t10_b_disp,
                    formats={
                        f"{lens_name} Fit (0–100)": "{:.1f}",
                        f"{lens_name} Press Econ": "{:.2f}",
                        f"{lens_name} Ord Econ": "{:.2f}",
                        "Quick-Wkt SR": "{:.1f}",
                        "Dot %": "{:.1f}",
                        "Match Win %": "{:.1f}",
                    },
                    bar_cols={f"{lens_name} Fit (0–100)": 100.0},
                    num_cols=[
                        f"{lens_name} Fit (0–100)", "India Overall (Inns · Wkts · Econ)",
                        f"{lens_name} Pressure Record",
                        f"{lens_name} Press Econ", f"{lens_name} Ord Econ",
                        "Quick-Wkt SR", "Dot %", "Death Contain (≤30b, ≤2W)",
                        "Quick Wkts (CRR > 11)", f"{alt_name} Pressure Record", "Match Win %",
                    ],
                )

            st.markdown("")

            # ----------------------------------------------------------------
            # 3. Dual-Scenario Breakdown & IPL vs T20I / India vs Overseas
            # ----------------------------------------------------------------
            st.markdown(f"#### 3 · Death containment vs quick-wicket strike power & {lens_name} vs {alt_name} split")
            d_left, d_right = st.columns([1.1, 1])
            with d_left:
                dual_df = bp_qual[(bp_qual["active_wickets"] >= 1) & (bp_qual["active_econ"] <= 13.5)].copy()
                fig_dual = px.scatter(
                    dual_df,
                    x="active_econ",
                    y="active_sr",
                    size="active_balls",
                    color="pace_or_spin",
                    hover_name="bowler_name",
                    size_max=28,
                    color_discrete_map={"Pace": TEAL, "Spin": AMBER, "Unknown": "#64748b"},
                    custom_data=["active_wickets", "active_balls", "active_dot_pct", "active_win_pct", "bowling_type"],
                    labels={
                        "active_econ": "Pressure Economy Rate (Containment — lower is better)",
                        "active_sr": "Pressure Bowling Strike Rate (Quick Wickets — lower is better)",
                        "pace_or_spin": "",
                    },
                )
                fig_dual.update_traces(
                    marker=dict(line=dict(width=1, color=NAVY), opacity=0.86),
                    hovertemplate=(
                        "<b>%{hovertext}</b> (%{customdata[4]})<br>"
                        "Pressure Economy: <b>%{x:.2f}</b> · Quick-Wicket SR: <b>%{y:.1f}</b><br>"
                        "Wickets: <b>%{customdata[0]:,.0f}W</b> in %{customdata[1]:,.0f} balls · Dot %: <b>%{customdata[2]:.1f}%</b><br>"
                        "Match Win %: <b>%{customdata[3]:.1f}%</b><extra></extra>"
                    ),
                )
                fig_dual.add_vline(x=9.0, line_dash="dash", line_color="#64748b", line_width=1.2)
                fig_dual.add_hline(y=18.0, line_dash="dash", line_color="#64748b", line_width=1.2)
                fig_dual.update_layout(legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"))
                st.plotly_chart(
                    style_fn(
                        fig_dual,
                        "Containment (Economy ≤ 9) vs Quick-Wicket Strike Power (SR ≤ 18) by Pace & Spin",
                        height=430,
                    ),
                    width="stretch",
                    theme=None,
                )

            with d_right:
                both_cl = bp_qual[(bp_qual[f"{prim_prefix}_balls"] >= 12) & (bp_qual[f"{sec_prefix}_balls"] >= 12)].copy()
                both_cl = both_cl.sort_values("cluster_econ_diff", ascending=False).head(18)
                if both_cl.empty:
                    st.info(f"Not enough bowlers with ≥ 12 pressure balls in both {lens_name} and {alt_name}.")
                else:
                    both_cl["edge_label"] = np.where(
                        both_cl["cluster_econ_diff"] <= 0,
                        f"More economical in {lens_name}",
                        f"More economical in {alt_name}",
                    )
                    fig_bdiv = px.bar(
                        both_cl,
                        x="cluster_econ_diff",
                        y="bowler_name",
                        orientation="h",
                        color="edge_label",
                        color_discrete_map={
                            f"More economical in {lens_name}": TEAL,
                            f"More economical in {alt_name}": "#0284c7",
                        },
                        custom_data=[
                            f"{prim_prefix}_econ", f"{prim_prefix}_balls",
                            f"{sec_prefix}_econ", f"{sec_prefix}_balls",
                        ],
                        labels={
                            "cluster_econ_diff": f"{lens_name} Pressure Econ minus {alt_name} Pressure Econ (negative = better in {lens_name})",
                            "bowler_name": "",
                            "edge_label": "",
                        },
                    )
                    fig_bdiv.update_traces(
                        hovertemplate=(
                            "<b>%{y}</b><br>"
                            f"Economy difference: <b>%{{x:+.2f}} rpo</b><br>"
                            f"{lens_name} Pressure Econ: <b>%{{customdata[0]:.2f}}</b> (%{{customdata[1]:,.0f}}b)<br>"
                            f"{alt_name} Pressure Econ: <b>%{{customdata[2]:.2f}}</b> (%{{customdata[3]:,.0f}}b)<extra></extra>"
                        )
                    )
                    fig_bdiv.add_vline(x=0, line_color=NAVY, line_width=1.5)
                    fig_bdiv.update_layout(legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"))
                    st.plotly_chart(
                        style_fn(
                            fig_bdiv,
                            f"Bowlers tested in both: {lens_name} vs {alt_name} pressure economy differential",
                            height=430,
                        ),
                        width="stretch",
                        theme=None,
                    )

            if not alt_stars.empty:
                st.markdown(f"##### Strong {alt_name} pressure bowlers outside the {lens_name} Top-10")
                alt_tbl = alt_stars.head(10).copy()
                alt_tbl[f"{alt_name} Pressure"] = [
                    f"{int(w)}W/{int(r)}R ({int(b)}b · Econ {ec:.2f})"
                    for w, r, b, ec in zip(
                        alt_tbl[f"{sec_prefix}_wickets"], alt_tbl[f"{sec_prefix}_runs"],
                        alt_tbl[f"{sec_prefix}_balls"], alt_tbl[f"{sec_prefix}_econ"],
                    )
                ]
                alt_tbl[f"{lens_name} Pressure"] = [
                    f"{int(w)}W/{int(r)}R ({int(b)}b · Econ {ec:.2f})" if b > 0 and pd.notna(ec) else f"0 balls in {lens_name}"
                    for w, r, b, ec in zip(
                        alt_tbl[f"{prim_prefix}_wickets"], alt_tbl[f"{prim_prefix}_runs"],
                        alt_tbl[f"{prim_prefix}_balls"], alt_tbl[f"{prim_prefix}_econ"],
                    )
                ]
                alt_disp = alt_tbl[[
                    "bowler_name", "bowling_type", "pressure_balls", "pressure_wickets", "pressure_econ",
                    f"{alt_name} Pressure", f"{lens_name} Pressure", "pressure_dot_pct", "pressure_win_pct",
                ]].rename(columns={
                    "bowler_name": "Bowler",
                    "bowling_type": "Style",
                    "pressure_balls": "Total Press Balls",
                    "pressure_wickets": "Press Wkts",
                    "pressure_econ": "Overall Press Econ",
                    "pressure_dot_pct": "Dot %",
                    "pressure_win_pct": "Match Win %",
                })
                html_table_fn(
                    alt_disp,
                    formats={"Overall Press Econ": "{:.2f}", "Dot %": "{:.1f}", "Match Win %": "{:.1f}"},
                    num_cols=[
                        "Total Press Balls", "Press Wkts", "Overall Press Econ",
                        f"{alt_name} Pressure", f"{lens_name} Pressure", "Dot %", "Match Win %",
                    ],
                )

            st.markdown("")

            # ----------------------------------------------------------------
            # 4. The Containment Escalator (Dumbbell: Ordinary Economy vs Pressure Economy)
            # ----------------------------------------------------------------
            st.markdown("#### 4 · The containment escalator: bowlers who tighten their economy under crunch pressure")
            top_tight = bp_qual.sort_values("econ_delta", ascending=False).tail(18).copy()
            fig_bdumb = go.Figure()
            for _, r in top_tight.iterrows():
                fig_bdumb.add_trace(
                    go.Scatter(
                        x=[r["ordinary_econ"], r["active_econ"]],
                        y=[r["bowler_name"], r["bowler_name"]],
                        mode="lines",
                        line=dict(color="#94a3b8", width=2.5),
                        showlegend=False,
                        hoverinfo="skip",
                    )
                )
            fig_bdumb.add_trace(
                go.Scatter(
                    x=top_tight["ordinary_econ"],
                    y=top_tight["bowler_name"],
                    mode="markers",
                    name="Ordinary Economy (non-pressure)",
                    marker=dict(size=10, color="#64748b", line=dict(width=1.5, color="#ffffff")),
                    customdata=top_tight[["ordinary_balls", "ordinary_runs"]],
                    hovertemplate=(
                        "<b>%{y}</b><br>"
                        "Ordinary Economy: <b>%{x:.2f}</b> (%{customdata[1]:,.0f}R off %{customdata[0]:,.0f}b)<extra></extra>"
                    ),
                )
            )
            fig_bdumb.add_trace(
                go.Scatter(
                    x=top_tight["active_econ"],
                    y=top_tight["bowler_name"],
                    mode="markers+text",
                    name=f"Pressure Economy ({scen_label})",
                    text=[f"{d:+.2f}" for d in top_tight["econ_delta"]],
                    textposition="middle left",
                    textfont=dict(color=TEAL, size=11),
                    marker=dict(size=12, color=TEAL, line=dict(width=1.5, color="#ffffff")),
                    customdata=top_tight[["active_balls", "active_runs", "active_wickets", "econ_delta"]],
                    hovertemplate=(
                        "<b>%{y}</b><br>"
                        "Pressure Economy: <b>%{x:.2f}</b> (%{customdata[2]:,.0f}W / %{customdata[1]:,.0f}R off %{customdata[0]:,.0f}b)<br>"
                        "Economy tightening: <b>%{customdata[3]:+.2f} rpo</b><extra></extra>"
                    ),
                )
            )
            fig_bdumb.add_vline(x=9.0, line_dash="dash", line_color=AMBER, line_width=1.3)
            fig_bdumb.update_layout(
                xaxis_title="Economy rate (runs per over — left shift means tighter under pressure)",
                yaxis_title="",
                legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"),
            )
            st.plotly_chart(
                style_fn(
                    fig_bdumb,
                    "Bowlers who improve their economy most under pressure compared with ordinary situations",
                    height=500,
                ),
                width="stretch",
                theme=None,
            )

    # ------------------------------------------------------------------------
    # 8. About
    # ------------------------------------------------------------------------
    with tab_about:
        st.markdown("""
**Bowling Definitions & Consolidated Report**
- **Consolidated bowling report:** `cleaned_data/player_bowling_innings.csv` (`10,094` bowler-innings spells across `867` matches), `cleaned_data/player_bowling_profile.csv` (`647` bowlers), `cleaned_data/bowling_wicket_types.csv` (`10,261` bowler-credited wickets), and `cleaned_data/pressure_bowler_summary.csv` (`392` pressure-tested bowlers).
- **Match format (`player_batting_innings.csv` / `player_bowling_innings.csv`):** `T20` refers to **IPL** and `T20I` refers to **T20 Internationals**.
- **Super overs:** Innings 3 and 4 are excluded throughout.
- **Legal balls & overs:** Exclude wides (`wide`) and no-balls (`Overstep`, `other`). Six legal balls equal one over (`overs = balls // 6 + (balls % 6) / 10`).
- **Runs conceded:** Batter runs off the bat plus wides and no-balls. Byes (`byes`), leg-byes (`legbyes`), and penalty runs are not charged against the bowler.
- **Bowler wickets:** Credited for `Caught`, `Bowled`, `LBW`, `Stumped`, and `Hit wicket`. Run-outs (`RunOut`), `Retire Out`, and `Obstructing the field` are team wickets and not credited to the bowler.
- **Bowling pressure conditions:**
  1. **Death-Overs Containment Pressure:** Last 5 overs (`0 < legal_balls_remaining ≤ 30`), at most 2 wickets down (`wickets_down ≤ 2`), and required/current run rate around or above 9 RPO — where the bowler must contain set batters and win the match.
  2. **Quick Wickets Needed Pressure:** `Current Run Rate > 11.0` (after 2 overs) with `wickets_down ≤ 2` — where the batting team is flying and quick wickets are needed.
""")
