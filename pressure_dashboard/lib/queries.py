"""Parameterized SQLite queries shared by the dashboard pages."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from typing import Any

from .db import query
from .filters import delivery_filter, match_filter, summary_filter
from .player_names import (
    apply_player_display_names,
    display_player_aggregate_rows,
    player_display_name,
)


def filter_options() -> dict[str, Any]:
    formats = query(
        "SELECT DISTINCT match_format FROM matches WHERE match_format <> '' ORDER BY match_format"
    )
    seasons = query(
        """SELECT DISTINCT season FROM matches WHERE season <> ''
        ORDER BY CAST(substr(season, 1, 4) AS INTEGER), season"""
    )
    countries = query(
        "SELECT DISTINCT venue_country FROM matches WHERE venue_country <> '' ORDER BY venue_country"
    )
    scope = query(
        """SELECT COUNT(*) AS matches,
                  (SELECT COUNT(*) FROM deliveries) AS deliveries,
                  (SELECT COUNT(*) FROM chase_states WHERE state_known=1) AS known_chase_states
           FROM matches"""
    )
    return {
        "formats": [row["match_format"] for row in formats],
        "seasons": [row["season"] for row in seasons],
        "countries": [row["venue_country"] for row in countries],
        **(scope[0] if scope else {}),
    }


def overview(filters: dict[str, Any]) -> dict[str, Any]:
    where, params = summary_filter(filters, "s", "m")
    rows = query(
        f"""
        SELECT COUNT(*) AS chase_innings,
               SUM(CASE WHEN s.chase_success IS NOT NULL THEN 1 ELSE 0 END) AS decided_chases,
               SUM(CASE WHEN s.pressure_legal_balls > 0 THEN 1 ELSE 0 END) AS pressure_chases,
               SUM(CASE WHEN s.pressure_legal_balls > 0 AND s.chase_success=1 THEN 1 ELSE 0 END) AS pressure_chase_wins,
               SUM(CASE WHEN s.pressure_legal_balls > 0 AND s.chase_success IS NOT NULL THEN 1 ELSE 0 END) AS decided_pressure_chases,
               SUM(s.known_legal_balls) AS chase_legal_balls,
               SUM(s.pressure_legal_balls) AS pressure_legal_balls,
               SUM(s.pressure_raw_runs_proxy) AS pressure_raw_runs_proxy,
               SUM(s.pressure_wicket_events) AS pressure_wicket_events,
               SUM(s.unknown_legality_events) AS unknown_legality_events,
               SUM(s.unknown_rrr_states) AS unknown_rrr_states
        FROM innings_summary s JOIN matches m ON m.match_id=s.match_id
        WHERE s.innings=2 AND {where}
        """,
        tuple(params),
    )
    return rows[0] if rows else {}


def overview_by_year(filters: dict[str, Any]) -> list[dict[str, Any]]:
    where, params = summary_filter(filters, "s", "m")
    return query(
        f"""
        SELECT CAST(substr(m.match_date, 1, 4) AS INTEGER) AS year,
               COUNT(*) AS chase_innings,
               SUM(CASE WHEN s.pressure_legal_balls > 0 THEN 1 ELSE 0 END) AS pressure_chases,
               SUM(s.pressure_legal_balls) AS pressure_legal_balls,
               SUM(s.known_legal_balls) AS chase_legal_balls,
               SUM(CASE WHEN s.pressure_legal_balls > 0 AND s.chase_success=1 THEN 1 ELSE 0 END) AS pressure_wins,
               SUM(CASE WHEN s.pressure_legal_balls > 0 AND s.chase_success IS NOT NULL THEN 1 ELSE 0 END) AS decided_pressure_chases
        FROM innings_summary s JOIN matches m ON m.match_id=s.match_id
        WHERE s.innings=2 AND {where}
        GROUP BY substr(m.match_date, 1, 4)
        ORDER BY year
        """,
        tuple(params),
    )


def state_comparison(
    filters: dict[str, Any],
    role: str,
    venue_id: str | None = None,
) -> list[dict[str, Any]]:
    where, params = match_filter(filters, "m")
    pressure_field = "cs.pressure" if role == "batter" else "cs.bowling_pressure"
    if venue_id is not None:
        where += " AND m.venue_id = ?"
        params.append(venue_id)
    if role == "batter":
        group_id = "cs.striker_id"
        name_expr = "MAX(cs.striker_name)"
        rows = query(
            f"""
            SELECT {group_id} AS player_id, {name_expr} AS player,
                   {pressure_field} AS pressure,
                   SUM(cs.runs) AS runs,
                   SUM(cs.faced_ball) AS balls,
                   SUM(cs.is_four) AS fours,
                   SUM(cs.is_six) AS sixes,
                   SUM(cs.batter_dot) AS dots,
                   SUM(CASE WHEN cs.is_wicket=1 AND cs.dismissed_player_id=cs.striker_id THEN 1 ELSE 0 END) AS dismissals,
                   COUNT(DISTINCT cs.match_id) AS matches
            FROM chase_states cs JOIN matches m ON m.match_id=cs.match_id
            WHERE {where} AND cs.state_known=1 AND cs.striker_id>=0
            GROUP BY cs.striker_id, cs.pressure
            HAVING SUM(cs.faced_ball)>0
            ORDER BY player
            """,
            tuple(params),
        )
        return display_player_aggregate_rows(rows)
    rows = query(
        f"""
        SELECT cs.bowler_id AS player_id, MAX(cs.bowler_name) AS player,
               {pressure_field} AS pressure,
               SUM(cs.total_runs_proxy) AS runs_proxy,
               SUM(cs.legal) AS legal_balls,
               SUM(cs.unknown_legality) AS unknown_legality,
               SUM(cs.credited_wicket) AS credited_wickets,
               SUM(CASE WHEN cs.legal=1 AND cs.team_dot=1 THEN 1 ELSE 0 END) AS dots,
               SUM(cs.is_four + cs.is_six) AS boundary_events,
               SUM(CASE WHEN lower(cs.extras_type)='wide' THEN 1 ELSE 0 END) AS wides,
               SUM(CASE WHEN lower(cs.extras_type)='overstep' THEN 1 ELSE 0 END) AS no_balls,
               COUNT(DISTINCT cs.match_id) AS matches
        FROM chase_states cs JOIN matches m ON m.match_id=cs.match_id
        WHERE {where} AND cs.state_known=1 AND cs.bowler_id>=0
        GROUP BY cs.bowler_id, {pressure_field}
        HAVING SUM(cs.legal)>0
        ORDER BY player
        """,
        tuple(params),
    )
    return display_player_aggregate_rows(rows)


def match_filter_sql(filters: dict[str, Any]) -> str:
    return match_filter(filters, "m")[0]


def match_filter_params(filters: dict[str, Any]) -> list[Any]:
    return match_filter(filters, "m")[1]


def batter_stats(filters: dict[str, Any], venue_id: str | None = None) -> list[dict[str, Any]]:
    where, params = delivery_filter(filters, "d", "m")
    clauses = [where, "d.innings IN (1,2)", "d.striker_id>=0"]
    if venue_id is not None:
        clauses.append("m.venue_id=?")
        params.append(venue_id)
    rows = query(
        f"""
        SELECT d.striker_id AS player_id, MAX(d.striker_name) AS player,
               COUNT(DISTINCT d.match_id) AS matches,
               COUNT(DISTINCT CAST(d.match_id AS TEXT) || ':' || CAST(d.innings AS TEXT)) AS innings,
               SUM(d.runs) AS runs,
               SUM(d.faced_ball) AS balls,
               SUM(CASE WHEN d.is_wicket=1 AND d.dismissed_player_id=d.striker_id THEN 1 ELSE 0 END) AS dismissals,
               SUM(d.is_four) AS fours,
               SUM(d.is_six) AS sixes,
               SUM(d.batter_dot) AS dots,
               SUM(CASE WHEN d.over_no BETWEEN 1 AND 6 THEN d.runs ELSE 0 END) AS powerplay_runs,
               SUM(CASE WHEN d.over_no BETWEEN 1 AND 6 THEN d.faced_ball ELSE 0 END) AS powerplay_balls,
               SUM(CASE WHEN d.over_no BETWEEN 7 AND 15 THEN d.runs ELSE 0 END) AS middle_runs,
               SUM(CASE WHEN d.over_no BETWEEN 7 AND 15 THEN d.faced_ball ELSE 0 END) AS middle_balls,
               SUM(CASE WHEN d.over_no BETWEEN 16 AND 20 THEN d.runs ELSE 0 END) AS death_runs,
               SUM(CASE WHEN d.over_no BETWEEN 16 AND 20 THEN d.faced_ball ELSE 0 END) AS death_balls,
               SUM(CASE WHEN d.pressure=1 THEN d.runs ELSE 0 END) AS pressure_runs,
               SUM(CASE WHEN d.pressure=1 THEN d.faced_ball ELSE 0 END) AS pressure_balls,
               SUM(CASE WHEN d.pressure=1 THEN d.is_wicket ELSE 0 END) AS pressure_wicket_events
        FROM deliveries d JOIN matches m ON m.match_id=d.match_id
        WHERE {' AND '.join(f'({c})' for c in clauses)}
        GROUP BY d.striker_id
        ORDER BY runs DESC, player
        """,
        tuple(params),
    )
    for row in rows:
        row["source_player"] = row.get("player")
        row["player"] = player_display_name(row.get("player_id"), row.get("player"))
    return rows


def source_batter_stats(filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Aggregate the separate raw-CSV record table for the selected cohort."""
    where, params = match_filter(filters, "m")
    return query(
        f"""
        SELECT s.player_id, MAX(s.source_name) AS source_name,
               COUNT(DISTINCT s.match_id) AS matches,
               COUNT(DISTINCT CAST(s.match_id AS TEXT) || ':' || CAST(s.innings AS TEXT)) AS innings,
               SUM(s.runs) AS runs, SUM(s.balls) AS balls,
               SUM(s.dismissals) AS dismissals, SUM(s.fours) AS fours, SUM(s.sixes) AS sixes,
               (SELECT COUNT(DISTINCT n.source_name) FROM source_player_names n
                WHERE n.role='batter' AND n.player_id=s.player_id) AS source_name_variants,
               (SELECT GROUP_CONCAT(n.source_name, ' / ') FROM source_player_names n
                WHERE n.role='batter' AND n.player_id=s.player_id) AS source_names
        FROM source_batter_records s JOIN matches m ON m.match_id=s.match_id
        WHERE {where}
        GROUP BY s.player_id
        ORDER BY runs DESC, s.player_id
        """,
        tuple(params),
    )


def batter_profile(
    filters: dict[str, Any],
    player_id: int,
    venue_id: str | None = None,
) -> list[dict[str, Any]]:
    where, params = delivery_filter(filters, "d", "m")
    clauses = [where, "d.innings IN (1,2)", "d.striker_id=?"]
    params.append(player_id)
    if venue_id is not None:
        clauses.append("m.venue_id=?")
        params.append(venue_id)
    rows = query(
        f"""
        SELECT d.*, m.match_date, m.match_format, m.season, m.competition_name,
               m.venue_id, m.venue_country, m.result, m.chase_success
        FROM deliveries d JOIN (
            SELECT mt.*, c.comp_name AS competition_name
            FROM matches mt LEFT JOIN competitions c ON c.comp_id=mt.comp_id
        ) m ON m.match_id=d.match_id
        WHERE {' AND '.join(f'({c})' for c in clauses)}
        ORDER BY m.match_date, d.match_id, d.innings, d.seq
        """,
        tuple(params),
    )
    return apply_player_display_names(rows)


def bowler_stats(filters: dict[str, Any], venue_id: str | None = None) -> list[dict[str, Any]]:
    where, params = delivery_filter(
        filters, "d", "m", pressure_column="bowling_pressure"
    )
    clauses = [where, "d.innings IN (1,2)", "d.bowler_id>=0"]
    if venue_id is not None:
        clauses.append("m.venue_id=?")
        params.append(venue_id)
    rows = query(
        f"""
        SELECT d.bowler_id AS player_id, MAX(d.bowler_name) AS player,
               COUNT(DISTINCT d.match_id) AS matches,
               COUNT(DISTINCT CAST(d.match_id AS TEXT) || ':' || CAST(d.innings AS TEXT)) AS innings,
               COUNT(*) AS event_rows,
               SUM(d.legal) AS legal_balls,
               SUM(d.unknown_legality) AS unknown_legality,
               SUM(d.total_runs_proxy) AS runs_proxy,
               SUM(d.is_wicket) AS wicket_events,
               SUM(d.credited_wicket) AS credited_wickets,
               SUM(d.team_dot) AS dots,
               SUM(d.is_four + d.is_six) AS boundary_events,
               SUM(CASE WHEN lower(d.extras_type)='wide' THEN 1 ELSE 0 END) AS wides,
               SUM(CASE WHEN lower(d.extras_type)='overstep' THEN 1 ELSE 0 END) AS no_balls,
               SUM(CASE WHEN d.pace_or_spin='Pace' THEN 1 ELSE 0 END) AS pace_events,
               SUM(CASE WHEN d.pace_or_spin='Spin' THEN 1 ELSE 0 END) AS spin_events,
               SUM(CASE WHEN d.bowling_pressure=1 THEN d.total_runs_proxy ELSE 0 END) AS pressure_runs_proxy,
               SUM(CASE WHEN d.bowling_pressure=1 THEN d.legal ELSE 0 END) AS pressure_legal_balls,
               SUM(CASE WHEN d.bowling_pressure=1 THEN d.credited_wicket ELSE 0 END) AS pressure_credited_wickets,
               SUM(CASE WHEN d.bowling_pressure=1 AND d.legal=1 AND d.team_dot=1 THEN 1 ELSE 0 END) AS pressure_dots,
               COUNT(DISTINCT CASE WHEN lower(m.venue_country)='india' THEN CAST(d.match_id AS TEXT) || ':' || CAST(d.innings AS TEXT) END) AS india_innings,
               SUM(CASE WHEN lower(m.venue_country)='india' THEN d.legal ELSE 0 END) AS india_legal_balls,
               SUM(CASE WHEN lower(m.venue_country)='india' THEN d.total_runs_proxy ELSE 0 END) AS india_runs_proxy,
               SUM(CASE WHEN lower(m.venue_country)='india' THEN d.credited_wicket ELSE 0 END) AS india_credited_wickets,
               SUM(CASE WHEN lower(m.venue_country)='india' AND d.bowling_pressure=1 THEN d.legal ELSE 0 END) AS india_pressure_legal_balls,
               SUM(CASE WHEN lower(m.venue_country)='india' AND d.bowling_pressure=1 THEN d.total_runs_proxy ELSE 0 END) AS india_pressure_runs_proxy,
               SUM(CASE WHEN lower(m.venue_country)='india' AND d.bowling_pressure=1 THEN d.credited_wicket ELSE 0 END) AS india_pressure_credited_wickets,
               SUM(CASE WHEN lower(m.venue_country)='india' AND d.bowling_pressure=1 AND d.legal=1 AND d.team_dot=1 THEN 1 ELSE 0 END) AS india_pressure_dots,
               SUM(CASE WHEN d.bowling_pressure=0 AND d.state_known=1 AND d.innings=2 THEN d.total_runs_proxy ELSE 0 END) AS ordinary_chase_runs_proxy,
               SUM(CASE WHEN d.bowling_pressure=0 AND d.state_known=1 AND d.innings=2 THEN d.legal ELSE 0 END) AS ordinary_chase_legal_balls
        FROM deliveries d JOIN matches m ON m.match_id=d.match_id
        WHERE {' AND '.join(f'({c})' for c in clauses)}
        GROUP BY d.bowler_id
        ORDER BY credited_wickets DESC, runs_proxy
        """,
        tuple(params),
    )
    for row in rows:
        row["source_player"] = row.get("player")
        row["player"] = player_display_name(row.get("player_id"), row.get("player"))
    return rows


def source_bowler_stats(filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Aggregate independent raw-CSV bowling records for the selected cohort."""
    where, params = match_filter(filters, "m")
    return query(
        f"""
        SELECT s.player_id, MAX(s.source_name) AS source_name,
               COUNT(DISTINCT s.match_id) AS matches,
               COUNT(DISTINCT CAST(s.match_id AS TEXT) || ':' || CAST(s.innings AS TEXT)) AS innings,
               SUM(s.runs_proxy) AS runs_proxy, SUM(s.legal_balls) AS legal_balls,
               SUM(s.wicket_events) AS wicket_events,
               SUM(s.credited_wickets) AS credited_wickets,
               (SELECT COUNT(DISTINCT n.source_name) FROM source_player_names n
                WHERE n.role='bowler' AND n.player_id=s.player_id) AS source_name_variants,
               (SELECT GROUP_CONCAT(n.source_name, ' / ') FROM source_player_names n
                WHERE n.role='bowler' AND n.player_id=s.player_id) AS source_names
        FROM source_bowler_records s JOIN matches m ON m.match_id=s.match_id
        WHERE {where}
        GROUP BY s.player_id
        ORDER BY credited_wickets DESC, s.player_id
        """,
        tuple(params),
    )


def bowler_profile(
    filters: dict[str, Any],
    player_id: int,
    venue_id: str | None = None,
) -> list[dict[str, Any]]:
    where, params = delivery_filter(
        filters, "d", "m", pressure_column="bowling_pressure"
    )
    clauses = [where, "d.innings IN (1,2)", "d.bowler_id=?"]
    params.append(player_id)
    if venue_id is not None:
        clauses.append("m.venue_id=?")
        params.append(venue_id)
    rows = query(
        f"""
        SELECT d.*, m.match_date, m.match_format, m.season, m.venue_id,
               m.venue_country, m.result
        FROM deliveries d JOIN matches m ON m.match_id=d.match_id
        WHERE {' AND '.join(f'({c})' for c in clauses)}
        ORDER BY m.match_date, d.match_id, d.innings, d.seq
        """,
        tuple(params),
    )
    return apply_player_display_names(rows)


def match_list(filters: dict[str, Any]) -> list[dict[str, Any]]:
    where, params = summary_filter(filters, "s", "m")
    return query(
        f"""
        SELECT m.match_id, m.match_date, m.match_format, m.season, m.comp_id,
               c.comp_name, m.venue_id, m.venue_country, m.home_team, m.away_team,
               m.result, m.win_team_id, m.chase_success, m.revised_target,
               s.batting_team, s.total_runs_proxy AS chase_runs_proxy, s.target,
               s.target_source, s.known_legal_balls, s.pressure_legal_balls,
               s.unknown_legality_events, s.wicket_events
        FROM innings_summary s
        JOIN matches m ON m.match_id=s.match_id
        LEFT JOIN competitions c ON c.comp_id=m.comp_id
        WHERE s.innings=2 AND {where}
        ORDER BY m.match_date DESC, m.match_id DESC
        """,
        tuple(params),
    )


def match_innings(filters: dict[str, Any], match_id: int) -> list[dict[str, Any]]:
    where, params = match_filter(filters, "m")
    return query(
        f"""
        SELECT s.*, m.match_date, m.match_format, m.season, m.venue_id,
               m.venue_country, m.home_team, m.away_team, m.result
        FROM innings_summary s JOIN matches m ON m.match_id=s.match_id
        WHERE s.match_id=? AND {where}
        ORDER BY s.innings
        """,
        (match_id, *params),
    )


def match_deliveries(match_id: int) -> list[dict[str, Any]]:
    """Return both innings of a selected match for score progression and scorecards."""
    rows = query(
        """SELECT d.*, m.home_team_id, m.home_team, m.away_team_id, m.away_team,
                  m.match_date, m.match_format, m.season, m.result
           FROM deliveries d JOIN matches m ON m.match_id=d.match_id
           WHERE d.match_id=? AND d.innings IN (1,2)
           ORDER BY d.innings, d.seq""",
        (match_id,),
    )
    return rows


def chase_events(match_id: int) -> list[dict[str, Any]]:
    rows = query(
        """SELECT seq, over_no, over_ball_num, innings_ball_num, striker_name, bowler_name,
                  score_before, target,
                  CASE WHEN target IS NULL THEN NULL ELSE MAX(target-score_before, 0) END AS runs_required,
                  balls_remaining, wickets_lost, rrr, current_rpo,
                  state_known, pressure, bowling_pressure, runs, extras2_runs, total_runs_proxy, extras_type,
                  legal, unknown_legality, is_wicket, credited_wicket, dismissal_type, match_id
           FROM chase_states WHERE match_id=? ORDER BY seq""",
        (match_id,),
    )
    return apply_player_display_names(rows)


def venue_innings(filters: dict[str, Any]) -> list[dict[str, Any]]:
    where, params = summary_filter(filters, "s", "m")
    return query(
        f"""
        SELECT s.*, m.match_date, m.match_format, m.season, m.venue_id,
               m.venue_country, m.win_team_id, m.chase_success,
               m.batting_first_team_id, m.chasing_team_id
        FROM innings_summary s JOIN matches m ON m.match_id=s.match_id
        WHERE s.innings IN (1,2) AND {where}
        ORDER BY m.venue_country, m.venue_id, m.match_date
        """,
        tuple(params),
    )


def venue_state_aggregates(filters: dict[str, Any]) -> list[dict[str, Any]]:
    where, params = match_filter(filters, "m")
    return query(
        f"""
        SELECT m.venue_id, m.venue_country, m.match_format,
               SUM(CASE WHEN cs.pressure=1 THEN cs.runs ELSE 0 END) AS batter_pressure_runs,
               SUM(CASE WHEN cs.pressure=1 THEN cs.faced_ball ELSE 0 END) AS batter_pressure_balls,
               SUM(CASE WHEN cs.pressure=0 THEN cs.runs ELSE 0 END) AS batter_ordinary_runs,
               SUM(CASE WHEN cs.pressure=0 THEN cs.faced_ball ELSE 0 END) AS batter_ordinary_balls,
               SUM(CASE WHEN cs.bowling_pressure=1 THEN cs.total_runs_proxy ELSE 0 END) AS bowling_pressure_runs_proxy,
               SUM(CASE WHEN cs.bowling_pressure=1 THEN cs.legal ELSE 0 END) AS bowling_pressure_legal_balls,
               SUM(CASE WHEN cs.bowling_pressure=1 THEN cs.credited_wicket ELSE 0 END) AS bowling_pressure_credited_wickets,
               SUM(CASE WHEN cs.bowling_pressure=1 THEN cs.team_dot ELSE 0 END) AS bowling_pressure_dots
        FROM chase_states cs JOIN matches m ON m.match_id=cs.match_id
        WHERE {where} AND cs.state_known=1
        GROUP BY m.venue_id, m.venue_country, m.match_format
        """,
        tuple(params),
    )


def scenario_cells(filters: dict[str, Any]) -> list[dict[str, Any]]:
    where, params = match_filter(filters, "m")
    return query(
        f"""
        WITH cell_matches AS (
            SELECT DISTINCT cs.match_id,
                   CASE
                     WHEN cs.rrr < 8 THEN 'Low'
                     WHEN cs.rrr <= 12 THEN 'Medium'
                     WHEN cs.rrr <= 15 THEN 'High'
                     ELSE 'Extreme'
                   END AS rrr_band,
                   CASE
                     WHEN cs.balls_remaining <= 6 THEN '1–6'
                     WHEN cs.balls_remaining <= 12 THEN '7–12'
                     WHEN cs.balls_remaining <= 18 THEN '13–18'
                     WHEN cs.balls_remaining <= 30 THEN '19–30'
                     WHEN cs.balls_remaining <= 60 THEN '31–60'
                     ELSE '61+'
                   END AS balls_band,
                   cs.wickets_lost,
                   m.chase_success
            FROM chase_states cs JOIN matches m ON m.match_id=cs.match_id
            WHERE {where} AND cs.state_known=1 AND cs.legal=1
              AND cs.rrr IS NOT NULL AND cs.target IS NOT NULL
              AND cs.score_before < cs.target AND m.chase_success IS NOT NULL
        )
        SELECT rrr_band, balls_band, wickets_lost,
               COUNT(*) AS chase_matches,
               SUM(chase_success) AS chase_wins,
               ROUND(100.0 * SUM(chase_success) / NULLIF(COUNT(*),0), 2) AS win_rate
        FROM cell_matches
        GROUP BY rrr_band, balls_band, wickets_lost
        """,
        tuple(params),
    )


def reconciliation(filters: dict[str, Any]) -> list[dict[str, Any]]:
    where, params = match_filter(filters, "m")
    return query(
        f"""
        SELECT w.match_id, m.match_date, m.match_format, m.season, m.venue_id,
               m.venue_country, m.home_team, m.away_team, m.result,
               i.pressure_legal_balls AS app_pressure_legal_balls,
               i.pressure_delivery_rows AS app_pressure_event_rows,
               w.workbook_pressure_count,
               w.workbook_high_extreme_count,
               w.workbook_target,
               i.target AS app_target,
               i.target_source,
               i.scheduled_balls,
               i.schedule_source,
               i.unknown_legality_events,
               i.unknown_rrr_states,
               CASE WHEN w.workbook_pressure_count IS NULL THEN 'No workbook count'
                    WHEN i.pressure_legal_balls = w.workbook_pressure_count THEN 'Match'
                    ELSE 'Different'
               END AS pressure_count_status
        FROM workbook_pressure w
        LEFT JOIN innings_summary i ON i.match_id=w.match_id AND i.innings=2
        LEFT JOIN matches m ON m.match_id=w.match_id
        WHERE {where}
        ORDER BY CASE WHEN pressure_count_status='Different' THEN 0 ELSE 1 END,
                 m.match_date DESC, w.match_id
        """,
        tuple(params),
    )


def export_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()
