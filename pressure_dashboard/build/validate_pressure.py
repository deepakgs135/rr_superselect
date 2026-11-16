"""Independently recount pressure states and sample player rows from the raw CSVs."""

from __future__ import annotations

import csv
import json
import math
import random
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = APP_DIR.parent
RAW_DIR = PROJECT_DIR / "Raw_Data"
DB_PATH = APP_DIR / "data" / "processed" / "analytics.sqlite3"
OUTPUT_DIR = APP_DIR / "data" / "pressure_report"
REPORT_PATH = OUTPUT_DIR / "pressure_report.json"
VALIDATION_PATH = OUTPUT_DIR / "pressure_validation.json"
VALIDATION_CSV = OUTPUT_DIR / "pressure_validation_log.csv"
EXCEPTIONS_CSV = OUTPUT_DIR / "pressure_reproduction_exceptions.csv"
SAMPLE_SEED = 20261115


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value or "").strip()))
    except (TypeError, ValueError):
        return default


def norm(value: Any) -> str:
    return str(value or "").strip().casefold()


def yes(value: Any) -> bool:
    return norm(value) in {"1", "true", "yes"}


def is_legal(kind: Any) -> bool:
    return norm(kind) in {"none", "byes", "legbyes"}


def is_unknown(kind: Any) -> bool:
    return norm(kind) not in {"none", "byes", "legbyes", "wide", "overstep"}


def team_run(row: dict[str, Any]) -> int:
    return as_int(row.get("runs")) + int(norm(row.get("extras_type")) in {"wide", "overstep", "byes", "legbyes"})


def bowler_run(row: dict[str, Any]) -> int:
    return as_int(row.get("runs")) + int(norm(row.get("extras_type")) in {"wide", "overstep"})


def batter_dismissal(row: dict[str, Any]) -> bool:
    excluded = {"retire out", "retired out", "retire hurt", "retired hurt", "obstracting the field", "obstructing the field"}
    return yes(row.get("is_wicket")) and norm(row.get("dismissal_type")) not in excluded


def credited(row: dict[str, Any]) -> bool:
    return yes(row.get("is_wicket")) and norm(row.get("dismissal_type")) in {"caught", "bowled", "lbw", "stump", "hit wicket"}


def load_raw() -> tuple[dict[int, dict[str, Any]], dict[tuple[int, int], list[dict[str, Any]]], dict[int, set[str]], dict[str, int]]:
    with (RAW_DIR / "competitions.csv").open(encoding="utf-8-sig", newline="") as file:
        competitions = {as_int(row.get("comp_id")): row for row in csv.DictReader(file)}
    matches = {}
    with (RAW_DIR / "matches.csv").open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            comp = competitions.get(as_int(row.get("comp_id")), {})
            matches[as_int(row.get("match_id"), -1)] = {
                **row,
                "match_format": str(comp.get("match_format") or "").strip(),
                "season": str(comp.get("season") or "").strip(),
            }
    groups: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    names: dict[int, set[str]] = defaultdict(set)
    totals = {"delivery_rows": 0, "runs": 0, "legal_balls": 0, "unknown_legality_rows": 0}
    with (RAW_DIR / "ball_by_ball.csv").open(encoding="utf-8-sig", newline="") as file:
        for order, row in enumerate(csv.DictReader(file)):
            totals["delivery_rows"] += 1
            totals["runs"] += as_int(row.get("runs"))
            totals["legal_balls"] += int(is_legal(row.get("extras_type")))
            totals["unknown_legality_rows"] += int(is_unknown(row.get("extras_type")))
            row["_source_order"] = order
            groups[(as_int(row.get("match_id"), -1), as_int(row.get("innings"), -1))].append(row)
            for id_field, name_field in (("striker_id", "striker_name"), ("non_striker_id", "non_striker_name"), ("bowler_id", "bowler_name")):
                player_id = as_int(row.get(id_field), -1)
                name = str(row.get(name_field) or "").strip()
                if player_id > 0:
                    names[player_id].add(name)
    for rows in groups.values():
        rows.sort(key=lambda row: (as_int(row.get("overid"), -1), as_int(row.get("innings_ball_num"), -1), as_int(row.get("over_ball_num"), -1), as_int(row.get("_source_order"), -1)))
    return matches, groups, names, totals


def player_aggregates_from_raw(
    matches: dict[int, dict[str, Any]],
    groups: dict[tuple[int, int], list[dict[str, Any]]],
    valid_ids: set[int],
) -> tuple[dict[tuple[int, str, str], dict[str, int]], dict[tuple[int, int, int], dict[str, Any]], list[dict[str, Any]]]:
    first_totals = {
        match_id: sum(team_run(row) for row in rows)
        for (match_id, innings_no), rows in groups.items()
        if innings_no == 1 and matches.get(match_id, {}).get("match_format") == "T20"
    }
    aggregates: dict[tuple[int, str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    expected_states: dict[tuple[int, int, int], dict[str, Any]] = {}
    state_row_counts: dict[str, dict[str, Any]] = {
        name: {"delivery_rows": 0, "matches": set(), "decided_chases": set(), "legal_balls": 0}
        for name in ("Batting pressure", "Ordinary batting chase", "Bowling pressure", "Ordinary bowling chase")
    }
    for match_id, meta in matches.items():
        if meta.get("match_format") != "T20":
            continue
        rows = groups.get((match_id, 2), [])
        revised = str(meta.get("revised_target") or "").strip()
        target = as_int(revised) if revised else first_totals.get(match_id, 0) + 1 if (match_id, 1) in groups else None
        score = legal_balls = wickets = seq = 0
        known = target is not None
        for row in rows:
            seq += 1
            kind = norm(row.get("extras_type"))
            unknown = is_unknown(kind)
            legal = is_legal(kind)
            if unknown:
                known = False
            remaining = 120 - legal_balls if known else None
            needed = int(target) - score if known and target is not None else None
            row_known = bool(known and remaining is not None and remaining > 0)
            rrr = needed * 6.0 / remaining if row_known and needed is not None else None
            crr = score * 6.0 / legal_balls if row_known and legal_balls > 0 else None
            active_chase = bool(row_known and needed is not None and needed > 0)
            bat_pressure = bool(active_chase and remaining is not None and remaining <= 30 and wickets >= 3 and rrr is not None and rrr >= 15)
            bowl_pressure = bool(active_chase and remaining is not None and remaining <= 30 and wickets <= 2 and rrr is not None and rrr >= 9 and crr is not None and crr >= 11)
            key = (match_id, 2, seq)
            expected_states[key] = {"state_known": int(row_known), "pressure": int(bat_pressure), "bowling_pressure": int(bowl_pressure)}
            if active_chase:
                bat_state = "Batting pressure" if bat_pressure else "Ordinary batting chase"
                bowl_state = "Bowling pressure" if bowl_pressure else "Ordinary bowling chase"
                decided = as_int(meta.get("win_team_id"), 0) > 0 and not any(
                    token in norm(meta.get("result"))
                    for token in ("tie", "no result", "abandoned", "cancelled")
                )
                for state_name in (bat_state, bowl_state):
                    state_count = state_row_counts[state_name]
                    state_count["delivery_rows"] += 1
                    state_count["matches"].add(match_id)
                    if decided:
                        state_count["decided_chases"].add(match_id)
                    state_count["legal_balls"] += int(legal)
                batter_id = as_int(row.get("striker_id"), -1)
                if batter_id in valid_ids:
                    agg = aggregates[(batter_id, "Batter", bat_state)]
                    agg["deliveries"] += 1
                    agg["runs"] += as_int(row.get("runs"))
                    agg["balls"] += int(kind != "wide" and not unknown)
                    agg["dismissals"] += int(batter_dismissal(row) and as_int(row.get("dismissed_player_id"), -1) == batter_id)
                    agg["fours"] += int(yes(row.get("is_four")))
                    agg["sixes"] += int(yes(row.get("is_six")))
                    agg["dots"] += int(kind != "wide" and not unknown and as_int(row.get("runs")) == 0)
                    agg[f"match:{match_id}"] = 1
                    agg[f"innings:{match_id}:2"] = 1
                dismissed_id = as_int(row.get("dismissed_player_id"), -1)
                if batter_dismissal(row) and dismissed_id > 0 and dismissed_id != batter_id and dismissed_id in valid_ids:
                    agg = aggregates[(dismissed_id, "Batter", bat_state)]
                    agg["dismissals"] += 1
                    agg[f"match:{match_id}"] = 1
                    agg[f"innings:{match_id}:2"] = 1
                bowler_id = as_int(row.get("bowler_id"), -1)
                if bowler_id in valid_ids:
                    agg = aggregates[(bowler_id, "Bowler", bowl_state)]
                    charge = bowler_run(row)
                    agg["deliveries"] += 1
                    agg["runs"] += charge
                    agg["legal_balls"] += int(legal)
                    agg["credited_wickets"] += int(credited(row))
                    agg["dots"] += int(legal and charge == 0)
                    agg["boundaries"] += int(yes(row.get("is_four"))) + int(yes(row.get("is_six")))
                    agg[f"match:{match_id}"] = 1
                    agg[f"innings:{match_id}:2"] = 1
            score += team_run(row)
            legal_balls += int(legal)
            wickets += int(batter_dismissal(row))
            if unknown:
                known = False
    for values in aggregates.values():
        values["matches"] = sum(value for key, value in values.items() if key.startswith("match:"))
        values["innings"] = sum(value for key, value in values.items() if key.startswith("innings:"))
    finalized_state_counts = []
    for name, values in state_row_counts.items():
        role = "Batter" if "batting" in name.casefold() else "Bowler"
        finalized_state_counts.append(
            {
                "state": name,
                "delivery_rows": values["delivery_rows"],
                "matches": len(values["matches"]),
                "decided_chases": len(values["decided_chases"]),
                "legal_balls": values["legal_balls"],
                "players": len({key[0] for key in aggregates if key[1] == role and key[2] == name}),
            }
        )
    return aggregates, expected_states, finalized_state_counts


def recent_form_from_raw(
    matches: dict[int, dict[str, Any]],
    groups: dict[tuple[int, int], list[dict[str, Any]]],
    valid_ids: set[int],
) -> tuple[dict[tuple[str, int], dict[str, Any]], dict[str, set[int]]]:
    """Recompute 2026 activity and each player's latest ten known T20 chase innings."""
    first_totals = {
        match_id: sum(team_run(row) for row in rows)
        for (match_id, innings_no), rows in groups.items()
        if innings_no == 1 and matches.get(match_id, {}).get("match_format") == "T20"
    }
    active = {"Batter": set(), "Bowler": set()}
    raw_innings: dict[tuple[str, int, int], dict[str, Any]] = {}

    for match_id, meta in matches.items():
        if meta.get("match_format") != "T20":
            continue
        rows1 = groups.get((match_id, 1), [])
        rows2 = groups.get((match_id, 2), [])
        if meta.get("season") == "2026":
            for row in rows1 + rows2:
                for field in ("striker_id", "non_striker_id"):
                    player_id = as_int(row.get(field), -1)
                    if player_id in valid_ids:
                        active["Batter"].add(player_id)
                bowler_id = as_int(row.get("bowler_id"), -1)
                if bowler_id in valid_ids:
                    active["Bowler"].add(bowler_id)

        revised = str(meta.get("revised_target") or "").strip()
        target = as_int(revised) if revised else first_totals.get(match_id, 0) + 1 if (match_id, 1) in groups else None
        if target is None:
            continue
        score = legal_balls = 0
        state_known = True
        for row in rows2:
            kind = norm(row.get("extras_type"))
            if is_unknown(kind):
                state_known = False
            remaining = 120 - legal_balls if state_known else None
            known_state = bool(state_known and remaining is not None and remaining > 0)
            if known_state:
                batter_id = as_int(row.get("striker_id"), -1)
                if batter_id in valid_ids:
                    item = raw_innings.setdefault(
                        ("Batter", batter_id, match_id),
                        {"match_id": match_id, "runs": 0, "balls": 0, "dismissals": 0, "wickets": 0, "date": str(meta.get("match_date") or "")},
                    )
                    item["runs"] += as_int(row.get("runs"))
                    item["balls"] += int(kind != "wide" and not is_unknown(kind))
                    item["dismissals"] += int(
                        batter_dismissal(row) and as_int(row.get("dismissed_player_id"), -1) == batter_id
                    )
                dismissed_id = as_int(row.get("dismissed_player_id"), -1)
                striker_id = as_int(row.get("striker_id"), -1)
                if batter_dismissal(row) and dismissed_id > 0 and dismissed_id != striker_id and dismissed_id in valid_ids:
                    item = raw_innings.setdefault(
                        ("Batter", dismissed_id, match_id),
                        {"match_id": match_id, "runs": 0, "balls": 0, "dismissals": 0, "wickets": 0, "date": str(meta.get("match_date") or "")},
                    )
                    item["dismissals"] += 1
                bowler_id = as_int(row.get("bowler_id"), -1)
                if bowler_id in valid_ids:
                    item = raw_innings.setdefault(
                        ("Bowler", bowler_id, match_id),
                        {"match_id": match_id, "runs": 0, "balls": 0, "dismissals": 0, "wickets": 0, "date": str(meta.get("match_date") or "")},
                    )
                    item["runs"] += bowler_run(row)
                    item["balls"] += int(is_legal(kind))
                    item["wickets"] += int(credited(row))
            score += team_run(row)
            legal_balls += int(is_legal(kind))
            if is_unknown(kind):
                state_known = False

    by_player: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for (role, player_id, _match_id), item in raw_innings.items():
        by_player[(role, player_id)].append(item)
    summary: dict[tuple[str, int], dict[str, Any]] = {}
    for key, innings_rows in by_player.items():
        recent = sorted(innings_rows, key=lambda row: (row["date"], row.get("match_id", 0)), reverse=True)[:10]
        runs = sum(int(row["runs"]) for row in recent)
        balls = sum(int(row["balls"]) for row in recent)
        dismissals = sum(int(row["dismissals"]) for row in recent)
        wickets = sum(int(row["wickets"]) for row in recent)
        summary[key] = {
            "recent_innings": len(recent),
            "recent_runs": runs,
            "recent_balls": balls,
            "recent_dismissals": dismissals,
            "recent_wickets": wickets,
            "recent_sr": round(100 * runs / balls, 4) if balls else None,
            "recent_average": round(runs / dismissals, 2) if dismissals >= 3 else "Not reported",
            "recent_economy": round(6 * runs / balls, 4) if balls else None,
            "recent_wicket_rate_per_6": round(6 * wickets / balls, 4) if balls else None,
            "recent_latest_date": recent[0]["date"] if recent else "",
        }
    return summary, active


def db_aggregates(conn: sqlite3.Connection) -> dict[tuple[int, str, str], dict[str, int]]:
    conn.row_factory = sqlite3.Row
    sql = """
    SELECT player_id, role, state, SUM(deliveries) AS deliveries, SUM(runs) AS runs,
           SUM(balls) AS balls, SUM(dismissals) AS dismissals, SUM(fours) AS fours,
           SUM(sixes) AS sixes, SUM(dots) AS dots, SUM(legal_balls) AS legal_balls,
           SUM(credited_wickets) AS credited_wickets, SUM(boundaries) AS boundaries,
           COUNT(DISTINCT match_id) AS matches, COUNT(DISTINCT match_id || ':' || innings) AS innings
    FROM (
      SELECT d.striker_id AS player_id, 'Batter' AS role,
             CASE WHEN d.pressure=1 THEN 'Batting pressure' ELSE 'Ordinary batting chase' END AS state,
             1 AS deliveries, d.runs AS runs, d.faced_ball AS balls,
             CASE WHEN d.is_wicket=1 AND d.dismissed_player_id=d.striker_id
                       AND lower(trim(coalesce(d.dismissal_type,''))) NOT IN
                           ('retire out','retired out','retire hurt','retired hurt','obstracting the field','obstructing the field')
                  THEN 1 ELSE 0 END AS dismissals,
             d.is_four AS fours, d.is_six AS sixes, d.batter_dot AS dots,
             0 AS legal_balls, 0 AS credited_wickets, 0 AS boundaries,
             d.match_id, d.innings
      FROM deliveries d JOIN matches m ON m.match_id=d.match_id
      WHERE m.match_format='T20' AND d.innings=2 AND d.state_known=1
        AND d.balls_remaining>0 AND d.target-d.score_before>0 AND d.striker_id>0
      UNION ALL
      SELECT d.dismissed_player_id AS player_id, 'Batter' AS role,
             CASE WHEN d.pressure=1 THEN 'Batting pressure' ELSE 'Ordinary batting chase' END AS state,
             0 AS deliveries, 0 AS runs, 0 AS balls, 1 AS dismissals,
             0 AS fours, 0 AS sixes, 0 AS dots,
             0 AS legal_balls, 0 AS credited_wickets, 0 AS boundaries,
             d.match_id, d.innings
      FROM deliveries d JOIN matches m ON m.match_id=d.match_id
      WHERE m.match_format='T20' AND d.innings=2 AND d.state_known=1
        AND d.balls_remaining>0 AND d.target-d.score_before>0
        AND d.is_wicket=1 AND d.dismissed_player_id>0 AND d.dismissed_player_id<>d.striker_id
        AND lower(trim(coalesce(d.dismissal_type,''))) NOT IN
            ('retire out','retired out','retire hurt','retired hurt','obstracting the field','obstructing the field')
      UNION ALL
      SELECT d.bowler_id AS player_id, 'Bowler' AS role,
             CASE WHEN d.bowling_pressure=1 THEN 'Bowling pressure' ELSE 'Ordinary bowling chase' END AS state,
             1 AS deliveries, d.bowler_runs_proxy AS runs, 0 AS balls,
             0 AS dismissals, 0 AS fours, 0 AS sixes,
             CASE WHEN d.legal=1 AND d.bowler_runs_proxy=0 THEN 1 ELSE 0 END AS dots,
             d.legal AS legal_balls, d.credited_wicket AS credited_wickets,
             d.is_four+d.is_six AS boundaries, d.match_id, d.innings
      FROM deliveries d JOIN matches m ON m.match_id=d.match_id
      WHERE m.match_format='T20' AND d.innings=2 AND d.state_known=1
        AND d.balls_remaining>0 AND d.target-d.score_before>0 AND d.bowler_id>0
    ) events
    GROUP BY player_id, role, state
    """
    result = {}
    for row in conn.execute(sql):
        values = dict(row)
        key = (int(values["player_id"]), str(values["role"]), str(values["state"]))
        result[key] = {field: int(values.get(field) or 0) for field in (
            "deliveries", "runs", "balls", "dismissals", "fours", "sixes", "dots", "legal_balls", "credited_wickets", "boundaries", "matches", "innings"
        )}
    return result


def close(actual: Any, expected: Any) -> bool:
    if isinstance(expected, str):
        return actual == expected
    if expected is None:
        return actual is None
    if isinstance(expected, bool):
        return bool(actual) is expected
    try:
        return math.isclose(float(actual), float(expected), rel_tol=0, abs_tol=0.0051)
    except (TypeError, ValueError):
        return False


def shrink(raw: float | None, sample: int, baseline: float | None, prior: int) -> float | None:
    if baseline is None:
        return round(raw, 4) if raw is not None else None
    value = baseline if raw is None else raw
    return round((value * sample + baseline * prior) / (sample + prior), 4) if sample + prior else round(baseline, 4)


def percentile_map(keys: list[tuple[int, str, str]], values: dict[tuple[int, str, str], float], higher: bool, names: dict[tuple[int, str, str], str]) -> dict[tuple[int, str, str], float]:
    ordered = sorted(keys, key=lambda key: ((-values[key]) if higher else values[key], names.get(key, "")))
    result: dict[tuple[int, str, str], float] = {}
    start = 0
    while start < len(ordered):
        value = values[ordered[start]]
        end = start + 1
        while end < len(ordered) and values[ordered[end]] == value:
            end += 1
        average_rank = ((start + 1) + end) / 2
        score = 100.0 if len(ordered) == 1 else 100.0 * (len(ordered) - average_rank) / (len(ordered) - 1)
        for key in ordered[start:end]:
            result[key] = round(score, 4)
        start = end
    return result


def compare_sample(
    raw: dict[tuple[int, str, str], dict[str, int]],
    db: dict[tuple[int, str, str], dict[str, int]],
    report: dict[str, Any],
    recent: dict[tuple[str, int], dict[str, Any]],
    active: dict[str, set[int]],
    state_counts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    randomizer = random.Random(SAMPLE_SEED)
    sampled: list[tuple[int, str, str]] = []
    for role in ("Batter", "Bowler"):
        candidates = sorted(key for key in raw if key[1] == role)
        sampled.extend(randomizer.sample(candidates, min(5, len(candidates))))

    report_rows: dict[tuple[int, str, str], dict[str, Any]] = {}
    for role, table_name in (("Batter", "batter_table"), ("Bowler", "bowler_table")):
        for row in report.get(table_name, []):
            key = (int(row["player_id"]), role, str(row["state"]))
            report_rows[key] = row

    totals: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for key, item in raw.items():
        role, state = key[1], key[2]
        totals[(role, state)]["runs"] += int(item.get("runs", 0))
        totals[(role, state)]["balls"] += int(item.get("balls" if role == "Batter" else "legal_balls", 0))
        totals[(role, state)]["dismissals"] += int(item.get("dismissals", 0))
        totals[(role, state)]["wickets"] += int(item.get("credited_wickets", 0))

    expected_metrics: dict[tuple[int, str, str], dict[str, Any]] = {}
    for key, item in raw.items():
        role, state = key[1], key[2]
        base = totals[(role, state)]
        balls = int(item.get("balls" if role == "Batter" else "legal_balls", 0))
        runs = int(item.get("runs", 0))
        if role == "Batter":
            sr = round(100 * runs / balls, 4) if balls else None
            avg = round(runs / int(item["dismissals"]), 4) if int(item["dismissals"]) >= 3 else "Not reported"
            baseline_sr = 100 * base["runs"] / base["balls"] if base["balls"] else None
            baseline_avg = base["runs"] / base["dismissals"] if base["dismissals"] else None
            adjusted_sr = shrink(sr, balls, baseline_sr, 60)
            internal_avg = round(runs / int(item["dismissals"]), 4) if int(item["dismissals"]) else None
            adjusted_avg_internal = shrink(internal_avg, int(item["dismissals"]), baseline_avg, 3)
            adjusted_avg = adjusted_avg_internal if int(item["dismissals"]) >= 3 else "Not reported"
            boundary_share = round(100 * (int(item["fours"]) + int(item["sixes"])) / balls, 4) if balls else None
            dot_share = round(100 * int(item["dots"]) / balls, 4) if balls else None
            values = {
                "strike_rate": sr,
                "adjusted_strike_rate": adjusted_sr,
                "average": avg,
                "adjusted_average": adjusted_avg,
                "_adjusted_average_for_composite": adjusted_avg_internal,
                "boundary_events": int(item["fours"]) + int(item["sixes"]),
                "boundary_share": boundary_share,
                "dot_share": dot_share,
            }
        else:
            economy = round(6 * runs / balls, 4) if balls else None
            wicket_rate = round(6 * int(item["credited_wickets"]) / balls, 4) if balls else None
            baseline_economy = 6 * base["runs"] / base["balls"] if base["balls"] else None
            baseline_wicket_rate = 6 * base["wickets"] / base["balls"] if base["balls"] else None
            values = {
                "economy": economy,
                "adjusted_economy": shrink(economy, balls, baseline_economy, 60),
                "credited_wickets": int(item["credited_wickets"]),
                "balls_per_wicket": round(balls / int(item["credited_wickets"]), 4) if int(item["credited_wickets"]) else "Not defined",
                "wicket_rate_per_6": wicket_rate,
                "adjusted_wicket_rate_per_6": shrink(wicket_rate, balls, baseline_wicket_rate, 60),
                "dot_share": round(100 * int(item["dots"]) / balls, 4) if balls else None,
                "boundaries_conceded": int(item["boundaries"]),
            }
        expected_metrics[key] = values

    expected_eligible: set[tuple[int, str, str]] = set()
    recent_counts: dict[tuple[int, str, str], int] = {}
    for key, item in raw.items():
        role = key[1]
        sample_balls = int(item.get("balls" if role == "Batter" else "legal_balls", 0))
        form = recent.get((role, key[0]), {})
        recent_counts[key] = int(form.get("recent_innings", 0))
        eligible = sample_balls >= 30 and key[0] in active.get(role, set()) and recent_counts[key] >= 10
        if role == "Bowler":
            eligible = eligible and int(item.get("credited_wickets", 0)) >= 3
        if eligible:
            expected_eligible.add(key)

    composite_scores: dict[tuple[int, str, str], float] = {}
    expected_ranks: dict[tuple[int, str, str], int | None] = {}
    decided_by_state = {str(row["state"]): int(row.get("decided_chases") or 0) for row in state_counts}
    for role in ("Batter", "Bowler"):
        states = {key[2] for key in raw if key[1] == role}
        for state in states:
            keys = [key for key in expected_eligible if key[1] == role and key[2] == state]
            names = {key: str(report_rows.get(key, {}).get("player") or key[0]) for key in keys}
            if len(keys) < 10 or decided_by_state.get(state, 0) < 20:
                expected_ranks.update({key: None for key in keys})
                continue
            if role == "Batter":
                p_sr = percentile_map(keys, {key: float(expected_metrics[key]["adjusted_strike_rate"]) for key in keys}, True, names)
                p_avg = percentile_map(keys, {key: float(expected_metrics[key]["_adjusted_average_for_composite"]) for key in keys}, True, names)
                p_bound = percentile_map(keys, {key: float(expected_metrics[key]["boundary_share"]) for key in keys}, True, names)
                for key in keys:
                    composite_scores[key] = round(0.5 * p_sr[key] + 0.3 * p_avg[key] + 0.2 * p_bound[key], 4)
            else:
                p_econ = percentile_map(keys, {key: float(expected_metrics[key]["adjusted_economy"]) for key in keys}, False, names)
                p_wickets = percentile_map(keys, {key: float(expected_metrics[key]["adjusted_wicket_rate_per_6"]) for key in keys}, True, names)
                p_dots = percentile_map(keys, {key: float(expected_metrics[key]["dot_share"]) for key in keys}, True, names)
                for key in keys:
                    composite_scores[key] = round(0.4 * p_econ[key] + 0.4 * p_wickets[key] + 0.2 * p_dots[key], 4)
            sample_field = "balls" if role == "Batter" else "legal_balls"
            ordered = sorted(keys, key=lambda key: (-composite_scores[key], -int(raw[key].get(sample_field, 0)), names[key]))
            expected_ranks.update({key: index for index, key in enumerate(ordered, 1)})

    checks = []
    db_fields = ("deliveries", "runs", "balls", "dismissals", "fours", "sixes", "dots", "legal_balls", "credited_wickets", "boundaries", "matches", "innings")
    for key in sampled:
        role, player_id, state = key[1], key[0], key[2]
        raw_row = raw[key]
        db_row = db.get(key, {})
        report_row = report_rows.get(key)
        mismatches: dict[str, Any] = {}
        for field in db_fields:
            expected = int(raw_row.get(field, 0))
            actual = int(db_row.get(field, 0))
            if expected != actual:
                mismatches[f"database.{field}"] = {"raw": expected, "database": actual}
        if report_row is None:
            mismatches["report_row"] = {"raw": "present", "report": "missing"}
        else:
            report_core = {
                "deliveries": int(raw_row.get("deliveries", 0)),
                "runs": int(raw_row.get("runs", 0)),
                "sample_balls": int(raw_row.get("balls" if role == "Batter" else "legal_balls", 0)),
                "dismissals": int(raw_row.get("dismissals", 0)),
                "fours": int(raw_row.get("fours", 0)),
                "sixes": int(raw_row.get("sixes", 0)),
                "dots": int(raw_row.get("dots", 0)),
                "matches": int(raw_row.get("matches", 0)),
                "innings": int(raw_row.get("innings", 0)),
            }
            if role == "Bowler":
                report_core.update({"credited_wickets": int(raw_row.get("credited_wickets", 0)), "boundaries_conceded": int(raw_row.get("boundaries", 0))})
            for field, expected in report_core.items():
                if not close(report_row.get(field), expected):
                    mismatches[f"report.{field}"] = {"raw": expected, "report": report_row.get(field)}
            for field, expected in expected_metrics[key].items():
                if field.startswith("_"):
                    continue
                if not close(report_row.get(field), expected):
                    mismatches[f"report.{field}"] = {"raw_recomputed": expected, "report": report_row.get(field)}
            form = recent.get((role, player_id), {})
            for field in (
                "recent_innings", "recent_runs", "recent_balls", "recent_dismissals", "recent_wickets",
                "recent_sr", "recent_average", "recent_economy", "recent_wicket_rate_per_6", "recent_latest_date",
            ):
                report_field = {
                    "recent_sr": "recent_strike_rate",
                }.get(field, field)
                if role == "Batter" and field in {"recent_wickets", "recent_economy", "recent_wicket_rate_per_6"}:
                    continue
                if role == "Bowler" and field in {"recent_dismissals", "recent_sr", "recent_average"}:
                    continue
                expected = form.get(field)
                if not close(report_row.get(report_field), expected):
                    mismatches[f"report.{report_field}"] = {"raw_recomputed": expected, "report": report_row.get(report_field)}
            expected_active = player_id in active.get(role, set())
            expected_recent_status = "Eligible form" if int(form.get("recent_innings", 0)) >= 10 else "Review sample"
            expected_sample_status = "Eligible sample" if int(report_core["sample_balls"]) >= 30 else "Review sample"
            expected_wicket_status = "Eligible for ranking" if int(raw_row.get("credited_wickets", 0)) >= 3 else "Review sample"
            if not close(report_row.get("active_2026_all_venues"), expected_active):
                mismatches["report.active_2026_all_venues"] = {"raw_recomputed": expected_active, "report": report_row.get("active_2026_all_venues")}
            if not close(report_row.get("recent_form_status"), expected_recent_status):
                mismatches["report.recent_form_status"] = {"raw_recomputed": expected_recent_status, "report": report_row.get("recent_form_status")}
            if not close(report_row.get("sample_status"), expected_sample_status):
                mismatches["report.sample_status"] = {"raw_recomputed": expected_sample_status, "report": report_row.get("sample_status")}
            if role == "Bowler" and not close(report_row.get("wicket_rate_status"), expected_wicket_status):
                mismatches["report.wicket_rate_status"] = {"raw_recomputed": expected_wicket_status, "report": report_row.get("wicket_rate_status")}
            expected_is_eligible = key in expected_eligible
            if not close(report_row.get("ranking_eligible"), expected_is_eligible):
                mismatches["report.ranking_eligible"] = {"raw_recomputed": expected_is_eligible, "report": report_row.get("ranking_eligible")}
            expected_score = composite_scores.get(key)
            expected_rank = expected_ranks.get(key)
            if not close(report_row.get("composite_score"), expected_score):
                mismatches["report.composite_score"] = {"raw_recomputed": expected_score, "report": report_row.get("composite_score")}
            if not close(report_row.get("rank"), expected_rank):
                mismatches["report.rank"] = {"raw_recomputed": expected_rank, "report": report_row.get("rank")}
        checks.append({"player_id": player_id, "role": role, "state": state, "status": "PASS" if not mismatches else "FAIL", "mismatches": mismatches})
    return checks


def main() -> None:
    matches, groups, names, raw_totals = load_raw()
    invalid_ids = {
        player_id for player_id, variants in names.items()
        if len(variants) != 1 or any(
            not name.strip()
            or name.casefold() in {"unknown", "unknown player", "unknown batter", "unknown bowler"}
            for name in variants
        )
    }
    valid_ids = {player_id for player_id in names if player_id > 0 and player_id not in invalid_ids}
    raw_aggregates, expected_states, state_row_counts = player_aggregates_from_raw(matches, groups, valid_ids)
    raw_recent, raw_active = recent_form_from_raw(matches, groups, valid_ids)
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else {}
    conn = sqlite3.connect(str(DB_PATH))
    db_totals = conn.execute("SELECT COUNT(*), COALESCE(SUM(runs),0), COALESCE(SUM(legal),0) FROM deliveries").fetchone()
    raw_total_runs = conn.execute("SELECT COALESCE(SUM(runs),0) FROM deliveries").fetchone()[0]
    db_states = {
        (int(row[0]), int(row[1]), int(row[2])): {"state_known": int(row[3] or 0), "pressure": int(row[4] or 0), "bowling_pressure": int(row[5] or 0)}
        for row in conn.execute("SELECT match_id,innings,seq,state_known,pressure,bowling_pressure FROM deliveries WHERE innings=2")
    }
    flag_mismatches = []
    for key, expected in expected_states.items():
        actual = db_states.get(key)
        if actual != expected:
            flag_mismatches.append({"match_id": key[0], "innings": key[1], "seq": key[2], "expected": expected, "database": actual})
    db_player_rows = db_aggregates(conn)
    random_rows = compare_sample(raw_aggregates, db_player_rows, report, raw_recent, raw_active, state_row_counts)
    conn.close()

    report_state_map = {str(row.get("state")): row for row in report.get("state_table", [])}
    state_count_mismatches = []
    for expected in state_row_counts:
        actual = report_state_map.get(str(expected["state"]))
        differences = {
            field: {"raw_recomputed": expected[field], "report": actual.get(field) if actual else None}
            for field in ("delivery_rows", "matches", "decided_chases", "legal_balls", "players")
            if actual is None or int(actual.get(field) or 0) != int(expected[field])
        }
        if differences:
            state_count_mismatches.append({"state": expected["state"], "mismatches": differences})

    margin_checks = []
    margin_rows_checked = 0
    for match_id, meta in matches.items():
        if meta.get("match_format") != "T20":
            continue
        result = str(meta.get("result") or "")
        match = re.search(r"won\s+by\s+(\d+)\s+runs?", result, flags=re.IGNORECASE)
        if not match or (match_id, 1) not in groups or (match_id, 2) not in groups:
            continue
        margin_rows_checked += 1
        first_score = sum(team_run(row) for row in groups[(match_id, 1)])
        second_score = sum(team_run(row) for row in groups[(match_id, 2)])
        reported = int(match.group(1))
        computed = first_score - second_score
        if computed != reported:
            margin_checks.append({"match_id": match_id, "reported_run_margin": reported, "computed_margin": computed, "first_innings_count_formula": first_score, "second_innings_count_formula": second_score, "status": "Not reproducible from the supplied count-based extras formula"})

    row_count_match = int(db_totals[0]) == raw_totals["delivery_rows"]
    run_total_match = int(db_totals[1]) == raw_totals["runs"] == int(raw_total_runs)
    legal_total_match = int(db_totals[2]) == raw_totals["legal_balls"]
    flag_match = not flag_mismatches
    sample_match = len(random_rows) >= 10 and all(row["status"] == "PASS" for row in random_rows)
    log = [
        {"check": "Raw delivery row count equals database", "raw": raw_totals["delivery_rows"], "processed": int(db_totals[0]), "status": "PASS" if row_count_match else "FAIL"},
        {"check": "Raw runs column sum equals database runs sum", "raw": raw_totals["runs"], "processed": int(db_totals[1]), "status": "PASS" if run_total_match else "FAIL"},
        {"check": "Known legal-ball count equals database legal count", "raw": raw_totals["legal_balls"], "processed": int(db_totals[2]), "status": "PASS" if legal_total_match else "FAIL"},
        {"check": "Independent pressure flags equal database flags", "raw": len(expected_states), "processed": len(expected_states)-len(flag_mismatches), "status": "PASS" if flag_match else "FAIL"},
        {"check": "State table totals equal independent raw recount", "raw": len(state_row_counts), "processed": len(state_row_counts)-len(state_count_mismatches), "status": "PASS" if not state_count_mismatches else "FAIL"},
        {"check": "Random player-state aggregates match raw recomputation", "raw": len(random_rows), "processed": sum(row["status"] == "PASS" for row in random_rows), "status": "PASS" if sample_match else "FAIL"},
        {"check": "Source run-margin reconciliation", "raw": margin_rows_checked, "processed": margin_rows_checked-len(margin_checks), "status": "SOURCE LIMITATION" if margin_checks else "PASS"},
        {"check": "Unknown or multi-name IDs excluded", "raw": len(invalid_ids), "processed": len(valid_ids), "status": "PASS"},
    ]
    validation = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "Separate raw-CSV recount; does not import the dashboard pressure-state functions.",
        "random_seed": SAMPLE_SEED,
        "random_player_rows_requested": 10,
        "random_player_rows_checked": len(random_rows),
        "raw_totals": raw_totals,
        "database_totals": {"delivery_rows": int(db_totals[0]), "runs": int(db_totals[1]), "known_legal_balls": int(db_totals[2])},
        "pressure_delivery_recount": state_row_counts,
        "state_count_mismatches": state_count_mismatches,
        "pressure_flag_rows_checked": len(expected_states),
        "pressure_flag_mismatches": len(flag_mismatches),
        "flag_mismatch_examples": flag_mismatches[:100],
        "random_player_row_checks": random_rows,
        "source_run_margin_reconciliation": {"checked_rows": margin_rows_checked, "mismatched_rows": len(margin_checks), "unreproducible_rows": margin_checks},
        "excluded_player_ids": {"count": len(invalid_ids), "ids": sorted(invalid_ids)},
        "validation_log": log,
        "overall_status": (
            "FAIL"
            if not (row_count_match and run_total_match and legal_total_match and flag_match and not state_count_mismatches and sample_match)
            else "PASS WITH SOURCE LIMITATIONS" if margin_checks else "PASS"
        ),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    VALIDATION_PATH.write_text(json.dumps(validation, indent=2), encoding="utf-8")
    with VALIDATION_CSV.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=["check", "raw", "processed", "status"])
        writer.writeheader()
        writer.writerows(log)
    exception_rows = [
        {"kind": "state_flag", **row} for row in flag_mismatches
    ] + [
        {"kind": "state_count", **row} for row in state_count_mismatches
    ] + [
        {"kind": "random_player_state", "player_id": row["player_id"], "role": row["role"], "state": row["state"], "mismatches": json.dumps(row["mismatches"], ensure_ascii=False)}
        for row in random_rows if row["status"] != "PASS"
    ] + [
        {"kind": "result_run_margin", **row} for row in margin_checks
    ]
    columns = sorted({key for row in exception_rows for key in row}) if exception_rows else ["kind", "status"]
    with EXCEPTIONS_CSV.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(exception_rows)
    if REPORT_PATH.exists():
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        report["validation"] = validation
        REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"overall_status": validation["overall_status"], "checks": log, "random_rows": len(random_rows), "state_flag_mismatches": len(flag_mismatches), "run_margin_mismatches": len(margin_checks), "output": str(VALIDATION_PATH)}, indent=2))


if __name__ == "__main__":
    main()
