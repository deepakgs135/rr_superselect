"""Small presentation helpers that avoid dataframe-runtime dependencies."""

from __future__ import annotations

import json
import math
from typing import Any, Callable

import streamlit as st

from .metrics import fmt, pct

from html import escape

PRESSURE = "#E76F51"
ORDINARY = "#0D9488"
BLUE = "#5387C5"
GOLD = "#C98B12"
PURPLE = "#7C5CE0"
SLATE = "#718096"

UI_CSS = """
<style>
.block-container {
    max-width: 1580px;
    padding-top: 1.65rem;
}
.pd-hero {
    padding: 1.45rem 1.8rem;
    border-radius: 18px;
    margin-bottom: 1.4rem;
    background: linear-gradient(112deg, #E8F0FF 0%, #F2EEFF 52%, #FFF2E8 100%);
    border: 1px solid #DCE4F2;
    box-shadow: 0 8px 24px rgba(46, 72, 120, 0.07);
    position: relative;
    overflow: hidden;
}
.pd-hero h1, .pd-hero h1 * {
    margin: 0 !important;
    padding: 0 !important;
    font-size: 2rem !important;
    font-weight: 800 !important;
    color: #202B3C !important;
    letter-spacing: -0.035em;
}
.pd-hero p {
    margin: 0.45rem 0 0 0 !important;
    color: #52647B !important;
    font-size: 1.02rem !important;
    font-weight: 500 !important;
}
.pd-eyebrow {
    color: #4F6FC8;
    font-size: 0.72rem;
    font-weight: 800;
    letter-spacing: 0.11em;
    text-transform: uppercase;
    margin-bottom: 0.4rem;
}
[data-testid="stTabs"] [role="tablist"] {
    gap: 0.45rem;
    border-bottom: 1px solid #DCE4F0;
    margin-bottom: 1.1rem;
}
[data-testid="stTabs"] button[role="tab"] {
    border: 1px solid transparent;
    border-radius: 12px 12px 0 0;
    color: #596A80;
    padding: 0.7rem 1.15rem;
    font-weight: 700;
    transition: background 120ms ease, color 120ms ease;
}
[data-testid="stTabs"] button[role="tab"]:hover {
    background: #EFF4FF;
    color: #315BC6;
}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color: #315BC6;
    background: #EAF1FF;
    border-color: #DCE4F0;
    border-bottom: 3px solid #4F7DF3;
}
[data-testid="stMetric"] {
    background: linear-gradient(140deg, #FFFFFF 0%, #F7F9FF 100%);
    border: 1px solid #E0E7F1;
    border-left: 4px solid #4F7DF3;
    border-radius: 14px;
    padding: 0.8rem 1rem;
    min-height: 92px;
    box-shadow: 0 4px 14px rgba(46, 72, 120, 0.045);
}
[data-testid="stMetricLabel"] p {
    color: #687990;
    font-size: 0.78rem;
    font-weight: 700;
}
[data-testid="stMetricValue"] div {
    color: #24364F;
    font-weight: 750;
}
.pd-tbl-wrap {
    width: 100%;
    overflow-x: auto;
    border-radius: 12px;
    border: 1px solid #DCE4F0;
    background: var(--secondary-background-color);
    margin: 0.45rem 0 0.8rem;
    box-shadow: 0 3px 12px rgba(46, 72, 120, 0.04);
}
.pd-tbl {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.84rem;
    background: var(--secondary-background-color);
}
.pd-tbl th {
    position: sticky;
    top: 0;
    z-index: 2;
    text-align: left;
    background: #EAF1FF;
    color: #26364A !important;
    padding: 10px 12px;
    font-weight: 700;
    border-bottom: 2px solid #25A99A;
    white-space: nowrap;
}
.pd-tbl th.num, .pd-tbl td.num {
    text-align: right;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}
.pd-tbl td {
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-color);
    color: var(--text-color) !important;
    font-weight: 500;
    white-space: nowrap;
}
.pd-tbl tr:nth-child(even) td {
    background: #F7F9FD;
}
.pd-tbl tr:hover td {
    background: #FFF4E7;
}
[data-testid="stExpander"] {
    border: 1px solid #DCE4F0;
    border-radius: 14px;
    background: #FFFFFF;
}
@media (max-width: 760px) {
    .block-container { padding: 1rem 0.8rem 2rem; }
    .pd-hero { padding: 1.1rem 1.15rem; border-radius: 14px; }
    .pd-hero h1, .pd-hero h1 * { font-size: 1.55rem !important; }
    [data-testid="stTabs"] button[role="tab"] { padding: 0.58rem 0.65rem; }
}
</style>
"""


def page_header(title: str, subtitle: str, icon: str = ":material/analytics:") -> None:
    st.markdown(UI_CSS, unsafe_allow_html=True)
    st.markdown(
        f"<div class='pd-hero'><div class='pd-eyebrow'>CRICKET PERFORMANCE · RAW DATA</div>"
        f"<h1>{escape(title)}</h1><p>{escape(subtitle)}</p></div>",
        unsafe_allow_html=True,
    )


def metric_row(metrics: list[tuple[str, str, str | None]]) -> None:
    cols = st.columns(len(metrics), border=True)
    for col, (label, value, help_text) in zip(cols, metrics):
        col.metric(label, value, help=help_text)


def _cell(value: Any, formatter: Callable[[Any], str] | None = None) -> tuple[str, bool]:
    is_num = isinstance(value, (int, float)) and not isinstance(value, bool)
    if formatter:
        text = formatter(value)
    elif value is None:
        text = "–"
    elif isinstance(value, bool):
        text = "Yes" if value else "No"
    elif isinstance(value, int):
        text = f"{value:,}"
    elif isinstance(value, float):
        if not math.isfinite(value):
            text = "–"
        elif value.is_integer():
            text = f"{int(round(value)):,}"
        else:
            text = f"{value:,.2f}"
    else:
        text = str(value)
    return escape(str(text)), is_num


def markdown_table(
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str] | tuple[str, str, Callable[[Any], str]]],
    *,
    empty_message: str = "No records match these filters.",
    max_height: int | None = None,
) -> None:
    if not rows:
        st.info(empty_message)
        return
    num_keys = set()
    for item in columns:
        k = item[0]
        for r in rows[:10]:
            v = r.get(k)
            if v is not None:
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    num_keys.add(k)
                break
    num_attr = " class='num'"
    head = "".join(
        f"<th{num_attr if item[0] in num_keys else ''}>{escape(item[1])}</th>"
        for item in columns
    )
    body_rows = []
    for row in rows:
        tds = []
        for item in columns:
            key, _, *formatter = item
            cell_html, is_num = _cell(row.get(key), formatter[0] if formatter else None)
            cls = " class='num'" if (is_num or key in num_keys) else ""
            tds.append(f"<td{cls}>{cell_html}</td>")
        body_rows.append("<tr>" + "".join(tds) + "</tr>")
    wrap_style = f"max-height:{int(max_height)}px; overflow:auto;" if max_height else ""
    st.markdown(
        f"<div class='pd-tbl-wrap' style='{wrap_style}'><table class='pd-tbl'><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def chart(fig: Any, alt: str, *, height: int = 360) -> None:
    fig.update_layout(
        height=height,
        margin=dict(l=28, r=34, t=48 if fig.layout.title.text else 24, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="sans-serif", size=12, color="#26364A"),
        title_font=dict(size=15, color="#26364A"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor="#DCE4F0", tickfont=dict(color="#53657A"), automargin=True)
    fig.update_yaxes(zeroline=False, gridcolor="#E8EDF5", tickfont=dict(color="#53657A"), automargin=True)
    st.plotly_chart(fig, alt=alt, width="stretch", config={"displayModeBar": False})


def year_axis(fig: Any, years: list[Any]) -> None:
    """Show one discrete calendar-year tick for each annual trend point."""
    labels = [str(year) for year in years]
    if labels:
        fig.update_xaxes(
            type="category",
            categoryorder="array",
            categoryarray=labels,
            tickmode="array",
            tickvals=labels,
            ticktext=labels,
        )


def csv_download(rows: list[dict[str, Any]], label: str, filename: str, key: str) -> None:
    import csv
    import io

    if not rows:
        return
    buffer = io.StringIO(newline="")
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    st.download_button(
        label,
        data=buffer.getvalue().encode("utf-8-sig"),
        file_name=filename,
        mime="text/csv",
        key=key,
        icon=":material/download:",
    )


def json_block(data: dict[str, Any]) -> None:
    st.code(json.dumps(data, indent=2, ensure_ascii=False), language="json")


def fmt_or_na(value: Any, digits: int = 1) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, (int, float)):
        return fmt(value, digits)
    return str(value)


def signed(value: float | int | None, digits: int = 1) -> str:
    if value is None:
        return "N/A"
    return f"{value:+,.{digits}f}"
