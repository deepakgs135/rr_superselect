from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from lib.metrics import economy_rate, share, strike_rate
from lib.queries import state_comparison
from lib.ui import BLUE, ORDINARY, PRESSURE, chart, fmt_or_na, markdown_table, page_header, pct, signed

filters = st.session_state.get("dashboard_filters", {})
page_header(
    "Ordinary vs pressure",
    "Compare player output under the separate batting- and bowling-pressure chase rules.",
    ":material/compare_arrows:",
)

include_small = st.toggle(
    "Include players below the sample minimum (marked for review)",
    value=False,
    key="include_small_pressure_samples",
    help="When off (default), only Eligible players meeting the sample minimum in both ordinary and pressure states are shown.",
)
minimum = int(filters.get("min_balls", 30))
st.caption(
    "Batting pressure: RRR ≥ 15, ≤30 legal balls, and at least 3 wickets lost. "
    "Bowling pressure: exactly 2 wickets lost, ≤30 legal balls, current rate ≥11 RPO, and required rate ≥9 RPO."
)
batter_raw = state_comparison(filters, "batter")
bowler_raw = state_comparison(filters, "bowler")


def by_state(rows: list[dict], keys: tuple[str, ...]) -> dict[int, dict[int, dict]]:
    result: dict[int, dict[int, dict]] = {}
    for row in rows:
        result.setdefault(int(row["player_id"]), {})[int(row["pressure"])] = row
    return result


batter_states = by_state(batter_raw, ("runs", "balls"))
bowler_states = by_state(bowler_raw, ("runs_proxy", "legal_balls"))

batter_compare = []
for player_id, states in batter_states.items():
    pressure = states.get(1, {})
    ordinary = states.get(0, {})
    p_balls = int(pressure.get("balls") or 0)
    o_balls = int(ordinary.get("balls") or 0)
    p_sr = strike_rate(int(pressure.get("runs") or 0), p_balls)
    o_sr = strike_rate(int(ordinary.get("runs") or 0), o_balls)
    if p_sr is None or o_sr is None:
        continue
    sample_flag = p_balls < minimum or o_balls < minimum
    if sample_flag and not include_small:
        continue
    batter_compare.append(
        {
            "player_id": player_id,
            "player": pressure.get("player") or ordinary.get("player") or f"Player {player_id}",
            "pressure_balls": p_balls,
            "ordinary_balls": o_balls,
            "pressure_sr": p_sr,
            "ordinary_sr": o_sr,
            "sr_uplift": round(p_sr - o_sr, 2),
            "pressure_boundary": share(
                int(pressure.get("fours") or 0) + int(pressure.get("sixes") or 0), p_balls
            ),
            "ordinary_boundary": share(
                int(ordinary.get("fours") or 0) + int(ordinary.get("sixes") or 0), o_balls
            ),
            "pressure_dot": share(int(pressure.get("dots") or 0), p_balls),
            "ordinary_dot": share(int(ordinary.get("dots") or 0), o_balls),
            "sample": "Review sample" if sample_flag else "Eligible",
        }
    )
batter_compare.sort(key=lambda row: (-row["sr_uplift"], -row["pressure_balls"]))

bowler_compare = []
for player_id, states in bowler_states.items():
    pressure = states.get(1, {})
    ordinary = states.get(0, {})
    p_balls = int(pressure.get("legal_balls") or 0)
    o_balls = int(ordinary.get("legal_balls") or 0)
    p_econ = economy_rate(int(pressure.get("runs_proxy") or 0), p_balls)
    o_econ = economy_rate(int(ordinary.get("runs_proxy") or 0), o_balls)
    if p_econ is None or o_econ is None:
        continue
    sample_flag = p_balls < minimum or o_balls < minimum
    if sample_flag and not include_small:
        continue
    p_wickets = int(pressure.get("credited_wickets") or 0)
    bowler_compare.append(
        {
            "player_id": player_id,
            "player": pressure.get("player") or ordinary.get("player") or f"Player {player_id}",
            "pressure_balls": p_balls,
            "ordinary_balls": o_balls,
            "pressure_economy": p_econ,
            "ordinary_economy": o_econ,
            "economy_change": round(p_econ - o_econ, 2),
            "pressure_wickets_per_6": round(p_wickets * 6 / p_balls, 3) if p_balls else None,
            "sample": "Review sample" if sample_flag else "Eligible",
        }
    )
bowler_compare.sort(key=lambda row: (row["economy_change"], -row["pressure_balls"]))

if include_small:
    st.warning(
        f"Rows below {minimum} balls in either state are included and marked “Review sample”.",
        title="Small samples",
        icon=":material/warning:",
    )

tab_bat, tab_bowl = st.tabs(["Batting", "Bowling"])
with tab_bat:
    st.subheader("Batter rankings")
    st.caption("Strike-rate uplift is pressure SR minus ordinary SR. Boundary measure is events per 100 balls.")
    bar_rows = batter_compare[:15]
    col1, col2 = st.columns([1.4, 1])
    with col1:
        with st.container(border=True):
            st.markdown("**Top pressure strike-rate uplift**")
            fig = go.Figure(
                go.Bar(
                    x=[row["sr_uplift"] for row in reversed(bar_rows)],
                    y=[row["player"] for row in reversed(bar_rows)],
                    orientation="h",
                    marker_color=PRESSURE,
                    customdata=[[row["pressure_balls"], row["ordinary_balls"]] for row in reversed(bar_rows)],
                    hovertemplate="%{y}<br>Uplift %{x:+.1f}<br>Pressure balls %{customdata[0]}<br>Ordinary balls %{customdata[1]}<extra></extra>",
                )
            )
            fig.update_layout(xaxis_title="Pressure SR − ordinary SR", yaxis_title="")
            chart(fig, "Top batters by pressure strike-rate uplift", height=440)
    with col2:
        with st.container(border=True):
            st.markdown("**Pressure and ordinary strike rate**")
            eligible = [row for row in batter_compare if row["sample"] == "Eligible"]
            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=[row["ordinary_sr"] for row in eligible],
                    y=[row["pressure_sr"] for row in eligible],
                    mode="markers",
                    marker=dict(
                        color=[row["sr_uplift"] for row in eligible],
                        colorscale=[[0, ORDINARY], [0.5, BLUE], [1, PRESSURE]],
                        size=10,
                        line=dict(color="white", width=1),
                        colorbar=dict(title="SR uplift"),
                    ),
                    text=[row["player"] for row in eligible],
                    customdata=[[row["pressure_balls"], row["ordinary_balls"]] for row in eligible],
                    hovertemplate="%{text}<br>Ordinary SR %{x:.1f}<br>Pressure SR %{y:.1f}<br>Pressure balls %{customdata[0]}<br>Ordinary balls %{customdata[1]}<extra></extra>",
                )
            )
            if eligible:
                maximum = max(
                    max(row["ordinary_sr"] or 0, row["pressure_sr"] or 0) for row in eligible
                )
                fig.add_trace(
                    go.Scatter(
                        x=[0, maximum],
                        y=[0, maximum],
                        mode="lines",
                        name="Parity",
                        line=dict(color="#94A3B8", dash="dash"),
                        hoverinfo="skip",
                    )
                )
            fig.update_layout(xaxis_title="Ordinary strike rate", yaxis_title="Pressure strike rate")
            chart(fig, "Player strike rate under pressure versus ordinary chase states", height=440)
    markdown_table(
        batter_compare[:40],
        [
            ("player", "Batter"),
            ("pressure_balls", "Pressure balls"),
            ("ordinary_balls", "Ordinary balls"),
            ("pressure_sr", "Pressure SR"),
            ("ordinary_sr", "Ordinary SR"),
            ("sr_uplift", "SR uplift"),
            ("pressure_boundary", "Pressure boundaries / 100"),
            ("pressure_dot", "Pressure dot share"),
            ("sample", "Sample"),
        ],
    )

with tab_bowl:
    st.subheader("Bowler rankings")
    st.caption(
        "Bowling pressure uses exactly two wickets down, the final 30 legal balls, current rate ≥11 RPO, "
        "and required rate ≥9 RPO. Economy is a raw-field proxy (runs + extras_2_runs) per six legal balls."
    )
    top_bowlers = sorted(bowler_compare, key=lambda row: (row["economy_change"], row["player"]))[:15]
    col1, col2 = st.columns([1.25, 1])
    with col1:
        with st.container(border=True):
            st.markdown("**Pressure economy change**")
            plotted = list(reversed(top_bowlers))
            fig = go.Figure(
                go.Bar(
                    x=[row["economy_change"] for row in plotted],
                    y=[row["player"] for row in plotted],
                    orientation="h",
                    marker_color=[PRESSURE if row["economy_change"] > 0 else ORDINARY for row in plotted],
                    customdata=[[row["pressure_balls"], row["ordinary_balls"]] for row in plotted],
                    hovertemplate="%{y}<br>Pressure − ordinary %{x:+.2f}<br>Pressure legal balls %{customdata[0]}<br>Ordinary legal balls %{customdata[1]}<extra></extra>",
                )
            )
            fig.update_layout(xaxis_title="Pressure economy − ordinary economy", yaxis_title="")
            chart(fig, "Bowler raw economy change in bowling-pressure chase states", height=440)
    with col2:
        with st.container(border=True):
            st.markdown("**Pressure wicket rate**")
            fig = go.Figure(
                go.Scatter(
                    x=[row["pressure_economy"] for row in bowler_compare],
                    y=[row["pressure_wickets_per_6"] for row in bowler_compare],
                    mode="markers",
                    marker=dict(color=BLUE, size=10, opacity=0.8),
                    text=[row["player"] for row in bowler_compare],
                    customdata=[[row["pressure_balls"], row["economy_change"]] for row in bowler_compare],
                    hovertemplate="%{text}<br>Pressure economy %{x:.2f}<br>Wickets / 6 balls %{y:.3f}<br>Pressure balls %{customdata[0]}<br>Economy change %{customdata[1]:+.2f}<extra></extra>",
                )
            )
            fig.update_layout(xaxis_title="Pressure raw economy proxy", yaxis_title="Credited wickets per 6 legal balls")
            chart(fig, "Bowling-pressure economy against credited wickets per six legal balls", height=440)
    markdown_table(
        bowler_compare[:40],
        [
            ("player", "Bowler"),
            ("pressure_balls", "Pressure legal balls"),
            ("ordinary_balls", "Ordinary legal balls"),
            ("pressure_economy", "Pressure economy"),
            ("ordinary_economy", "Ordinary economy"),
            ("economy_change", "Economy change"),
            ("pressure_wickets_per_6", "Wickets / 6 balls"),
            ("sample", "Sample"),
        ],
    )
