"""Rebuild and audit the Indian-venue clutch-batting window from raw CSVs."""

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

LEGAL_TYPES = {"none", "byes", "legbyes"}
ILLEGAL_TYPES = {"wide", "overstep"}
EXTRA_RUN_TYPES = ILLEGAL_TYPES | {"byes", "legbyes"}
DISMISSAL_EXCLUSIONS = {
    "retire out", "retired out", "retire hurt", "retired hurt",
    "obstracting the field", "obstructing the field",
}
UNKNOWN_NAMES = {"", "unknown", "unknown player", "unknown batter", "unknown bowler"}
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
    recent_chase_matches: dict[int, set[int]] = defaultdict(set)
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
            if state_known and remaining > 0 and runs_needed > 0:
                striker_id = integer(delivery.get("striker_id"), -1)
                if striker_id in valid_names:
                    recent_chase_matches[striker_id].add(match_id)
                dismissed_id = integer(delivery.get("dismissed_player_id"), -1)
                if batter_dismissal(delivery) and dismissed_id in valid_names:
                    recent_chase_matches[dismissed_id].add(match_id)
            if not state_known:
                break
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
                })
                batter_faced = kind != "wide"
                if batter_faced:
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
            "boundaries_per_100": round((stats["fours"] + stats["sixes"]) * 100 / balls, 1) if balls else None,
            "dots": int(stats["dots"]),
            "dot_pct": round(stats["dots"] * 100 / balls, 1) if balls else None,
            "dismissals": int(stats["dismissals"]),
            "stayed_to_16": f"{stats['stayed_to_16_innings']} of {stats['stay_eligible_innings']}",
            "stay_eligible_innings": int(stats["stay_eligible_innings"]),
            "stayed_to_16_innings": int(stats["stayed_to_16_innings"]),
            "sample_status": "Eligible sample" if balls >= 30 else "Review sample",
            "active_2026_all_venues": stats["player_id"] in active_2026_ids,
            "recent_chase_innings": len(recent_chase_matches.get(stats["player_id"], set())),
            "selection_gate_status": (
                "Not active in 2026" if stats["player_id"] not in active_2026_ids
                else "Review recent sample" if len(recent_chase_matches.get(stats["player_id"], set())) < 10
                else "10+ chase innings available"
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
        row["boundary_share"] = round(row["boundaries"] * 100 / balls, 4) if balls else 0.0
        row["base_eligible"] = bool(
            balls >= 30 and row["active_2026_all_venues"] and row["recent_chase_innings"] >= 10
        )
        row["ranking_eligible"] = row["base_eligible"] and not row["user_excluded"]
        row["rank"] = None
        row["composite_score"] = None
        row["ranking_status"] = (
            row["exclusion_reason"] if row["user_excluded"]
            else "Eligible for ranking" if row["ranking_eligible"]
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
            "composite_formula": "Raw-data rank: 50% adjusted strike-rate percentile + 30% adjusted-average percentile + 20% boundary-share percentile; adjusted SR uses a 60-ball cohort-baseline prior; adjusted average uses a 3-dismissal cohort-baseline prior. Raw figures remain displayed. Players need 30 balls, 2026 all-venue T20 activity, and at least 10 known chase innings; cohort needs 20 decided chases and 10 eligible players.",
            "unweighted_diagnostics": "Dot percentage and survival through over 16 are shown as diagnostics but are not part of the confirmed composite score.",
            "manual_exclusions": "Rashid Khan (ID 4722), Dhruv Jurel (ID 7260), and Shashank Singh (ID 2756) are retained in the raw figures and excluded only from the final ranking at the user's request.",
            "previous_selection_gates": "The previously confirmed 30-ball minimum, a 2026 T20 appearance at any venue, and at least 10 known second-innings chase appearances are shown separately as eligibility flags; they do not change raw figures displayed here.",
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
            "players_excluded_by_user": sum(1 for row in player_rows if row["user_excluded"]),
            "players_remaining_after_user_exclusions": sum(1 for row in player_rows if row["ranking_eligible"]),
            "invalid_or_multi_name_ids_excluded": len(invalid_ids),
        },
        "ranking_status": ranking_status,
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
    return report


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    report = build_clutch_report()
    print(json.dumps({
        "cohort": report["cohort"],
        "reference_audit": report["reference_audit"],
        "highest_runs_observations": report["player_rows"][:10],
        "outputs": [
            str(OUTPUT_DIR / "clutch_batting_report.json"),
            str(OUTPUT_DIR / "clutch_anchor_chases.csv"),
            str(OUTPUT_DIR / "clutch_entry_timing_reference_audit.csv"),
            str(OUTPUT_DIR / "clutch_entry_timing_innings.csv"),
            str(OUTPUT_DIR / "clutch_batter_reference_audit.csv"),
            str(OUTPUT_DIR / "clutch_batter_figures.csv"),
            str(OUTPUT_DIR / "clutch_candidate_innings_audit.csv"),
        ],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
