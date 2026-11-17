"""Build an India death-over bowling ranking directly from the raw CSV sources."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = APP_DIR.parent
RAW_DIR = PROJECT_DIR / "Raw_Data"
OUTPUT_DIR = APP_DIR / "data" / "pressure_report"
REPORT_PATH = OUTPUT_DIR / "death_bowling_report.json"
CSV_PATH = OUTPUT_DIR / "india_death_bowler_rankings.csv"

FORMATS = {"T20", "T20I"}
DEATH_OVERS = range(16, 21)
LEGAL_TYPES = {"none", "byes", "legbyes"}
ILLEGAL_TYPES = {"wide", "overstep"}
UNKNOWN_TYPES = {"", "other", "penalty"}
CREDITED_WICKETS = {"caught", "bowled", "lbw", "stump", "hit wicket"}
UNKNOWN_NAMES = {"", "unknown", "unknown player", "unknown bowler", "n/a", "na"}
ACTIVE_SEASON = "2026"
MIN_LATEST_INDIA_DEATH_YEAR = ACTIVE_SEASON
MIN_DEATH_BALLS = 30
MIN_DEATH_INNINGS = 10
MIN_CREDITED_WICKETS = 3
MIN_RANKED_PLAYERS = 10
USER_EXCLUDED_PLAYERS = {
    2382: "Jamie Overton",
    4641: "Lungi Ngidi",
    6628: "Gerald Coetzee",
}
ECONOMY_PRIOR_BALLS = 60
WICKET_RATE_PRIOR_BALLS = 60
WEIGHTS = {
    "adjusted_economy": 0.30,
    "ranking_dot_pct": 0.25,
    "adjusted_wickets_per_100": 0.20,
    "ranking_boundary_pct": 0.15,
    "ranking_singles_twos_pct": 0.10,
}

SUGGESTED_BOWLERS = [
    "Jasprit Bumrah",
    "Arshdeep Singh",
    "Sunil Narine",
    "Rashid Khan",
    "Axar Patel",
    "Hardik Pandya",
    "Varun Chakravarthy",
    "Kuldeep Yadav",
    "T Natarajan",
    "Harshit Rana",
]


def _int(value: Any, default: int = 0) -> int:
    try:
        text = str(value or "").strip()
        return int(float(text)) if text else default
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return _text(value).casefold()


def _bool(value: Any) -> bool:
    return _norm(value) in {"true", "1", "yes"}


def _name_key(value: Any) -> str:
    return " ".join("".join(char for char in _norm(value) if char.isalnum() or char.isspace()).split())


def _read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def _empty_metrics() -> dict[str, Any]:
    return {
        "delivery_rows": 0,
        "legal_balls": 0,
        "bowler_runs": 0,
        "dot_balls": 0,
        "credited_wickets": 0,
        "boundary_events": 0,
        "singles_twos": 0,
        "wide_rows": 0,
        "no_ball_rows": 0,
    }


def _add_delivery(target: dict[str, Any], row: dict[str, str], kind: str) -> None:
    runs = _int(row.get("runs"))
    legal = kind in LEGAL_TYPES
    wide = kind == "wide"
    no_ball = kind == "overstep"
    team_runs = runs + int(kind in {"wide", "overstep", "byes", "legbyes"})
    target["delivery_rows"] += 1
    target["bowler_runs"] += runs + int(wide or no_ball)
    target["wide_rows"] += int(wide)
    target["no_ball_rows"] += int(no_ball)
    target["legal_balls"] += int(legal)
    target["dot_balls"] += int(legal and team_runs == 0)
    target["singles_twos"] += int(legal and team_runs in {1, 2})
    target["boundary_events"] += int(_bool(row.get("is_four"))) + int(_bool(row.get("is_six")))
    target["credited_wickets"] += int(
        _bool(row.get("is_wicket")) and _norm(row.get("dismissal_type")) in CREDITED_WICKETS
    )


def _metric_values(item: dict[str, Any]) -> dict[str, Any]:
    balls = int(item["legal_balls"])
    return {
        "economy": round(int(item["bowler_runs"]) * 6 / balls, 4) if balls else None,
        "dot_pct": round(int(item["dot_balls"]) * 100 / balls, 4) if balls else None,
        "wickets_per_100": round(int(item["credited_wickets"]) * 100 / balls, 4) if balls else None,
        "boundary_pct": round(int(item["boundary_events"]) * 100 / balls, 4) if balls else None,
        "singles_twos_pct": round(int(item["singles_twos"]) * 100 / balls, 4) if balls else None,
    }


def _assign_percentiles(rows: list[dict[str, Any]], field: str, higher_is_better: bool) -> None:
    ordered = sorted(
        rows,
        key=lambda row: (
            -float(row[field]) if higher_is_better else float(row[field]),
            row["player"],
            int(row["player_id"]),
        ),
    )
    start = 0
    while start < len(ordered):
        value = ordered[start][field]
        end = start + 1
        while end < len(ordered) and ordered[end][field] == value:
            end += 1
        average_rank = ((start + 1) + end) / 2
        percentile = 100.0 if len(ordered) == 1 else 100 * (len(ordered) - average_rank) / (len(ordered) - 1)
        for row in ordered[start:end]:
            row[f"{field}_percentile"] = round(percentile, 4)
        start = end


def build_death_bowling_report() -> dict[str, Any]:
    competitions = {
        _int(row.get("comp_id"), -1): row
        for row in _read_csv(RAW_DIR / "competitions.csv")
    }
    matches: dict[int, dict[str, Any]] = {}
    for row in _read_csv(RAW_DIR / "matches.csv"):
        comp = competitions.get(_int(row.get("comp_id"), -1), {})
        matches[_int(row.get("match_id"), -1)] = {
            "match_format": _text(comp.get("match_format")).upper(),
            "season": _text(comp.get("season")),
            "venue_country": _text(row.get("venue_country")),
            "match_date": _text(row.get("match_date")),
        }

    names_by_id: dict[int, set[str]] = defaultdict(set)
    active_2026: set[int] = set()
    players: dict[int, dict[str, Any]] = {}
    appearances: dict[tuple[int, int, int], dict[str, Any]] = {}
    row_counts = {
        "raw_delivery_rows": 0,
        "raw_batter_runs_sum": 0,
        "raw_legal_balls_all_deliveries": 0,
        "raw_india_death_rows": 0,
        "usable_india_death_rows": 0,
        "unknown_legality_rows_in_cohort": 0,
        "death_rows_after_unknown_state_excluded": 0,
        "excluded_unknown_or_multi_name_ids": 0,
    }

    unknown_innings: set[tuple[int, int]] = set()
    for row in _read_csv(RAW_DIR / "ball_by_ball.csv"):
        row_counts["raw_delivery_rows"] += 1
        kind = _norm(row.get("extras_type"))
        row_counts["raw_batter_runs_sum"] += _int(row.get("runs"))
        row_counts["raw_legal_balls_all_deliveries"] += int(kind in LEGAL_TYPES)
        player_id = _int(row.get("bowler_id"), -1)
        source_name = _text(row.get("bowler_name"))
        if player_id > 0 and source_name:
            names_by_id[player_id].add(source_name)

        match_id = _int(row.get("match_id"), -1)
        innings = _int(row.get("innings"), -1)
        match = matches.get(match_id, {})
        if match.get("match_format") not in FORMATS or innings not in {1, 2}:
            continue

        if match.get("season") == ACTIVE_SEASON and player_id > 0:
            active_2026.add(player_id)

        india_death_scope = (
            match.get("venue_country", "").casefold() == "india"
            and _int(row.get("overid"), -1) in DEATH_OVERS
        )
        if india_death_scope:
            row_counts["raw_india_death_rows"] += 1

        unknown = kind in UNKNOWN_TYPES or kind not in LEGAL_TYPES | ILLEGAL_TYPES
        innings_key = (match_id, innings)
        if unknown:
            # Unknown legality invalidates the state for the rest of this innings.
            unknown_innings.add(innings_key)
            if india_death_scope:
                row_counts["unknown_legality_rows_in_cohort"] += 1
            continue

        if innings_key in unknown_innings:
            if india_death_scope:
                row_counts["death_rows_after_unknown_state_excluded"] += 1
            continue
        if player_id <= 0 or not india_death_scope:
            continue

        row_counts["usable_india_death_rows"] += 1

        player = players.setdefault(
            player_id,
            {
                "player_id": player_id,
                "player": source_name or f"Player {player_id}",
                "source_player": source_name,
                **_empty_metrics(),
                "match_ids": set(),
                "innings_keys": set(),
            },
        )
        _add_delivery(player, row, kind)
        match_id = _int(row.get("match_id"), -1)
        innings = _int(row.get("innings"), -1)
        player["match_ids"].add(match_id)
        player["innings_keys"].add((match_id, innings))

        appearance = appearances.setdefault(
            (player_id, match_id, innings),
            {
                **_empty_metrics(),
                "match_date": match.get("match_date", ""),
            },
        )
        _add_delivery(appearance, row, kind)

    invalid_ids = {
        player_id
        for player_id, names in names_by_id.items()
        if len(names) != 1 or any(name.casefold() in UNKNOWN_NAMES for name in names)
    }
    row_counts["excluded_unknown_or_multi_name_ids"] = len(
        invalid_ids.intersection(players)
    )

    valid_rows: list[dict[str, Any]] = []
    recent_by_id: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for (player_id, match_id, innings), item in appearances.items():
        if player_id in invalid_ids or int(item["legal_balls"]) == 0:
            continue
        recent_by_id[player_id].append(
            {
                **item,
                "match_id": match_id,
                "innings": innings,
            }
        )

    for player_id, item in players.items():
        if player_id in invalid_ids:
            continue
        row = {key: value for key, value in item.items() if key not in {"match_ids", "innings_keys"}}
        row["death_matches"] = len(item["match_ids"])
        row["death_innings"] = len(item["innings_keys"])
        row["death_overs"] = round(int(item["legal_balls"]) / 6, 2)
        row.update(_metric_values(item))
        last_ten = sorted(
            recent_by_id.get(player_id, []),
            key=lambda appearance: (
                appearance.get("match_date", ""),
                int(appearance.get("match_id", -1)),
                int(appearance.get("innings", -1)),
            ),
            reverse=True,
        )[:10]
        recent_totals = _empty_metrics()
        for appearance in last_ten:
            for key in recent_totals:
                recent_totals[key] += int(appearance.get(key) or 0)
        recent_values = _metric_values(recent_totals)
        row.update(
            {
                "active_2026_all_venues": player_id in active_2026,
                "recent_death_innings": len(last_ten),
                "recent_death_balls": int(recent_totals["legal_balls"]),
                "recent_death_economy": recent_values["economy"],
                "recent_death_dot_pct": recent_values["dot_pct"],
                "recent_death_wickets": int(recent_totals["credited_wickets"]),
                "recent_death_wickets_per_100": recent_values["wickets_per_100"],
                "recent_latest_date": last_ten[0].get("match_date") if last_ten else None,
            }
        )
        row["ranking_innings"] = len(last_ten)
        row["ranking_balls"] = int(recent_totals["legal_balls"])
        row["ranking_runs"] = int(recent_totals["bowler_runs"])
        row["ranking_dot_balls"] = int(recent_totals["dot_balls"])
        row["ranking_wickets"] = int(recent_totals["credited_wickets"])
        row["ranking_boundary_events"] = int(recent_totals["boundary_events"])
        row["ranking_singles_twos"] = int(recent_totals["singles_twos"])
        row["ranking_first_date"] = last_ten[-1].get("match_date") if last_ten else None
        row["ranking_latest_date"] = last_ten[0].get("match_date") if last_ten else None
        row["ranking_economy"] = recent_values["economy"]
        row["ranking_dot_pct"] = recent_values["dot_pct"]
        row["ranking_wickets_per_100"] = recent_values["wickets_per_100"]
        row["ranking_boundary_pct"] = recent_values["boundary_pct"]
        row["ranking_singles_twos_pct"] = recent_values["singles_twos_pct"]
        row["sample_status"] = "Eligible sample" if int(row["ranking_balls"]) >= MIN_DEATH_BALLS else "Review sample"
        reasons = []
        if player_id in USER_EXCLUDED_PLAYERS:
            reasons.append("excluded from the final list at the user's request")
        if int(row["ranking_balls"]) < MIN_DEATH_BALLS:
            reasons.append(f"{row['ranking_balls']} legal balls in latest {MIN_DEATH_INNINGS} death innings; {MIN_DEATH_BALLS} required")
        if int(row["ranking_wickets"]) < MIN_CREDITED_WICKETS:
            reasons.append(f"{row['ranking_wickets']} credited wickets in latest {MIN_DEATH_INNINGS} death innings; {MIN_CREDITED_WICKETS} required for wicket-rate ranking")
        if not row["active_2026_all_venues"]:
            reasons.append("no 2026 T20/T20I bowling appearance at any venue")
        if int(row["recent_death_innings"]) < MIN_DEATH_INNINGS:
            reasons.append(f"{row['recent_death_innings']} death-over innings in the cohort; {MIN_DEATH_INNINGS} required")
        if not str(row.get("ranking_latest_date") or "").startswith(MIN_LATEST_INDIA_DEATH_YEAR):
            latest_date = row.get("ranking_latest_date") or "no dated Indian death-over appearance"
            reasons.append(f"latest Indian death-over appearance is {latest_date}; {MIN_LATEST_INDIA_DEATH_YEAR} required")
        row["ranking_eligible"] = not reasons
        row["ranking_reasons"] = "; ".join(reasons)
        row["user_excluded"] = player_id in USER_EXCLUDED_PLAYERS
        row["ranking_status"] = (
            "Excluded by user request" if row["user_excluded"]
            else "Eligible" if not reasons
            else "Review sample"
        )
        row["sample_status"] = "Eligible for ranking" if not reasons else row["ranking_status"]
        valid_rows.append(row)

    eligible = [row for row in valid_rows if row["ranking_eligible"]]
    population_runs = sum(int(row["ranking_runs"]) for row in eligible)
    population_balls = sum(int(row["ranking_balls"]) for row in eligible)
    population_wickets = sum(int(row["ranking_wickets"]) for row in eligible)
    baseline_economy = population_runs * 6 / population_balls if population_balls else None
    baseline_wicket_rate = population_wickets * 100 / population_balls if population_balls else None

    for row in eligible:
        balls = int(row["ranking_balls"])
        row["adjusted_economy"] = round(
            (float(row["ranking_economy"]) * balls + float(baseline_economy or 0) * ECONOMY_PRIOR_BALLS)
            / (balls + ECONOMY_PRIOR_BALLS),
            4,
        )
        row["adjusted_wickets_per_100"] = round(
            (float(row["ranking_wickets_per_100"]) * balls + float(baseline_wicket_rate or 0) * WICKET_RATE_PRIOR_BALLS)
            / (balls + WICKET_RATE_PRIOR_BALLS),
            4,
        )

    component_directions = [
        ("adjusted_economy", False),
        ("ranking_dot_pct", True),
        ("adjusted_wickets_per_100", True),
        ("ranking_boundary_pct", False),
        ("ranking_singles_twos_pct", False),
    ]
    for field, higher_is_better in component_directions:
        _assign_percentiles(eligible, field, higher_is_better)
    for row in eligible:
        row["composite_score"] = round(
            sum(row[f"{field}_percentile"] * weight for field, weight in WEIGHTS.items()),
            4,
        )

    eligible.sort(
        key=lambda row: (
            -float(row["composite_score"]),
            -int(row["legal_balls"]),
            -int(row["credited_wickets"]),
            row["player"].casefold(),
            int(row["player_id"]),
        )
    )
    ranking_published = len(eligible) >= MIN_RANKED_PLAYERS
    for position, row in enumerate(eligible, 1):
        row["rank"] = position if ranking_published else None
        row["ranking_status"] = "Ranked" if ranking_published else "Eligible, list not ranked: fewer than 10 players"
    eligible_ids = {int(row["player_id"]) for row in eligible}
    for row in valid_rows:
        if int(row["player_id"]) not in eligible_ids:
            row["rank"] = None
            row["composite_score"] = None

    valid_rows.sort(
        key=lambda row: (
            row.get("rank") is None,
            row.get("rank") or 999999,
            row["player"].casefold(),
            int(row["player_id"]),
        )
    )
    normalized_names = {_name_key(row["player"]): row for row in valid_rows}
    candidate_audit = []
    for candidate in SUGGESTED_BOWLERS:
        row = normalized_names.get(_name_key(candidate))
        candidate_audit.append(
            {
                "suggested_bowler": candidate,
                "found_in_raw_source": row is not None,
                "player_id": row.get("player_id") if row else None,
                "player": row.get("player") if row else None,
                "rank": row.get("rank") if row else None,
                "ranking_status": row.get("ranking_status") if row else "Not found in raw bowler names",
                "ranking_reasons": row.get("ranking_reasons") if row else "No matching unique source player ID",
                "ranking_innings": row.get("ranking_innings") if row else None,
                "ranking_first_date": row.get("ranking_first_date") if row else None,
                "ranking_latest_date": row.get("ranking_latest_date") if row else None,
                "ranking_balls": row.get("ranking_balls") if row else None,
                "ranking_runs": row.get("ranking_runs") if row else None,
                "ranking_economy": row.get("ranking_economy") if row else None,
                "ranking_dot_balls": row.get("ranking_dot_balls") if row else None,
                "ranking_dot_pct": row.get("ranking_dot_pct") if row else None,
                "ranking_wickets": row.get("ranking_wickets") if row else None,
                "ranking_wickets_per_100": row.get("ranking_wickets_per_100") if row else None,
                "ranking_boundary_events": row.get("ranking_boundary_events") if row else None,
                "ranking_boundary_pct": row.get("ranking_boundary_pct") if row else None,
                "ranking_singles_twos": row.get("ranking_singles_twos") if row else None,
                "ranking_singles_twos_pct": row.get("ranking_singles_twos_pct") if row else None,
                "adjusted_economy": row.get("adjusted_economy") if row else None,
                "adjusted_wickets_per_100": row.get("adjusted_wickets_per_100") if row else None,
                "death_matches": row.get("death_matches") if row else None,
                "death_innings": row.get("death_innings") if row else None,
                "legal_balls": row.get("legal_balls") if row else None,
                "bowler_runs": row.get("bowler_runs") if row else None,
                "economy": row.get("economy") if row else None,
                "dot_balls": row.get("dot_balls") if row else None,
                "dot_pct": row.get("dot_pct") if row else None,
                "credited_wickets": row.get("credited_wickets") if row else None,
                "wickets_per_100": row.get("wickets_per_100") if row else None,
                "boundary_events": row.get("boundary_events") if row else None,
                "boundary_pct": row.get("boundary_pct") if row else None,
                "singles_twos": row.get("singles_twos") if row else None,
                "singles_twos_pct": row.get("singles_twos_pct") if row else None,
                "composite_score": row.get("composite_score") if row else None,
            }
        )

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_files": {name: str(RAW_DIR / name) for name in ("ball_by_ball.csv", "matches.csv", "competitions.csv")},
        "method": "Direct raw CSV aggregation. No processed player-stat table is used for ranking inputs.",
        "scope": "India-hosted T20 and T20I; innings 1 and 2; death overs overid 16-20 only. Ranking uses each bowler's latest 10 eligible Indian death-over innings and requires the latest Indian death-over appearance to be in 2026.",
        "definitions": {
            "legal_ball": "extras_type none, byes, or legbyes; wides and Overstep/no-balls are not legal; other, Penalty, blank and unrecognized types are excluded.",
            "bowler_runs": "Raw runs plus one per wide or Overstep/no-ball delivery; byes and leg-byes are not charged to the bowler.",
            "dot_ball": "A legal death-over ball with zero team runs; byes and leg-byes imputed as one team run per delivery.",
            "credited_wicket": "is_wicket with dismissal_type Caught, Bowled, LBW, Stump, or Hit Wicket.",
            "boundary_concession": "Raw is_four plus is_six events per 100 legal death-over balls.",
            "singles_twos_containment": "Rate of legal death-over balls yielding exactly one or two team runs; lower is better. Byes and leg-byes add one team run for this metric.",
            "economy": "Death-over bowler runs times six divided by death-over legal balls. The ranking uses the latest 10 eligible Indian death-over innings; career Indian death-over figures are shown separately.",
            "wickets_per_100": "Credited death-over wickets times 100 divided by death-over legal balls.",
            "percentile_scoring": "Each latest-10 component is converted to a tie-aware 0-100 percentile across eligible players. Lower economy, boundary rate and singles/twos rate receive higher percentiles.",
            "composite_formula": "30% adjusted economy percentile + 25% dot-ball percentage percentile + 20% adjusted wickets/100 percentile + 15% inverse boundary-concession-rate percentile + 10% inverse singles/twos-rate percentile. Components use the latest 10 Indian death-over innings only.",
            "shrinkage": "For the composite only, latest-10 economy and wickets/100 are blended toward the eligible-player latest-10 death-over baseline using 60 prior legal balls. Career Indian death-over rates are displayed separately.",
            "eligibility": "At least 30 legal death-over balls and at least 3 credited wickets within the latest 10 India death-over cohort innings, at least one 2026 T20/T20I bowling appearance at any venue, 10 eligible India death-over innings, and a latest Indian death-over appearance in 2026. Jamie Overton (2382), Lungi Ngidi (4641), and Gerald Coetzee (6628) are excluded from the final ranking at the user's request. Unknown or multi-name player IDs are excluded. If an unknown-legality delivery occurs in an innings, that delivery and all later deliveries in that innings are excluded.",
            "outcomes": "Match wins, losses, and win contribution are not used.",
        },
        "weights": WEIGHTS,
        "minimums": {
            "death_legal_balls": MIN_DEATH_BALLS,
            "death_innings": MIN_DEATH_INNINGS,
            "credited_wickets": MIN_CREDITED_WICKETS,
            "eligible_players_for_published_ranks": MIN_RANKED_PLAYERS,
            "active_season": ACTIVE_SEASON,
            "latest_india_death_appearance_year": MIN_LATEST_INDIA_DEATH_YEAR,
        },
        "counts": {
            **row_counts,
            "source_bowler_ids": len(names_by_id),
            "eligible_players": len(eligible),
            "excluded_by_user_request": sum(1 for row in valid_rows if row.get("user_excluded")),
            "players_without_latest_india_death_appearance_in_2026": sum(
                1 for row in valid_rows
                if not str(row.get("ranking_latest_date") or "").startswith(MIN_LATEST_INDIA_DEATH_YEAR)
            ),
            "published_top10_count": min(len(eligible), 10),
            "ranking_published": ranking_published,
            "eligible_cohort_legal_balls": population_balls,
            "eligible_cohort_death_overs": round(population_balls / 6, 2),
            "eligible_cohort_credited_wickets": population_wickets,
            "eligible_cohort_baseline_economy": round(baseline_economy, 4) if baseline_economy is not None else None,
            "eligible_cohort_baseline_wickets_per_100": round(baseline_wicket_rate, 4) if baseline_wicket_rate is not None else None,
        },
        "ranking_status": (
            f"Ranked {len(eligible)} eligible bowlers using the requested weighted death-over score."
            if ranking_published
            else f"Only {len(eligible)} eligible bowlers; list without ranks because 10 are required."
        ),
        "top_ten": eligible[:10],
        "eligible_rankings": eligible,
        "player_rows": valid_rows,
        "user_exclusions": [
            {"player_id": player_id, "player": name, "reason": "Excluded at the user's request"}
            for player_id, name in USER_EXCLUDED_PLAYERS.items()
        ],
        "suggested_candidate_audit": candidate_audit,
        "excluded_player_ids": sorted(invalid_ids.intersection(players)),
    }


def save_report(report: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    columns = [
        "rank", "player", "player_id", "death_matches", "death_innings", "death_overs", "legal_balls",
        "bowler_runs", "economy", "adjusted_economy", "dot_balls", "dot_pct", "credited_wickets",
        "wickets_per_100", "adjusted_wickets_per_100", "boundary_events", "boundary_pct",
        "singles_twos", "singles_twos_pct", "adjusted_economy_percentile", "ranking_dot_pct_percentile",
        "adjusted_wickets_per_100_percentile", "ranking_boundary_pct_percentile", "ranking_singles_twos_pct_percentile",
        "composite_score", "active_2026_all_venues", "recent_death_innings", "recent_death_balls",
        "recent_death_economy", "recent_death_dot_pct", "recent_death_wickets", "recent_death_wickets_per_100",
        "recent_latest_date", "ranking_innings", "ranking_balls", "ranking_runs", "ranking_dot_balls",
        "ranking_wickets", "ranking_boundary_events", "ranking_singles_twos", "ranking_first_date", "ranking_latest_date", "ranking_economy",
        "ranking_dot_pct", "ranking_wickets_per_100", "ranking_boundary_pct", "ranking_singles_twos_pct",
        "ranking_eligible", "ranking_reasons", "ranking_status", "user_excluded",
    ]
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["player_rows"])


def main() -> None:
    report = build_death_bowling_report()
    from validate_death_bowling import save_validation, validate_death_bowling_report

    validation = validate_death_bowling_report(report)
    report["validation"] = validation
    save_validation(validation)
    save_report(report)
    print(json.dumps({"counts": report["counts"], "validation": {"all_passed": validation["all_passed"], "checks_passed": validation["checks_passed"], "checks_total": validation["checks_total"]}, "ranking_status": report["ranking_status"], "top_ten": report["top_ten"], "report": str(REPORT_PATH), "csv": str(CSV_PATH)}, indent=2))


if __name__ == "__main__":
    main()
