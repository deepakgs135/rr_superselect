"""Small presentation helpers that avoid dataframe-runtime dependencies."""

from __future__ import annotations

import json
import math
from typing import Any, Callable

import streamlit as st

from .metrics import fmt, pct

from html import escape

PRESSURE = "#F07854"
ORDINARY = "#0F766E"
BLUE = "#4F7CAC"
GOLD = "#D4A72C"
PURPLE = "#805AD5"
SLATE = "#64748B"

UI_CSS = """
<style>
.pd-hero {
    padding: 1.25rem 1.6rem;
    border-radius: 14px;
    margin-bottom: 1.1rem;
    background: linear-gradient(135deg, #0f172a 0%, #115e59 100%);
    border: 1px solid #0f766e;
    box-shadow: 0 4px 12px rgba(15, 23, 42, 0.12);
}
.pd-hero h1, .pd-hero h1 * {
    margin: 0 !important;
    padding: 0 !important;
    font-size: 1.85rem !important;
    font-weight: 800 !important;
    color: #ffffff !important;
}
.pd-hero p {
    margin: 0.35rem 0 0 0 !important;
    color: #ccfbf1 !important;
    font-size: 1rem !important;
    font-weight: 500 !important;
}
[data-testid="stMetric"] {
    background: #ffffff;
    border-radius: 10px;
    padding: 6px 8px;
}
.pd-tbl-wrap {
    width: 100%;
    overflow-x: auto;
    border-radius: 10px;
    border: 1px solid #cbd5e1;
    background: #ffffff;
    margin-bottom: 0.85rem;
    box-shadow: 0 1px 4px rgba(15, 23, 42, 0.04);
}
.pd-tbl {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.88rem;
    background: #ffffff;
}
.pd-tbl th {
    text-align: left;
    background: #0f172a;
    color: #ffffff !important;
    padding: 9px 12px;
    font-weight: 700;
    border-bottom: 3px solid #0f766e;
    white-space: nowrap;
}
.pd-tbl th.num, .pd-tbl td.num {
    text-align: right;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}
.pd-tbl td {
    padding: 8px 12px;
    border-bottom: 1px solid #e2e8f0;
    color: #0f172a !important;
    font-weight: 500;
}
.pd-tbl tr:nth-child(even) td {background: #f8fafc;}
.pd-tbl tr:hover td {background: #f0fdfa;}
</style>
"""


def page_header(title: str, subtitle: str, icon: str = ":material/analytics:") -> None:
    st.markdown(UI_CSS, unsafe_allow_html=True)
    st.markdown(
        f"<div class='pd-hero'><h1>{escape(title)}</h1><p>{escape(subtitle)}</p></div>",
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
    st.markdown(
        f"<div class='pd-tbl-wrap'><table class='pd-tbl'><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def chart(fig: Any, alt: str, *, height: int = 360) -> None:
    fig.update_layout(
        height=height,
        margin=dict(l=20, r=16, t=28, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="sans-serif", size=12),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(zeroline=False)
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
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
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
