"""Rebuild and audit the Indian-venue clutch-batting window from raw CSVs."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = APP_DIR.parent
RAW_DIR = PROJECT_DIR / "Raw_Data"
OUTPUT_DIR = APP_DIR / "data" / "pressure_report"

LEGAL_TYPES = {"none", "byes", "legbyes"}
ILLEGAL_TYPES = {"wide", "overstep"}
EXTRA_RUN_TYPES = ILLEGAL_TYPES | {"byes", "legbyes"}
DISMISSAL_EXCLUSIONS = {
    "retire out", "retired out", "retire hurt", "retired hurt",
    "obstracting the field", "obstructing the field",
}
UNKNOWN_NAMES = {"", "unknown", "unknown player", "unknown batter", "unknown bowler"}
MIN_PRESSURE_BALLS = 30
MIN_PRESSURE_INNINGS_FOR_RANKING = 3
MIN_RECENT_CHASE_INNINGS = 10
PHASE_MIN_BALLS = 30
PHASE_PRIOR_BALLS = 60
PHASE_AVERAGE_PRIOR_DISMISSALS = 3
APPROVED_TOP_SEVEN = [
    (7897, "Namboori Tilak Varma"),
    (3330, "Hardik Pandya"),
    (3125, "Nicholas Pooran"),
    (2639, "Marcus Stoinis"),
    (4708, "Rinku Singh"),
    (5039, "Rajat Patidar"),
    (6396, "Tim David"),
]
PHASE_WEIGHTS = {
    "death_phase_adjusted_strike_rate": 0.25,
    "middle_phase_adjusted_strike_rate": 0.15,
    "phase_sr_acceleration": 0.20,
    "phase_total_runs": 0.15,
    "phase_boundary_rate_acceleration": 0.15,
    "phase_average_adjusted": 0.10,
}
USER_EXCLUDED_PLAYERS = {
    4722: "Rashid Khan",
    7260: "Dhruv Jurel",
    2756: "Shashank Singh",
}
INVESTIGATION_PLAYER_IDS = {
    "Tim David": 6396,
    "Rinku Singh": 4708,
    "Rajat Patidar": 5039,
    "Ayush Badoni": 6460,
    "Sanju Samson": 2258,
    "David Miller": 1077,
    "Aiden Markram": 3605,
    "Liam Livingstone": 4391,
    "Sherfane Rutherford": 6725,
    "Nitish Rana": 4246,
}

# These are the reference figures explicitly supplied for display and audit.
REFERENCE_TOP_TEN = [
    {"rank": 1, "player": "David Miller", "innings": 3, "balls": 80, "runs": 158, "strike_rate": 197.5, "balls_per_innings": 26.7, "boundaries_per_100": 27.5, "dot_pct": 20.0, "stayed_to_16": "1 of 3"},
    {"rank": 2, "player": "Tim David", "innings": 4, "balls": 59, "runs": 116, "strike_rate": 196.6, "balls_per_innings": 14.8, "boundaries_per_100": 30.5, "dot_pct": 22.0, "stayed_to_16": "3 of 4"},
    {"rank": 3, "player": "Namboori Tilak Varma", "innings": 6, "balls": 148, "runs": 286, "strike_rate": 193.2, "balls_per_innings": 24.7, "boundaries_per_100": 27.0, "dot_pct": 22.3, "stayed_to_16": "3 of 5"},
    {"rank": 4, "player": "Marcus Stoinis", "innings": 5, "balls": 112, "runs": 212, "strike_rate": 189.3, "balls_per_innings": 22.4, "boundaries_per_100": 27.7, "dot_pct": 25.0, "stayed_to_16": "1 of 3"},
    {"rank": 5, "player": "Hardik Pandya", "innings": 5, "balls": 51, "runs": 103, "strike_rate": 202.0, "balls_per_innings": 10.2, "boundaries_per_100": 31.4, "dot_pct": 25.5, "stayed_to_16": "1 of 4"},
    {"rank": 6, "player": "Sherfane Rutherford", "innings": 3, "balls": 42, "runs": 84, "strike_rate": 200.0, "balls_per_innings": 14.0, "boundaries_per_100": 33.3, "dot_pct": 40.5, "stayed_to_16": "0 of 3"},
    {"rank": 7, "player": "Rajat Patidar", "innings": 3, "balls": 44, "runs": 87, "strike_rate": 197.7, "balls_per_innings": 14.7, "boundaries_per_100": 25.0, "dot_pct": 22.7, "stayed_to_16": "0 of 2"},
    {"rank": 8, "player": "Shivam Dube", "innings": 6, "balls": 90, "runs": 174, "strike_rate": 193.3, "balls_per_innings": 15.0, "boundaries_per_100": 30.0, "dot_pct": 32.2, "stayed_to_16": "1 of 4"},
    {"rank": 9, "player": "Daryl Mitchell", "innings": 3, "balls": 69, "runs": 117, "strike_rate": 169.6, "balls_per_innings": 23.0, "boundaries_per_100": 24.6, "dot_pct": 27.5, "stayed_to_16": "1 of 2"},
    {"rank": 10, "player": "Nicholas Pooran", "innings": 5, "balls": 68, "runs": 132, "strike_rate": 194.1, "balls_per_innings": 13.6, "boundaries_per_100": 29.4, "dot_pct": 36.8, "stayed_to_16": "2 of 4"},
]

ENTRY_TIMING_REFERENCE = [
    {"rank": 1, "player_id": 1077, "player": "David Miller", "entry_overs": [4, 7, 8], "median_entry_over": 7, "came_before_anchor": 1},
    {"rank": 2, "player_id": 6396, "player": "Tim David", "entry_overs": [8, 11, 13, 15], "median_entry_over": 12, "came_before_anchor": 0},
    {"rank": 3, "player_id": 7897, "player": "Namboori Tilak Varma", "entry_overs": [3, 3, 5, 5, 9, 10], "median_entry_over": 5, "came_before_anchor": 2},
    {"rank": 4, "player_id": 2639, "player": "Marcus Stoinis", "entry_overs": [1, 2, 4, 5, 6, 8], "median_entry_over": 4.5, "came_before_anchor": 3},
    {"rank": 5, "player_id": 3330, "player": "Hardik Pandya", "entry_overs": [2, 3, 7, 7, 11, 12, 13], "median_entry_over": 7, "came_before_anchor": 2},
    {"rank": 6, "player_id": 6725, "player": "Sherfane Rutherford", "entry_overs": [4, 6, 13], "median_entry_over": 6, "came_before_anchor": 0},
    {"rank": 7, "player_id": 5039, "player": "Rajat Patidar", "entry_overs": [2, 4, 6], "median_entry_over": 4, "came_before_anchor": 2},
    {"rank": 8, "player_id": 4755, "player": "Shivam Dube", "entry_overs": [7, 8, 9, 9, 10, 13], "median_entry_over": 9, "came_before_anchor": 0},
    {"rank": 9, "player_id": 4106, "player": "Daryl Mitchell", "entry_overs": [1, 2, 3, 14], "median_entry_over": 2.5, "came_before_anchor": 3},
    {"rank": 10, "player_id": 3125, "player": "Nicholas Pooran", "entry_overs": [3, 4, 8, 11, 12], "median_entry_over": 8, "came_before_anchor": 1},
]


def integer(value: Any, default: int = 0) -> int:
    try:
        text = str(value or "").strip()
        return int(float(text)) if text else default
    except (TypeError, ValueError):
        return default


def text(value: Any) -> str:
    return str(value or "").strip()


def normalized(value: Any) -> str:
    return text(value).casefold()


def truth(value: Any) -> bool:
    return normalized(value) in {"1", "true", "yes"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def team_run_value(row: dict[str, Any]) -> int:
    return integer(row.get("runs")) + int(normalized(row.get("extras_type")) in EXTRA_RUN_TYPES)


def batter_dismissal(row: dict[str, Any]) -> bool:
    return truth(row.get("is_wicket")) and normalized(row.get("dismissal_type")) not in DISMISSAL_EXCLUSIONS


def is_known_type(kind: str) -> bool:
    return kind in LEGAL_TYPES or kind in ILLEGAL_TYPES


def build_raw_entry_timing_audit(
    competitions: dict[int, dict[str, Any]],
    matches: dict[int, dict[str, Any]],
    innings: dict[tuple[int, int], list[dict[str, Any]]],
    valid_names: dict[int, str],
) -> dict[str, Any]:
    """Recompute supplied batter entry timings directly from raw T20/T20I deliveries."""
    t20_formats = {"T20", "T20I"}
    first_totals = {
        match_id: sum(team_run_value(delivery) for delivery in deliveries)
        for (match_id, innings_no), deliveries in innings.items()
        if innings_no == 1
        and matches.get(match_id, {}).get("format") in t20_formats
    }
    anchors: dict[int, dict[str, Any]] = {}
    entries_by_match: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
    anchor_counts = {"T20": 0, "T20I": 0}
    names_by_id = {row["player_id"]: row["player"] for row in ENTRY_TIMING_REFERENCE}
    identity_matches = {
        player_id: player_id in valid_names and normalized(valid_names[player_id]) == normalized(player)
        for player_id, player in names_by_id.items()
    }

    for match_id, meta in matches.items():
        match_format = text(meta.get("format")).upper()
        if match_format not in t20_formats or normalized(meta.get("venue_country")) != "india":
            continue
        first_innings = innings.get((match_id, 1), [])
        chase = innings.get((match_id, 2), [])
        if not first_innings or not chase:
            continue
        target = meta.get("revised_target_value")
        if target is None:
            target = first_totals.get(match_id, 0) + 1
        if target < 0:
            continue

        runs_before = legal_balls_before = wickets_before = 0
        state_known = True
        anchor: dict[str, Any] | None = None
        for index, delivery in enumerate(chase):
            kind = normalized(delivery.get("extras_type"))
            if not is_known_type(kind):
                state_known = False
            balls_remaining = 120 - legal_balls_before
            runs_needed = int(target) - runs_before
            required_rate = runs_needed * 6.0 / balls_remaining if balls_remaining > 0 else None
            if (
                state_known
                and 18 <= legal_balls_before <= 42
                and 2 <= wickets_before <= 4
                and runs_needed > 0
                and required_rate is not None
                and 12 <= required_rate <= 20
            ):
                anchor = {
                    "delivery_index": index,
                    "legal_balls_bowled": legal_balls_before,
                    "wickets_down": wickets_before,
                    "required_rate": round(required_rate, 4),
                }
                break
            if not state_known:
                break
            runs_before += team_run_value(delivery)
            legal_balls_before += int(kind in LEGAL_TYPES)
            wickets_before += int(batter_dismissal(delivery))

        if anchor is None:
            continue
        anchors[match_id] = anchor
        anchor_counts[match_format] += 1

        for index, delivery in enumerate(chase):
            for id_key, name_key in (
                ("striker_id", "striker_name"),
                ("non_striker_id", "non_striker_name"),
            ):
                player_id = integer(delivery.get(id_key), -1)
                if (
                    player_id not in names_by_id
                    or not identity_matches[player_id]
                    or player_id in entries_by_match[match_id]
                ):
                    continue
                entries_by_match[match_id][player_id] = {
                    "player_id": player_id,
                    "player": names_by_id[player_id],
                    "match_date": text(meta.get("match_date")),
                    "competition": text(competitions.get(integer(meta.get("comp_id"), -1), {}).get("comp_name")),
                    "match_format": match_format,
                    "match_id": match_id,
                    "entry_over": integer(delivery.get("overid"), 0),
                    "entry_delivery_index": index,
                }

    detail_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    for reference in ENTRY_TIMING_REFERENCE:
        player_rows = []
        for match_id, anchor in anchors.items():
            entry = entries_by_match.get(match_id, {}).get(reference["player_id"])
            if entry is None:
                continue
            row = {
                **entry,
                "anchor_legal_balls": anchor["legal_balls_bowled"],
                "anchor_over": anchor["legal_balls_bowled"] // 6 + 1,
                "anchor_wickets_down": anchor["wickets_down"],
                "anchor_required_rate": anchor["required_rate"],
                "came_in_before_anchor": entry["entry_delivery_index"] < anchor["delivery_index"],
            }
            player_rows.append(row)
        player_rows.sort(key=lambda row: (row["entry_over"], row["match_date"], row["match_id"]))
        entry_overs = [row["entry_over"] for row in player_rows]
        sorted_overs = sorted(entry_overs)
        count = len(sorted_overs)
        if count:
            middle = count // 2
            median_entry_over = (
                sorted_overs[middle]
                if count % 2
                else (sorted_overs[middle - 1] + sorted_overs[middle]) / 2
            )
        else:
            median_entry_over = None
        before_count = sum(bool(row["came_in_before_anchor"]) for row in player_rows)
        reference_overs = reference["entry_overs"]
        matches_reference = (
            entry_overs == reference_overs
            and median_entry_over == reference["median_entry_over"]
            and before_count == reference["came_before_anchor"]
        )
        summary_rows.append({
            "rank": reference["rank"],
            "player": reference["player"],
            "player_id": reference["player_id"],
            "raw_entry_overs": ", ".join(str(value) for value in entry_overs),
            "reference_entry_overs": ", ".join(str(value) for value in reference_overs),
            "raw_innings": count,
            "reference_innings": len(reference_overs),
            "raw_median_entry_over": median_entry_over,
            "reference_median_entry_over": reference["median_entry_over"],
            "raw_came_before_anchor": f"{before_count} of {count}",
            "reference_came_before_anchor": f"{reference['came_before_anchor']} of {len(reference_overs)}",
            "identity_status": "PASS" if identity_matches[reference["player_id"]] else "FAIL",
            "matches_reference": matches_reference,
            "status": "MATCH" if matches_reference and identity_matches[reference["player_id"]] else "DIFFERS",
        })
        detail_rows.extend(player_rows)

    detail_rows.sort(key=lambda row: (row["player"], row["match_date"], row["match_id"]))
    return {
        "scope": (
            "Raw ball-by-ball rows joined to matches and competitions; India-hosted T20 and T20I second innings. "
            "First known pre-delivery anchor with 2–4 wickets down, 18–42 legal balls already bowled, "
            "required rate 12–20, and runs needed > 0. Entry over is the raw overid at first striker/non-striker appearance."
        ),
        "anchor_chases": len(anchors),
        "format_anchor_chases": anchor_counts,
        "reference_rows_matching": sum(row["matches_reference"] for row in summary_rows),
        "reference_rows_compared": len(summary_rows),
        "summary": summary_rows,
        "innings": detail_rows,
    }


def build_phase_batting_ranking(
    player_rows: list[dict[str, Any]],
    matches: dict[int, dict[str, Any]],
    innings: dict[tuple[int, int], list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Score the clutch-qualified candidate pool from raw Indian T20 phase data."""
    rows_by_id = {int(row["player_id"]): row for row in player_rows}
    candidate_ids = set(rows_by_id)
    phase_stats: dict[int, dict[str, dict[str, Any]]] = defaultdict(lambda: {
        phase: {"balls": 0, "runs": 0, "fours": 0, "sixes": 0, "dismissals": 0, "innings": set()}
        for phase in ("middle", "death")
    })

    for (match_id, innings_no), deliveries in innings.items():
        match = matches.get(match_id, {})
        if (
            match.get("format") != "T20"
            or normalized(match.get("venue_country")) != "india"
            or innings_no not in (1, 2)
        ):
            continue
        for delivery in deliveries:
            kind = normalized(delivery.get("extras_type"))
            if not is_known_type(kind):
                break
            over = integer(delivery.get("overid"), 0)
            if 7 <= over <= 15:
                phase = "middle"
            elif 16 <= over <= 20:
                phase = "death"
            else:
                continue

            striker_id = integer(delivery.get("striker_id"), -1)
            if striker_id in candidate_ids and kind != "wide":
                stats = phase_stats[striker_id][phase]
                stats["balls"] += 1
                stats["runs"] += integer(delivery.get("runs"))
                stats["fours"] += int(truth(delivery.get("is_four")))
                stats["sixes"] += int(truth(delivery.get("is_six")))
                stats["innings"].add((match_id, innings_no))

            dismissed_id = integer(delivery.get("dismissed_player_id"), -1)
            if dismissed_id in candidate_ids and batter_dismissal(delivery):
                phase_stats[dismissed_id][phase]["dismissals"] += 1

    for player_id, row in rows_by_id.items():
        middle = phase_stats[player_id]["middle"]
        death = phase_stats[player_id]["death"]
        middle_balls, death_balls = int(middle["balls"]), int(death["balls"])
        middle_runs, death_runs = int(middle["runs"]), int(death["runs"])
        middle_boundaries = int(middle["fours"] + middle["sixes"])
        death_boundaries = int(death["fours"] + death["sixes"])
        middle_dismissals, death_dismissals = int(middle["dismissals"]), int(death["dismissals"])
        total_runs = middle_runs + death_runs
        total_dismissals = middle_dismissals + death_dismissals
        middle_boundary_rate = middle_boundaries * 100 / middle_balls if middle_balls else None
        death_boundary_rate = death_boundaries * 100 / death_balls if death_balls else None
        row.update({
            "middle_phase_innings": len(middle["innings"]),
            "middle_phase_balls": middle_balls,
            "middle_phase_runs": middle_runs,
            "middle_phase_fours": int(middle["fours"]),
            "middle_phase_sixes": int(middle["sixes"]),
            "middle_phase_dismissals": middle_dismissals,
            "middle_phase_strike_rate": round(middle_runs * 100 / middle_balls, 2) if middle_balls else None,
            "middle_phase_boundary_rate": round(middle_boundary_rate, 2) if middle_boundary_rate is not None else None,
            "death_phase_innings": len(death["innings"]),
            "death_phase_balls": death_balls,
            "death_phase_runs": death_runs,
            "death_phase_fours": int(death["fours"]),
            "death_phase_sixes": int(death["sixes"]),
            "death_phase_dismissals": death_dismissals,
            "death_phase_strike_rate": round(death_runs * 100 / death_balls, 2) if death_balls else None,
            "death_phase_boundary_rate": round(death_boundary_rate, 2) if death_boundary_rate is not None else None,
            "phase_total_runs": total_runs,
            "phase_total_dismissals": total_dismissals,
            "phase_average_raw": round(total_runs / total_dismissals, 2) if total_dismissals >= 3 else "Not reported",
            "phase_boundary_rate_acceleration": round(death_boundary_rate - middle_boundary_rate, 2)
            if middle_boundary_rate is not None and death_boundary_rate is not None else None,
            "phase_sample_status": "Eligible phase sample"
            if middle_balls >= PHASE_MIN_BALLS and death_balls >= PHASE_MIN_BALLS
            else "Review sample: fewer than 30 balls in a phase",
        })

    eligible = [
        row for row in player_rows
        if row.get("ranking_eligible")
        and int(row.get("middle_phase_balls", 0)) >= PHASE_MIN_BALLS
        and int(row.get("death_phase_balls", 0)) >= PHASE_MIN_BALLS
    ]
    middle_ball_total = sum(int(row["middle_phase_balls"]) for row in eligible)
    middle_run_total = sum(int(row["middle_phase_runs"]) for row in eligible)
    death_ball_total = sum(int(row["death_phase_balls"]) for row in eligible)
    death_run_total = sum(int(row["death_phase_runs"]) for row in eligible)
    phase_run_total = sum(int(row["phase_total_runs"]) for row in eligible)
    phase_dismissal_total = sum(int(row["phase_total_dismissals"]) for row in eligible)
    middle_baseline_sr = middle_run_total * 100 / middle_ball_total if middle_ball_total else 0.0
    death_baseline_sr = death_run_total * 100 / death_ball_total if death_ball_total else 0.0
    average_baseline = phase_run_total / phase_dismissal_total if phase_dismissal_total else 0.0

    for row in player_rows:
        middle_balls = int(row["middle_phase_balls"])
        death_balls = int(row["death_phase_balls"])
        middle_runs = int(row["middle_phase_runs"])
        death_runs = int(row["death_phase_runs"])
        phase_runs = int(row["phase_total_runs"])
        phase_dismissals = int(row["phase_total_dismissals"])
        row["middle_phase_adjusted_strike_rate"] = round(
            (middle_runs + PHASE_PRIOR_BALLS * middle_baseline_sr / 100)
            * 100 / (middle_balls + PHASE_PRIOR_BALLS), 4
        ) if middle_balls else round(middle_baseline_sr, 4)
        row["death_phase_adjusted_strike_rate"] = round(
            (death_runs + PHASE_PRIOR_BALLS * death_baseline_sr / 100)
            * 100 / (death_balls + PHASE_PRIOR_BALLS), 4
        ) if death_balls else round(death_baseline_sr, 4)
        row["phase_sr_acceleration"] = round(
            row["death_phase_adjusted_strike_rate"] - row["middle_phase_adjusted_strike_rate"], 4
        )
        row["phase_average_adjusted"] = round(
            (phase_runs + PHASE_AVERAGE_PRIOR_DISMISSALS * average_baseline)
            / (phase_dismissals + PHASE_AVERAGE_PRIOR_DISMISSALS), 4
        )
        row["phase_weighted_score"] = None
        row["phase_weighted_rank"] = None
        row["phase_comparison_rank"] = None
        for metric in PHASE_WEIGHTS:
            row[f"{metric}_percentile"] = None
            row[f"{metric}_points"] = None

    def set_percentile(field: str) -> None:
        ordered = sorted(eligible, key=lambda row: (-float(row[field]), row["player"], row["player_id"]))
        index = 0
        while index < len(ordered):
            end = index + 1
            while end < len(ordered) and float(ordered[end][field]) == float(ordered[index][field]):
                end += 1
            average_rank = ((index + 1) + end) / 2
            percentile_score = 100.0 if len(ordered) == 1 else 100.0 * (len(ordered) - average_rank) / (len(ordered) - 1)
            for tied in ordered[index:end]:
                tied[f"_{field}_percentile"] = percentile_score
            index = end

    for field in PHASE_WEIGHTS:
        if eligible:
            set_percentile(field)
    eligible.sort(key=lambda row: (
        -sum(float(row.get(f"_{field}_percentile", 0.0)) * weight for field, weight in PHASE_WEIGHTS.items()),
        -int(row["death_phase_balls"]), -int(row["phase_total_runs"]), row["player"], row["player_id"],
    ))
    cohort_can_publish_ranks = len(eligible) >= 10
    for rank, row in enumerate(eligible, start=1):
        row["phase_weighted_rank"] = rank if cohort_can_publish_ranks else None
        row["phase_weighted_score"] = round(sum(
            float(row[f"_{field}_percentile"]) * weight
            for field, weight in PHASE_WEIGHTS.items()
        ), 4)
        for field, weight in PHASE_WEIGHTS.items():
            row[f"{field}_percentile"] = round(float(row[f"_{field}_percentile"]), 4)
            row[f"{field}_points"] = round(float(row[f"{field}_percentile"]) * weight, 4)
            row.pop(f"_{field}_percentile", None)

    eligible_ids = {int(row["player_id"]) for row in eligible}
    approved_ids = {player_id for player_id, _ in APPROVED_TOP_SEVEN}
    final_rows: list[dict[str, Any]] = []
    alternatives = [row for row in eligible if int(row["player_id"]) not in approved_ids]
    alternatives.sort(key=lambda row: (
        -float(row["phase_weighted_score"]), -int(row["death_phase_balls"]),
        -int(row["phase_total_runs"]), row["player"], row["player_id"],
    ))
    if cohort_can_publish_ranks:
        for rank, (player_id, expected_name) in enumerate(APPROVED_TOP_SEVEN, start=1):
            player = rows_by_id.get(player_id)
            if player and player_id in eligible_ids and normalized(player.get("player")) == normalized(expected_name):
                selection = dict(player)
                selection["final_rank"] = rank
                selection["selection_reason"] = "Approved top seven retained"
                final_rows.append(selection)
        for offset, row in enumerate(alternatives[:max(0, 10 - len(final_rows))], start=len(final_rows) + 1):
            selection = dict(row)
            selection["final_rank"] = offset
            selection["selection_reason"] = "Selected from remaining clutch-qualified batters by the phase-weighted score"
            final_rows.append(selection)

    phase_rankings = [dict(row) for row in eligible]
    summary = {
        "phase_eligible_players": len(eligible),
        "phase_candidates_available_for_replacement": len(alternatives),
        "final_top_ten_count": len(final_rows),
        "middle_baseline_strike_rate": round(middle_baseline_sr, 4),
        "death_baseline_strike_rate": round(death_baseline_sr, 4),
        "average_baseline": round(average_baseline, 4),
        "minimum_balls_per_phase": PHASE_MIN_BALLS,
        "shrinkage_prior_balls": PHASE_PRIOR_BALLS,
        "shrinkage_prior_dismissals": PHASE_AVERAGE_PRIOR_DISMISSALS,
        "published_ranking": len(eligible) >= 10 and len(final_rows) == 10,
        "ranking_status": "Ranked using the phase formula" if len(eligible) >= 10 else f"List without ranking: {len(eligible)} eligible phase samples; 10 are required.",
    }
    return phase_rankings, final_rows, summary


def build_clutch_report() -> dict[str, Any]:
    competitions = {
        integer(row.get("comp_id"), -1): row for row in read_csv(RAW_DIR / "competitions.csv")
    }
    matches: dict[int, dict[str, Any]] = {}
    for row in read_csv(RAW_DIR / "matches.csv"):
        comp = competitions.get(integer(row.get("comp_id"), -1), {})
        revised = text(row.get("revised_target"))
        matches[integer(row.get("match_id"), -1)] = {
            **row,
            "format": text(comp.get("match_format")).upper(),
            "season": text(comp.get("season")),
            "revised_target_value": integer(revised, -1) if revised else None,
        }

    innings: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    names_by_id: dict[int, set[str]] = defaultdict(set)
    for source_order, row in enumerate(read_csv(RAW_DIR / "ball_by_ball.csv")):
        row["_source_order"] = source_order
        innings[(integer(row.get("match_id"), -1), integer(row.get("innings"), -1))].append(row)
        for id_key, name_key in (
            ("striker_id", "striker_name"),
            ("non_striker_id", "non_striker_name"),
            ("bowler_id", "bowler_name"),
        ):
            player_id = integer(row.get(id_key), -1)
            if player_id > 0:
                names_by_id[player_id].add(text(row.get(name_key)))

    for deliveries in innings.values():
        deliveries.sort(
            key=lambda row: (
                integer(row.get("overid"), -1),
                integer(row.get("innings_ball_num"), -1),
                integer(row.get("over_ball_num"), -1),
                integer(row.get("_source_order"), -1),
            )
        )

    invalid_ids = {
        player_id
        for player_id, names in names_by_id.items()
        if len(names) != 1 or any(name.casefold() in UNKNOWN_NAMES for name in names)
    }
    valid_names = {
        player_id: next(iter(names))
        for player_id, names in names_by_id.items()
        if player_id not in invalid_ids
    }

    first_totals = {
        match_id: sum(team_run_value(row) for row in rows)
        for (match_id, innings_no), rows in innings.items()
        if innings_no == 1 and matches.get(match_id, {}).get("format") == "T20"
    }

    active_2026_ids: set[int] = set()
    chase_form_by_player: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
    for match_id, meta in matches.items():
        if meta.get("format") != "T20":
            continue
        if meta.get("season") == "2026":
            for innings_no in (1, 2):
                for delivery in innings.get((match_id, innings_no), []):
                    for id_key in ("striker_id", "non_striker_id"):
                        player_id = integer(delivery.get(id_key), -1)
                        if player_id in valid_names:
                            active_2026_ids.add(player_id)

        # The form cohort is Indian-venue T20 chases. The 2026 activity gate
        # above deliberately remains all venues, as confirmed by the user.
        if normalized(meta.get("venue_country")) != "india":
            continue

        first_innings = innings.get((match_id, 1), [])
        chase = innings.get((match_id, 2), [])
        target = meta.get("revised_target_value")
        if target is None and first_innings:
            target = first_totals.get(match_id, 0) + 1
        if target is None or target < 0:
            continue
        runs_before = legal_balls_before = 0
        state_known = True
        for delivery in chase:
            kind = normalized(delivery.get("extras_type"))
            if not is_known_type(kind):
                state_known = False
            remaining = 120 - legal_balls_before
            runs_needed = int(target) - runs_before
            if not state_known:
                break
            if remaining <= 0 or runs_needed <= 0:
                break

            striker_id = integer(delivery.get("striker_id"), -1)
            if striker_id in valid_names:
                form = chase_form_by_player[striker_id].setdefault(match_id, {
                    "match_id": match_id,
                    "match_date": text(meta.get("match_date")),
                    "runs": 0,
                    "balls": 0,
                    "fours": 0,
                    "sixes": 0,
                    "dots": 0,
                    "dismissals": 0,
                })
                if kind != "wide":
                    form["balls"] += 1
                    form["runs"] += integer(delivery.get("runs"))
                    form["fours"] += int(truth(delivery.get("is_four")))
                    form["sixes"] += int(truth(delivery.get("is_six")))
                    form["dots"] += int(integer(delivery.get("runs")) == 0)
            dismissed_id = integer(delivery.get("dismissed_player_id"), -1)
            if batter_dismissal(delivery) and dismissed_id in valid_names:
                form = chase_form_by_player[dismissed_id].setdefault(match_id, {
                    "match_id": match_id,
                    "match_date": text(meta.get("match_date")),
                    "runs": 0,
                    "balls": 0,
                    "fours": 0,
                    "sixes": 0,
                    "dots": 0,
                    "dismissals": 0,
                })
                form["dismissals"] += 1
            runs_before += team_run_value(delivery)
            legal_balls_before += int(kind in LEGAL_TYPES)

    anchors: list[dict[str, Any]] = []
    for match_id, meta in matches.items():
        if meta.get("format") != "T20" or normalized(meta.get("venue_country")) != "india":
            continue
        first_innings = innings.get((match_id, 1), [])
        chase = innings.get((match_id, 2), [])
        if not first_innings or not chase:
            continue
        target = meta.get("revised_target_value")
        if target is None:
            target = first_totals.get(match_id, 0) + 1
        if target < 0:
            continue

        runs_before = legal_balls_before = wickets_before = 0
        state_known = True
        for index, delivery in enumerate(chase):
            kind = normalized(delivery.get("extras_type"))
            if not is_known_type(kind):
                state_known = False
            balls_remaining = 120 - legal_balls_before
            runs_needed = int(target) - runs_before
            required_rate = runs_needed * 6.0 / balls_remaining if balls_remaining > 0 else None
            if (
                state_known
                and 1 <= balls_remaining <= 120
                and 18 <= legal_balls_before <= 42
                and 2 <= wickets_before <= 4
                and runs_needed > 0
                and required_rate is not None
                and 12 <= required_rate <= 20
            ):
                result_text = normalized(meta.get("result"))
                winner = integer(meta.get("win_team_id"), 0)
                decided = winner > 0 and not any(
                    token in result_text for token in ("tie", "no result", "abandoned", "cancelled")
                )
                anchors.append({
                    "match_id": match_id,
                    "match_date": text(meta.get("match_date")),
                    "competition": text(competitions.get(integer(meta.get("comp_id"), -1), {}).get("comp_name")),
                    "venue_country": text(meta.get("venue_country")),
                    "anchor_delivery_index": index,
                    "legal_balls_bowled": legal_balls_before,
                    "anchor_over": round(legal_balls_before / 6, 2),
                    "wickets_down": wickets_before,
                    "target": target,
                    "score_before": runs_before,
                    "runs_needed": runs_needed,
                    "required_rate": round(required_rate, 4),
                    "decided_chase": decided,
                    "deliveries": chase,
                })
                break

            if not state_known:
                break
            runs_before += team_run_value(delivery)
            legal_balls_before += int(kind in LEGAL_TYPES)
            wickets_before += int(batter_dismissal(delivery))

    batter_stats: dict[int, dict[str, Any]] = {}
    anchor_output: list[dict[str, Any]] = []
    candidate_innings_audit: list[dict[str, Any]] = []
    for anchor in anchors:
        player_row_state: dict[int, dict[str, Any]] = {}
        entry_by_player: dict[int, dict[str, Any]] = {}
        for entry_index, delivery in enumerate(anchor["deliveries"]):
            entry_kind = normalized(delivery.get("extras_type"))
            if not is_known_type(entry_kind):
                break
            striker_id = integer(delivery.get("striker_id"), -1)
            non_striker_id = integer(delivery.get("non_striker_id"), -1)
            for batter_id in (striker_id, non_striker_id):
                if batter_id in valid_names:
                    entry_by_player.setdefault(
                        batter_id,
                        {
                            "first_index": entry_index,
                            "entry_over": integer(delivery.get("overid"), 0),
                            "batting_order": None,
                        },
                    )
            if striker_id in valid_names and entry_by_player[striker_id]["batting_order"] is None:
                entry_by_player[striker_id]["batting_order"] = integer(delivery.get("batting_order"), 0)

        known_segment: list[tuple[dict[str, Any], int]] = []
        legal_before = int(anchor["legal_balls_bowled"])
        for delivery in anchor["deliveries"][anchor["anchor_delivery_index"]:]:
            kind = normalized(delivery.get("extras_type"))
            if not is_known_type(kind):
                break
            known_segment.append((delivery, legal_before))
            legal_before += int(kind in LEGAL_TYPES)

        candidate_rows: dict[int, dict[str, Any]] = {}
        for delivery, legal_before_delivery in known_segment:
            kind = normalized(delivery.get("extras_type"))
            striker_id = integer(delivery.get("striker_id"), -1)
            if striker_id in INVESTIGATION_PLAYER_IDS.values():
                detail = candidate_rows.setdefault(striker_id, {
                    "player_id": striker_id,
                    "player": valid_names.get(striker_id, ""),
                    "match_id": anchor["match_id"],
                    "match_date": anchor["match_date"],
                    "batting_order": text(delivery.get("batting_order")),
                    "anchor_legal_balls": anchor["legal_balls_bowled"],
                    "anchor_wickets_down": anchor["wickets_down"],
                    "anchor_required_rate": anchor["required_rate"],
                    "entry_legal_balls_bowled": None,
                    "balls": 0,
                    "runs": 0,
                    "fours": 0,
                    "sixes": 0,
                    "dots": 0,
                    "dismissals": 0,
                    "dismissal_types": [],
                })
                if kind != "wide" and detail["entry_legal_balls_bowled"] is None:
                    detail["entry_legal_balls_bowled"] = legal_before_delivery
                if kind != "wide":
                    detail["balls"] += 1
                    detail["runs"] += integer(delivery.get("runs"))
                    detail["fours"] += int(truth(delivery.get("is_four")))
                    detail["sixes"] += int(truth(delivery.get("is_six")))
                    detail["dots"] += int(integer(delivery.get("runs")) == 0)

            dismissed_id = integer(delivery.get("dismissed_player_id"), -1)
            if dismissed_id in INVESTIGATION_PLAYER_IDS.values() and batter_dismissal(delivery):
                detail = candidate_rows.setdefault(dismissed_id, {
                    "player_id": dismissed_id,
                    "player": valid_names.get(dismissed_id, ""),
                    "match_id": anchor["match_id"],
                    "match_date": anchor["match_date"],
                    "batting_order": "",
                    "anchor_legal_balls": anchor["legal_balls_bowled"],
                    "anchor_wickets_down": anchor["wickets_down"],
                    "anchor_required_rate": anchor["required_rate"],
                    "entry_legal_balls_bowled": None,
                    "balls": 0,
                    "runs": 0,
                    "fours": 0,
                    "sixes": 0,
                    "dots": 0,
                    "dismissals": 0,
                    "dismissal_types": [],
                })
                detail["dismissals"] += 1
                dismissal_type = text(delivery.get("dismissal_type"))
                if dismissal_type and dismissal_type not in detail["dismissal_types"]:
                    detail["dismissal_types"].append(dismissal_type)

        for detail in candidate_rows.values():
            balls = int(detail["balls"])
            detail["entry_over"] = (
                int(detail["entry_legal_balls_bowled"]) // 6 + 1
                if detail["entry_legal_balls_bowled"] is not None else None
            )
            detail["strike_rate"] = round(detail["runs"] * 100 / balls, 1) if balls else None
            detail["boundaries_per_100"] = round((detail["fours"] + detail["sixes"]) * 100 / balls, 1) if balls else None
            detail["dot_pct"] = round(detail["dots"] * 100 / balls, 1) if balls else None
            detail["dismissal_types"] = ", ".join(detail["dismissal_types"])
            candidate_innings_audit.append(detail)

        for delivery, legal_before_delivery in known_segment:
            kind = normalized(delivery.get("extras_type"))
            striker_id = integer(delivery.get("striker_id"), -1)
            if striker_id in valid_names:
                player_row_state.setdefault(striker_id, {
                    "appeared": False,
                    "dismissed_by_16": False,
                    "appeared_before_16": False,
                })
                player_row_state[striker_id]["appeared"] = True
                row = batter_stats.setdefault(striker_id, {
                    "player_id": striker_id,
                    "player": valid_names[striker_id],
                    "innings_matches": set(),
                    "runs": 0,
                    "balls": 0,
                    "fours": 0,
                    "sixes": 0,
                    "dots": 0,
                    "dismissals": 0,
                    "matches": set(),
                    "stay_eligible_innings": 0,
                    "stayed_to_16_innings": 0,
                    "entry_overs": [],
                    "batting_orders": [],
                    "came_before_anchor_innings": 0,
                    "entered_at_or_after_anchor_innings": 0,
                })
                batter_faced = kind != "wide"
                if batter_faced:
                    if not player_row_state[striker_id].get("entry_recorded", False):
                        entry_info = entry_by_player.get(striker_id)
                        if entry_info is not None:
                            row["entry_overs"].append(entry_info["entry_over"])
                            if entry_info["first_index"] < anchor["anchor_delivery_index"]:
                                row["came_before_anchor_innings"] += 1
                            else:
                                row["entered_at_or_after_anchor_innings"] += 1
                            if entry_info["batting_order"]:
                                row["batting_orders"].append(entry_info["batting_order"])
                        player_row_state[striker_id]["entry_recorded"] = True
                    row["innings_matches"].add(anchor["match_id"])
                    row["matches"].add(anchor["match_id"])
                    row["balls"] += 1
                    row["runs"] += integer(delivery.get("runs"))
                    row["fours"] += int(truth(delivery.get("is_four")))
                    row["sixes"] += int(truth(delivery.get("is_six")))
                    row["dots"] += int(integer(delivery.get("runs")) == 0)
                    player_row_state[striker_id]["appeared_before_16"] |= legal_before_delivery < 96

            # Track both batters who were at the crease for the over-16 survival check.
            if legal_before_delivery < 96:
                for id_key in ("striker_id", "non_striker_id"):
                    player_id = integer(delivery.get(id_key), -1)
                    if player_id in valid_names:
                        player_row_state.setdefault(player_id, {
                            "appeared": False,
                            "dismissed_by_16": False,
                            "appeared_before_16": False,
                        })
                        player_row_state[player_id]["appeared_before_16"] = True

            dismissed_id = integer(delivery.get("dismissed_player_id"), -1)
            if batter_dismissal(delivery) and dismissed_id in valid_names:
                player_row_state.setdefault(dismissed_id, {
                    "appeared": False,
                    "dismissed_by_16": False,
                    "appeared_before_16": False,
                })
                batter_stats.setdefault(dismissed_id, {
                    "player_id": dismissed_id,
                    "player": valid_names[dismissed_id],
                    "innings_matches": set(),
                    "runs": 0,
                    "balls": 0,
                    "fours": 0,
                    "sixes": 0,
                    "dots": 0,
                    "dismissals": 0,
                    "matches": set(),
                    "stay_eligible_innings": 0,
                    "stayed_to_16_innings": 0,
                    "entry_overs": [],
                    "batting_orders": [],
                    "came_before_anchor_innings": 0,
                    "entered_at_or_after_anchor_innings": 0,
                })["dismissals"] += 1
                if legal_before_delivery < 96:
                    player_row_state[dismissed_id]["dismissed_by_16"] = True

        legal_total = legal_before
        if legal_total >= 96:
            for player_id, state in player_row_state.items():
                if state["appeared_before_16"]:
                    target_row = batter_stats.setdefault(player_id, {
                        "player_id": player_id,
                        "player": valid_names[player_id],
                        "innings_matches": set(),
                        "runs": 0,
                        "balls": 0,
                        "fours": 0,
                        "sixes": 0,
                        "dots": 0,
                        "dismissals": 0,
                        "matches": set(),
                        "stay_eligible_innings": 0,
                        "stayed_to_16_innings": 0,
                        "entry_overs": [],
                        "batting_orders": [],
                        "came_before_anchor_innings": 0,
                        "entered_at_or_after_anchor_innings": 0,
                    })
                    target_row["stay_eligible_innings"] += 1
                    if not state["dismissed_by_16"]:
                        target_row["stayed_to_16_innings"] += 1

        for player_id, state in player_row_state.items():
            if state["appeared"]:
                batter_stats[player_id]["innings_matches"].add(anchor["match_id"])
                batter_stats[player_id]["matches"].add(anchor["match_id"])

        anchor_output.append({key: value for key, value in anchor.items() if key != "deliveries"})

    player_rows: list[dict[str, Any]] = []
    for stats in batter_stats.values():
        balls = int(stats["balls"])
        innings_count = len(stats["innings_matches"])
        chase_innings = [
            row for row in chase_form_by_player.get(int(stats["player_id"]), {}).values()
            if int(row["balls"]) > 0
        ]
        chase_innings.sort(key=lambda row: (row["match_date"], row["match_id"]), reverse=True)
        latest_ten_chases = chase_innings[:10]
        recent_runs = sum(int(row["runs"]) for row in latest_ten_chases)
        recent_balls = sum(int(row["balls"]) for row in latest_ten_chases)
        recent_dismissals = sum(int(row["dismissals"]) for row in latest_ten_chases)
        recent_boundary_runs = sum(int(row["fours"]) * 4 + int(row["sixes"]) * 6 for row in latest_ten_chases)
        recent_boundaries = sum(int(row["fours"]) + int(row["sixes"]) for row in latest_ten_chases)
        recent_dots = sum(int(row["dots"]) for row in latest_ten_chases)
        ordered_entries = sorted(int(value) for value in stats["entry_overs"])
        middle = len(ordered_entries) // 2
        median_entry_over = (
            ordered_entries[middle]
            if len(ordered_entries) % 2
            else (ordered_entries[middle - 1] + ordered_entries[middle]) / 2
            if ordered_entries else None
        )
        order_counts = Counter(stats["batting_orders"])
        typical_batting_order = order_counts.most_common(1)[0][0] if order_counts else None
        player_rows.append({
            "player_id": stats["player_id"],
            "player": stats["player"],
            "innings": innings_count,
            "matches": len(stats["matches"]),
            "balls": balls,
            "runs": int(stats["runs"]),
            "strike_rate": round(stats["runs"] * 100 / balls, 1) if balls else None,
            "balls_per_innings": round(balls / innings_count, 1) if innings_count else None,
            "fours": int(stats["fours"]),
            "sixes": int(stats["sixes"]),
            "boundaries": int(stats["fours"] + stats["sixes"]),
            "boundary_runs": int(stats["fours"] * 4 + stats["sixes"] * 6),
            "boundaries_per_100": round((stats["fours"] + stats["sixes"]) * 100 / balls, 1) if balls else None,
            "dots": int(stats["dots"]),
            "dot_pct": round(stats["dots"] * 100 / balls, 1) if balls else None,
            "dismissals": int(stats["dismissals"]),
            "stayed_to_16": f"{stats['stayed_to_16_innings']} of {stats['stay_eligible_innings']}",
            "stay_eligible_innings": int(stats["stay_eligible_innings"]),
            "stayed_to_16_innings": int(stats["stayed_to_16_innings"]),
            "entry_overs": ", ".join(str(value) for value in ordered_entries),
            "median_entry_over": median_entry_over,
            "typical_batting_order": typical_batting_order,
            "came_before_anchor": f"{stats['came_before_anchor_innings']} of {innings_count}",
            "came_before_anchor_innings": int(stats["came_before_anchor_innings"]),
            "entered_at_or_after_anchor_innings": int(stats["entered_at_or_after_anchor_innings"]),
            "recent_chase_innings": len(chase_innings),
            "recent_form_innings": len(latest_ten_chases),
            "recent_form_window_start": latest_ten_chases[-1]["match_date"] if latest_ten_chases else None,
            "recent_form_window_end": latest_ten_chases[0]["match_date"] if latest_ten_chases else None,
            "recent_form_runs": recent_runs,
            "recent_form_balls": recent_balls,
            "recent_form_strike_rate": round(recent_runs * 100 / recent_balls, 1) if recent_balls else None,
            "recent_form_dismissals": recent_dismissals,
            "recent_form_average": round(recent_runs / recent_dismissals, 1) if recent_dismissals >= 3 else "Not reported",
            "recent_form_boundary_runs": recent_boundary_runs,
            "recent_form_boundary_share": round(recent_boundary_runs * 100 / recent_runs, 1) if recent_runs else 0.0,
            "recent_form_boundaries_per_100": round(recent_boundaries * 100 / recent_balls, 1) if recent_balls else None,
            "recent_form_dot_balls": recent_dots,
            "recent_form_dot_pct": round(recent_dots * 100 / recent_balls, 1) if recent_balls else None,
            "sample_status": "Eligible sample" if balls >= 30 else "Review sample",
            "active_2026_all_venues": stats["player_id"] in active_2026_ids,
            "selection_gate_status": (
                "Not active in 2026" if stats["player_id"] not in active_2026_ids
                else "Review Indian-venue chase sample" if len(chase_innings) < MIN_RECENT_CHASE_INNINGS
                else "10+ Indian-venue chase innings available"
            ),
            "user_excluded": stats["player_id"] in USER_EXCLUDED_PLAYERS,
            "exclusion_reason": "Excluded by user review" if stats["player_id"] in USER_EXCLUDED_PLAYERS else "",
        })

    match_count = len(anchors)
    decided_count = sum(bool(row["decided_chase"]) for row in anchors)
    total_runs = sum(int(row["runs"]) for row in player_rows)
    total_balls = sum(int(row["balls"]) for row in player_rows)
    total_dismissals = sum(int(row["dismissals"]) for row in player_rows)
    baseline_sr = total_runs * 100 / total_balls if total_balls else 0.0
    baseline_average = total_runs / total_dismissals if total_dismissals else 0.0
    for row in player_rows:
        balls = int(row["balls"])
        dismissals = int(row["dismissals"])
        raw_average = row["runs"] / dismissals if dismissals else None
        row["average"] = round(raw_average, 1) if dismissals >= 3 else "Not reported"
        row["adjusted_strike_rate"] = round(
            ((row["runs"] * 100 / balls) * balls + baseline_sr * 60) / (balls + 60), 4
        ) if balls else round(baseline_sr, 4)
        adjusted_average = (
            (raw_average * dismissals + baseline_average * 3) / (dismissals + 3)
            if raw_average is not None
            else baseline_average
        )
        row["adjusted_average"] = round(adjusted_average, 4) if dismissals >= 3 else "Not reported"
        row["_composite_average"] = adjusted_average
        row["boundary_share"] = round(row["boundary_runs"] * 100 / row["runs"], 4) if row["runs"] else 0.0
        row["base_eligible"] = bool(
            balls >= MIN_PRESSURE_BALLS
            and row["active_2026_all_venues"]
            and row["recent_chase_innings"] >= MIN_RECENT_CHASE_INNINGS
        )
        row["pressure_innings_gate"] = int(row["innings"]) >= MIN_PRESSURE_INNINGS_FOR_RANKING
        row["ranking_eligible"] = row["base_eligible"] and row["pressure_innings_gate"] and not row["user_excluded"]
        row["rank"] = None
        row["composite_score"] = None
        row["ranking_status"] = (
            row["exclusion_reason"] if row["user_excluded"]
            else "Eligible for ranking" if row["ranking_eligible"]
            else f"Review pressure sample: {row['innings']} qualifying innings; {MIN_PRESSURE_INNINGS_FOR_RANKING} required"
            if row["base_eligible"] and not row["pressure_innings_gate"]
            else row["selection_gate_status"]
        )

    eligible_rows = [row for row in player_rows if row["ranking_eligible"]]
    ranking_status = ""
    if decided_count < 20:
        ranking_status = f"List without ranking: {decided_count} decided anchor chases; 20 are required."
    elif len(eligible_rows) < 10:
        ranking_status = f"List without ranking: {len(eligible_rows)} players pass gates; 10 are required."
    else:
        def set_percentiles(rows: list[dict[str, Any]], field: str) -> None:
            ordered = sorted(rows, key=lambda row: (-float(row[field]), row["player"], row["player_id"]))
            start = 0
            while start < len(ordered):
                value = float(ordered[start][field])
                end = start + 1
                while end < len(ordered) and float(ordered[end][field]) == value:
                    end += 1
                avg_rank = ((start + 1) + end) / 2
                score = 100.0 if len(ordered) == 1 else 100.0 * (len(ordered) - avg_rank) / (len(ordered) - 1)
                for tied in ordered[start:end]:
                    tied[f"_{field}_percentile"] = score
                start = end

        set_percentiles(eligible_rows, "adjusted_strike_rate")
        set_percentiles(eligible_rows, "_composite_average")
        set_percentiles(eligible_rows, "boundary_share")
        for row in eligible_rows:
            row["adjusted_sr_percentile"] = round(row["_adjusted_strike_rate_percentile"], 4)
            row["adjusted_average_percentile"] = round(row["__composite_average_percentile"], 4)
            row["boundary_share_percentile"] = round(row["_boundary_share_percentile"], 4)
            row["weighted_sr_points"] = round(0.50 * row["_adjusted_strike_rate_percentile"], 4)
            row["weighted_average_points"] = round(0.30 * row["__composite_average_percentile"], 4)
            row["weighted_boundary_points"] = round(0.20 * row["_boundary_share_percentile"], 4)
            row["composite_score"] = round(
                0.50 * row["_adjusted_strike_rate_percentile"]
                + 0.30 * row["__composite_average_percentile"]
                + 0.20 * row["_boundary_share_percentile"],
                4,
            )
        eligible_rows.sort(key=lambda row: (-float(row["composite_score"]), -int(row["balls"]), row["player"], row["player_id"]))
        for rank, row in enumerate(eligible_rows, start=1):
            row["rank"] = rank
            row["ranking_status"] = "Ranked"
        ranking_status = (
            f"Ranked {len(eligible_rows)} eligible batters by the confirmed composite after "
            f"the {MIN_PRESSURE_INNINGS_FOR_RANKING}-pressure-innings reliability gate and "
            f"{len(USER_EXCLUDED_PLAYERS)} user-requested exclusions."
        )
    for row in player_rows:
        row.pop("_composite_average", None)
        row.pop("_adjusted_strike_rate_percentile", None)
        row.pop("__composite_average_percentile", None)
        row.pop("_boundary_share_percentile", None)
    player_rows.sort(
        key=lambda row: (
            row["rank"] is None,
            row["rank"] if row["rank"] is not None else 0,
            -row["runs"], -row["balls"], row["player"], row["player_id"],
        )
    )

    phase_candidate_rankings, final_batting_top_ten, phase_summary = build_phase_batting_ranking(
        player_rows, matches, innings
    )

    by_name = {row["player"]: row for row in player_rows}
    audit_rows: list[dict[str, Any]] = []
    compared_fields = (
        "innings", "balls", "runs", "strike_rate", "balls_per_innings",
        "boundaries_per_100", "dot_pct", "stayed_to_16",
    )
    for reference in REFERENCE_TOP_TEN:
        computed = by_name.get(reference["player"], {})
        audit = {
            "rank": reference["rank"],
            "player": reference["player"],
            "source_player_id": computed.get("player_id"),
            "reference_status": "Compared" if computed else "No source row",
            "source_active_2026_all_venues": computed.get("active_2026_all_venues"),
            "source_recent_chase_innings": computed.get("recent_chase_innings"),
            "selection_gate_status": computed.get("selection_gate_status", "No source row"),
        }
        checks = []
        for field in compared_fields:
            ref_value = reference[field]
            actual_value = computed.get(field)
            audit[f"reference_{field}"] = ref_value
            audit[f"source_{field}"] = actual_value
            # Displayed numeric reference figures are rounded to one decimal place.
            if actual_value is None:
                checks.append(False)
            elif isinstance(ref_value, (float, int)) and not isinstance(ref_value, bool):
                checks.append(round(float(actual_value), 1) == round(float(ref_value), 1))
            else:
                checks.append(str(actual_value) == str(ref_value))
        audit["all_reference_figures_match"] = all(checks)
        audit_rows.append(audit)

    entry_timing_audit = build_raw_entry_timing_audit(competitions, matches, innings, valid_names)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_files": {name: str(RAW_DIR / name) for name in ("ball_by_ball.csv", "matches.csv", "competitions.csv")},
        "source_counts": {"raw_delivery_rows": sum(len(rows) for rows in innings.values())},
        "definition": {
            "scenario": "T20 at Indian venues; second innings only; first known pre-delivery state per chase with 2-4 wickets down, 18-42 legal balls already bowled, required rate 12-20 RPO, and runs needed > 0.",
            "anchor": "The first delivery in each chase meeting every condition; measurements start on that delivery.",
            "measurement_window": "Anchor delivery through the innings, stopping before the first unknown-legality row. Unknown-legality rows and subsequent state-unknown deliveries are excluded.",
            "batter_runs_and_balls": "Runs use the raw runs field; faced balls are known deliveries that are not wides. Byes and leg-byes are counted as one team run for target/state reconstruction, as in the confirmed source-data rule.",
            "boundary_and_dot_metrics": "Boundary events are fours plus sixes; boundaries per 100 balls and dot percentage use batter balls faced as the denominator.",
            "stayed_to_over_16": "Numerator: player was not dismissed before the 96th known legal ball. Denominator: player was at the crease before legal ball 96 and the known segment reached at least 96 legal balls. Innings without that opportunity are excluded.",
            "dismissals": "is_wicket rows excluding retire-outs, retire-hurt rows, and obstruction labels.",
            "target": "revised_target when present; otherwise first-innings raw total plus one, counting one run for each wide, no-ball, bye, or leg-bye event.",
            "rank_order": "The displayed supplied list order is a user reference, not recalculated from raw data. The supplied table does not define a clutch-specific ranking formula.",
            "composite_formula": "Raw-data rank: 50% adjusted strike-rate percentile + 30% adjusted-average percentile + 20% boundary-run-share percentile; boundary-run-share is boundary runs divided by batter runs. Adjusted SR uses a 60-ball cohort-baseline prior; adjusted average uses a 3-dismissal cohort-baseline prior. Raw figures remain displayed.",
            "phase_composite_formula": "Death-over strike rate 25%, middle-over strike rate 15%, adjusted death-minus-middle strike-rate acceleration 20%, raw runs across middle and death phases 15%, death-minus-middle boundary events per 100 batter balls 15%, and adjusted average across both phases 10%. Each component is converted to a tie-aware percentile within the eligible clutch-qualified phase cohort before weighting. Higher is better for every component.",
            "phase_tie_breaker": "Equal composite scores are ordered by more death-phase balls, then more combined middle/death runs, then player name and source ID.",
            "phase_scope": "Raw Indian-venue T20 innings 1 and 2 across the available source history; middle phase is overid 7-15 and death phase is overid 16-20. Unknown-legality rows and all later deliveries in that innings are excluded. Batter balls are non-wide known deliveries; batter runs use the raw runs field.",
            "phase_sample_rule": f"Candidates need at least {PHASE_MIN_BALLS} batter balls in both middle and death phases. Raw strike rates and averages are displayed alongside adjusted values. Adjusted phase strike rates use a {PHASE_PRIOR_BALLS}-ball cohort-baseline prior; adjusted average uses {PHASE_AVERAGE_PRIOR_DISMISSALS} prior dismissals. Raw average is not reported below 3 dismissals.",
            "final_batting_top_ten_logic": "The user's approved top seven are retained in the stated order. Positions 8-10 are filled by the highest phase-composite alternatives among the remaining clutch-qualified eligible players. The phase composite is computed for the full eligible clutch cohort, while the approved top-seven order is held fixed per user instruction.",
            "reliability_gate": f"Ranked batters need at least {MIN_PRESSURE_BALLS} pressure balls and at least {MIN_PRESSURE_INNINGS_FOR_RANKING} qualifying clutch-window innings, plus the confirmed 2026 all-venue activity and 10-chase-innings gates. Players below these gates remain visible as review samples.",
            "recent_form_window": "For each batter, latest 10 Indian-venue T20 second-innings batting innings are recomputed from raw deliveries and shown separately as form context. The composite remains based on the qualifying clutch-window innings; the recent-form figures are not mixed into the score because no extra form weight was specified.",
            "unweighted_diagnostics": "Dot percentage and survival through over 16 are shown as diagnostics but are not part of the confirmed composite score.",
            "manual_exclusions": "Rashid Khan (ID 4722), Dhruv Jurel (ID 7260), and Shashank Singh (ID 2756) are retained in the raw figures and excluded only from the final ranking at the user's request.",
            "previous_selection_gates": "The confirmed 30-ball minimum, a 2026 T20 appearance at any venue, and at least 10 known Indian-venue second-innings chase appearances apply. A 3-qualifying-pressure-innings reliability gate was added so a single strong pressure innings cannot be presented as a reliable top-ten record.",
        },
        "cohort": {
            "anchor_chases": match_count,
            "decided_anchor_chases": decided_count,
            "players_with_post_anchor_balls": sum(1 for row in player_rows if row["balls"] > 0),
            "players_meeting_30_ball_minimum": sum(1 for row in player_rows if row["balls"] >= 30),
            "players_meeting_30_ball_2026_activity_and_10_recent_chase_gates": sum(
                1 for row in player_rows
                if row["base_eligible"]
            ),
            "players_meeting_three_pressure_innings_gate": sum(
                1 for row in player_rows
                if row["base_eligible"] and row["pressure_innings_gate"]
            ),
            "players_held_for_pressure_sample": sum(
                1 for row in player_rows
                if row["base_eligible"] and not row["pressure_innings_gate"] and not row["user_excluded"]
            ),
            "players_excluded_by_user": sum(1 for row in player_rows if row["user_excluded"]),
            "players_remaining_after_user_exclusions": sum(1 for row in player_rows if row["ranking_eligible"]),
            "invalid_or_multi_name_ids_excluded": len(invalid_ids),
            "phase_eligible_players": phase_summary["phase_eligible_players"],
            "phase_candidates_available_for_replacement": phase_summary["phase_candidates_available_for_replacement"],
        },
        "ranking_status": ranking_status,
        "phase_ranking_summary": phase_summary,
        "reference_audit": {
            "rows_matching_all_figures": sum(bool(row["all_reference_figures_match"]) for row in audit_rows),
            "rows_compared": len(audit_rows),
            "status": "MATCH" if audit_rows and all(row["all_reference_figures_match"] for row in audit_rows) else "REFERENCE FIGURES DO NOT REPRODUCE FROM RAW CSVs",
        },
        "anchor_matches": anchor_output,
        "reference_top_ten": REFERENCE_TOP_TEN,
        "user_excluded_players": [
            {"player_id": player_id, "player": name, "reason": "Excluded by user review"}
            for player_id, name in USER_EXCLUDED_PLAYERS.items()
        ],
        "computed_top_ten": [row for row in player_rows if row.get("rank") is not None][:10],
        "computed_top_twenty": [row for row in player_rows if row.get("rank") is not None][:20],
        "phase_candidate_rankings": phase_candidate_rankings,
        "final_batting_top_ten": final_batting_top_ten,
        "reference_audit_rows": audit_rows,
        "entry_timing_audit": entry_timing_audit,
        "candidate_innings_audit": candidate_innings_audit,
        "player_rows": player_rows,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "clutch_batting_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(OUTPUT_DIR / "clutch_anchor_chases.csv", anchor_output)
    write_csv(OUTPUT_DIR / "clutch_batter_reference_audit.csv", audit_rows)
    write_csv(OUTPUT_DIR / "clutch_entry_timing_reference_audit.csv", entry_timing_audit["summary"])
    write_csv(OUTPUT_DIR / "clutch_entry_timing_innings.csv", entry_timing_audit["innings"])
    write_csv(OUTPUT_DIR / "clutch_batter_figures.csv", player_rows)
    write_csv(OUTPUT_DIR / "clutch_candidate_innings_audit.csv", candidate_innings_audit)
    write_csv(OUTPUT_DIR / "clutch_batting_phase_rankings.csv", phase_candidate_rankings)
    write_csv(OUTPUT_DIR / "final_batting_top_ten.csv", final_batting_top_ten)
    return report


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    report = build_clutch_report()
    from validate_clutch_batting import save_validation, validate_clutch_batting_report

    validation = validate_clutch_batting_report(report)
    report["validation"] = validation
    (OUTPUT_DIR / "clutch_batting_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    save_validation(validation)
    print(json.dumps({
        "cohort": report["cohort"],
        "reference_audit": report["reference_audit"],
        "validation": {"all_passed": validation["all_passed"], "checks_passed": validation["checks_passed"], "checks_total": validation["checks_total"]},
        "highest_runs_observations": report["player_rows"][:10],
        "outputs": [
            str(OUTPUT_DIR / "clutch_batting_report.json"),
            str(OUTPUT_DIR / "clutch_anchor_chases.csv"),
            str(OUTPUT_DIR / "clutch_entry_timing_reference_audit.csv"),
            str(OUTPUT_DIR / "clutch_entry_timing_innings.csv"),
            str(OUTPUT_DIR / "clutch_batter_reference_audit.csv"),
            str(OUTPUT_DIR / "clutch_batter_figures.csv"),
            str(OUTPUT_DIR / "clutch_candidate_innings_audit.csv"),
            str(OUTPUT_DIR / "clutch_batting_phase_rankings.csv"),
            str(OUTPUT_DIR / "final_batting_top_ten.csv"),
        ],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
