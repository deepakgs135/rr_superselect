"""Independent raw-source recount for the Indian clutch-batting leaderboard."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = APP_DIR.parent / "Raw_Data"
OUTPUT_DIR = APP_DIR / "data" / "pressure_report"
VALIDATION_PATH = OUTPUT_DIR / "clutch_batting_validation.json"

LEGAL = {"none", "byes", "legbyes"}
ILLEGAL = {"wide", "overstep"}
EXTRA_RUN = ILLEGAL | {"byes", "legbyes"}
UNKNOWN = {"", "other", "penalty"}
DISMISSAL_EXCLUSIONS = {"retire out", "retired out", "retire hurt", "retired hurt", "obstracting the field", "obstructing the field"}
UNKNOWN_NAMES = {"", "unknown", "unknown player", "unknown batter", "unknown bowler"}
USER_EXCLUDED = {4722, 7260, 2756}
PHASE_MIN_BALLS = 30
PHASE_PRIOR_BALLS = 60
PHASE_AVERAGE_PRIOR_DISMISSALS = 3
APPROVED_TOP_SEVEN = [7897, 3330, 3125, 2639, 4708, 5039, 6396]
PHASE_WEIGHTS = {
    "death_phase_adjusted_strike_rate": 0.25,
    "middle_phase_adjusted_strike_rate": 0.15,
    "phase_sr_acceleration": 0.20,
    "phase_total_runs": 0.15,
    "phase_boundary_rate_acceleration": 0.15,
    "phase_average_adjusted": 0.10,
}
WEIGHTS = {
    "adjusted_strike_rate": 0.50,
    "_composite_average": 0.30,
    "boundary_share": 0.20,
}
METRIC_COUNTS = (
    "runs", "balls", "fours", "sixes", "dots", "dismissals",
    "stay_eligible_innings", "stayed_to_16_innings",
    "came_before_anchor_innings", "entered_at_or_after_anchor_innings",
)


def _read(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def _int(value: Any, default: int = 0) -> int:
    try:
        raw = str(value or "").strip()
        return int(float(raw)) if raw else default
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return _text(value).casefold()


def _truth(value: Any) -> bool:
    return _norm(value) in {"1", "true", "yes"}


def _known(kind: str) -> bool:
    return kind in LEGAL or kind in ILLEGAL


def _team_runs(row: dict[str, Any]) -> int:
    return _int(row.get("runs")) + int(_norm(row.get("extras_type")) in EXTRA_RUN)


def _dismissal(row: dict[str, Any]) -> bool:
    return _truth(row.get("is_wicket")) and _norm(row.get("dismissal_type")) not in DISMISSAL_EXCLUSIONS


def _empty_stats() -> dict[str, Any]:
    return {
        "player_id": 0,
        "player": "",
        "innings_matches": set(),
        "matches": set(),
        "runs": 0,
        "balls": 0,
        "fours": 0,
        "sixes": 0,
        "dots": 0,
        "dismissals": 0,
        "stay_eligible_innings": 0,
        "stayed_to_16_innings": 0,
        "entry_overs": [],
        "batting_orders": [],
        "came_before_anchor_innings": 0,
        "entered_at_or_after_anchor_innings": 0,
    }


def _same(actual: Any, expected: Any) -> bool:
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return abs(float(actual) - float(expected)) <= 0.00011
    return actual == expected


def validate_clutch_batting_report(report: dict[str, Any]) -> dict[str, Any]:
    competitions = {
        _int(row.get("comp_id"), -1): row for row in _read(RAW_DIR / "competitions.csv")
    }
    matches: dict[int, dict[str, Any]] = {}
    for row in _read(RAW_DIR / "matches.csv"):
        competition = competitions.get(_int(row.get("comp_id"), -1), {})
        matches[_int(row.get("match_id"), -1)] = {
            **row,
            "format": _text(competition.get("match_format")).upper(),
            "season": _text(competition.get("season")),
            "competition_name": _text(competition.get("comp_name")),
            "revised_target_value": _int(row.get("revised_target"), -1) if _text(row.get("revised_target")) else None,
        }

    innings: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    names_by_id: dict[int, set[str]] = defaultdict(set)
    raw_rows = 0
    for source_order, row in enumerate(_read(RAW_DIR / "ball_by_ball.csv")):
        raw_rows += 1
        row["_source_order"] = source_order
        match_id = _int(row.get("match_id"), -1)
        innings_no = _int(row.get("innings"), -1)
        innings[(match_id, innings_no)].append(row)
        for id_field, name_field in (
            ("striker_id", "striker_name"),
            ("non_striker_id", "non_striker_name"),
            ("bowler_id", "bowler_name"),
        ):
            player_id = _int(row.get(id_field), -1)
            if player_id > 0:
                names_by_id[player_id].add(_text(row.get(name_field)))
    for rows in innings.values():
        rows.sort(key=lambda row: (
            _int(row.get("overid"), -1),
            _int(row.get("innings_ball_num"), -1),
            _int(row.get("over_ball_num"), -1),
            _int(row.get("_source_order"), -1),
        ))

    invalid_ids = {
        player_id for player_id, names in names_by_id.items()
        if len(names) != 1 or any(name.casefold() in UNKNOWN_NAMES for name in names)
    }
    valid_names = {
        player_id: next(iter(names))
        for player_id, names in names_by_id.items() if player_id not in invalid_ids
    }
    first_totals = {
        match_id: sum(_team_runs(row) for row in rows)
        for (match_id, innings_no), rows in innings.items()
        if innings_no == 1 and matches.get(match_id, {}).get("format") == "T20"
    }

    active_2026: set[int] = set()
    chase_form_by_player: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
    for match_id, meta in matches.items():
        if meta.get("format") != "T20":
            continue
        if meta.get("season") == "2026":
            for innings_no in (1, 2):
                for delivery in innings.get((match_id, innings_no), []):
                    for key in ("striker_id", "non_striker_id"):
                        player_id = _int(delivery.get(key), -1)
                        if player_id in valid_names:
                            active_2026.add(player_id)

        if _norm(meta.get("venue_country")) != "india":
            continue

        chase = innings.get((match_id, 2), [])
        target = meta.get("revised_target_value")
        if target is None and innings.get((match_id, 1)):
            target = first_totals.get(match_id, 0) + 1
        if target is None or target < 0:
            continue
        score = legal_balls = 0
        state_known = True
        for delivery in chase:
            kind = _norm(delivery.get("extras_type"))
            if not _known(kind):
                state_known = False
            balls_left = 120 - legal_balls
            runs_needed = int(target) - score
            if not state_known:
                break
            if balls_left <= 0 or runs_needed <= 0:
                break

            striker_id = _int(delivery.get("striker_id"), -1)
            if striker_id in valid_names:
                form = chase_form_by_player[striker_id].setdefault(match_id, {
                    "match_id": match_id,
                    "match_date": _text(meta.get("match_date")),
                    "runs": 0,
                    "balls": 0,
                    "fours": 0,
                    "sixes": 0,
                    "dots": 0,
                    "dismissals": 0,
                })
                if kind != "wide":
                    form["balls"] += 1
                    form["runs"] += _int(delivery.get("runs"))
                    form["fours"] += int(_truth(delivery.get("is_four")))
                    form["sixes"] += int(_truth(delivery.get("is_six")))
                    form["dots"] += int(_int(delivery.get("runs")) == 0)
            dismissed_id = _int(delivery.get("dismissed_player_id"), -1)
            if _dismissal(delivery) and dismissed_id in valid_names:
                form = chase_form_by_player[dismissed_id].setdefault(match_id, {
                    "match_id": match_id,
                    "match_date": _text(meta.get("match_date")),
                    "runs": 0,
                    "balls": 0,
                    "fours": 0,
                    "sixes": 0,
                    "dots": 0,
                    "dismissals": 0,
                })
                form["dismissals"] += 1
            score += _team_runs(delivery)
            legal_balls += int(kind in LEGAL)

    anchors: list[dict[str, Any]] = []
    for match_id, meta in matches.items():
        if meta.get("format") != "T20" or _norm(meta.get("venue_country")) != "india":
            continue
        first = innings.get((match_id, 1), [])
        chase = innings.get((match_id, 2), [])
        if not first or not chase:
            continue
        target = meta.get("revised_target_value")
        if target is None:
            target = first_totals.get(match_id, 0) + 1
        if target < 0:
            continue
        runs = legal_balls = wickets = 0
        known = True
        for index, delivery in enumerate(chase):
            kind = _norm(delivery.get("extras_type"))
            if not _known(kind):
                known = False
            remaining = 120 - legal_balls
            needed = int(target) - runs
            rrr = needed * 6 / remaining if remaining > 0 else None
            if (
                known and 1 <= remaining <= 120 and 18 <= legal_balls <= 42
                and 2 <= wickets <= 4 and needed > 0 and rrr is not None and 12 <= rrr <= 20
            ):
                result = _norm(meta.get("result"))
                winner = _int(meta.get("win_team_id"), 0)
                decided = winner > 0 and not any(term in result for term in ("tie", "no result", "abandoned", "cancelled"))
                anchors.append({
                    "match_id": match_id,
                    "date": _text(meta.get("match_date")),
                    "anchor_index": index,
                    "legal_balls": legal_balls,
                    "decided": decided,
                    "deliveries": chase,
                })
                break
            if not known:
                break
            runs += _team_runs(delivery)
            legal_balls += int(kind in LEGAL)
            wickets += int(_dismissal(delivery))

    stats_by_id: dict[int, dict[str, Any]] = {}
    for anchor in anchors:
        deliveries = anchor["deliveries"]
        anchor_index = anchor["anchor_index"]
        entry_map: dict[int, dict[str, Any]] = {}
        for index, delivery in enumerate(deliveries):
            kind = _norm(delivery.get("extras_type"))
            if not _known(kind):
                break
            striker = _int(delivery.get("striker_id"), -1)
            non_striker = _int(delivery.get("non_striker_id"), -1)
            for player_id in (striker, non_striker):
                if player_id in valid_names:
                    entry_map.setdefault(player_id, {
                        "index": index,
                        "over": _int(delivery.get("overid"), 0),
                        "order": None,
                    })
            if striker in valid_names and entry_map[striker]["order"] is None:
                entry_map[striker]["order"] = _int(delivery.get("batting_order"), 0)

        known_segment = []
        for delivery in deliveries[anchor_index:]:
            kind = _norm(delivery.get("extras_type"))
            if not _known(kind):
                break
            known_segment.append(delivery)

        inning_state: dict[int, dict[str, Any]] = {}
        legal_before = anchor["legal_balls"]
        for delivery in known_segment:
            kind = _norm(delivery.get("extras_type"))
            striker = _int(delivery.get("striker_id"), -1)
            if striker in valid_names:
                state = inning_state.setdefault(striker, {
                    "appeared": False, "dismissed_before_96": False,
                    "appeared_before_96": False, "entry_recorded": False,
                })
                state["appeared"] = True
                player = stats_by_id.setdefault(striker, _empty_stats())
                player["player_id"] = striker
                player["player"] = valid_names[striker]
                if kind != "wide":
                    player["innings_matches"].add(anchor["match_id"])
                    player["matches"].add(anchor["match_id"])
                    player["balls"] += 1
                    player["runs"] += _int(delivery.get("runs"))
                    player["fours"] += int(_truth(delivery.get("is_four")))
                    player["sixes"] += int(_truth(delivery.get("is_six")))
                    player["dots"] += int(_int(delivery.get("runs")) == 0)
                    if not state["entry_recorded"]:
                        entry = entry_map.get(striker)
                        if entry is not None:
                            player["entry_overs"].append(entry["over"])
                            if entry["index"] < anchor_index:
                                player["came_before_anchor_innings"] += 1
                            else:
                                player["entered_at_or_after_anchor_innings"] += 1
                            if entry["order"]:
                                player["batting_orders"].append(entry["order"])
                        state["entry_recorded"] = True
                    if legal_before < 96:
                        state["appeared_before_96"] = True

            if legal_before < 96:
                for field in ("striker_id", "non_striker_id"):
                    player_id = _int(delivery.get(field), -1)
                    if player_id in valid_names:
                        inning_state.setdefault(player_id, {
                            "appeared": False, "dismissed_before_96": False,
                            "appeared_before_96": False, "entry_recorded": False,
                        })["appeared_before_96"] = True

            dismissed_id = _int(delivery.get("dismissed_player_id"), -1)
            if _dismissal(delivery) and dismissed_id in valid_names:
                player = stats_by_id.setdefault(dismissed_id, _empty_stats())
                player["player_id"] = dismissed_id
                player["player"] = valid_names[dismissed_id]
                player["dismissals"] += 1
                state = inning_state.setdefault(dismissed_id, {
                    "appeared": False, "dismissed_before_96": False,
                    "appeared_before_96": False, "entry_recorded": False,
                })
                if legal_before < 96:
                    state["dismissed_before_96"] = True
            legal_before += int(kind in LEGAL)

        if legal_before >= 96:
            for player_id, state in inning_state.items():
                if state["appeared_before_96"]:
                    player = stats_by_id.setdefault(player_id, _empty_stats())
                    player["player_id"] = player_id
                    player["player"] = valid_names[player_id]
                    player["stay_eligible_innings"] += 1
                    player["stayed_to_16_innings"] += int(not state["dismissed_before_96"])

        for player_id, state in inning_state.items():
            if state["appeared"]:
                stats_by_id[player_id]["innings_matches"].add(anchor["match_id"])
                stats_by_id[player_id]["matches"].add(anchor["match_id"])

    rows: list[dict[str, Any]] = []
    for player_id, stats in stats_by_id.items():
        balls = int(stats["balls"])
        innings_count = len(stats["innings_matches"])
        chase_innings = [
            item for item in chase_form_by_player.get(player_id, {}).values()
            if int(item["balls"]) > 0
        ]
        chase_innings.sort(key=lambda item: (item["match_date"], item["match_id"]), reverse=True)
        latest_ten = chase_innings[:10]
        recent_runs = sum(int(item["runs"]) for item in latest_ten)
        recent_balls = sum(int(item["balls"]) for item in latest_ten)
        recent_dismissals = sum(int(item["dismissals"]) for item in latest_ten)
        recent_boundary_runs = sum(int(item["fours"]) * 4 + int(item["sixes"]) * 6 for item in latest_ten)
        recent_boundaries = sum(int(item["fours"]) + int(item["sixes"]) for item in latest_ten)
        recent_dots = sum(int(item["dots"]) for item in latest_ten)
        entries = sorted(int(value) for value in stats["entry_overs"])
        if entries:
            middle = len(entries) // 2
            median_entry = entries[middle] if len(entries) % 2 else (entries[middle - 1] + entries[middle]) / 2
        else:
            median_entry = None
        order_counts = Counter(stats["batting_orders"])
        row = {
            "player_id": player_id,
            "player": stats["player"],
            "innings": innings_count,
            "matches": len(stats["matches"]),
            "balls": balls,
            "runs": stats["runs"],
            "strike_rate": round(stats["runs"] * 100 / balls, 1) if balls else None,
            "balls_per_innings": round(balls / innings_count, 1) if innings_count else None,
            "fours": stats["fours"],
            "sixes": stats["sixes"],
            "boundaries": stats["fours"] + stats["sixes"],
            "boundary_runs": stats["fours"] * 4 + stats["sixes"] * 6,
            "boundaries_per_100": round((stats["fours"] + stats["sixes"]) * 100 / balls, 1) if balls else None,
            "dots": stats["dots"],
            "dot_pct": round(stats["dots"] * 100 / balls, 1) if balls else None,
            "dismissals": stats["dismissals"],
            "stay_eligible_innings": stats["stay_eligible_innings"],
            "stayed_to_16_innings": stats["stayed_to_16_innings"],
            "entry_overs": ", ".join(str(value) for value in entries),
            "median_entry_over": median_entry,
            "typical_batting_order": order_counts.most_common(1)[0][0] if order_counts else None,
            "came_before_anchor_innings": stats["came_before_anchor_innings"],
            "entered_at_or_after_anchor_innings": stats["entered_at_or_after_anchor_innings"],
            "active_2026_all_venues": player_id in active_2026,
            "recent_chase_innings": len(chase_innings),
            "recent_form_innings": len(latest_ten),
            "recent_form_window_start": latest_ten[-1]["match_date"] if latest_ten else None,
            "recent_form_window_end": latest_ten[0]["match_date"] if latest_ten else None,
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
            "user_excluded": player_id in USER_EXCLUDED,
        }
        row["average"] = round(row["runs"] / row["dismissals"], 1) if row["dismissals"] >= 3 else "Not reported"
        row["boundary_share"] = round(row["boundary_runs"] * 100 / row["runs"], 4) if row["runs"] else 0.0
        row["base_eligible"] = (
            balls >= 30 and row["active_2026_all_venues"] and row["recent_chase_innings"] >= 10
        )
        row["pressure_innings_gate"] = innings_count >= 3
        row["ranking_eligible"] = row["base_eligible"] and row["pressure_innings_gate"] and not row["user_excluded"]
        rows.append(row)

    all_runs = sum(row["runs"] for row in rows)
    all_balls = sum(row["balls"] for row in rows)
    all_dismissals = sum(row["dismissals"] for row in rows)
    base_sr = all_runs * 100 / all_balls if all_balls else 0
    base_average = all_runs / all_dismissals if all_dismissals else 0
    for row in rows:
        balls = row["balls"]
        dismissals = row["dismissals"]
        raw_average = row["runs"] / dismissals if dismissals else None
        row["adjusted_strike_rate"] = round(
            ((row["runs"] * 100 / balls) * balls + base_sr * 60) / (balls + 60), 4
        ) if balls else round(base_sr, 4)
        row["_composite_average"] = (
            (raw_average * dismissals + base_average * 3) / (dismissals + 3)
            if raw_average is not None else base_average
        )

    eligible = [row for row in rows if row["ranking_eligible"]]
    def percentile(field: str) -> None:
        ordered = sorted(eligible, key=lambda row: (-float(row[field]), row["player"], row["player_id"]))
        index = 0
        while index < len(ordered):
            end = index + 1
            while end < len(ordered) and float(ordered[end][field]) == float(ordered[index][field]):
                end += 1
            average_rank = ((index + 1) + end) / 2
            value = 100.0 if len(ordered) == 1 else 100 * (len(ordered) - average_rank) / (len(ordered) - 1)
            for item in ordered[index:end]:
                item[f"_{field}_percentile"] = value
            index = end

    for field in ("adjusted_strike_rate", "_composite_average", "boundary_share"):
        percentile(field)
    for row in eligible:
        row["composite_score"] = round(sum(row[f"_{field}_percentile"] * weight for field, weight in WEIGHTS.items()), 4)
    eligible.sort(key=lambda row: (-row["composite_score"], -row["balls"], row["player"], row["player_id"]))
    for rank, row in enumerate(eligible, 1):
        row["rank"] = rank

    # Independent second pass for the proposed middle-to-death batting score.
    phase_raw: dict[int, dict[str, dict[str, Any]]] = defaultdict(lambda: {
        phase: {"balls": 0, "runs": 0, "fours": 0, "sixes": 0, "dismissals": 0, "innings": set()}
        for phase in ("middle", "death")
    })
    raw_player_ids = {int(row["player_id"]) for row in rows}
    for (match_id, innings_no), deliveries in innings.items():
        meta = matches.get(match_id, {})
        if (
            meta.get("format") != "T20"
            or _norm(meta.get("venue_country")) != "india"
            or innings_no not in (1, 2)
        ):
            continue
        for delivery in deliveries:
            kind = _norm(delivery.get("extras_type"))
            if not _known(kind):
                break
            over = _int(delivery.get("overid"), 0)
            if 7 <= over <= 15:
                phase = "middle"
            elif 16 <= over <= 20:
                phase = "death"
            else:
                continue
            striker_id = _int(delivery.get("striker_id"), -1)
            if striker_id in raw_player_ids and kind != "wide":
                stats = phase_raw[striker_id][phase]
                stats["balls"] += 1
                stats["runs"] += _int(delivery.get("runs"))
                stats["fours"] += int(_truth(delivery.get("is_four")))
                stats["sixes"] += int(_truth(delivery.get("is_six")))
                stats["innings"].add((match_id, innings_no))
            dismissed_id = _int(delivery.get("dismissed_player_id"), -1)
            if dismissed_id in raw_player_ids and _dismissal(delivery):
                phase_raw[dismissed_id][phase]["dismissals"] += 1

    for row in rows:
        player_id = int(row["player_id"])
        middle = phase_raw[player_id]["middle"]
        death = phase_raw[player_id]["death"]
        middle_balls, death_balls = int(middle["balls"]), int(death["balls"])
        middle_runs, death_runs = int(middle["runs"]), int(death["runs"])
        middle_boundaries = int(middle["fours"] + middle["sixes"])
        death_boundaries = int(death["fours"] + death["sixes"])
        phase_runs = middle_runs + death_runs
        phase_dismissals = int(middle["dismissals"] + death["dismissals"])
        middle_boundary_rate = middle_boundaries * 100 / middle_balls if middle_balls else None
        death_boundary_rate = death_boundaries * 100 / death_balls if death_balls else None
        row.update({
            "middle_phase_innings": len(middle["innings"]),
            "middle_phase_balls": middle_balls,
            "middle_phase_runs": middle_runs,
            "middle_phase_fours": int(middle["fours"]),
            "middle_phase_sixes": int(middle["sixes"]),
            "middle_phase_dismissals": int(middle["dismissals"]),
            "middle_phase_strike_rate": round(middle_runs * 100 / middle_balls, 2) if middle_balls else None,
            "middle_phase_boundary_rate": round(middle_boundary_rate, 2) if middle_boundary_rate is not None else None,
            "death_phase_innings": len(death["innings"]),
            "death_phase_balls": death_balls,
            "death_phase_runs": death_runs,
            "death_phase_fours": int(death["fours"]),
            "death_phase_sixes": int(death["sixes"]),
            "death_phase_dismissals": int(death["dismissals"]),
            "death_phase_strike_rate": round(death_runs * 100 / death_balls, 2) if death_balls else None,
            "death_phase_boundary_rate": round(death_boundary_rate, 2) if death_boundary_rate is not None else None,
            "phase_total_runs": phase_runs,
            "phase_total_dismissals": phase_dismissals,
            "phase_average_raw": round(phase_runs / phase_dismissals, 2) if phase_dismissals >= 3 else "Not reported",
            "phase_boundary_rate_acceleration": round(death_boundary_rate - middle_boundary_rate, 2)
            if middle_boundary_rate is not None and death_boundary_rate is not None else None,
            "phase_sample_status": "Eligible phase sample"
            if middle_balls >= PHASE_MIN_BALLS and death_balls >= PHASE_MIN_BALLS
            else "Review sample: fewer than 30 balls in a phase",
        })

    phase_eligible = [
        row for row in rows
        if row["ranking_eligible"]
        and row["middle_phase_balls"] >= PHASE_MIN_BALLS
        and row["death_phase_balls"] >= PHASE_MIN_BALLS
    ]
    mid_balls = sum(row["middle_phase_balls"] for row in phase_eligible)
    mid_runs = sum(row["middle_phase_runs"] for row in phase_eligible)
    death_balls = sum(row["death_phase_balls"] for row in phase_eligible)
    death_runs = sum(row["death_phase_runs"] for row in phase_eligible)
    baseline_phase_runs = sum(row["phase_total_runs"] for row in phase_eligible)
    baseline_phase_dismissals = sum(row["phase_total_dismissals"] for row in phase_eligible)
    baseline_mid_sr = mid_runs * 100 / mid_balls if mid_balls else 0.0
    baseline_death_sr = death_runs * 100 / death_balls if death_balls else 0.0
    baseline_phase_average = baseline_phase_runs / baseline_phase_dismissals if baseline_phase_dismissals else 0.0
    for row in rows:
        middle_balls = int(row["middle_phase_balls"])
        death_balls = int(row["death_phase_balls"])
        middle_runs = int(row["middle_phase_runs"])
        death_runs = int(row["death_phase_runs"])
        phase_runs = int(row["phase_total_runs"])
        phase_dismissals = int(row["phase_total_dismissals"])
        row["middle_phase_adjusted_strike_rate"] = round(
            (middle_runs + PHASE_PRIOR_BALLS * baseline_mid_sr / 100) * 100 / (middle_balls + PHASE_PRIOR_BALLS), 4
        ) if middle_balls else round(baseline_mid_sr, 4)
        row["death_phase_adjusted_strike_rate"] = round(
            (death_runs + PHASE_PRIOR_BALLS * baseline_death_sr / 100) * 100 / (death_balls + PHASE_PRIOR_BALLS), 4
        ) if death_balls else round(baseline_death_sr, 4)
        row["phase_sr_acceleration"] = round(
            row["death_phase_adjusted_strike_rate"] - row["middle_phase_adjusted_strike_rate"], 4
        )
        row["phase_average_adjusted"] = round(
            (phase_runs + PHASE_AVERAGE_PRIOR_DISMISSALS * baseline_phase_average)
            / (phase_dismissals + PHASE_AVERAGE_PRIOR_DISMISSALS), 4
        )
        row["phase_weighted_score"] = None
        row["phase_weighted_rank"] = None
        for metric in PHASE_WEIGHTS:
            row[f"{metric}_percentile"] = None
            row[f"{metric}_points"] = None

    def phase_percentile(field: str) -> None:
        ordered = sorted(phase_eligible, key=lambda row: (-float(row[field]), row["player"], row["player_id"]))
        index = 0
        while index < len(ordered):
            end = index + 1
            while end < len(ordered) and float(ordered[end][field]) == float(ordered[index][field]):
                end += 1
            average_rank = ((index + 1) + end) / 2
            value = 100.0 if len(ordered) == 1 else 100.0 * (len(ordered) - average_rank) / (len(ordered) - 1)
            for tied in ordered[index:end]:
                tied[f"_{field}_percentile"] = value
            index = end

    for field in PHASE_WEIGHTS:
        if phase_eligible:
            phase_percentile(field)
    phase_eligible.sort(key=lambda row: (
        -sum(float(row.get(f"_{field}_percentile", 0.0)) * weight for field, weight in PHASE_WEIGHTS.items()),
        -int(row["death_phase_balls"]), -int(row["phase_total_runs"]), row["player"], row["player_id"],
    ))
    phase_cohort_can_publish_ranks = len(phase_eligible) >= 10
    for rank, row in enumerate(phase_eligible, 1):
        row["phase_weighted_rank"] = rank if phase_cohort_can_publish_ranks else None
        row["phase_weighted_score"] = round(sum(
            float(row[f"_{field}_percentile"]) * weight for field, weight in PHASE_WEIGHTS.items()
        ), 4)
        for field in PHASE_WEIGHTS:
            row[f"{field}_percentile"] = round(float(row[f"_{field}_percentile"]), 4)
            row[f"{field}_points"] = round(float(row[f"{field}_percentile"]) * PHASE_WEIGHTS[field], 4)
            row.pop(f"_{field}_percentile", None)

    rows_by_id = {int(row["player_id"]): row for row in rows}
    final_ids = [player_id for player_id in APPROVED_TOP_SEVEN if player_id in rows_by_id and rows_by_id[player_id]["ranking_eligible"]]
    phase_replacements = [row for row in phase_eligible if int(row["player_id"]) not in set(APPROVED_TOP_SEVEN)]
    independent_final_top_ten = (
        final_ids + [int(row["player_id"]) for row in phase_replacements[:max(0, 10 - len(final_ids))]]
        if phase_cohort_can_publish_ranks else []
    )

    checks: list[dict[str, Any]] = []
    def check(name: str, computed: Any, expected: Any) -> None:
        checks.append({"check": name, "computed": computed, "reference": expected, "passed": _same(computed, expected)})

    cohort = report.get("cohort", {})
    check("Raw ball-by-ball rows read", raw_rows, report.get("source_counts", {}).get("raw_delivery_rows"))
    check("Qualifying Indian clutch chases", len(anchors), cohort.get("anchor_chases"))
    check("Decided qualifying chases", sum(anchor["decided"] for anchor in anchors), cohort.get("decided_anchor_chases"))
    check("Invalid or multi-name player IDs excluded", len(invalid_ids), cohort.get("invalid_or_multi_name_ids_excluded"))
    saved_eligible_ids = sorted(
        int(row["player_id"]) for row in report.get("player_rows", []) if row.get("ranking_eligible")
    )
    check("Eligible player IDs", sorted(row["player_id"] for row in eligible), saved_eligible_ids)
    check("Top 10 player IDs in order", [row["player_id"] for row in eligible[:10]], [int(row["player_id"]) for row in report.get("computed_top_ten", [])])
    saved_phase_rankings = report.get("phase_candidate_rankings", [])
    saved_final_rows = report.get("final_batting_top_ten", [])
    check("Phase-eligible player count", len(phase_eligible), report.get("phase_ranking_summary", {}).get("phase_eligible_players"))
    check("Phase-weighted ranking IDs in order", [int(row["player_id"]) for row in phase_eligible], [int(row["player_id"]) for row in saved_phase_rankings])
    check("Approved top seven kept in requested order", APPROVED_TOP_SEVEN, [int(row["player_id"]) for row in saved_final_rows[:7]])
    check("Final batting top 10 IDs", independent_final_top_ten, [int(row["player_id"]) for row in saved_final_rows])

    saved_rows = {int(row["player_id"]): row for row in report.get("player_rows", [])}
    compare_fields = (
        "innings", "matches", "balls", "runs", "strike_rate", "balls_per_innings", "fours", "sixes",
        "boundaries", "boundary_runs", "boundaries_per_100", "dots", "dot_pct", "dismissals",
        "stay_eligible_innings", "stayed_to_16_innings", "entry_overs", "median_entry_over",
        "typical_batting_order", "came_before_anchor_innings", "entered_at_or_after_anchor_innings",
        "recent_chase_innings", "recent_form_innings", "recent_form_window_start", "recent_form_window_end",
        "recent_form_runs", "recent_form_balls", "recent_form_strike_rate", "recent_form_dismissals",
        "recent_form_average", "recent_form_boundary_runs", "recent_form_boundary_share",
        "recent_form_boundaries_per_100", "recent_form_dot_balls", "recent_form_dot_pct",
        "average", "boundary_share", "active_2026_all_venues", "base_eligible",
        "pressure_innings_gate", "ranking_eligible",
        "middle_phase_innings", "middle_phase_balls", "middle_phase_runs", "middle_phase_fours",
        "middle_phase_sixes", "middle_phase_dismissals", "middle_phase_strike_rate",
        "middle_phase_boundary_rate", "death_phase_innings", "death_phase_balls", "death_phase_runs",
        "death_phase_fours", "death_phase_sixes", "death_phase_dismissals", "death_phase_strike_rate",
        "death_phase_boundary_rate", "phase_total_runs", "phase_total_dismissals", "phase_average_raw",
        "phase_boundary_rate_acceleration", "phase_sample_status", "middle_phase_adjusted_strike_rate",
        "death_phase_adjusted_strike_rate", "phase_sr_acceleration", "phase_average_adjusted",
        "phase_weighted_score", "phase_weighted_rank",
        *[f"{field}_{suffix}" for field in PHASE_WEIGHTS for suffix in ("percentile", "points")],
    )
    check("Raw-source player ID coverage", sorted(row["player_id"] for row in rows), sorted(saved_rows))
    for raw_row in rows:
        saved = saved_rows.get(raw_row["player_id"], {})
        for field in compare_fields:
            check(f"Player {raw_row['player_id']} {field}", saved.get(field), raw_row.get(field))
    for raw_row in eligible:
        saved = saved_rows.get(raw_row["player_id"], {})
        check(f"Player {raw_row['player_id']} rank", saved.get("rank"), raw_row.get("rank"))
        check(f"Player {raw_row['player_id']} adjusted strike rate", saved.get("adjusted_strike_rate"), raw_row.get("adjusted_strike_rate"))
        check(f"Player {raw_row['player_id']} adjusted average", saved.get("adjusted_average"), round(raw_row["_composite_average"], 4) if raw_row["dismissals"] >= 3 else "Not reported")
        check(f"Player {raw_row['player_id']} composite score", saved.get("composite_score"), raw_row.get("composite_score"))

    saved_phase_by_id = {int(row["player_id"]): row for row in saved_phase_rankings}
    for raw_row in phase_eligible:
        saved = saved_phase_by_id.get(int(raw_row["player_id"]), {})
        check(f"Phase rank for player {raw_row['player_id']}", saved.get("phase_weighted_rank"), raw_row.get("phase_weighted_rank"))
        check(f"Phase score for player {raw_row['player_id']}", saved.get("phase_weighted_score"), raw_row.get("phase_weighted_score"))

    saved_final_by_id = {int(row["player_id"]): row for row in saved_final_rows}
    for player_id in independent_final_top_ten:
        raw_row = rows_by_id.get(player_id, {})
        saved = saved_final_by_id.get(player_id, {})
        check(f"Final rank for player {player_id}", saved.get("final_rank"), independent_final_top_ten.index(player_id) + 1)
        check(f"Final-list player name for {player_id}", saved.get("player"), raw_row.get("player"))

    passed = sum(bool(item["passed"]) for item in checks)
    return {
        "method": "Independent second-pass raw ball-by-ball reconstruction; uses only raw ball_by_ball.csv, matches.csv, and competitions.csv and does not import the batting report builder.",
        "source_files": report.get("source_files", {}),
        "raw_delivery_rows": raw_rows,
        "qualifying_anchor_chases": len(anchors),
        "ranked_players": len(eligible),
        "phase_eligible_players": len(phase_eligible),
        "final_batting_top_ten_ids": independent_final_top_ten,
        "checks_passed": passed,
        "checks_total": len(checks),
        "all_passed": passed == len(checks),
        "checks": checks,
        "top_ten": [
            {key: row.get(key) for key in (
                "rank", "player", "player_id", "innings", "balls", "runs", "strike_rate",
                "adjusted_strike_rate", "average", "boundary_runs", "boundary_share", "dots", "dot_pct",
                "dismissals", "stayed_to_16_innings", "stay_eligible_innings", "typical_batting_order",
                "median_entry_over", "came_before_anchor_innings", "composite_score",
            )}
            for row in eligible[:10]
        ],
        "final_batting_top_ten": [
            {key: row.get(key) for key in (
                "final_rank", "player", "player_id", "selection_reason", "middle_phase_balls",
                "middle_phase_runs", "middle_phase_strike_rate", "middle_phase_adjusted_strike_rate",
                "death_phase_balls", "death_phase_runs", "death_phase_strike_rate",
                "death_phase_adjusted_strike_rate", "phase_sr_acceleration", "phase_total_runs",
                "phase_boundary_rate_acceleration", "phase_average_raw", "phase_average_adjusted",
                "phase_weighted_score",
            )}
            for row in saved_final_rows
        ],
    }


def save_validation(validation: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    VALIDATION_PATH.write_text(json.dumps(validation, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    report_path = OUTPUT_DIR / "clutch_batting_report.json"
    current = json.loads(report_path.read_text(encoding="utf-8"))
    validation = validate_clutch_batting_report(current)
    current["validation"] = validation
    report_path.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    save_validation(validation)
    print(json.dumps({"all_passed": validation["all_passed"], "checks_passed": validation["checks_passed"], "checks_total": validation["checks_total"], "validation": str(VALIDATION_PATH)}, indent=2))
