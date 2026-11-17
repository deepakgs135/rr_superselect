"""Independent raw-source validation for the Indian death-over bowling report."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = APP_DIR.parent / "Raw_Data"
OUTPUT_DIR = APP_DIR / "data" / "pressure_report"
VALIDATION_PATH = OUTPUT_DIR / "death_bowling_validation.json"

FORMATS = {"T20", "T20I"}
LEGAL = {"none", "byes", "legbyes"}
ILLEGAL = {"wide", "overstep"}
UNKNOWN = {"", "other", "penalty"}
CREDITED = {"caught", "bowled", "lbw", "stump", "hit wicket"}
UNKNOWN_NAMES = {"", "unknown", "unknown player", "unknown bowler", "n/a", "na"}
ACTIVE_SEASON = "2026"
USER_EXCLUDED_PLAYERS = {
    2382: "Jamie Overton",
    4641: "Lungi Ngidi",
    6628: "Gerald Coetzee",
}
WEIGHTS = {
    "adjusted_economy": 0.30,
    "ranking_dot_pct": 0.25,
    "adjusted_wickets_per_100": 0.20,
    "ranking_boundary_pct": 0.15,
    "ranking_singles_twos_pct": 0.10,
}
RATE_FIELDS = (
    "economy",
    "dot_pct",
    "wickets_per_100",
    "boundary_pct",
    "singles_twos_pct",
)
COUNT_FIELDS = (
    "delivery_rows",
    "legal_balls",
    "bowler_runs",
    "dot_balls",
    "credited_wickets",
    "boundary_events",
    "singles_twos",
    "wide_rows",
    "no_ball_rows",
)


def _read(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def _integer(value: Any, default: int = 0) -> int:
    try:
        value = str(value or "").strip()
        return int(float(value)) if value else default
    except (TypeError, ValueError):
        return default


def _normalized(value: Any) -> str:
    return str(value or "").strip().casefold()


def _truth(value: Any) -> bool:
    return _normalized(value) in {"true", "1", "yes"}


def _blank_metrics() -> dict[str, int]:
    return {key: 0 for key in COUNT_FIELDS}


def _raw_delivery(metrics: dict[str, int], row: dict[str, str], kind: str) -> None:
    runs = _integer(row.get("runs"))
    legal = kind in LEGAL
    team_runs = runs + int(kind in {"wide", "overstep", "byes", "legbyes"})
    metrics["delivery_rows"] += 1
    metrics["legal_balls"] += int(legal)
    metrics["bowler_runs"] += runs + int(kind in {"wide", "overstep"})
    metrics["wide_rows"] += int(kind == "wide")
    metrics["no_ball_rows"] += int(kind == "overstep")
    metrics["dot_balls"] += int(legal and team_runs == 0)
    metrics["singles_twos"] += int(legal and team_runs in {1, 2})
    metrics["boundary_events"] += int(_truth(row.get("is_four"))) + int(_truth(row.get("is_six")))
    metrics["credited_wickets"] += int(
        _truth(row.get("is_wicket")) and _normalized(row.get("dismissal_type")) in CREDITED
    )


def _rates(metrics: dict[str, int]) -> dict[str, float | None]:
    balls = metrics["legal_balls"]
    if not balls:
        return {key: None for key in RATE_FIELDS}
    return {
        "economy": round(metrics["bowler_runs"] * 6 / balls, 4),
        "dot_pct": round(metrics["dot_balls"] * 100 / balls, 4),
        "wickets_per_100": round(metrics["credited_wickets"] * 100 / balls, 4),
        "boundary_pct": round(metrics["boundary_events"] * 100 / balls, 4),
        "singles_twos_pct": round(metrics["singles_twos"] * 100 / balls, 4),
    }


def _same(actual: Any, expected: Any) -> bool:
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return abs(float(actual) - float(expected)) <= 0.00011
    return actual == expected


def validate_death_bowling_report(report: dict[str, Any]) -> dict[str, Any]:
    """Rebuild cohort aggregates and ranks independently, then compare with report."""
    comps = {
        _integer(row.get("comp_id"), -1): row
        for row in _read(RAW_DIR / "competitions.csv")
    }
    matches: dict[int, dict[str, str]] = {}
    for row in _read(RAW_DIR / "matches.csv"):
        competition = comps.get(_integer(row.get("comp_id"), -1), {})
        matches[_integer(row.get("match_id"), -1)] = {
            "format": str(competition.get("match_format", "")).upper().strip(),
            "season": str(competition.get("season", "")).strip(),
            "country": str(row.get("venue_country", "")).strip(),
            "date": str(row.get("match_date", "")).strip(),
        }

    totals = {
        "raw_delivery_rows": 0,
        "raw_batter_runs_sum": 0,
        "raw_legal_balls_all_deliveries": 0,
        "raw_india_death_rows": 0,
        "usable_india_death_rows": 0,
        "unknown_legality_rows_in_cohort": 0,
        "death_rows_after_unknown_state_excluded": 0,
    }
    names_by_id: dict[int, set[str]] = defaultdict(set)
    active_2026: set[int] = set()
    career: dict[int, dict[str, Any]] = {}
    innings_rows: dict[tuple[int, int, int], dict[str, Any]] = {}
    unknown_innings: set[tuple[int, int]] = set()
    last_sequence: dict[tuple[int, int], tuple[int, int, int]] = {}
    ordering_inversions = 0

    for source_row in _read(RAW_DIR / "ball_by_ball.csv"):
        totals["raw_delivery_rows"] += 1
        kind = _normalized(source_row.get("extras_type"))
        totals["raw_batter_runs_sum"] += _integer(source_row.get("runs"))
        totals["raw_legal_balls_all_deliveries"] += int(kind in LEGAL)
        player_id = _integer(source_row.get("bowler_id"), -1)
        player_name = str(source_row.get("bowler_name") or "").strip()
        if player_id > 0 and player_name:
            names_by_id[player_id].add(player_name)

        match_id = _integer(source_row.get("match_id"), -1)
        innings = _integer(source_row.get("innings"), -1)
        match = matches.get(match_id, {})
        if match.get("format") not in FORMATS or innings not in {1, 2}:
            continue
        if match.get("season") == "2026" and player_id > 0:
            active_2026.add(player_id)

        key = (match_id, innings)
        sequence = (
            _integer(source_row.get("overid"), -1),
            _integer(source_row.get("over_ball_num"), -1),
            _integer(source_row.get("innings_ball_num"), -1),
        )
        if key in last_sequence and sequence < last_sequence[key]:
            ordering_inversions += 1
        last_sequence[key] = sequence

        in_scope = match.get("country", "").casefold() == "india" and 16 <= sequence[0] <= 20
        if in_scope:
            totals["raw_india_death_rows"] += 1

        if kind in UNKNOWN or kind not in LEGAL | ILLEGAL:
            unknown_innings.add(key)
            if in_scope:
                totals["unknown_legality_rows_in_cohort"] += 1
            continue
        if key in unknown_innings:
            if in_scope:
                totals["death_rows_after_unknown_state_excluded"] += 1
            continue
        if player_id <= 0 or not in_scope:
            continue

        totals["usable_india_death_rows"] += 1
        player = career.setdefault(
            player_id,
            {"player_id": player_id, "player": player_name or f"Player {player_id}", **_blank_metrics(), "matches": set(), "innings": set()},
        )
        _raw_delivery(player, source_row, kind)
        player["matches"].add(match_id)
        player["innings"].add((match_id, innings))

        appearance = innings_rows.setdefault(
            (player_id, match_id, innings),
            {**_blank_metrics(), "date": match.get("date", "")},
        )
        _raw_delivery(appearance, source_row, kind)

    invalid_ids = {
        player_id
        for player_id, names in names_by_id.items()
        if len(names) != 1 or any(name.casefold() in UNKNOWN_NAMES for name in names)
    }
    totals["excluded_unknown_or_multi_name_ids"] = len(invalid_ids.intersection(career))

    by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for (player_id, match_id, innings), stats in innings_rows.items():
        if player_id in invalid_ids or stats["legal_balls"] == 0:
            continue
        by_player[player_id].append(
            {**stats, "match_id": match_id, "innings": innings}
        )

    rows: list[dict[str, Any]] = []
    for player_id, all_stats in career.items():
        if player_id in invalid_ids:
            continue
        latest_ten = sorted(
            by_player.get(player_id, []),
            key=lambda item: (item["date"], item["match_id"], item["innings"]),
            reverse=True,
        )[:10]
        recent = _blank_metrics()
        for appearance in latest_ten:
            for field in COUNT_FIELDS:
                recent[field] += appearance[field]
        recent_rates = _rates(recent)
        career_rates = _rates(all_stats)
        row = {
            "player_id": player_id,
            "player": all_stats["player"],
            "death_matches": len(all_stats["matches"]),
            "death_innings": len(all_stats["innings"]),
            "legal_balls": all_stats["legal_balls"],
            "bowler_runs": all_stats["bowler_runs"],
            "credited_wickets": all_stats["credited_wickets"],
            "economy": career_rates["economy"],
            "dot_balls": all_stats["dot_balls"],
            "dot_pct": career_rates["dot_pct"],
            "wickets_per_100": career_rates["wickets_per_100"],
            "boundary_events": all_stats["boundary_events"],
            "boundary_pct": career_rates["boundary_pct"],
            "singles_twos": all_stats["singles_twos"],
            "singles_twos_pct": career_rates["singles_twos_pct"],
            "active_2026_all_venues": player_id in active_2026,
            "ranking_innings": len(latest_ten),
            "ranking_first_date": latest_ten[-1]["date"] if latest_ten else None,
            "ranking_latest_date": latest_ten[0]["date"] if latest_ten else None,
            "ranking_balls": recent["legal_balls"],
            "ranking_runs": recent["bowler_runs"],
            "ranking_dot_balls": recent["dot_balls"],
            "ranking_wickets": recent["credited_wickets"],
            "ranking_boundary_events": recent["boundary_events"],
            "ranking_singles_twos": recent["singles_twos"],
            "ranking_economy": recent_rates["economy"],
            "ranking_dot_pct": recent_rates["dot_pct"],
            "ranking_wickets_per_100": recent_rates["wickets_per_100"],
            "ranking_boundary_pct": recent_rates["boundary_pct"],
            "ranking_singles_twos_pct": recent_rates["singles_twos_pct"],
        }
        row["eligible"] = (
            row["ranking_balls"] >= 30
            and row["ranking_wickets"] >= 3
            and row["active_2026_all_venues"]
            and row["ranking_innings"] >= 10
            and str(row.get("ranking_latest_date") or "").startswith(ACTIVE_SEASON)
            and player_id not in USER_EXCLUDED_PLAYERS
        )
        row["user_excluded"] = player_id in USER_EXCLUDED_PLAYERS
        rows.append(row)

    eligible = [row for row in rows if row["eligible"]]
    all_balls = sum(row["ranking_balls"] for row in eligible)
    all_runs = sum(row["ranking_runs"] for row in eligible)
    all_wickets = sum(row["ranking_wickets"] for row in eligible)
    baseline_economy = all_runs * 6 / all_balls if all_balls else 0
    baseline_wicket_rate = all_wickets * 100 / all_balls if all_balls else 0
    for row in eligible:
        balls = row["ranking_balls"]
        row["adjusted_economy"] = round(
            (row["ranking_economy"] * balls + baseline_economy * 60) / (balls + 60), 4
        )
        row["adjusted_wickets_per_100"] = round(
            (row["ranking_wickets_per_100"] * balls + baseline_wicket_rate * 60) / (balls + 60), 4
        )

    def add_percentile(field: str, higher_is_better: bool) -> None:
        ordered = sorted(
            eligible,
            key=lambda row: (-row[field] if higher_is_better else row[field], row["player"], row["player_id"]),
        )
        start = 0
        while start < len(ordered):
            end = start + 1
            while end < len(ordered) and ordered[end][field] == ordered[start][field]:
                end += 1
            avg_rank = ((start + 1) + end) / 2
            score = 100.0 if len(ordered) == 1 else 100 * (len(ordered) - avg_rank) / (len(ordered) - 1)
            for item in ordered[start:end]:
                item[f"{field}_percentile"] = round(score, 4)
            start = end

    for field, direction in (
        ("adjusted_economy", False),
        ("ranking_dot_pct", True),
        ("adjusted_wickets_per_100", True),
        ("ranking_boundary_pct", False),
        ("ranking_singles_twos_pct", False),
    ):
        add_percentile(field, direction)
    for row in eligible:
        row["composite_score"] = round(
            sum(row[f"{field}_percentile"] * weight for field, weight in WEIGHTS.items()), 4
        )
    eligible.sort(
        key=lambda row: (
            -row["composite_score"],
            -row["ranking_balls"],
            -row["ranking_wickets"],
            row["player"].casefold(),
            row["player_id"],
        )
    )
    for rank, row in enumerate(eligible, 1):
        row["rank"] = rank

    checks: list[dict[str, Any]] = []

    def check(label: str, computed: Any, reference: Any) -> None:
        checks.append({"check": label, "computed": computed, "reference": reference, "passed": _same(computed, reference)})

    reported_counts = report.get("counts", {})
    for field, value in totals.items():
        check(f"Raw recount: {field}", value, reported_counts.get(field))
    check("Raw-source ordering is monotonic by innings delivery", ordering_inversions, 0)
    check("Eligible player count", len(eligible), reported_counts.get("eligible_players"))
    check(
        "Players excluded at user request",
        sum(1 for row in rows if row["user_excluded"]),
        reported_counts.get("excluded_by_user_request"),
    )
    check(
        "Players without a 2026 Indian death-over appearance",
        sum(1 for row in rows if not str(row.get("ranking_latest_date") or "").startswith(ACTIVE_SEASON)),
        reported_counts.get("players_without_latest_india_death_appearance_in_2026"),
    )
    check(
        "User-excluded player IDs and names",
        sorted((int(item["player_id"]), item["player"]) for item in report.get("user_exclusions", [])),
        sorted(USER_EXCLUDED_PLAYERS.items()),
    )
    check("Recent-window legal balls", all_balls, reported_counts.get("eligible_cohort_legal_balls"))
    check("Recent-window credited wickets", all_wickets, reported_counts.get("eligible_cohort_credited_wickets"))

    reported_eligible = {int(row["player_id"]): row for row in report.get("eligible_rankings", [])}
    check("Eligible player IDs and raw ranking rows", sorted(row["player_id"] for row in eligible), sorted(reported_eligible))
    fields_to_compare = (
        "ranking_innings", "ranking_balls", "ranking_runs", "ranking_dot_balls", "ranking_wickets",
        "ranking_boundary_events", "ranking_singles_twos", "ranking_first_date", "ranking_latest_date",
        "ranking_economy", "ranking_dot_pct",
        "ranking_wickets_per_100", "ranking_boundary_pct", "ranking_singles_twos_pct",
        "adjusted_economy", "adjusted_wickets_per_100", "adjusted_economy_percentile",
        "ranking_dot_pct_percentile", "adjusted_wickets_per_100_percentile",
        "ranking_boundary_pct_percentile", "ranking_singles_twos_pct_percentile", "composite_score",
    )
    for rank, raw_row in enumerate(eligible, 1):
        saved = reported_eligible.get(raw_row["player_id"], {})
        check(f"Player {raw_row['player_id']} unique-ID row and rank", saved.get("rank"), rank)
        for field in fields_to_compare:
            check(f"Player {raw_row['player_id']} {field}", saved.get(field), raw_row.get(field))
    check(
        "Top 10 player IDs in order",
        [row["player_id"] for row in eligible[:10]],
        [int(row["player_id"]) for row in report.get("top_ten", [])],
    )

    passed_count = sum(bool(item["passed"]) for item in checks)
    return {
        "method": "Independent one-pass recount of raw ball_by_ball.csv joined directly to matches.csv and competitions.csv. This validator does not import the report builder or reuse its delivery-aggregation functions.",
        "source_files": report.get("source_files", {}),
        "checks_passed": passed_count,
        "checks_total": len(checks),
        "all_passed": passed_count == len(checks),
        "raw_totals": totals,
        "eligible_players": len(eligible),
        "top_ten": [
            {key: row[key] for key in ("rank", "player", "player_id", "ranking_innings", "ranking_balls", "ranking_runs", "ranking_economy", "ranking_dot_balls", "ranking_dot_pct", "ranking_wickets", "ranking_wickets_per_100", "ranking_boundary_events", "ranking_boundary_pct", "ranking_singles_twos", "ranking_singles_twos_pct", "composite_score")}
            for row in eligible[:10]
        ],
        "checks": checks,
    }


def save_validation(validation: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    VALIDATION_PATH.write_text(json.dumps(validation, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    report_path = OUTPUT_DIR / "death_bowling_report.json"
    current_report = json.loads(report_path.read_text(encoding="utf-8"))
    validation = validate_death_bowling_report(current_report)
    save_validation(validation)
    print(json.dumps({"all_passed": validation["all_passed"], "checks_passed": validation["checks_passed"], "checks_total": validation["checks_total"], "validation": str(VALIDATION_PATH)}, indent=2))
