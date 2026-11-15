"""Batting insights dashboard (v3).

Run:   streamlit run app.py
Data:  cleaned_data/player_batting_innings.csv        (required)
       cleaned_data/batting_dismissal_types.csv       (optional, dismissal donut)
       cleaned_data/pressure_batter_summary.csv       (optional, from the pipeline)

Rules used throughout:
- Super overs (innings 3 and 4) are excluded.
- Balls faced exclude wides (no-balls are counted).
- Average = runs per dismissal. Strike rate = runs per 100 balls faced.
- Venues are shown by ID, because the pack has no stadium names.
- Tables are rendered as HTML, so the app does not need pyarrow.
"""
from html import escape
import importlib
from pathlib import Path
import sys

# Prevent Windows Application Control DLL blocks on pandas/pyarrow C-extensions (.pyd)
sys.modules["pandas"] = None
sys.modules["pyarrow"] = None

import plotly.graph_objects as go
import streamlit as st
import pure_engine

importlib.reload(pure_engine)
from pure_engine import np, pd, px

st.set_page_config(page_title="Batting insights", page_icon="🏏", layout="wide")

BASE = Path(__file__).resolve().parent / "cleaned_data"
RAW_BASE = Path(__file__).resolve().parent / "Raw_Data"
INNINGS_FILE = BASE / "player_batting_innings.csv"
DISMISSAL_FILE = BASE / "batting_dismissal_types.csv"
PRESSURE_FILE = BASE / "pressure_batter_summary_rrr15.csv"
BOWLING_INNINGS_FILE = BASE / "player_bowling_innings.csv"
BOWLING_WICKETS_FILE = BASE / "bowling_wicket_types.csv"

TEAL, NAVY, AMBER, GREY, LIGHT = "#0f766e", "#0f172a", "#d97706", "#475569", "#0284c7"
INK, MUTED_TEXT, SOFT_BG, CARD, BORDER = "#0f172a", "#334155", "#f1f5f9", "#ffffff", "#cbd5e1"
CATEGORY = [
    "#0f766e", "#d97706", "#2563eb", "#7c3aed", "#db2777",
    "#0284c7", "#16a34a", "#dc2626", "#4f46e5", "#ca8a04", "#475569",
]
SCALE = ["#2dd4bf", "#0d9488", "#0f766e", "#1e3a8a"]
PLAYER_COLOURS = [TEAL, AMBER]
TEMPLATE = "plotly_white"
MIN_VENUE_BALLS = 30
MIN_INNINGS_COMPARE = 10

CSS = """
<style>
/* Base app & header */
.stApp {background-color: #f1f5f9 !important; color: #0f172a !important;}
header[data-testid="stHeader"] {background-color: #ffffff !important; border-bottom: 1px solid #cbd5e1 !important;}
header[data-testid="stHeader"] * {color: #0f172a !important;}
.block-container {padding-top: 1.5rem; max-width: 1420px;}

/* Typography & general text contrast */
h1, h2, h3, h4, h5, h6 {color: #0f172a !important; font-weight: 700 !important;}
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] span,
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p {
    color: #1e293b !important;
}
[data-testid="stWidgetLabel"],
[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] span,
label[data-testid="stWidgetLabel"] {
    color: #0f172a !important;
    font-weight: 600 !important;
    font-size: 0.92rem !important;
}

/* Sidebar styling */
section[data-testid="stSidebar"] {
    background-color: #ffffff !important;
    border-right: 2px solid #cbd5e1 !important;
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span {
    color: #0f172a !important;
}
section[data-testid="stSidebar"] hr {
    border-color: #cbd5e1 !important;
}

/* Inputs: Selectbox & Multiselect high contrast */
div[data-baseweb="select"] > div {
    background-color: #f8fafc !important;
    border: 1.5px solid #94a3b8 !important;
    border-radius: 8px !important;
    color: #0f172a !important;
}
div[data-baseweb="select"] input {
    color: #0f172a !important;
}
div[data-baseweb="select"] svg {
    fill: #0f172a !important;
    color: #0f172a !important;
}
span[data-baseweb="tag"] {
    background-color: #0f766e !important;
    color: #ffffff !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
}
span[data-baseweb="tag"] span,
span[data-baseweb="tag"] svg {
    color: #ffffff !important;
    fill: #ffffff !important;
}
/* Dropdown menu options (scoped so tooltips are not affected) */
ul[data-baseweb="menu"],
li[role="option"] {
    background-color: #ffffff !important;
    color: #0f172a !important;
}
li[role="option"]:hover,
li[role="option"][aria-selected="true"] {
    background-color: #ccfbf1 !important;
    color: #0f766e !important;
}

/* Streamlit native help tooltips */
div[data-baseweb="tooltip"],
div[data-testid="stTooltipContent"] {
    background-color: #0f172a !important;
    color: #f8fafc !important;
    border: 1px solid #0f766e !important;
    border-radius: 8px !important;
    padding: 8px 12px !important;
    font-size: 0.86rem !important;
    font-weight: 500 !important;
    box-shadow: 0 8px 20px rgba(15, 23, 42, 0.22) !important;
}
div[data-testid="stTooltipContent"] p,
div[data-testid="stTooltipContent"] span {
    color: #f8fafc !important;
}
svg[data-testid="stTooltipIcon"] {
    fill: #0f766e !important;
    color: #0f766e !important;
}

/* Plotly hover tooltip visual polish (rounded card + drop shadow) */
.js-plotly-plot .plotly .hoverlayer .hovertext path {
    rx: 8px !important;
    ry: 8px !important;
    stroke-width: 1.5px !important;
    filter: drop-shadow(0 6px 16px rgba(15, 23, 42, 0.18));
}
.js-plotly-plot .plotly .hoverlayer .hovertext text {
    font-family: "Segoe UI", system-ui, -apple-system, sans-serif !important;
}

/* Sliders */
[data-testid="stTickBarMin"],
[data-testid="stTickBarMax"],
[data-testid="stThumbValue"] {
    color: #0f172a !important;
    font-weight: 600 !important;
}

/* Hero Banner */
.hero {
    padding: 1.35rem 1.75rem;
    border-radius: 14px;
    margin-bottom: 1.2rem;
    background: linear-gradient(135deg, #0f172a 0%, #115e59 100%);
    border: 1px solid #0f766e;
    box-shadow: 0 4px 12px rgba(15, 23, 42, 0.12);
}
.hero h1,
.hero h1 *,
[data-testid="stMarkdownContainer"] .hero h1,
[data-testid="stMarkdownContainer"] .hero h1 * {
    margin: 0 !important;
    padding: 0 !important;
    font-size: 1.95rem !important;
    font-weight: 800 !important;
    color: #ffffff !important;
    letter-spacing: -0.01em !important;
}
.hero p,
.hero p *,
[data-testid="stMarkdownContainer"] .hero p,
[data-testid="stMarkdownContainer"] .hero p * {
    margin: .35rem 0 0 0 !important;
    color: #ccfbf1 !important;
    font-size: 1.02rem !important;
    font-weight: 500 !important;
}

/* KPI Cards */
.kpi {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-top: 4px solid #0f766e;
    border-radius: 12px;
    padding: 14px 16px;
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.05);
}
.kpi .label {
    font-size: .76rem;
    color: #334155 !important;
    text-transform: uppercase;
    letter-spacing: .06em;
    font-weight: 700;
}
.kpi .value {
    font-size: 1.55rem;
    font-weight: 800;
    color: #0f172a !important;
    line-height: 1.25;
    margin-top: 2px;
}

/* Plotly chart cards */
[data-testid="stPlotlyChart"] {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 12px;
    padding: 6px;
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.04);
}

/* Notes & Tables */
.note {
    font-size: .9rem;
    color: #1e293b !important;
    background: #e2e8f0;
    padding: 8px 12px;
    border-left: 4px solid #0f766e;
    border-radius: 6px;
    margin: .3rem 0 .8rem 0;
}
.tbl-wrap {
    width: 100%;
    overflow-x: auto;
    border-radius: 10px;
    border: 1px solid #cbd5e1;
    background: #ffffff;
    margin-bottom: 1rem;
    box-shadow: 0 1px 4px rgba(15, 23, 42, 0.04);
}
.tbl {
    width: 100%;
    border-collapse: collapse;
    font-size: .9rem;
    margin-bottom: 0;
    background: #ffffff;
}
.tbl th {
    text-align: left;
    background: #0f172a;
    color: #ffffff !important;
    padding: 10px 12px;
    font-weight: 700;
    border-bottom: 3px solid #0f766e;
    white-space: nowrap;
}
.tbl th.num {
    text-align: right;
}
.tbl td {
    padding: 9px 12px;
    border-bottom: 1px solid #e2e8f0;
    color: #0f172a !important;
    font-weight: 500;
    vertical-align: middle;
}
.tbl tr:last-child td {border-bottom: none;}
.tbl tr:nth-child(even) td {background: #f8fafc;}
.tbl tr:hover td {background: #f0fdfa;}
.tbl td.num {
    text-align: right;
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    white-space: nowrap;
}
.bar {height: 9px; border-radius: 4px; background: #0f766e; min-width: 2px;}
.pill {display:inline-block; padding:3px 10px; border-radius:999px; font-size:.78rem; font-weight:700; white-space:nowrap;}
.pill.ok {background:#a7f3d0; color:#064e3b !important; border: 1px solid #10b981;}
.pill.overseas {background:#bae6fd; color:#0c4a6e !important; border: 1px solid #0284c7;}
.pill.small {background:#fde68a; color:#78350f !important; border: 1px solid #f59e0b;}
.pill.warn {background:#fee2e2; color:#991b1b !important; border: 1px solid #f87171;}

/* Tabs */
div[data-baseweb="tab-list"],
div[role="tablist"] {
    gap: 8px !important;
    border-bottom: 2px solid #cbd5e1 !important;
    padding-bottom: 4px !important;
    margin-bottom: 0.5rem !important;
}
button[data-baseweb="tab"],
button[role="tab"] {
    background-color: #e2e8f0 !important;
    border-radius: 8px 8px 0 0 !important;
    padding: 8px 18px !important;
    border: 1px solid #cbd5e1 !important;
    border-bottom: none !important;
    transition: all 0.15s ease !important;
}
button[data-baseweb="tab"],
button[data-baseweb="tab"] p,
button[data-baseweb="tab"] div,
button[data-baseweb="tab"] span,
button[role="tab"],
button[role="tab"] p,
button[role="tab"] div,
button[role="tab"] span {
    color: #1e293b !important;
    font-weight: 600 !important;
    font-size: 0.94rem !important;
}
button[data-baseweb="tab"][aria-selected="true"],
button[role="tab"][aria-selected="true"] {
    background-color: #0f766e !important;
    border-color: #0f766e !important;
    box-shadow: 0 2px 6px rgba(15, 118, 110, 0.22) !important;
}
button[data-baseweb="tab"][aria-selected="true"],
button[data-baseweb="tab"][aria-selected="true"] p,
button[data-baseweb="tab"][aria-selected="true"] div,
button[data-baseweb="tab"][aria-selected="true"] span,
button[role="tab"][aria-selected="true"],
button[role="tab"][aria-selected="true"] p,
button[role="tab"][aria-selected="true"] div,
button[role="tab"][aria-selected="true"] span {
    color: #ffffff !important;
    font-weight: 700 !important;
}
div[data-baseweb="tab-highlight"] {background-color: #0f766e !important; height: 3px !important;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def kpi(label, value):
    st.markdown(
        f"<div class='kpi'><div class='label'>{label}</div>"
        f"<div class='value'>{value}</div></div>",
        unsafe_allow_html=True,
    )


def fmt(x, digits=1):
    return "–" if x is None or pd.isna(x) else f"{x:,.{digits}f}"


HOVER_STYLE = dict(
    bgcolor="#0f172a",
    bordercolor="#14b8a6",
    font=dict(color="#f8fafc", size=13, family="Segoe UI, system-ui, sans-serif"),
    align="left",
    namelength=-1,
)


def style(fig, title, height=360):
    has_h_legend = getattr(fig.layout.legend, "orientation", None) == "h" and (
        getattr(fig.layout.legend, "y", 1) is None or getattr(fig.layout.legend, "y", 1) > 0
    )
    top_margin = 92 if has_h_legend else 54
    bottom_margin = 16
    plot_h = max(120, height - top_margin - bottom_margin)
    legend_cfg = dict(
        font=dict(color=INK, size=12),
        bgcolor="rgba(255,255,255,0.95)",
        bordercolor="#cbd5e1",
        borderwidth=1,
    )
    if has_h_legend:
        legend_cfg.update(
            orientation="h",
            x=0.0,
            xanchor="left",
            y=1.0 + (8.0 / plot_h),
            yanchor="bottom",
        )
    fig.update_layout(
        template=TEMPLATE,
        title=dict(
            text=f"<b>{title}</b>",
            x=0.0,
            xanchor="left",
            xref="paper",
            y=1.0,
            yanchor="bottom",
            yref="paper",
            pad=dict(b=52 if has_h_legend else 14),
            font=dict(size=16, color=INK, family="sans-serif"),
        ),
        height=height,
        margin=dict(l=14, r=14, t=top_margin, b=bottom_margin),
        legend_title_text="",
        legend=legend_cfg,
        coloraxis_colorbar=dict(
            title_font=dict(color=INK, size=12),
            tickfont=dict(color=MUTED_TEXT, size=11),
        ),
        hoverlabel=HOVER_STYLE,
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(color=INK, size=13, family="sans-serif"),
    )
    fig.update_traces(hoverlabel=HOVER_STYLE)
    fig.update_xaxes(
        gridcolor="#e2e8f0",
        linecolor="#94a3b8",
        zerolinecolor="#cbd5e1",
        tickfont=dict(color=INK, size=12),
        title_font=dict(color=INK, size=13),
    )
    fig.update_yaxes(
        gridcolor="#e2e8f0",
        linecolor="#94a3b8",
        zerolinecolor="#cbd5e1",
        tickfont=dict(color=INK, size=12),
        title_font=dict(color=INK, size=13),
    )
    if "yaxis2" in fig.layout:
        fig.layout.yaxis2.update(
            tickfont=dict(color=AMBER, size=12),
            title_font=dict(color=AMBER, size=13),
            linecolor="#94a3b8",
        )
    return fig


def html_table(df, formats=None, bar_cols=None, num_cols=None):
    """Render a DataFrame as a styled HTML table. No pyarrow needed.

    formats:   {col: "{:.1f}"} format string per column
    bar_cols:  {col: max_value} draws a small bar behind the number
    num_cols:  columns to right-align
    Values already containing HTML (for example pills) are passed through unescaped
    when they start with '<'.
    """
    formats = formats or {}
    bar_cols = bar_cols or {}
    num_cols = set(num_cols or [])
    th_cls_attr = " class='num'"
    head = "".join(
        f"<th{th_cls_attr if c in num_cols else ''}>{escape(str(c))}</th>"
        for c in df.columns
    )
    rows = []
    for _, r in df.iterrows():
        cells = []
        for c in df.columns:
            v = r[c]
            is_missing = (not isinstance(v, str)) and pd.isna(v)
            if is_missing:
                text = "–"
            elif isinstance(v, str) and v.startswith("<"):
                text = v
            else:
                if c in formats:
                    text = formats[c].format(v)
                elif isinstance(v, int) and not isinstance(v, bool):
                    text = f"{v:,}"
                elif isinstance(v, float) and v.is_integer():
                    text = f"{int(round(v)):,}"
                else:
                    text = str(v)
                text = escape(text)
            if c in bar_cols and not is_missing and bar_cols[c]:
                pct = max(0.0, min(100.0, 100 * float(r[c]) / bar_cols[c]))
                text = ("<div style='display:flex;align-items:center;justify-content:flex-end;gap:8px'>"
                        f"<span style='min-width:36px;text-align:right'>{text}</span>"
                        f"<div class='bar' style='width:{pct:.0f}px;max-width:70px'></div></div>")
            cls = " class='num'" if c in num_cols else ""
            cells.append(f"<td{cls}>{text}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    st.markdown(
        f"<div class='tbl-wrap'><table class='tbl'><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>",
        unsafe_allow_html=True,
    )


# ----------------------------------------------------------------------------
# Data (match_format in player_batting_innings.csv: T20 = IPL, T20I = T20 Internationals)
# ----------------------------------------------------------------------------
@st.cache_data(show_spinner="Loading batting innings…")
def load_innings(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    df["innings"] = pd.to_numeric(df["innings"], errors="coerce")
    df = df[df["innings"] <= 2].copy()  # super overs excluded

    for c in ["runs", "balls_faced", "fours", "sixes", "boundary_runs"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["batting_order"] = pd.to_numeric(df["batting_order"], errors="coerce")
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["date"] = pd.to_datetime(df["match_date"], errors="coerce", dayfirst=True)

    for c in ["dismissed", "not_out"]:
        df[c] = df[c].astype(str).str.lower().eq("true")

    home = df["batting_team_id"].eq(df["home_team_id"])
    df["batting_team"] = np.where(home, df["home_team"], df["away_team"])
    df["opposition"] = np.where(home, df["away_team"], df["home_team"])

    # In player_batting_innings.csv: T20 refers to IPL, T20I refers to T20 Internationals
    df["match_format"] = df["match_format"].fillna("T20I").astype(str).str.strip()
    df["is_ipl"] = df["match_format"].eq("T20")

    df["fifty"] = (df["runs"] >= 50) & (df["runs"] < 100)
    df["hundred"] = df["runs"] >= 100
    df["year"] = df["year"].fillna(df["date"].dt.year).astype(int)
    df["season"] = df["year"].astype(str)
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


DISMISSAL_LABELS = {
    "Bowled": "Bowled", "Caught": "Caught", "Hit Wicket": "Hit wicket", "LBW": "LBW",
    "RunOut": "Run out", "Run Out": "Run out", "Stump": "Stumped", "Stumped": "Stumped",
    "Obstracting the field": "Obstructing the field", "Obstructing the field": "Obstructing the field",
    "Retire Out": "Retired",
}


@st.cache_data
def load_dismissals(path: Path):
    if path.exists():
        d = pd.read_csv(path)
        if {"player_id", "dismissal_type", "dismissal_count"}.issubset(d.columns):
            d["player_id"] = pd.to_numeric(d["player_id"], errors="coerce")
            d["dismissal_count"] = pd.to_numeric(d["dismissal_count"], errors="coerce").fillna(0).astype(int)
            d = d[d["dismissal_type"].notna() & (d["dismissal_type"].astype(str).str.strip() != "")].copy()
            d["dismissal_type"] = d["dismissal_type"].map(DISMISSAL_LABELS).fillna(d["dismissal_type"])
            return d
    bbb_file = RAW_BASE / "ball_by_ball.csv"
    if not bbb_file.exists():
        return None
    bbb = pd.read_csv(bbb_file, low_memory=False)
    bbb["innings"] = pd.to_numeric(bbb["innings"], errors="coerce")
    bbb = bbb[bbb["innings"].isin([1, 2])].copy()
    is_wk = bbb["is_wicket"].astype(str).str.strip().str.lower().isin(["true", "1", "1.0"])
    wk = bbb[is_wk & bbb["dismissal_type"].notna() & (bbb["dismissal_type"].astype(str).str.strip() != "")].copy()
    wk["player_id"] = pd.to_numeric(wk["dismissed_player_id"], errors="coerce").fillna(
        pd.to_numeric(wk["striker_id"], errors="coerce")
    ).astype(int)
    wk["player_name"] = np.where(
        wk["player_id"].eq(pd.to_numeric(wk["non_striker_id"], errors="coerce")),
        wk["non_striker_name"],
        wk["striker_name"],
    )
    d = (wk.groupby(["player_id", "player_name", "dismissal_type"], as_index=False)
         .agg(dismissal_count=("runs", "size")))
    try:
        d.to_csv(path, index=False)
    except OSError:
        pass
    d["dismissal_type"] = d["dismissal_type"].map(DISMISSAL_LABELS).fillna(d["dismissal_type"])
    return d


@st.cache_data(show_spinner="Loading pressure metrics…")
def load_pressure(path: Path):
    needed = {
        "striker_name", "pressure_balls", "pressure_sr", "ordinary_sr",
        "india_pressure_balls", "india_pressure_sr",
        "overseas_pressure_balls", "overseas_pressure_sr",
        "india_sr", "overseas_sr",
        "ipl_pressure_balls", "ipl_pressure_sr",
        "t20i_pressure_balls", "t20i_pressure_sr",
    }
    if path.exists():
        p = pd.read_csv(path)
        if needed.issubset(p.columns):
            return p
    bbb_file = RAW_BASE / "ball_by_ball.csv"
    matches_file = RAW_BASE / "matches.csv"
    if not (bbb_file.exists() and matches_file.exists()):
        if path.exists():
            return pd.read_csv(path)
        return None
    m = pd.read_csv(matches_file)
    bbb = pd.read_csv(bbb_file, low_memory=False)
    bbb["innings"] = pd.to_numeric(bbb["innings"], errors="coerce")
    bbb = bbb[bbb["innings"].isin([1, 2])].copy()
    for c in ["overid", "over_ball_num", "innings_ball_num", "runs", "extras1_runs", "extras_2_runs"]:
        bbb[c] = pd.to_numeric(bbb[c], errors="coerce").fillna(0)
    bbb["is_wicket"] = bbb["is_wicket"].astype(str).str.strip().str.lower().isin(["true", "1", "1.0"]).astype(int)
    ext = bbb["extras_type"].astype(str).str.strip().str.lower()
    is_extra_1 = ext.isin(["wide", "overstep", "byes", "legbyes", "other"])
    is_penalty = ext.eq("penalty")
    bbb["team_runs_ball"] = (
        bbb["runs"] + is_extra_1.astype(int) + 5 * is_penalty.astype(int) + bbb["extras_2_runs"]
    )
    bbb = bbb.sort_values(["match_id", "innings", "innings_ball_num", "overid", "over_ball_num"]).reset_index(drop=True)

    inn1 = (bbb[bbb["innings"] == 1].groupby("match_id", as_index=False)["team_runs_ball"]
            .sum().rename(columns={"team_runs_ball": "inn1_runs"}))

    # Map match_format from player_batting_innings.csv: T20 -> IPL, T20I -> T20 Internationals
    if INNINGS_FILE.exists():
        inn_fmt = (pd.read_csv(INNINGS_FILE, low_memory=False)[["match_id", "match_format"]]
                   .drop_duplicates("match_id"))
        m = m.merge(inn_fmt, on="match_id", how="left")
        m["is_ipl"] = m["match_format"].fillna("T20I").astype(str).str.strip().eq("T20")
    else:
        m["is_ipl"] = False

    m_cols = ["match_id", "second_inn_revised_overs", "revised_target", "is_ipl"]
    if "venue_country" in m.columns:
        m_cols.append("venue_country")
    m_target = m[m_cols].drop_duplicates("match_id").merge(inn1, on="match_id", how="left")
    m_target["target"] = np.where(
        m_target["revised_target"].notna() & (m_target["revised_target"] > 0),
        m_target["revised_target"],
        m_target["inn1_runs"] + 1,
    )
    rev = pd.to_numeric(m_target["second_inn_revised_overs"], errors="coerce")
    m_target["max_balls"] = np.where(rev.notna() & (rev > 0), rev, 120.0)
    if "venue_country" not in m_target.columns:
        m_target["venue_country"] = "Unknown"

    bbb = bbb.merge(m_target[["match_id", "target", "max_balls", "venue_country", "is_ipl"]], on="match_id", how="left")
    bbb["wickets_after"] = bbb.groupby(["match_id", "innings"])["is_wicket"].cumsum()
    bbb["wickets_down"] = bbb["wickets_after"] - bbb["is_wicket"]
    bbb["team_runs_after"] = bbb.groupby(["match_id", "innings"])["team_runs_ball"].cumsum()
    bbb["team_runs_before"] = bbb["team_runs_after"] - bbb["team_runs_ball"]

    is_wide = bbb["extras_type"].astype(str).str.lower().eq("wide")
    is_noball = bbb["extras_type"].astype(str).str.lower().eq("overstep")
    bbb["is_legal"] = (~is_wide & ~is_noball).astype(int)
    bbb["legal_after"] = bbb.groupby(["match_id", "innings"])["is_legal"].cumsum()
    bbb["legal_before"] = bbb["legal_after"] - bbb["is_legal"]
    bbb["balls_left"] = bbb["max_balls"] - bbb["legal_before"]
    bbb["runs_needed"] = bbb["target"] - bbb["team_runs_before"]
    bbb["rrr"] = np.where(bbb["balls_left"] > 0, 6.0 * bbb["runs_needed"] / bbb["balls_left"], np.nan)

    faced = bbb[~is_wide].copy()
    faced["is_india"] = faced["venue_country"].astype(str).str.strip().str.lower().eq("india")
    faced["is_ipl"] = faced["is_ipl"].fillna(False).astype(bool)
    faced["is_pressure"] = (
        (faced["innings"] == 2)
        & (faced["balls_left"] > 0)
        & (faced["balls_left"] <= 30)
        & (faced["wickets_down"] >= 3)
        & (faced["rrr"] >= 15.0)
    )
    p_grp = faced[faced["is_pressure"]].groupby(["striker_id", "striker_name"], as_index=False).agg(
        pressure_balls=("runs", "size"), pressure_runs=("runs", "sum")
    )
    o_grp = faced[~faced["is_pressure"]].groupby(["striker_id", "striker_name"], as_index=False).agg(
        ordinary_balls=("runs", "size"), ordinary_runs=("runs", "sum")
    )
    p_ind = (faced[faced["is_pressure"] & faced["is_india"]]
             .groupby(["striker_id", "striker_name"], as_index=False)
             .agg(india_pressure_balls=("runs", "size"), india_pressure_runs=("runs", "sum")))
    p_ovr = (faced[faced["is_pressure"] & (~faced["is_india"])]
             .groupby(["striker_id", "striker_name"], as_index=False)
             .agg(overseas_pressure_balls=("runs", "size"), overseas_pressure_runs=("runs", "sum")))
    all_ind = (faced[faced["is_india"]]
               .groupby(["striker_id", "striker_name"], as_index=False)
               .agg(india_balls=("runs", "size"), india_runs=("runs", "sum")))
    all_ovr = (faced[~faced["is_india"]]
               .groupby(["striker_id", "striker_name"], as_index=False)
               .agg(overseas_balls=("runs", "size"), overseas_runs=("runs", "sum")))
    p_ipl = (faced[faced["is_pressure"] & faced["is_ipl"]]
             .groupby(["striker_id", "striker_name"], as_index=False)
             .agg(ipl_pressure_balls=("runs", "size"), ipl_pressure_runs=("runs", "sum")))
    o_ipl = (faced[(~faced["is_pressure"]) & faced["is_ipl"]]
             .groupby(["striker_id", "striker_name"], as_index=False)
             .agg(ipl_ordinary_balls=("runs", "size"), ipl_ordinary_runs=("runs", "sum")))
    all_ipl = (faced[faced["is_ipl"]]
               .groupby(["striker_id", "striker_name"], as_index=False)
               .agg(ipl_balls=("runs", "size"), ipl_runs=("runs", "sum")))
    p_t20i = (faced[faced["is_pressure"] & (~faced["is_ipl"])]
              .groupby(["striker_id", "striker_name"], as_index=False)
              .agg(t20i_pressure_balls=("runs", "size"), t20i_pressure_runs=("runs", "sum")))
    o_t20i = (faced[(~faced["is_pressure"]) & (~faced["is_ipl"])]
              .groupby(["striker_id", "striker_name"], as_index=False)
              .agg(t20i_ordinary_balls=("runs", "size"), t20i_ordinary_runs=("runs", "sum")))
    all_t20i = (faced[~faced["is_ipl"]]
                .groupby(["striker_id", "striker_name"], as_index=False)
                .agg(t20i_balls=("runs", "size"), t20i_runs=("runs", "sum")))

    out = p_grp.merge(o_grp, on=["striker_id", "striker_name"], how="inner")
    for sub in [p_ind, p_ovr, all_ind, all_ovr, p_ipl, o_ipl, all_ipl, p_t20i, o_t20i, all_t20i]:
        out = out.merge(sub, on=["striker_id", "striker_name"], how="left")

    int_cols = [
        "india_pressure_balls", "india_pressure_runs", "overseas_pressure_balls", "overseas_pressure_runs",
        "india_balls", "india_runs", "overseas_balls", "overseas_runs",
        "ipl_pressure_balls", "ipl_pressure_runs", "ipl_ordinary_balls", "ipl_ordinary_runs", "ipl_balls", "ipl_runs",
        "t20i_pressure_balls", "t20i_pressure_runs", "t20i_ordinary_balls", "t20i_ordinary_runs", "t20i_balls", "t20i_runs",
    ]
    for c in int_cols:
        out[c] = out[c].fillna(0).astype(int)

    out["pressure_sr"] = 100.0 * out["pressure_runs"] / out["pressure_balls"]
    out["ordinary_sr"] = 100.0 * out["ordinary_runs"] / out["ordinary_balls"]
    for prefix in ["india_pressure", "overseas_pressure", "india", "overseas",
                   "ipl_pressure", "ipl_ordinary", "ipl", "t20i_pressure", "t20i_ordinary", "t20i"]:
        b_col = f"{prefix}_balls"
        r_col = f"{prefix}_runs"
        out[f"{prefix}_sr"] = np.where(
            out[b_col] > 0,
            100.0 * out[r_col] / out[b_col].replace(0, np.nan),
            np.nan,
        )
    out = out.sort_values("pressure_balls", ascending=False)
    try:
        out.to_csv(path, index=False)
    except OSError:
        pass
    return out


def totals(df: pd.DataFrame) -> dict:
    runs = df["runs"].sum()
    balls = df["balls_faced"].sum()
    dismissals = df["dismissed"].sum()
    return {
        "runs": runs,
        "innings": len(df),
        "batters": df["striker_id"].nunique(),
        "matches": df["match_id"].nunique(),
        "average": runs / dismissals if dismissals else np.nan,
        "strike_rate": 100 * runs / balls if balls else np.nan,
        "boundary_pct": 100 * df["boundary_runs"].sum() / runs if runs else np.nan,
        "fifties": int(df["fifty"].sum()),
        "hundreds": int(df["hundred"].sum()),
    }


def player_table(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["striker_id", "striker_name"], as_index=False).agg(
        innings=("runs", "size"),
        runs=("runs", "sum"),
        balls=("balls_faced", "sum"),
        dismissals=("dismissed", "sum"),
        not_outs=("not_out", "sum"),
        boundary_runs=("boundary_runs", "sum"),
        fifties=("fifty", "sum"),
        hundreds=("hundred", "sum"),
    )
    g["average"] = np.where(g.dismissals > 0, g.runs / g.dismissals.replace(0, np.nan), np.nan)
    g["strike_rate"] = np.where(g.balls > 0, 100 * g.runs / g.balls.replace(0, np.nan), np.nan)
    g["boundary_pct"] = np.where(g.runs > 0, 100 * g.boundary_runs / g.runs.replace(0, np.nan), np.nan)
    g["not_out_pct"] = 100 * g.not_outs / g.innings
    g["fifty_rate"] = 100 * (g.fifties + g.hundreds) / g.innings
    return g


# ----------------------------------------------------------------------------
# Load & Department Switch (Bowling vs Batting)
# ----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Dashboard mode")
    dashboard_mode = st.radio(
        "Department",
        options=["Bowling insights", "Batting insights"],
        index=0,
        help="Switch between the consolidated Bowling dashboard and Batting dashboard.",
    )
    st.markdown("---")

if dashboard_mode == "Bowling insights":
    import bowling_dashboard

    importlib.reload(bowling_dashboard)
    bowling_dashboard.render_bowling_dashboard(
        bowling_file=BOWLING_INNINGS_FILE,
        wicket_file=BOWLING_WICKETS_FILE,
        style_fn=style,
        kpi_fn=kpi,
        fmt_fn=fmt,
        html_table_fn=html_table,
    )
    st.stop()

if not INNINGS_FILE.exists():
    st.error(f"Missing data file: {INNINGS_FILE}")
    st.stop()

raw = load_innings(INNINGS_FILE)
dismissals_raw = load_dismissals(DISMISSAL_FILE)

# ----------------------------------------------------------------------------
# Sidebar filters
# ----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Batting filters")
    formats = sorted(raw["match_format"].dropna().astype(str).unique())
    sel_formats = st.multiselect(
        "Match format (T20 = IPL · T20I = Intl)",
        formats,
        default=formats,
    )

    years = sorted(raw["year"].dropna().astype(int).unique())
    y0, y1 = st.select_slider("Years", options=years, value=(years[0], years[-1]))

    teams = sorted(raw["batting_team"].dropna().unique())
    sel_teams = st.multiselect("Batting team (optional)", teams)

    st.markdown("---")
    st.caption("Super overs are excluded. Balls faced exclude wides. T20 = IPL · T20I = T20 Internationals.")

f = raw[raw["match_format"].isin(sel_formats) & raw["year"].between(y0, y1)]
if sel_teams:
    f = f[f["batting_team"].isin(sel_teams)]

if f.empty:
    st.warning("No innings match these filters. Widen the years or formats.")
    st.stop()

# ----------------------------------------------------------------------------
# Header
# ----------------------------------------------------------------------------
t_all = totals(f)
st.markdown(
    "<div class='hero'><h1>Batting insights</h1>"
    f"<p>{t_all['innings']:,} innings · {t_all['matches']:,} matches · "
    f"{t_all['batters']:,} batters · {int(t_all['runs']):,} runs in the selected view</p></div>",
    unsafe_allow_html=True,
)

pt_all = player_table(f)
players_by_runs = pt_all.sort_values("runs", ascending=False)["striker_name"].tolist()
players_eligible = (pt_all[pt_all.innings >= MIN_INNINGS_COMPARE]
                    .sort_values("runs", ascending=False)["striker_name"].tolist())

tab_over, tab_profile, tab_h2h, tab_board, tab_venue, tab_pressure, tab_about = st.tabs(
    ["Overview", "Batter profile", "Player vs player", "Leaderboard", "Venue fit", "Pressure", "About"]
)

# ----------------------------------------------------------------------------
# Overview
# ----------------------------------------------------------------------------
with tab_over:
    st.markdown("#### Headline numbers")
    cols = st.columns(6)
    with cols[0]: kpi("Runs", f"{int(t_all['runs']):,}")
    with cols[1]: kpi("Innings", f"{t_all['innings']:,}")
    with cols[2]: kpi("Batting average", fmt(t_all["average"]))
    with cols[3]: kpi("Strike rate", fmt(t_all["strike_rate"]))
    with cols[4]: kpi("Boundary share", f"{fmt(t_all['boundary_pct'])}%")
    with cols[5]: kpi("50s / 100s", f"{t_all['fifties']:,} / {t_all['hundreds']:,}")

    st.markdown("")
    left, right = st.columns([1.4, 1])
    with left:
        season = f.groupby(["year", "season"], as_index=False).agg(
            runs=("runs", "sum"), balls=("balls_faced", "sum"), innings=("runs", "size"))
        season["strike_rate"] = 100 * season.runs / season.balls.replace(0, np.nan)
        season = season.sort_values("year")
        fig = go.Figure()
        fig.add_bar(
            x=season["season"], y=season["runs"], name="Runs", marker_color=TEAL,
            customdata=season[["innings", "strike_rate"]],
            hovertemplate=(
                "<b>Season %{x}</b><br>"
                "Runs: <b>%{y:,}</b><br>"
                "Strike rate: <b>%{customdata[1]:.1f}</b><br>"
                "Innings: <b>%{customdata[0]:,}</b><extra></extra>"
            ),
        )
        fig.add_scatter(
            x=season["season"], y=season["strike_rate"], name="Strike rate",
            mode="lines+markers", yaxis="y2",
            line=dict(color=AMBER, width=3.5),
            marker=dict(size=8, color=AMBER, line=dict(width=1.5, color="#ffffff")),
            customdata=season[["runs", "innings"]],
            hovertemplate=(
                "<b>Season %{x}</b><br>"
                "Strike rate: <b>%{y:.1f}</b><br>"
                "Runs: <b>%{customdata[0]:,}</b> (%{customdata[1]:,} inns)<extra></extra>"
            ),
        )
        fig.update_layout(xaxis=dict(type="category", title="Year"),
                          yaxis=dict(title="Runs"),
                          yaxis2=dict(title="Strike rate", overlaying="y", side="right", showgrid=False),
                          legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"))
        st.plotly_chart(style(fig, "Runs and strike rate by season"), width="stretch", theme=None)

    with right:
        top = pt_all.sort_values("runs", ascending=False).head(10).sort_values("runs")
        fig = px.bar(top, x="runs", y="striker_name", orientation="h",
                     color="strike_rate", color_continuous_scale=SCALE,
                     text="runs",
                     custom_data=["innings", "average", "strike_rate"],
                     labels={"runs": "Runs", "striker_name": "", "strike_rate": "Strike rate"})
        fig.update_traces(
            texttemplate="%{text:,}", textposition="inside", insidetextanchor="end",
            textfont=dict(color="#ffffff", size=11),
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Runs: <b>%{x:,}</b><br>"
                "Strike rate: <b>%{customdata[2]:.1f}</b><br>"
                "Average: <b>%{customdata[1]:.1f}</b><br>"
                "Innings: <b>%{customdata[0]:,}</b><extra></extra>"
            ),
        )
        fig.update_layout(coloraxis_colorbar_title="SR")
        st.plotly_chart(style(fig, "Top 10 run scorers (colour = strike rate)"), width="stretch", theme=None)

    left, right = st.columns(2)
    with left:
        pos = (f[f["batting_order"].between(1, 11)]
               .groupby("batting_order", as_index=False)
               .agg(runs=("runs", "sum"), balls=("balls_faced", "sum"), innings=("runs", "size")))
        pos["strike_rate"] = 100 * pos.runs / pos.balls.replace(0, np.nan)
        max_sr = float(pos["strike_rate"].max()) if not pos.empty else 160.0
        fig = px.bar(pos, x="batting_order", y="strike_rate",
                     text_auto=".1f",
                     custom_data=["runs", "innings"],
                     labels={"batting_order": "Batting position", "strike_rate": "Strike rate"})
        fig.update_traces(
            marker_color=TEAL, textposition="outside", textfont=dict(color=INK, size=11),
            hovertemplate=(
                "<b>Position #%{x}</b><br>"
                "Strike rate: <b>%{y:.1f}</b><br>"
                "Total runs: <b>%{customdata[0]:,}</b><br>"
                "Innings: <b>%{customdata[1]:,}</b><extra></extra>"
            ),
        )
        fig.update_xaxes(dtick=1)
        fig.update_yaxes(range=[0, max_sr * 1.18])
        st.plotly_chart(style(fig, "Strike rate by batting position", height=350), width="stretch", theme=None)

    with right:
        bp = (f[f["batting_order"].between(1, 11)]
              .groupby("batting_order", as_index=False)
              .agg(runs=("runs", "sum"))
              .sort_values("batting_order"))
        bp["pos_label"] = "Position #" + bp["batting_order"].astype(int).astype(str)
        fig = px.pie(bp, names="pos_label", values="runs", hole=0.52,
                     color_discrete_sequence=CATEGORY)
        fig.update_traces(
            sort=False,
            textposition="inside",
            textinfo="percent",
            insidetextorientation="horizontal",
            textfont=dict(color="#ffffff", size=11),
            marker=dict(line=dict(color="#ffffff", width=1.5)),
            hovertemplate=(
                "<b>%{label}</b><br>"
                "Runs: <b>%{value:,}</b><br>"
                "Share of total: <b>%{percent}</b><extra></extra>"
            ),
        )
        fig.update_layout(legend=dict(orientation="v", y=0.5, yanchor="middle", x=1.02))
        st.plotly_chart(style(fig, "Where the runs come from (batting position)", height=350), width="stretch", theme=None)

    st.markdown("#### Scoring mix by season")
    mix = f.groupby(["year", "season"], as_index=False).agg(
        runs=("runs", "sum"), boundary_runs=("boundary_runs", "sum")).sort_values("year")
    mix["Boundaries"] = mix.boundary_runs
    mix["Singles, twos and threes"] = mix.runs - mix.boundary_runs
    mix = mix.melt(id_vars=["year", "season", "runs"], value_vars=["Boundaries", "Singles, twos and threes"],
                   var_name="type", value_name="value")
    mix["share_pct"] = 100 * mix["value"] / mix["runs"].replace(0, np.nan)
    fig = px.bar(mix, x="season", y="value", color="type", barmode="stack",
                 custom_data=["share_pct", "runs"],
                 color_discrete_map={"Boundaries": TEAL, "Singles, twos and threes": AMBER},
                 labels={"season": "Season", "value": "Runs", "type": ""})
    fig.update_traces(
        hovertemplate=(
            "<b>Season %{x}</b> · %{fullData.name}<br>"
            "Runs: <b>%{y:,}</b> (<b>%{customdata[0]:.1f}%</b> of %{customdata[1]:,})<extra></extra>"
        )
    )
    fig.update_layout(xaxis=dict(type="category"),
                      legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"))
    st.plotly_chart(style(fig, "Runs from boundaries against other runs, by season", height=340),
                    width="stretch", theme=None)

# ----------------------------------------------------------------------------
# Batter profile
# ----------------------------------------------------------------------------
with tab_profile:
    player = st.selectbox("Choose a batter", players_by_runs, index=0, key="profile_player")
    p = f[f["striker_name"] == player].sort_values("date")
    tp = totals(p)

    cols = st.columns(6)
    with cols[0]: kpi("Innings", f"{tp['innings']:,}")
    with cols[1]: kpi("Runs", f"{int(tp['runs']):,}")
    with cols[2]: kpi("Average", fmt(tp["average"]))
    with cols[3]: kpi("Strike rate", fmt(tp["strike_rate"]))
    with cols[4]: kpi("Boundary share", f"{fmt(tp['boundary_pct'])}%")
    with cols[5]: kpi("50s / 100s", f"{tp['fifties']} / {tp['hundreds']}")

    st.markdown("")
    left, right = st.columns(2)
    with left:
        cum = p.assign(cumulative=p.runs.cumsum())
        fig = px.line(cum, x="date", y="cumulative",
                      custom_data=["runs", "balls_faced", "opposition"],
                      labels={"date": "Date", "cumulative": "Career runs"})
        fig.update_traces(
            line_color=TEAL, line_width=3,
            hovertemplate=(
                "<b>%{x|%d %b %Y}</b><br>"
                "Career total: <b>%{y:,} runs</b><br>"
                "Innings: <b>%{customdata[0]:.0f}</b> (%{customdata[1]:.0f} balls) vs %{customdata[2]}<extra></extra>"
            ),
        )
        st.plotly_chart(style(fig, f"{player}: career runs over time", height=340), width="stretch", theme=None)

    with right:
        form = p.assign(rolling_avg=p.runs.rolling(10, min_periods=3).mean())
        fig = go.Figure()
        fig.add_bar(
            x=form.date, y=form.runs, name="Runs in innings", marker_color="#38bdf8",
            customdata=form[["balls_faced", "opposition"]],
            hovertemplate=(
                "<b>%{x|%d %b %Y}</b><br>"
                "Score: <b>%{y:.0f} runs</b> (%{customdata[0]:.0f} balls)<br>"
                "Opposition: <b>%{customdata[1]}</b><extra></extra>"
            ),
        )
        fig.add_scatter(
            x=form.date, y=form.rolling_avg, name="10-innings average", mode="lines",
            line=dict(color=NAVY, width=3),
            hovertemplate=(
                "<b>%{x|%d %b %Y}</b><br>"
                "10-innings avg: <b>%{y:.1f} runs</b><extra></extra>"
            ),
        )
        fig.update_layout(legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"), yaxis_title="Runs")
        st.plotly_chart(style(fig, f"{player}: form (10-innings rolling average)", height=340), width="stretch", theme=None)

    left, right = st.columns(2)
    with left:
        scat = p.assign(
            status=np.where(p.not_out, "Not out", "Out"),
            inn_sr=100 * p.runs / p.balls_faced.replace(0, np.nan),
        )
        fig = px.scatter(scat, x="balls_faced", y="runs", color="status",
                         color_discrete_map={"Not out": AMBER, "Out": TEAL},
                         custom_data=["match_date", "opposition", "inn_sr", "status"],
                         labels={"balls_faced": "Balls faced", "runs": "Runs", "status": ""})
        fig.update_traces(
            marker=dict(size=9, line=dict(width=1, color="#ffffff")),
            hovertemplate=(
                "<b>%{y:.0f} runs</b> off <b>%{x:.0f} balls</b> (%{customdata[3]})<br>"
                "Strike rate: <b>%{customdata[2]:.1f}</b><br>"
                "vs <b>%{customdata[1]}</b> · %{customdata[0]}<extra></extra>"
            ),
        )
        fig.update_layout(legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"))
        st.plotly_chart(style(fig, f"{player}: runs against balls faced", height=350), width="stretch", theme=None)

    with right:
        if dismissals_raw is not None and len(p):
            pid = p["striker_id"].iloc[0]
            if "player_name" in dismissals_raw.columns:
                dd = dismissals_raw[(dismissals_raw["player_id"] == pid) | (dismissals_raw["player_name"] == player)]
            else:
                dd = dismissals_raw[dismissals_raw["player_id"] == pid]
            dd = dd[dd["dismissal_type"].notna() & (dd["dismissal_type"].astype(str).str.strip() != "")]
            dd = dd.groupby("dismissal_type", as_index=False)["dismissal_count"].sum()
            dd = dd[dd.dismissal_count > 0]
            if dd.empty:
                st.info("No dismissals recorded for this batter (not out in all innings).")
            else:
                fig = px.pie(dd, names="dismissal_type", values="dismissal_count", hole=0.52,
                             color_discrete_sequence=CATEGORY)
                fig.update_traces(
                    textposition="inside", textinfo="percent+label",
                    textfont=dict(color="#ffffff", size=11),
                    marker=dict(line=dict(color="#ffffff", width=1.5)),
                    hovertemplate=(
                        "<b>%{label}</b><br>"
                        "Dismissals: <b>%{value:,}</b><br>"
                        "Share: <b>%{percent}</b><extra></extra>"
                    ),
                )
                st.plotly_chart(style(fig, f"{player}: how they were dismissed", height=350), width="stretch", theme=None)
        else:
            st.info("Add cleaned_data/batting_dismissal_types.csv to show how this batter was dismissed.")

    left, right = st.columns(2)
    with left:
        opp = (p.groupby("opposition", as_index=False)
               .agg(runs=("runs", "sum"), innings=("runs", "size"), balls=("balls_faced", "sum")))
        opp["strike_rate"] = 100 * opp.runs / opp.balls.replace(0, np.nan)
        opp = opp.sort_values("runs", ascending=False).head(10).sort_values("runs")
        fig = px.bar(opp, x="runs", y="opposition", orientation="h", color="strike_rate",
                     color_continuous_scale=SCALE,
                     custom_data=["innings", "strike_rate", "balls"],
                     labels={"runs": "Runs", "opposition": "", "strike_rate": "Strike rate"})
        fig.update_traces(
            hovertemplate=(
                "<b>vs %{y}</b><br>"
                "Runs: <b>%{x:,}</b> (%{customdata[2]:,} balls)<br>"
                "Strike rate: <b>%{customdata[1]:.1f}</b><br>"
                "Innings: <b>%{customdata[0]:,}</b><extra></extra>"
            )
        )
        st.plotly_chart(style(fig, f"{player}: runs by opposition (colour = strike rate)", height=350),
                        width="stretch", theme=None)

    with right:
        fig = px.histogram(p, x="runs", nbins=20, labels={"runs": "Runs in an innings"})
        fig.update_traces(
            marker_color=TEAL, marker_line_color="#ffffff", marker_line_width=1,
            hovertemplate=(
                "<b>Score range: %{x} runs</b><br>"
                "Innings count: <b>%{y:,}</b><extra></extra>"
            ),
        )
        st.plotly_chart(style(fig, f"{player}: how the innings scores are spread", height=350), width="stretch", theme=None)

# ----------------------------------------------------------------------------
# Player vs player
# ----------------------------------------------------------------------------
with tab_h2h:
    st.markdown(
        f"<div class='note'>Compare two batters on the same view. Only batters with at least "
        f"{MIN_INNINGS_COMPARE} innings can be chosen, so the comparison isn't driven by one or two innings.</div>",
        unsafe_allow_html=True,
    )
    if len(players_eligible) < 2:
        st.info("Not enough batters with enough innings in this view. Widen the filters.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            a = st.selectbox("Batter A", players_eligible, index=0, key="cmp_a")
        with c2:
            b = st.selectbox("Batter B", players_eligible, index=1, key="cmp_b")

        if a == b:
            st.info("Choose two different batters to compare.")
        else:
            pa = pt_all[pt_all.striker_name == a].iloc[0]
            pb = pt_all[pt_all.striker_name == b].iloc[0]

            ca, cb = st.columns(2)
            for col, name, row, colour in [(ca, a, pa, PLAYER_COLOURS[0]), (cb, b, pb, PLAYER_COLOURS[1])]:
                with col:
                    st.markdown(f"<h4 style='color:{colour} !important;margin-bottom:.4rem'>{escape(name)}</h4>",
                                unsafe_allow_html=True)
                    k = st.columns(4)
                    with k[0]: kpi("Runs", f"{int(row.runs):,}")
                    with k[1]: kpi("Average", fmt(row.average))
                    with k[2]: kpi("Strike rate", fmt(row.strike_rate))
                    with k[3]: kpi("Innings", f"{int(row.innings):,}")

            # Percentile ranks among eligible batters, so every axis is on the same scale
            pool = pt_all[pt_all.innings >= MIN_INNINGS_COMPARE]
            metrics = {"Runs": "runs", "Average": "average", "Strike rate": "strike_rate",
                       "Boundary %": "boundary_pct", "Not-out %": "not_out_pct", "50+ rate": "fifty_rate"}
            axes = list(metrics.keys())

            def pct_rank(metric_col, name):
                val = pt_all.loc[pt_all.striker_name == name, metric_col].iloc[0]
                if pd.isna(val):
                    return 0.0
                series = pool[metric_col].dropna()
                return 100 * (series < val).mean()

            fig = go.Figure()
            for name, colour in [(a, PLAYER_COLOURS[0]), (b, PLAYER_COLOURS[1])]:
                vals = [pct_rank(metrics[m], name) for m in axes]
                raw_vals = [float(pt_all.loc[pt_all.striker_name == name, metrics[m]].iloc[0]) for m in axes]
                fig.add_trace(go.Scatterpolar(
                    r=vals + vals[:1],
                    theta=axes + axes[:1],
                    customdata=raw_vals + raw_vals[:1],
                    name=name,
                    fill="toself",
                    line=dict(color=colour, width=2.5),
                    opacity=0.6,
                    hovertemplate=(
                        f"<b>{escape(name)}</b><br>"
                        "%{theta}: <b>%{customdata:,.1f}</b><br>"
                        "Percentile: <b>%{r:.0f}th</b><extra></extra>"
                    ),
                ))
            fig.update_layout(
                polar=dict(
                    bgcolor="#f8fafc",
                    radialaxis=dict(range=[0, 100], showticklabels=False, gridcolor="#cbd5e1"),
                    angularaxis=dict(tickfont=dict(color=INK, size=12), gridcolor="#cbd5e1"),
                ),
                legend=dict(orientation="h", y=-0.12, x=0.2),
            )

            left, right = st.columns([1, 1.2])
            with left:
                st.plotly_chart(style(fig, "Profile shape (percentile among eligible batters)", height=420),
                                width="stretch", theme=None)
            with right:
                st.markdown("#### Side by side")
                comp = pd.DataFrame({
                    "Metric": ["Innings", "Runs", "Average", "Strike rate", "Boundary %", "Not-out %", "50+ rate"],
                    a: [pa.innings, pa.runs, pa.average, pa.strike_rate, pa.boundary_pct, pa.not_out_pct, pa.fifty_rate],
                    b: [pb.innings, pb.runs, pb.average, pb.strike_rate, pb.boundary_pct, pb.not_out_pct, pb.fifty_rate],
                })
                html_table(comp, formats={a: "{:,.1f}", b: "{:,.1f}"}, num_cols=[a, b])
                st.markdown("<div class='note'>On the radar, a higher value means a better percentile among "
                            "eligible batters. Percentiles ignore a metric where a batter has no value.</div>",
                            unsafe_allow_html=True)

            sa = f[f.striker_name == a].groupby(["year", "season"], as_index=False).runs.sum()
            sb = f[f.striker_name == b].groupby(["year", "season"], as_index=False).runs.sum()
            sa["batter"], sb["batter"] = a, b
            both = pd.concat([sa, sb]).sort_values("year")
            fig = px.line(both, x="season", y="runs", color="batter", markers=True,
                          color_discrete_sequence=PLAYER_COLOURS,
                          labels={"season": "Season", "runs": "Runs", "batter": ""})
            fig.update_traces(
                line_width=3, marker_size=8,
                hovertemplate=(
                    "<b>%{fullData.name}</b><br>"
                    "Season %{x}: <b>%{y:,} runs</b><extra></extra>"
                ),
            )
            fig.update_layout(xaxis=dict(type="category"),
                              legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"))
            st.plotly_chart(style(fig, "Runs by season, head to head", height=350), width="stretch", theme=None)

            va = f[f.striker_name == a].groupby("venue", as_index=False).agg(
                runs=("runs", "sum"), balls=("balls_faced", "sum"))
            vb = f[f.striker_name == b].groupby("venue", as_index=False).agg(
                runs=("runs", "sum"), balls=("balls_faced", "sum"))
            va["sr"] = 100 * va.runs / va.balls.replace(0, np.nan)
            vb["sr"] = 100 * vb.runs / vb.balls.replace(0, np.nan)
            vv = va[["venue", "sr", "balls"]].merge(vb[["venue", "sr", "balls"]], on="venue", suffixes=("_a", "_b"))
            vv = vv[(vv.balls_a >= MIN_VENUE_BALLS) & (vv.balls_b >= MIN_VENUE_BALLS)]
            if not vv.empty:
                long = vv.melt(id_vars="venue", value_vars=["sr_a", "sr_b"], var_name="batter", value_name="sr")
                long["batter"] = long["batter"].map({"sr_a": a, "sr_b": b})
                fig = px.bar(long, x="venue", y="sr", color="batter", barmode="group",
                             color_discrete_sequence=PLAYER_COLOURS,
                             labels={"venue": "", "sr": "Strike rate", "batter": ""})
                fig.update_traces(
                    hovertemplate=(
                        "<b>%{fullData.name}</b> · %{x}<br>"
                        "Strike rate: <b>%{y:.1f}</b><extra></extra>"
                    )
                )
                fig.update_layout(legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"))
                st.plotly_chart(style(fig, "Strike rate at venues where both have at least 30 balls", height=350),
                                width="stretch", theme=None)
            else:
                st.info("No venue where both batters have at least 30 balls in this view.")

# ----------------------------------------------------------------------------
# Leaderboard
# ----------------------------------------------------------------------------
with tab_board:
    min_inn = st.slider("Minimum innings", 1, 50, 10,
                        help="Players with fewer innings are hidden to reduce small-sample noise.")
    board = pt_all[pt_all.innings >= min_inn].sort_values("runs", ascending=False)

    if board.empty:
        st.info("No batters meet this minimum. Lower the threshold.")
    else:
        fig = px.scatter(board, x="average", y="strike_rate", size="runs", color="fifty_rate",
                         color_continuous_scale=SCALE, hover_name="striker_name",
                         custom_data=["innings", "runs", "fifty_rate", "boundary_pct"],
                         labels={"average": "Batting average", "strike_rate": "Strike rate",
                                 "fifty_rate": "50+ rate (%)"})
        fig.update_traces(
            marker=dict(line=dict(width=0.8, color=NAVY), opacity=0.88),
            hovertemplate=(
                "<b>%{hovertext}</b><br>"
                "Runs: <b>%{customdata[1]:,.0f}</b> (%{customdata[0]:,.0f} inns)<br>"
                "Average: <b>%{x:.1f}</b> · Strike rate: <b>%{y:.1f}</b><br>"
                "50+ rate: <b>%{customdata[2]:.1f}%</b> · Boundary: <b>%{customdata[3]:.1f}%</b><extra></extra>"
            ),
        )
        st.plotly_chart(style(fig, "Average against strike rate (bubble = runs, colour = 50+ rate)", height=460),
                        width="stretch", theme=None)

        st.markdown(f"<div class='note'>{len(board):,} batters with at least {min_inn} innings. Sorted by runs.</div>",
                    unsafe_allow_html=True)
        table = board[["striker_name", "innings", "runs", "average", "strike_rate", "boundary_pct",
                       "fifties", "hundreds"]].rename(
            columns={"striker_name": "Batter", "innings": "Inns", "runs": "Runs", "average": "Average",
                     "strike_rate": "Strike rate", "boundary_pct": "Boundary %", "fifties": "50s", "hundreds": "100s"})
        html_table(table,
                   formats={"Average": "{:.1f}", "Strike rate": "{:.1f}", "Boundary %": "{:.1f}", "Runs": "{:,.0f}"},
                   bar_cols={"Runs": float(board.runs.max())},
                   num_cols=["Inns", "Runs", "Average", "Strike rate", "Boundary %", "50s", "100s"])

# ----------------------------------------------------------------------------
# Venue fit
# ----------------------------------------------------------------------------
with tab_venue:
    st.markdown(
        "<div class='note'>Strike rate at each venue is compared with the average strike rate of all batters "
        "at that venue in the same view. This separates a batter's own record from the ground's effect. "
        f"The chart shows venues with at least {MIN_VENUE_BALLS} balls faced.</div>",
        unsafe_allow_html=True,
    )
    player_v = st.selectbox("Choose a batter", players_by_runs, index=0, key="venue_player")

    # Indian vs Overseas venue breakdown & rating for the selected batter
    pf_v = f[f["striker_name"] == player_v]
    region_pool = (
        f.groupby(["striker_name", "pitch_region"], as_index=False)
        .agg(runs=("runs", "sum"), balls=("balls_faced", "sum"), dismissals=("dismissed", "sum"), innings=("runs", "size"))
    )
    region_pool = region_pool[region_pool["balls"] >= MIN_VENUE_BALLS].copy()
    region_pool["sr"] = 100.0 * region_pool["runs"] / region_pool["balls"].replace(0, np.nan)
    region_pool["avg"] = np.where(region_pool["dismissals"] > 0, region_pool["runs"] / region_pool["dismissals"].replace(0, np.nan), np.nan)

    def region_rating(region_name, sr_val, avg_val):
        sub = region_pool[region_pool["pitch_region"] == region_name]
        if sub.empty or pd.isna(sr_val):
            return np.nan
        sr_pct = 100.0 * (sub["sr"].dropna() < sr_val).mean()
        if pd.isna(avg_val) or sub["avg"].dropna().empty:
            return sr_pct
        avg_pct = 100.0 * (sub["avg"].dropna() < avg_val).mean()
        return 0.65 * sr_pct + 0.35 * avg_pct

    reg_rows = []
    reg_sr_map = {}
    for reg_label in ["Indian venue", "Overseas venue"]:
        sub_p = pf_v[pf_v["pitch_region"] == reg_label]
        r_runs = float(sub_p["runs"].sum())
        r_balls = float(sub_p["balls_faced"].sum())
        r_inns = int(len(sub_p))
        r_dism = float(sub_p["dismissed"].sum())
        r_bndry = float(sub_p["boundary_runs"].sum())
        r_sr = 100.0 * r_runs / r_balls if r_balls > 0 else np.nan
        r_avg = r_runs / r_dism if r_dism > 0 else np.nan
        r_bpct = 100.0 * r_bndry / r_runs if r_runs > 0 else np.nan
        r_rate = region_rating(reg_label, r_sr, r_avg) if r_balls > 0 else np.nan
        reg_sr_map[reg_label] = r_sr
        reg_rows.append({
            "Pitch / Venue Type": (
                "<span class='pill ok'>Indian venues</span>"
                if reg_label == "Indian venue"
                else "<span class='pill overseas'>Overseas venues</span>"
            ),
            "Inns": r_inns,
            "Runs": r_runs,
            "Balls": int(r_balls),
            "Average": r_avg,
            "Strike rate": r_sr,
            "Boundary %": r_bpct,
            "Pitch Rating (0–100)": r_rate,
        })

    ind_v_sr = reg_sr_map.get("Indian venue", np.nan)
    ovr_v_sr = reg_sr_map.get("Overseas venue", np.nan)
    if pd.notna(ind_v_sr) and pd.notna(ovr_v_sr):
        better_venue_badge = (
            "<span class='pill ok'>Indian pitches (+{:.1f} SR)</span>".format(ind_v_sr - ovr_v_sr)
            if ind_v_sr >= ovr_v_sr
            else "<span class='pill overseas'>Overseas pitches (+{:.1f} SR)</span>".format(ovr_v_sr - ind_v_sr)
        )
    elif pd.notna(ind_v_sr):
        better_venue_badge = "<span class='pill ok'>Indian pitches only</span>"
    elif pd.notna(ovr_v_sr):
        better_venue_badge = "<span class='pill overseas'>Overseas pitches only</span>"
    else:
        better_venue_badge = "–"

    st.markdown(
        f"#### Indian venues vs Overseas venues — {escape(player_v)} "
        f"&nbsp; <span style='font-size:0.9rem;font-weight:500'>Performed better on: {better_venue_badge}</span>",
        unsafe_allow_html=True,
    )
    reg_df = pd.DataFrame(reg_rows)
    html_table(
        reg_df,
        formats={
            "Runs": "{:,.0f}",
            "Average": "{:.1f}",
            "Strike rate": "{:.1f}",
            "Boundary %": "{:.1f}",
            "Pitch Rating (0–100)": "{:.1f}",
        },
        bar_cols={"Pitch Rating (0–100)": 100.0},
        num_cols=["Inns", "Runs", "Balls", "Average", "Strike rate", "Boundary %", "Pitch Rating (0–100)"],
    )

    venue_avg = f.groupby(["venue", "venue_country", "pitch_region"], as_index=False).agg(
        venue_runs=("runs", "sum"), venue_balls=("balls_faced", "sum")
    )
    venue_avg["venue_sr"] = 100 * venue_avg.venue_runs / venue_avg.venue_balls.replace(0, np.nan)

    pv = (pf_v.groupby("venue", as_index=False)
          .agg(runs=("runs", "sum"), balls=("balls_faced", "sum"), innings=("runs", "size")))
    pv["sr"] = 100 * pv.runs / pv.balls.replace(0, np.nan)
    pv = pv.merge(venue_avg[["venue", "venue_country", "pitch_region", "venue_sr"]], on="venue", how="left")
    pv["vs_venue"] = pv.sr - pv.venue_sr

    reliable = pv[pv.balls >= MIN_VENUE_BALLS].sort_values("vs_venue")
    if reliable.empty:
        st.info(f"{player_v} has no venue with at least {MIN_VENUE_BALLS} balls in this view.")
    else:
        fig = px.bar(reliable, x="vs_venue", y="venue", orientation="h",
                     color=np.where(reliable.vs_venue >= 0, "Above venue average", "Below venue average"),
                     color_discrete_map={"Above venue average": TEAL, "Below venue average": AMBER},
                     custom_data=["balls", "innings", "sr", "venue_sr", "runs", "venue_country", "pitch_region"],
                     labels={"vs_venue": "Strike rate vs venue average (points)", "venue": "", "color": ""})
        fig.update_traces(
            hovertemplate=(
                "<b>%{y}</b> (%{customdata[5]} · %{customdata[6]})<br>"
                "Difference: <b>%{x:+.1f} pts</b><br>"
                "Batter SR: <b>%{customdata[2]:.1f}</b> · Venue avg SR: <b>%{customdata[3]:.1f}</b><br>"
                "Record: <b>%{customdata[4]:,.0f} runs</b> off %{customdata[0]:,.0f} balls (%{customdata[1]:,.0f} inns)<extra></extra>"
            )
        )
        fig.add_vline(x=0, line_color=NAVY, line_width=1.5)
        fig.update_layout(legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"))
        st.plotly_chart(style(fig, f"{player_v}: strike rate against the venue average",
                              height=max(320, 40 * len(reliable) + 120)), width="stretch", theme=None)

    st.markdown("#### All venues for this batter")
    vt = pv.sort_values("balls", ascending=False).copy()
    vt["Pitch"] = np.where(
        vt["pitch_region"].eq("Indian venue"),
        "<span class='pill ok'>India</span>",
        "<span class='pill overseas'>" + vt["venue_country"].astype(str) + " (Overseas)</span>",
    )
    vt = vt[["venue", "Pitch", "innings", "runs", "balls", "sr", "venue_sr", "vs_venue"]].rename(
        columns={"venue": "Venue", "innings": "Inns", "runs": "Runs", "balls": "Balls",
                 "sr": "Strike rate", "venue_sr": "Venue average SR", "vs_venue": "Difference"}
    )
    html_table(vt, formats={"Strike rate": "{:.1f}", "Venue average SR": "{:.1f}", "Difference": "{:+.1f}"},
               num_cols=["Inns", "Runs", "Balls", "Strike rate", "Venue average SR", "Difference"])
    st.caption("Venue names are not in the data pack. Map venue IDs to stadium names before reporting.")

# ----------------------------------------------------------------------------
# Pressure
# ----------------------------------------------------------------------------
with tab_pressure:
    st.markdown(
        "<div class='note'><b>Pressure Situation Storytelling & IPL Finisher Scouting:</b> "
        "Deliveries where <b>Innings = 2</b> · <b>Legal Balls Remaining ≤ 30</b> · <b>Wickets Down ≥ 3</b> · "
        "<b>Required Run Rate ≥ 15.0</b> (targets reconstructed with bye & leg-bye extra-run adjustment). "
        "From <code>player_batting_innings.csv</code> (<code>match_format</code>), <b>T20</b> refers to <b>IPL</b> "
        "and <b>T20I</b> refers to <b>T20 Internationals</b>.</div>",
        unsafe_allow_html=True,
    )
    pressure = load_pressure(PRESSURE_FILE)
    if pressure is None:
        st.info(
            "The pressure view needs `cleaned_data/pressure_batter_summary_rrr15.csv` (or `Raw_Data/ball_by_ball.csv` + `matches.csv`). "
            "Columns required: striker_name, pressure_balls, pressure_sr, ordinary_sr. "
            "Pressure is defined as: Innings = 2, Legal Balls Remaining <= 30, Wickets Down >= 3, and Required Run Rate >= 15."
        )
    else:
        ctrl1, ctrl2 = st.columns([1.2, 1])
        with ctrl1:
            min_b = st.slider(
                "Minimum total pressure balls",
                min_value=10,
                max_value=100,
                value=25,
                step=5,
                help="Default 25 balls faced under all 4 simultaneous pressure conditions.",
            )
        with ctrl2:
            min_ind_b = st.slider(
                "Minimum IPL (T20) / India pressure balls (for Top-10 picks)",
                min_value=10,
                max_value=60,
                value=25,
                step=5,
                help="Default 25 pressure balls in IPL (T20) / Indian conditions.",
            )

        use_ipl_lens = True

        pr = pressure[pressure.pressure_balls >= min_b].copy()
        for col_name in [
            "ipl_pressure_balls", "ipl_pressure_runs", "ipl_pressure_sr",
            "ipl_ordinary_balls", "ipl_ordinary_runs", "ipl_ordinary_sr",
            "ipl_balls", "ipl_runs", "ipl_sr",
            "t20i_pressure_balls", "t20i_pressure_runs", "t20i_pressure_sr",
            "t20i_ordinary_balls", "t20i_ordinary_runs", "t20i_ordinary_sr",
            "t20i_balls", "t20i_runs", "t20i_sr",
        ]:
            if col_name not in pr.columns:
                pr[col_name] = 0 if col_name.endswith(("balls", "runs")) else np.nan

        pr["gap"] = pr.pressure_sr - pr.ordinary_sr
        pr["india_gap"] = pr["india_pressure_sr"] - pr["india_sr"]
        pr["overseas_gap"] = pr["overseas_pressure_sr"] - pr["overseas_sr"]
        pr["ipl_gap"] = pr["ipl_pressure_sr"] - pr["ipl_ordinary_sr"]
        pr["t20i_gap"] = pr["t20i_pressure_sr"] - pr["t20i_ordinary_sr"]
        pr["india_vs_overseas_sr"] = pr["india_pressure_sr"] - pr["overseas_pressure_sr"]
        pr["ipl_vs_t20i_sr"] = pr["ipl_pressure_sr"] - pr["t20i_pressure_sr"]
        pr["india_ball_share"] = 100.0 * pr["india_pressure_balls"] / pr["pressure_balls"].replace(0, np.nan)
        pr["ipl_ball_share"] = 100.0 * pr["ipl_pressure_balls"] / pr["pressure_balls"].replace(0, np.nan)

        # Compute Overall Average, Last 10 Matches Overall Average, Last 10 IPL (T20) Average, and Last 10 India Average
        f_chron = f.sort_values(["date", "match_id", "innings"])
        overall_avg_map = {}
        last10_avg_map = {}
        last10_ind_avg_map = {}
        last10_ipl_avg_map = {}

        for s_name, grp in f_chron.groupby("striker_name", sort=False):
            tot_r = float(grp["runs"].sum())
            tot_d = float(grp["dismissed"].sum())
            overall_avg_map[s_name] = tot_r / tot_d if tot_d > 0 else (tot_r if len(grp) > 0 else np.nan)

            l10 = grp.tail(10)
            l10_r = float(l10["runs"].sum())
            l10_d = float(l10["dismissed"].sum())
            last10_avg_map[s_name] = l10_r / l10_d if l10_d > 0 else (l10_r / len(l10) if len(l10) > 0 else np.nan)

            ind_grp = grp[grp["pitch_region"] == "Indian venue"].tail(10)
            if len(ind_grp) > 0:
                i10_r = float(ind_grp["runs"].sum())
                i10_d = float(ind_grp["dismissed"].sum())
                last10_ind_avg_map[s_name] = i10_r / i10_d if i10_d > 0 else (i10_r / len(ind_grp))
            else:
                last10_ind_avg_map[s_name] = np.nan

            ipl_grp = grp[grp["match_format"] == "T20"].tail(10)
            if len(ipl_grp) > 0:
                p10_r = float(ipl_grp["runs"].sum())
                p10_d = float(ipl_grp["dismissed"].sum())
                last10_ipl_avg_map[s_name] = p10_r / p10_d if p10_d > 0 else (p10_r / len(ipl_grp))
            else:
                last10_ipl_avg_map[s_name] = np.nan

        pr["overall_avg"] = pr["striker_name"].map(overall_avg_map)
        pr["last10_avg"] = pr["striker_name"].map(last10_avg_map)
        pr["last10_india_avg"] = pr["striker_name"].map(last10_ind_avg_map)
        pr["last10_ipl_avg"] = pr["striker_name"].map(last10_ipl_avg_map)

        # Compute percentiles and Fit Scores (0-100) for both IPL and India lenses
        ind_valid = pr.loc[pr["india_pressure_balls"] >= 6, "india_pressure_sr"].dropna()
        ovr_valid = pr.loc[pr["overseas_pressure_balls"] >= 6, "overseas_pressure_sr"].dropna()
        ind_gap_valid = pr.loc[pr["india_pressure_balls"] >= 6, "india_gap"].dropna()
        ind_vol_valid = pr.loc[pr["india_pressure_balls"] >= 6, "india_pressure_balls"].dropna()

        ipl_valid = pr.loc[pr["ipl_pressure_balls"] >= 6, "ipl_pressure_sr"].dropna()
        t20i_valid = pr.loc[pr["t20i_pressure_balls"] >= 6, "t20i_pressure_sr"].dropna()
        ipl_gap_valid = pr.loc[pr["ipl_pressure_balls"] >= 6, "ipl_gap"].dropna()
        ipl_vol_valid = pr.loc[pr["ipl_pressure_balls"] >= 6, "ipl_pressure_balls"].dropna()

        def pct_score(series, val):
            if pd.isna(val) or series.empty:
                return np.nan
            return 100.0 * (series < val).mean()

        pr["india_rating"] = [
            pct_score(ind_valid, s) if b >= 6 else np.nan
            for s, b in zip(pr["india_pressure_sr"], pr["india_pressure_balls"])
        ]
        pr["overseas_rating"] = [
            pct_score(ovr_valid, s) if b >= 6 else np.nan
            for s, b in zip(pr["overseas_pressure_sr"], pr["overseas_pressure_balls"])
        ]
        pr["ipl_rating"] = [
            pct_score(ipl_valid, s) if b >= 6 else np.nan
            for s, b in zip(pr["ipl_pressure_sr"], pr["ipl_pressure_balls"])
        ]
        pr["t20i_rating"] = [
            pct_score(t20i_valid, s) if b >= 6 else np.nan
            for s, b in zip(pr["t20i_pressure_sr"], pr["t20i_pressure_balls"])
        ]

        india_fit_scores = []
        ipl_fit_scores = []
        for _, r in pr.iterrows():
            ib = r.get("india_pressure_balls", 0)
            isr = r.get("india_pressure_sr", np.nan)
            igap = r.get("india_gap", np.nan)
            if ib >= 6 and pd.notna(isr):
                p_sr = pct_score(ind_valid, isr)
                p_gap = pct_score(ind_gap_valid, igap) if pd.notna(igap) else p_sr
                p_vol = pct_score(ind_vol_valid, ib)
                india_fit_scores.append(0.60 * p_sr + 0.25 * p_gap + 0.15 * p_vol)
            else:
                india_fit_scores.append(np.nan)

            pb = r.get("ipl_pressure_balls", 0)
            psr = r.get("ipl_pressure_sr", np.nan)
            pgap = r.get("ipl_gap", np.nan)
            if pb >= 6 and pd.notna(psr):
                p_sr_i = pct_score(ipl_valid, psr)
                p_gap_i = pct_score(ipl_gap_valid, pgap) if pd.notna(pgap) else p_sr_i
                p_vol_i = pct_score(ipl_vol_valid, pb)
                ipl_fit_scores.append(0.60 * p_sr_i + 0.25 * p_gap_i + 0.15 * p_vol_i)
            else:
                ipl_fit_scores.append(np.nan)

        pr["india_fit_score"] = india_fit_scores
        pr["ipl_fit_score"] = ipl_fit_scores

        def pick_best_pitch(row):
            ib = row.get("india_pressure_balls", 0)
            ob = row.get("overseas_pressure_balls", 0)
            isr = row.get("india_pressure_sr", np.nan)
            osr = row.get("overseas_pressure_sr", np.nan)
            if ib > 0 and ob > 0 and pd.notna(isr) and pd.notna(osr):
                if isr >= osr:
                    return f"<span class='pill ok'>Indian pitches (+{isr - osr:.1f} SR)</span>"
                return f"<span class='pill overseas'>Overseas pitches (+{osr - isr:.1f} SR)</span>"
            if ib > 0 and pd.notna(isr):
                return "<span class='pill ok'>Indian pitches (only)</span>"
            if ob > 0 and pd.notna(osr):
                return "<span class='pill overseas'>Overseas pitches (only)</span>"
            return "–"

        def pick_best_cluster(row):
            pb = row.get("ipl_pressure_balls", 0)
            tb = row.get("t20i_pressure_balls", 0)
            psr = row.get("ipl_pressure_sr", np.nan)
            tsr = row.get("t20i_pressure_sr", np.nan)
            if pb > 0 and tb > 0 and pd.notna(psr) and pd.notna(tsr):
                if psr >= tsr:
                    return f"<span class='pill ok'>IPL (+{psr - tsr:.1f} SR)</span>"
                return f"<span class='pill overseas'>T20I (+{tsr - psr:.1f} SR)</span>"
            if pb > 0 and pd.notna(psr):
                return "<span class='pill ok'>IPL (only)</span>"
            if tb > 0 and pd.notna(tsr):
                return "<span class='pill overseas'>T20I (only)</span>"
            return "–"

        def classify_archetype(row):
            if use_ipl_lens:
                pb = row.get("ipl_pressure_balls", 0)
                tb = row.get("t20i_pressure_balls", 0)
                psr = row.get("ipl_pressure_sr", np.nan)
                tsr = row.get("t20i_pressure_sr", np.nan)
                osr_all = row.get("pressure_sr", np.nan)
                pgap = row.get("ipl_gap", np.nan)
                if pb >= min_ind_b and pd.notna(psr) and psr >= 185 and (pd.isna(pgap) or pgap > 0):
                    if tb >= 12 and pd.notna(tsr) and tsr >= 185:
                        return "Dual Finisher (IPL + T20I)"
                    return "IPL Pressure Specialist"
                if (tb >= 12 and pd.notna(tsr) and tsr >= 170) or (pb < min_ind_b and pd.notna(osr_all) and osr_all >= 170):
                    return "T20I / Overseas Performer"
                if pb >= min_ind_b:
                    return "IPL Tested (Moderate SR)"
                return "Lower-Order / Other"
            else:
                ib = row.get("india_pressure_balls", 0)
                ob = row.get("overseas_pressure_balls", 0)
                isr = row.get("india_pressure_sr", np.nan)
                osr = row.get("overseas_pressure_sr", np.nan)
                psr = row.get("pressure_sr", np.nan)
                igap = row.get("india_gap", np.nan)
                if ib >= min_ind_b and pd.notna(isr) and isr >= 185 and (pd.isna(igap) or igap > 0):
                    if ob >= 15 and pd.notna(osr) and osr >= 185:
                        return "Dual Finisher (India + Overseas)"
                    return "India Pressure Specialist"
                if (ob >= 15 and pd.notna(osr) and osr >= 170) or (ib < min_ind_b and pd.notna(psr) and psr >= 170):
                    return "Overseas / Non-India Performer"
                if ib >= min_ind_b:
                    return "India Tested (Moderate SR)"
                return "Lower-Order / Other"

        pr["best_pitch"] = [pick_best_pitch(r) for _, r in pr.iterrows()]
        pr["best_cluster"] = [pick_best_cluster(r) for _, r in pr.iterrows()]
        pr["archetype"] = [classify_archetype(r) for _, r in pr.iterrows()]

        # Select active lens columns for Top 10 & contrast group
        if use_ipl_lens:
            primary_balls_col = "ipl_pressure_balls"
            primary_runs_col = "ipl_pressure_runs"
            primary_sr_col = "ipl_pressure_sr"
            primary_ord_sr_col = "ipl_ordinary_sr"
            primary_ord_balls_col = "ipl_ordinary_balls"
            primary_ord_runs_col = "ipl_ordinary_runs"
            primary_gap_col = "ipl_gap"
            primary_fit_col = "ipl_fit_score"
            primary_l10_col = "last10_ipl_avg"
            secondary_balls_col = "t20i_pressure_balls"
            secondary_runs_col = "t20i_pressure_runs"
            secondary_sr_col = "t20i_pressure_sr"
            share_col = "ipl_ball_share"
            diff_col = "ipl_vs_t20i_sr"
            lens_short = "IPL"
            alt_short = "T20I"
        else:
            primary_balls_col = "india_pressure_balls"
            primary_runs_col = "india_pressure_runs"
            primary_sr_col = "india_pressure_sr"
            primary_ord_sr_col = "india_sr"
            primary_ord_balls_col = "india_balls"
            primary_ord_runs_col = "india_runs"
            primary_gap_col = "india_gap"
            primary_fit_col = "india_fit_score"
            primary_l10_col = "last10_india_avg"
            secondary_balls_col = "overseas_pressure_balls"
            secondary_runs_col = "overseas_pressure_runs"
            secondary_sr_col = "overseas_pressure_sr"
            share_col = "india_ball_share"
            diff_col = "india_vs_overseas_sr"
            lens_short = "India"
            alt_short = "Overseas"

        # Top 10 Players Best Suited to Bat in IPL / India Under Pressure:
        # Must meet minimum IPL/India pressure balls AND perform better under pressure than ordinary situations (gap > 0)
        india_candidates = pr[
            (pr[primary_balls_col] >= min_ind_b) & (pr[primary_gap_col].fillna(0) > 0)
        ].copy()
        top10_india = india_candidates.sort_values(
            [primary_sr_col, primary_fit_col, primary_balls_col], ascending=[False, False, False]
        ).head(10).copy()
        top10_india["rank"] = range(1, len(top10_india) + 1)
        top10_names = set(top10_india["striker_name"].tolist())

        # Performers who excelled under pressure in T20Is / Overseas, but are NOT in the Top 10 IPL/India list
        overseas_stars = pr[
            (~pr["striker_name"].isin(top10_names))
            & ((pr[secondary_sr_col] >= 175) | (pr["pressure_sr"] >= 180))
            & ((pr[secondary_balls_col] >= 12) | (pr[primary_balls_col] < min_ind_b))
        ].sort_values("pressure_sr", ascending=False).copy()

        # --------------------------------------------------------------------
        # 1. Headline Storytelling KPIs
        # --------------------------------------------------------------------
        st.markdown(f"#### 1 · Pressure landscape at a glance ({lens_short} vs {alt_short} cluster)")
        kcols = st.columns(6)
        prim_p_balls = int(pr[primary_balls_col].sum())
        sec_p_balls = int(pr[secondary_balls_col].sum())
        w_prim_sr = 100.0 * pr[primary_runs_col].sum() / prim_p_balls if prim_p_balls > 0 else np.nan
        w_sec_sr = 100.0 * pr[secondary_runs_col].sum() / sec_p_balls if sec_p_balls > 0 else np.nan
        best_ind_name = top10_india.iloc[0]["striker_name"] if not top10_india.empty else "–"
        best_ind_sr = top10_india.iloc[0][primary_sr_col] if not top10_india.empty else np.nan

        with kcols[0]:
            kpi("Qualified batters", f"{len(pr):,}")
        with kcols[1]:
            kpi(f"Pressure balls ({lens_short} / {alt_short})", f"{prim_p_balls:,} / {sec_p_balls:,}")
        with kcols[2]:
            kpi(f"{lens_short} pressure SR", fmt(w_prim_sr))
        with kcols[3]:
            kpi(f"{alt_short} pressure SR", fmt(w_sec_sr))
        with kcols[4]:
            kpi(f"#1 {lens_short} pick", f"{best_ind_name} ({fmt(best_ind_sr)})")
        with kcols[5]:
            kpi(f"{alt_short}-first finishers", f"{len(overseas_stars):,}")

        st.markdown("")

        # --------------------------------------------------------------------
        # 2. Top 10 Best-Fit Batters for IPL / India Under Pressure
        # --------------------------------------------------------------------
        st.markdown(
            f"#### 2 · Top 10 IPL scouting picks under crunch pressure ({lens_short} lens) "
            f"<span style='font-size:0.88rem;font-weight:500;color:#475569'>(≥ {min_b} total pressure balls, ≥ {min_ind_b} balls in {lens_short}, & Pressure SR &gt; Ordinary SR)</span>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div class='note'><b>IPL Franchise Scouting Story:</b> Suppose you are an IPL scouting desk picking batters "
            f"for crunch chases (Innings = 2, ≤ 30 balls left, ≥ 3 wickets down, RRR ≥ 15). Each player in this Top 10 has "
            f"faced at least <b>{min_ind_b} pressure deliveries in {lens_short}</b> and <b>accelerated significantly above their "
            f"normal strike rate</b> (+71 to +130 SR points lift). Players who had low strike rates in other countries or T20Is "
            f"(e.g. <b>Sherfane Rutherford</b> 250.0 IPL SR vs 144.4 T20I SR; <b>Dinesh Karthik</b> 252.8 IPL SR vs 140.0 T20I SR; "
            f"<b>Washington Sundar</b> 214.3 India SR / 211.1 IPL SR despite 40.0 Overseas SR) are evaluated strictly on how "
            f"they perform for an IPL franchise in Indian conditions.</div>",
            unsafe_allow_html=True,
        )

        if top10_india.empty:
            st.info(f"No batters meet the current minimum {lens_short} pressure balls filter. Lower the slider above.")
        else:
            c_ind_left, c_ind_right = st.columns([1.15, 1])
            with c_ind_left:
                t10_plot = top10_india.sort_values(primary_sr_col, ascending=True).copy()
                fig_t10 = go.Figure()
                fig_t10.add_bar(
                    x=t10_plot[primary_sr_col],
                    y=t10_plot["striker_name"],
                    orientation="h",
                    name=f"{lens_short} Pressure SR (RRR ≥ 15)",
                    marker_color=TEAL,
                    text=[f"{v:.1f} ({int(b)}b)" for v, b in zip(t10_plot[primary_sr_col], t10_plot[primary_balls_col])],
                    textposition="inside",
                    insidetextanchor="end",
                    textfont=dict(color="#ffffff", size=11),
                    customdata=t10_plot[[primary_balls_col, primary_runs_col, primary_ord_sr_col, primary_gap_col, primary_fit_col]],
                    hovertemplate=(
                        "<b>%{y}</b><br>"
                        f"{lens_short} Pressure SR: <b>%{{x:.1f}}</b> (%{{customdata[1]:,.0f}} runs off %{{customdata[0]:,.0f}}b)<br>"
                        f"Ordinary {lens_short} SR: <b>%{{customdata[2]:.1f}}</b> · Clutch Lift: <b>%{{customdata[3]:+.1f}} pts</b><br>"
                        f"{lens_short} Fit Score: <b>%{{customdata[4]:.1f}} / 100</b><extra></extra>"
                    ),
                )
                fig_t10.add_scatter(
                    x=t10_plot[primary_ord_sr_col],
                    y=t10_plot["striker_name"],
                    mode="markers",
                    name=f"Ordinary {lens_short} SR (non-pressure)",
                    marker=dict(size=11, color=AMBER, symbol="diamond", line=dict(width=1.5, color="#ffffff")),
                    customdata=t10_plot[[primary_ord_balls_col, primary_ord_runs_col, primary_gap_col]],
                    hovertemplate=(
                        "<b>%{y}</b><br>"
                        f"Ordinary {lens_short} SR: <b>%{{x:.1f}}</b> (%{{customdata[1]:,.0f}} runs off %{{customdata[0]:,.0f}}b)<br>"
                        f"Pressure boost in {lens_short}: <b>%{{customdata[2]:+.1f}} pts</b><extra></extra>"
                    ),
                )
                fig_t10.update_layout(
                    xaxis_title=f"Strike rate in {lens_short}",
                    yaxis_title="",
                    legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"),
                )
                st.plotly_chart(
                    style(fig_t10, f"Top 10 for {lens_short}: Pressure SR (bars) vs Ordinary {lens_short} SR (diamonds)", height=440),
                    width="stretch",
                    theme=None,
                )

            with c_ind_right:
                fig_bub = px.scatter(
                    top10_india,
                    x=primary_balls_col,
                    y=primary_sr_col,
                    size=primary_runs_col,
                    color=primary_l10_col,
                    text="striker_name",
                    color_continuous_scale=SCALE,
                    size_max=34,
                    custom_data=[primary_runs_col, primary_fit_col, "overall_avg", "last10_avg", primary_l10_col],
                    labels={
                        primary_balls_col: f"Pressure balls faced in {lens_short}",
                        primary_sr_col: f"{lens_short} pressure strike rate",
                        primary_l10_col: f"Last 10 {lens_short} Avg",
                    },
                )
                fig_bub.update_traces(
                    textposition="top center",
                    textfont=dict(color=INK, size=11),
                    marker=dict(line=dict(width=1.5, color=NAVY), opacity=0.9),
                    hovertemplate=(
                        "<b>%{text}</b><br>"
                        f"{lens_short} Pressure SR: <b>%{{y:.1f}}</b> (%{{customdata[0]:,.0f}} runs off %{{x:,.0f}} balls)<br>"
                        f"{lens_short} Fit Score: <b>%{{customdata[1]:.1f}} / 100</b><br>"
                        f"Overall Avg: <b>%{{customdata[2]:.1f}}</b> · Last 10 Avg: <b>%{{customdata[3]:.1f}}</b> · "
                        f"Last 10 {lens_short} Avg: <b>%{{customdata[4]:.1f}}</b><extra></extra>"
                    ),
                )
                y_min = float(top10_india[primary_sr_col].min()) - 15
                y_max = float(top10_india[primary_sr_col].max()) + 22
                fig_bub.update_yaxes(range=[y_min, y_max])
                fig_bub.update_layout(coloraxis_colorbar_title=f"L10 {lens_short} Avg")
                st.plotly_chart(
                    style(fig_bub, f"Top 10 {lens_short} finishers: volume vs strike rate (colour = Last 10 {lens_short} Avg)", height=440),
                    width="stretch",
                    theme=None,
                )

            # Top 10 curated table showing BOTH IPL/T20I and India/Overseas records side by side
            t10_tbl = top10_india.copy()
            t10_tbl["Rank"] = [f"<span class='pill ok'>#{r} {lens_short} Pick</span>" for r in t10_tbl["rank"]]
            t10_tbl["IPL Pressure Record"] = [
                f"{sr:.1f} ({int(r)}r, {int(b)}b)" if b > 0 and pd.notna(sr) else "0b"
                for sr, r, b in zip(t10_tbl["ipl_pressure_sr"], t10_tbl["ipl_pressure_runs"], t10_tbl["ipl_pressure_balls"])
            ]
            t10_tbl["T20I Pressure Record"] = [
                f"{sr:.1f} ({int(r)}r, {int(b)}b)" if b > 0 and pd.notna(sr) else "Not tested (0b)"
                for sr, r, b in zip(t10_tbl["t20i_pressure_sr"], t10_tbl["t20i_pressure_runs"], t10_tbl["t20i_pressure_balls"])
            ]
            t10_tbl["India Pitch Pressure"] = [
                f"{sr:.1f} ({int(b)}b)" if b > 0 and pd.notna(sr) else "0b"
                for sr, b in zip(t10_tbl["india_pressure_sr"], t10_tbl["india_pressure_balls"])
            ]
            t10_tbl["Overseas Pitch Pressure"] = [
                f"{sr:.1f} ({int(b)}b)" if b > 0 and pd.notna(sr) else "Not tested (0b)"
                for sr, b in zip(t10_tbl["overseas_pressure_sr"], t10_tbl["overseas_pressure_balls"])
            ]
            t10_display = t10_tbl[[
                "Rank", "striker_name", primary_fit_col, primary_sr_col, primary_ord_sr_col, primary_gap_col,
                "IPL Pressure Record", "T20I Pressure Record",
                "India Pitch Pressure", "Overseas Pitch Pressure",
                "overall_avg", "last10_avg", "last10_india_avg",
            ]].rename(columns={
                "striker_name": "Batter",
                primary_fit_col: f"{lens_short} Fit Score (0–100)",
                primary_sr_col: f"{lens_short} Pressure SR",
                primary_ord_sr_col: f"{lens_short} Ordinary SR",
                primary_gap_col: f"{lens_short} SR Lift (Δ)",
                "overall_avg": "Overall Avg",
                "last10_avg": "Last 10 Matches Avg",
                "last10_india_avg": "Last 10 India Avg",
            })
            html_table(
                t10_display,
                formats={
                    f"{lens_short} Fit Score (0–100)": "{:.1f}",
                    f"{lens_short} Pressure SR": "{:.1f}",
                    f"{lens_short} Ordinary SR": "{:.1f}",
                    f"{lens_short} SR Lift (Δ)": "{:+.1f}",
                    "Overall Avg": "{:.1f}",
                    "Last 10 Matches Avg": "{:.1f}",
                    "Last 10 India Avg": "{:.1f}",
                },
                bar_cols={f"{lens_short} Fit Score (0–100)": 100.0},
                num_cols=[
                    f"{lens_short} Fit Score (0–100)", f"{lens_short} Pressure SR",
                    f"{lens_short} Ordinary SR", f"{lens_short} SR Lift (Δ)",
                    "IPL Pressure Record", "T20I Pressure Record",
                    "India Pitch Pressure", "Overseas Pitch Pressure",
                    "Overall Avg", "Last 10 Matches Avg", "Last 10 India Avg",
                ],
            )

        st.markdown("")

        # --------------------------------------------------------------------
        # 3. IPL vs T20I / India vs Overseas Cluster Comparison
        # --------------------------------------------------------------------
        st.markdown(f"#### 3 · {lens_short} specialists vs {alt_short} pressure performers")
        st.markdown(
            "<div class='note'><b>Why clustering between IPL and T20I changes the scouting board:</b> "
            "Several batters have high overall pressure strike rates (≥ 185 SR), but when we separate <b>IPL franchises</b> "
            "from <b>T20 Internationals</b>, their high strike rates come almost entirely from T20Is or overseas venues "
            "(e.g. <b>Marco Jansen</b> 308.3 T20I Pressure SR vs 95.7 IPL Pressure SR; <b>Dasun Shanaka</b> 295.7 T20I SR vs "
            "133.3 IPL SR; <b>Rovman Powell</b> 230.2 T20I SR vs 173.1 IPL SR; <b>Akeal Hosein</b> & <b>Towhid Hridoy</b> "
            "with 0 IPL pressure balls). Conversely, batters like <b>Sherfane Rutherford</b> (250.0 IPL SR vs 144.4 T20I SR), "
            "<b>Dinesh Karthik</b> (252.8 IPL SR vs 140.0 T20I SR), and <b>Washington Sundar</b> (214.3 India SR / 211.1 IPL SR "
            "vs 40.0 Overseas SR) thrive specifically in Indian / IPL conditions.</div>",
            unsafe_allow_html=True,
        )

        q_left, q_right = st.columns([1.1, 1])
        with q_left:
            quad_df = pr[pr["pressure_sr"] >= 120].copy()
            color_map = (
                {
                    "IPL Pressure Specialist": TEAL,
                    "Dual Finisher (IPL + T20I)": "#0284c7",
                    "T20I / Overseas Performer": AMBER,
                    "IPL Tested (Moderate SR)": "#64748b",
                    "Lower-Order / Other": "#94a3b8",
                }
                if use_ipl_lens
                else {
                    "India Pressure Specialist": TEAL,
                    "Dual Finisher (India + Overseas)": "#0284c7",
                    "Overseas / Non-India Performer": AMBER,
                    "India Tested (Moderate SR)": "#64748b",
                    "Lower-Order / Other": "#94a3b8",
                }
            )
            fig_quad = px.scatter(
                quad_df,
                x=share_col,
                y="pressure_sr",
                size="pressure_balls",
                color="archetype",
                hover_name="striker_name",
                size_max=28,
                color_discrete_map=color_map,
                custom_data=[
                    "pressure_balls", primary_balls_col, primary_sr_col,
                    secondary_balls_col, secondary_sr_col,
                ],
                labels={
                    share_col: f"Share of pressure balls played in {lens_short} (%)",
                    "pressure_sr": "Overall pressure strike rate",
                    "archetype": "",
                },
            )
            fig_quad.update_traces(
                marker=dict(line=dict(width=1, color=NAVY), opacity=0.88),
                hovertemplate=(
                    "<b>%{hovertext}</b><br>"
                    "Overall Pressure SR: <b>%{y:.1f}</b> (%{customdata[0]:,.0f} balls)<br>"
                    f"{lens_short} share: <b>%{{x:.0f}}%</b> (%{{customdata[1]:,.0f}}b · SR: <b>%{{customdata[2]:.1f}}</b>)<br>"
                    f"{alt_short}: <b>%{{customdata[3]:,.0f}}b</b> · SR: <b>%{{customdata[4]:.1f}}</b><extra></extra>"
                ),
            )
            fig_quad.add_hline(y=185, line_dash="dash", line_color="#64748b", line_width=1.2)
            fig_quad.add_vline(x=50, line_dash="dash", line_color="#64748b", line_width=1.2)
            fig_quad.update_layout(legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"))
            st.plotly_chart(
                style(fig_quad, f"Pressure cluster matrix: Overall SR vs % of pressure balls in {lens_short}", height=450),
                width="stretch",
                theme=None,
            )

        with q_right:
            both_venues = pr[(pr[primary_balls_col] >= 6) & (pr[secondary_balls_col] >= 6)].copy()
            both_venues = both_venues.sort_values(diff_col, ascending=True)
            if both_venues.empty:
                st.info(f"Not enough batters tested in both {lens_short} and {alt_short} at this filter level.")
            else:
                both_venues["pref_label"] = np.where(
                    both_venues[diff_col] >= 0,
                    f"Better in {lens_short}",
                    f"Better in {alt_short}",
                )
                fig_div = px.bar(
                    both_venues,
                    x=diff_col,
                    y="striker_name",
                    orientation="h",
                    color="pref_label",
                    color_discrete_map={f"Better in {lens_short}": TEAL, f"Better in {alt_short}": "#0284c7"},
                    custom_data=[
                        primary_sr_col, primary_balls_col,
                        secondary_sr_col, secondary_balls_col,
                    ],
                    labels={
                        diff_col: f"{lens_short} Pressure SR minus {alt_short} Pressure SR (points)",
                        "striker_name": "",
                        "pref_label": "",
                    },
                )
                fig_div.update_traces(
                    hovertemplate=(
                        "<b>%{y}</b><br>"
                        f"{lens_short} vs {alt_short} gap: <b>%{{x:+.1f}} SR pts</b><br>"
                        f"{lens_short} Pressure SR: <b>%{{customdata[0]:.1f}}</b> (%{{customdata[1]:,.0f}}b)<br>"
                        f"{alt_short} Pressure SR: <b>%{{customdata[2]:.1f}}</b> (%{{customdata[3]:,.0f}}b)<extra></extra>"
                    )
                )
                fig_div.add_vline(x=0, line_color=NAVY, line_width=1.5)
                fig_div.update_layout(legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"))
                st.plotly_chart(
                    style(fig_div, f"Batters tested in both: {lens_short} vs {alt_short} pressure SR differential", height=450),
                    width="stretch",
                    theme=None,
                )

        # Callout table of strong T20I / Overseas performers outside the IPL/India Top-10
        if not overseas_stars.empty:
            st.markdown(
                f"##### High-performing pressure batters outside the {lens_short} Top-10 (Strong {alt_short} / Limited {lens_short} Sample)"
            )
            ovr_tbl = overseas_stars.head(10).copy()
            ovr_tbl["IPL Pressure (balls)"] = [
                f"{sr:.1f} ({int(b)}b)" if b > 0 and pd.notna(sr) else "0 balls in IPL"
                for sr, b in zip(ovr_tbl["ipl_pressure_sr"], ovr_tbl["ipl_pressure_balls"])
            ]
            ovr_tbl["T20I Pressure (balls)"] = [
                f"{sr:.1f} ({int(b)}b)" if b > 0 and pd.notna(sr) else "0 balls in T20I"
                for sr, b in zip(ovr_tbl["t20i_pressure_sr"], ovr_tbl["t20i_pressure_balls"])
            ]
            ovr_tbl["India Pressure (balls)"] = [
                f"{sr:.1f} ({int(b)}b)" if b > 0 and pd.notna(sr) else "0 balls in India"
                for sr, b in zip(ovr_tbl["india_pressure_sr"], ovr_tbl["india_pressure_balls"])
            ]
            ovr_tbl["Overseas Pressure (balls)"] = [
                f"{sr:.1f} ({int(b)}b)" if b > 0 and pd.notna(sr) else "–"
                for sr, b in zip(ovr_tbl["overseas_pressure_sr"], ovr_tbl["overseas_pressure_balls"])
            ]
            ovr_tbl[f"Why Outside {lens_short} Top-10"] = [
                f"No pressure balls in {lens_short} (100% {alt_short})"
                if pb == 0
                else (
                    f"Small {lens_short} sample ({int(pb)}b < {min_ind_b}b)"
                    if pb < min_ind_b
                    else f"Higher {alt_short} SR ({ssr:.1f} vs {psr:.1f} in {lens_short})"
                )
                for pb, psr, ssr in zip(
                    ovr_tbl[primary_balls_col],
                    ovr_tbl[primary_sr_col],
                    ovr_tbl[secondary_sr_col],
                )
            ]
            ovr_display = ovr_tbl[[
                "striker_name", "pressure_balls", "pressure_sr",
                "IPL Pressure (balls)", "T20I Pressure (balls)",
                "India Pressure (balls)", "Overseas Pressure (balls)",
                "overall_avg", "last10_avg", f"Why Outside {lens_short} Top-10", "best_cluster",
            ]].rename(columns={
                "striker_name": "Batter",
                "pressure_balls": "Total Pressure Balls",
                "pressure_sr": "Overall Pressure SR",
                "overall_avg": "Overall Avg",
                "last10_avg": "Last 10 Matches Avg",
                "best_cluster": "IPL vs T20I Edge",
            })
            html_table(
                ovr_display,
                formats={
                    "Overall Pressure SR": "{:.1f}",
                    "Overall Avg": "{:.1f}",
                    "Last 10 Matches Avg": "{:.1f}",
                },
                num_cols=[
                    "Total Pressure Balls", "Overall Pressure SR",
                    "IPL Pressure (balls)", "T20I Pressure (balls)",
                    "India Pressure (balls)", "Overseas Pressure (balls)",
                    "Overall Avg", "Last 10 Matches Avg",
                ],
            )

        st.markdown("")

        # --------------------------------------------------------------------
        # 4. The Clutch Escalator: Ordinary SR -> Pressure SR (Dumbbell Plot)
        # --------------------------------------------------------------------
        st.markdown("#### 4 · The clutch escalator: how much batters accelerate from ordinary balls to pressure balls")
        top_lift = pr.sort_values("gap", ascending=True).tail(20).copy()
        fig_dumb = go.Figure()
        for _, r in top_lift.iterrows():
            fig_dumb.add_trace(
                go.Scatter(
                    x=[r["ordinary_sr"], r["pressure_sr"]],
                    y=[r["striker_name"], r["striker_name"]],
                    mode="lines",
                    line=dict(color="#94a3b8", width=2.5),
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
        fig_dumb.add_trace(
            go.Scatter(
                x=top_lift["ordinary_sr"],
                y=top_lift["striker_name"],
                mode="markers",
                name="Ordinary SR (non-pressure)",
                marker=dict(size=10, color="#64748b", line=dict(width=1.5, color="#ffffff")),
                customdata=top_lift[["ordinary_balls", "ordinary_runs"]],
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "Ordinary SR: <b>%{x:.1f}</b> (%{customdata[1]:,.0f} runs off %{customdata[0]:,.0f}b)<extra></extra>"
                ),
            )
        )
        fig_dumb.add_trace(
            go.Scatter(
                x=top_lift["pressure_sr"],
                y=top_lift["striker_name"],
                mode="markers+text",
                name="Pressure SR (RRR ≥ 15)",
                text=[f"+{g:.0f}" if g >= 0 else f"{g:.0f}" for g in top_lift["gap"]],
                textposition="middle right",
                textfont=dict(color=TEAL, size=11),
                marker=dict(size=12, color=TEAL, line=dict(width=1.5, color="#ffffff")),
                customdata=top_lift[["pressure_balls", "pressure_runs", "gap", "ipl_pressure_sr", "t20i_pressure_sr"]],
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "Pressure SR: <b>%{x:.1f}</b> (%{customdata[1]:,.0f} runs off %{customdata[0]:,.0f}b)<br>"
                    "Clutch SR Lift: <b>%{customdata[2]:+.1f} pts</b><br>"
                    "IPL Pressure SR: <b>%{customdata[3]:.1f}</b> · T20I Pressure SR: <b>%{customdata[4]:.1f}</b><extra></extra>"
                ),
            )
        )
        fig_dumb.update_xaxes(range=[60, float(top_lift["pressure_sr"].max()) + 35], title_text="Strike rate (runs per 100 balls)")
        fig_dumb.update_layout(legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"))
        st.plotly_chart(
            style(fig_dumb, "Top 20 clutch escalators: Ordinary SR → Pressure SR (label = +SR lift)", height=560),
            width="stretch",
            theme=None,
        )

        # --------------------------------------------------------------------
        # 5. Complete Master Pressure Table (All Batters + Filter by Group)
        # --------------------------------------------------------------------
        st.markdown("#### 5 · Complete pressure batters table (IPL vs T20I, India vs Overseas & Last 10 Averages)")
        f_col1, f_col2 = st.columns([1.2, 1])
        with f_col1:
            group_filter = st.radio(
                "Filter table view",
                options=[
                    "All qualified batters",
                    f"Top 10 best fit in {lens_short}",
                    f"Other high-SR batters ({alt_short} / Non-{lens_short})",
                ],
                horizontal=True,
            )
        with f_col2:
            sort_choice = st.selectbox(
                "Sort master table by",
                options=[
                    "IPL Fit Score (0–100)",
                    "IPL Pressure SR",
                    "India Fit Score (0–100)",
                    "India Pressure SR",
                    "Overall Pressure SR",
                    "SR Gap (Pressure minus Ordinary)",
                    "Total Pressure Balls",
                ],
                index=0 if use_ipl_lens else 2,
            )

        sort_col_map = {
            "IPL Fit Score (0–100)": "ipl_fit_score",
            "IPL Pressure SR": "ipl_pressure_sr",
            "India Fit Score (0–100)": "india_fit_score",
            "India Pressure SR": "india_pressure_sr",
            "Overall Pressure SR": "pressure_sr",
            "SR Gap (Pressure minus Ordinary)": "gap",
            "Total Pressure Balls": "pressure_balls",
        }
        pr_sorted = pr.copy()
        if group_filter == f"Top 10 best fit in {lens_short}":
            pr_sorted = pr_sorted[pr_sorted["striker_name"].isin(top10_names)].copy()
        elif group_filter == f"Other high-SR batters ({alt_short} / Non-{lens_short})":
            pr_sorted = pr_sorted[pr_sorted["striker_name"].isin(set(overseas_stars["striker_name"]))].copy()

        pr_sorted = pr_sorted.sort_values(sort_col_map[sort_choice], ascending=False, na_position="last")

        rank_lookup = dict(zip(top10_india["striker_name"], top10_india["rank"]))
        pr_sorted["Role / Fit Tag"] = [
            f"<span class='pill ok'>#{rank_lookup[n]} {lens_short} Top-10</span>"
            if n in rank_lookup
            else (
                f"<span class='pill overseas'>{alt_short} Star</span>"
                if n in set(overseas_stars["striker_name"])
                else "<span class='pill warn'>Squad Depth</span>"
            )
            for n in pr_sorted["striker_name"]
        ]

        pr_sorted["IPL Pressure (balls)"] = [
            f"{sr:.1f} ({int(b)}b)" if b > 0 and pd.notna(sr) else "–"
            for sr, b in zip(pr_sorted.get("ipl_pressure_sr", []), pr_sorted.get("ipl_pressure_balls", []))
        ]
        pr_sorted["T20I Pressure (balls)"] = [
            f"{sr:.1f} ({int(b)}b)" if b > 0 and pd.notna(sr) else "–"
            for sr, b in zip(pr_sorted.get("t20i_pressure_sr", []), pr_sorted.get("t20i_pressure_balls", []))
        ]
        pr_sorted["Indian Pressure (balls)"] = [
            f"{sr:.1f} ({int(b)}b)" if b > 0 and pd.notna(sr) else "–"
            for sr, b in zip(pr_sorted.get("india_pressure_sr", []), pr_sorted.get("india_pressure_balls", []))
        ]
        pr_sorted["Overseas Pressure (balls)"] = [
            f"{sr:.1f} ({int(b)}b)" if b > 0 and pd.notna(sr) else "–"
            for sr, b in zip(pr_sorted.get("overseas_pressure_sr", []), pr_sorted.get("overseas_pressure_balls", []))
        ]
        pt_cols = [
            "striker_name", "Role / Fit Tag", "pressure_balls", "pressure_runs", "pressure_sr",
            "ordinary_sr", "gap",
            "IPL Pressure (balls)", "T20I Pressure (balls)",
            "Indian Pressure (balls)", "Overseas Pressure (balls)",
            "overall_avg", "last10_avg", "last10_ipl_avg", "last10_india_avg",
            "ipl_fit_score", "india_fit_score", "best_cluster", "best_pitch",
        ]
        pt_cols = [c for c in pt_cols if c in pr_sorted.columns]
        pr_tbl = pr_sorted[pt_cols].rename(
            columns={
                "striker_name": "Batter",
                "pressure_balls": "Pressure balls",
                "pressure_runs": "Pressure runs",
                "pressure_sr": "Pressure SR",
                "ordinary_sr": "Ordinary SR",
                "gap": "SR Gap",
                "overall_avg": "Overall Avg",
                "last10_avg": "Last 10 Matches Avg",
                "last10_ipl_avg": "Last 10 IPL Avg",
                "last10_india_avg": "Last 10 India Avg",
                "ipl_fit_score": "IPL Fit Score (0–100)",
                "india_fit_score": "India Fit Score (0–100)",
                "best_cluster": "IPL vs T20I Edge",
                "best_pitch": "Performed Better On",
            }
        )
        html_table(
            pr_tbl,
            formats={
                "Pressure runs": "{:,.0f}",
                "Pressure SR": "{:.1f}",
                "Ordinary SR": "{:.1f}",
                "SR Gap": "{:+.1f}",
                "Overall Avg": "{:.1f}",
                "Last 10 Matches Avg": "{:.1f}",
                "Last 10 IPL Avg": "{:.1f}",
                "Last 10 India Avg": "{:.1f}",
                "IPL Fit Score (0–100)": "{:.1f}",
                "India Fit Score (0–100)": "{:.1f}",
            },
            bar_cols={"IPL Fit Score (0–100)": 100.0, "India Fit Score (0–100)": 100.0},
            num_cols=[
                c for c in [
                    "Pressure balls", "Pressure runs", "Pressure SR", "Ordinary SR",
                    "SR Gap", "IPL Pressure (balls)", "T20I Pressure (balls)",
                    "Indian Pressure (balls)", "Overseas Pressure (balls)",
                    "Overall Avg", "Last 10 Matches Avg", "Last 10 IPL Avg", "Last 10 India Avg",
                    "IPL Fit Score (0–100)", "India Fit Score (0–100)",
                ] if c in pr_tbl.columns
            ],
        )

# ----------------------------------------------------------------------------
# About
# ----------------------------------------------------------------------------
with tab_about:
    st.markdown("""
**Definitions**
- **Average:** runs divided by dismissals. Not-outs are not counted as dismissals.
- **Strike rate:** runs per 100 balls faced. Wides are excluded from balls faced; no-balls are included.
- **Boundary share:** runs from fours and sixes as a share of total runs.
- **50+ rate:** the share of innings with a 50 or more.
- **Venue difference:** the batter's strike rate at a venue minus the average strike rate of all batters there in the same view.
- **Percentile (player vs player):** where a batter's figure sits among all batters with at least 10 innings in the view.
- **Pressure state:** deliveries where `Innings = 2`, `Legal Balls Remaining <= 30`, `Wickets Down >= 3`, and `Required Run Rate >= 15`.

**Data scope**
- Super overs are excluded.
- Venues are shown by ID. Stadium names are not in the data pack.
- Pressure uses ball-level state (`Innings = 2`, `Legal Balls Remaining <= 30`, `Wickets Down >= 3`, `Required Run Rate >= 15`).
- The dismissal breakdown uses `batting_dismissal_types.csv` if it is in the data folder.

**Cautions**
- Small samples can look extreme. Check innings and balls before drawing conclusions.
- Results combine all selected formats unless you filter them.
""")