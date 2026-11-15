"""Shared, parameterized filtering for match and delivery queries."""

from __future__ import annotations

from typing import Any


def match_filter(
    filters: dict[str, Any],
    match_alias: str = "m",
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    formats = filters.get("formats") or []
    if formats:
        clauses.append(f"{match_alias}.match_format IN ({','.join('?' for _ in formats)})")
        params.extend(formats)

    seasons = filters.get("seasons") or []
    if seasons:
        clauses.append(f"{match_alias}.season IN ({','.join('?' for _ in seasons)})")
        params.extend(seasons)

    country = filters.get("country", "All countries")
    if country and country != "All countries":
        clauses.append(f"{match_alias}.venue_country = ?")
        params.append(country)

    return (" AND ".join(clauses) if clauses else "1=1"), params


def delivery_filter(
    filters: dict[str, Any],
    delivery_alias: str = "d",
    match_alias: str = "m",
    *,
    apply_pressure_toggle: bool = True,
    pressure_column: str = "pressure",
) -> tuple[str, list[Any]]:
    where, params = match_filter(filters, match_alias)
    clauses = [where]
    if apply_pressure_toggle and filters.get("pressure_only"):
        if pressure_column not in {"pressure", "bowling_pressure"}:
            raise ValueError("Unsupported pressure flag")
        clauses.append(f"{delivery_alias}.{pressure_column} = 1")
    return " AND ".join(f"({part})" for part in clauses), params


def summary_filter(
    filters: dict[str, Any],
    summary_alias: str = "s",
    match_alias: str = "m",
) -> tuple[str, list[Any]]:
    where, params = match_filter(filters, match_alias)
    if filters.get("pressure_only"):
        where = (
            f"({where}) AND EXISTS (SELECT 1 FROM chase_states pc "
            f"WHERE pc.match_id = {summary_alias}.match_id AND pc.pressure = 1)"
        )
    return where, params
