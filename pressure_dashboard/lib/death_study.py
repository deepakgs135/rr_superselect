"""Dedicated queries for the India death-over study and bowling-pressure sample."""

from __future__ import annotations

from typing import Any

from .db import query
from .filters import delivery_filter
from .metrics import economy_rate, share, shrink_to_baseline
from .player_names import player_display_name

INDIA_DEATH_MIN_LEGAL_BALLS = 120
INDIA_DEATH_MIN_INNINGS = 15
INDIA_DEATH_MIN_SEASONS = 3
CURRENT_SEASON = "2026"
RECENT_FORM_INNINGS = 10
MIN_BATTING_PRESSURE_BALLS = 30


def bowling_pressure_summary(filters: dict[str, Any]) -> dict[str, Any]:
    """Return distinct-match and delivery totals for the exact bowling-pressure state."""
    where, params = delivery_filter(
        filters,
        "d",
        "m",
        apply_pressure_toggle=False,
        pressure_column="bowling_pressure",
    )
    rows = query(
        f"""
        SELECT COUNT(DISTINCT d.match_id) AS pressure_matches,
               COUNT(DISTINCT d.bowler_id) AS pressure_bowlers,
               COUNT(DISTINCT CAST(d.match_id AS TEXT) || ':' || CAST(d.bowler_id AS TEXT)) AS bowler_match_samples,
               SUM(d.legal) AS pressure_legal_balls,
               SUM(d.credited_wicket) AS pressure_credited_wickets,
               SUM(d.bowler_runs_proxy) AS pressure_runs_proxy,
               SUM(CASE WHEN d.legal=1 AND d.team_dot=1 THEN 1 ELSE 0 END) AS pressure_dots
        FROM deliveries d JOIN matches m ON m.match_id=d.match_id
        WHERE ({where}) AND d.innings=2 AND d.bowler_id>=0 AND d.bowling_pressure=1
        """,
        tuple(params),
    )
    return rows[0] if rows else {}


def india_death_bowler_study() -> list[dict[str, Any]]:
    """Aggregate death-over bowling at Indian venues across the supplied T20 sample."""
    rows = query(
        """
        WITH death_appearances AS (
            SELECT d.match_id, d.innings, d.bowler_id,
                   MAX(d.bowler_name) AS player,
                   m.season,
                   SUM(d.legal) AS legal_balls,
                   SUM(d.bowler_runs_proxy) AS runs_proxy,
                   SUM(d.credited_wicket) AS credited_wickets,
                   SUM(CASE WHEN d.legal=1 AND d.team_dot=1 THEN 1 ELSE 0 END) AS dot_balls
            FROM deliveries d JOIN matches m ON m.match_id=d.match_id
            WHERE m.venue_country='India'
              AND m.match_format IN ('T20', 'T20I')
              AND d.innings IN (1,2)
              AND d.over_no BETWEEN 16 AND 20
              AND d.bowler_id>=0
            GROUP BY d.match_id, d.innings, d.bowler_id
            HAVING SUM(d.legal)>0
        )
        SELECT bowler_id AS player_id, MAX(player) AS player,
               COUNT(DISTINCT match_id) AS death_matches,
               COUNT(*) AS death_innings,
               COUNT(DISTINCT season) AS seasons,
               SUM(legal_balls) AS legal_balls,
               SUM(runs_proxy) AS runs_proxy,
               SUM(credited_wickets) AS credited_wickets,
               SUM(dot_balls) AS dot_balls,
               SUM(CASE WHEN credited_wickets>0 THEN 1 ELSE 0 END) AS wicket_innings
        FROM death_appearances
        GROUP BY bowler_id
        ORDER BY legal_balls DESC, player
        """
    )
    for row in rows:
        row["source_player"] = row.get("player")
        row["player"] = player_display_name(row.get("player_id"), row.get("player"))
    return rows


def _assign_component_rank(
    rows: list[dict[str, Any]], field: str, *, higher_is_better: bool
) -> None:
    ordered = sorted(
        rows,
        key=lambda row: (
            row.get(field) is None,
            (-row[field] if higher_is_better else row[field]) if row.get(field) is not None else 0,
            row.get("player") or "",
            int(row.get("player_id") or -1),
        ),
    )
    start = 0
    while start < len(ordered):
        value = ordered[start].get(field)
        end = start + 1
        while end < len(ordered) and ordered[end].get(field) == value:
            end += 1
        average_rank = (start + 1 + end) / 2
        for row in ordered[start:end]:
            row[f"{field}_rank"] = average_rank
        start = end


def india_death_bowler_rankings(
    rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Rank adequately sampled India death bowlers on economy, dots, wicket pace, and consistency."""
    study_rows = rows if rows is not None else india_death_bowler_study()
    for row in study_rows:
        balls = int(row.get("legal_balls") or 0)
        wickets = int(row.get("credited_wickets") or 0)
        row["economy_proxy"] = economy_rate(int(row.get("runs_proxy") or 0), balls)
        row["balls_per_wicket"] = round(balls / wickets, 2) if wickets else None
        row["wicket_innings_pct"] = share(
            int(row.get("wicket_innings") or 0), int(row.get("death_innings") or 0)
        )
        row["dot_pct"] = share(
            int(row.get("dot_balls") or 0), balls
        )

    eligible = [
        row for row in study_rows
        if int(row.get("legal_balls") or 0) >= INDIA_DEATH_MIN_LEGAL_BALLS
        and int(row.get("death_innings") or 0) >= INDIA_DEATH_MIN_INNINGS
        and int(row.get("seasons") or 0) >= INDIA_DEATH_MIN_SEASONS
    ]
    if not eligible:
        return []

    _assign_component_rank(eligible, "economy_proxy", higher_is_better=False)
    _assign_component_rank(eligible, "balls_per_wicket", higher_is_better=False)
    _assign_component_rank(eligible, "wicket_innings_pct", higher_is_better=True)
    _assign_component_rank(eligible, "dot_pct", higher_is_better=True)
    for row in eligible:
        row["balanced_rank"] = round(
            (
                row["economy_proxy_rank"]
                + row["balls_per_wicket_rank"]
                + row["wicket_innings_pct_rank"]
                + row["dot_pct_rank"]
            ) / 4,
            2,
        )
    return sorted(
        eligible,
        key=lambda row: (
            row["balanced_rank"],
            -int(row.get("legal_balls") or 0),
            -int(row.get("credited_wickets") or 0),
            row.get("player") or "",
            int(row.get("player_id") or -1),
        ),
    )


def current_batting_pressure_candidates() -> dict[str, Any]:
    """Return pressure batters ranked with 2026 eligibility and latest-ten form."""
    pressure_rows = query(
        """
        SELECT d.striker_id AS player_id,
               MAX(d.striker_name) AS source_player,
               COUNT(DISTINCT d.match_id) AS pressure_matches,
               SUM(d.runs) AS pressure_runs,
               SUM(d.faced_ball) AS pressure_balls,
               SUM(CASE WHEN d.is_wicket=1 AND d.dismissed_player_id=d.striker_id
                        THEN 1 ELSE 0 END) AS pressure_dismissals
        FROM deliveries d JOIN matches m ON m.match_id=d.match_id
        WHERE m.match_format IN ('T20','T20I')
          AND d.pressure=1 AND d.striker_id>=0
        GROUP BY d.striker_id
        HAVING SUM(d.faced_ball)>=?
        """,
        (MIN_BATTING_PRESSURE_BALLS,),
    )
    if not pressure_rows:
        return {"rows": [], "leaders": [], "eligible_count": 0, "baseline_sr": None}

    cohort_runs = sum(int(row.get("pressure_runs") or 0) for row in pressure_rows)
    cohort_balls = sum(int(row.get("pressure_balls") or 0) for row in pressure_rows)
    baseline_sr = cohort_runs * 100.0 / cohort_balls if cohort_balls else None

    recent_rows = query(
        """
        SELECT s.player_id, s.match_id, s.innings, m.match_date, m.season,
               SUM(s.runs) AS runs, SUM(s.balls) AS balls,
               SUM(s.dismissals) AS dismissals
        FROM source_batter_records s JOIN matches m ON m.match_id=s.match_id
        WHERE m.match_format IN ('T20','T20I')
        GROUP BY s.player_id, s.match_id, s.innings
        ORDER BY m.match_date DESC, s.match_id DESC, s.innings DESC
        """
    )
    latest_by_player: dict[int, list[dict[str, Any]]] = {}
    for row in recent_rows:
        latest_by_player.setdefault(int(row["player_id"]), []).append(row)

    active_rows = query(
        """
        SELECT s.player_id
        FROM source_batter_records s JOIN matches m ON m.match_id=s.match_id
        WHERE m.match_format IN ('T20','T20I') AND m.season=?
        UNION
        SELECT s.player_id
        FROM source_bowler_records s JOIN matches m ON m.match_id=s.match_id
        WHERE m.match_format IN ('T20','T20I') AND m.season=?
        """,
        (CURRENT_SEASON, CURRENT_SEASON),
    )
    active_ids = {int(row["player_id"]) for row in active_rows}

    output: list[dict[str, Any]] = []
    for row in pressure_rows:
        player_id = int(row["player_id"])
        balls = int(row.get("pressure_balls") or 0)
        runs = int(row.get("pressure_runs") or 0)
        raw_sr = runs * 100.0 / balls if balls else None
        row["pressure_sr"] = round(raw_sr, 2) if raw_sr is not None else None
        row["pressure_adjusted_sr"] = shrink_to_baseline(
            row["pressure_sr"], balls, baseline_sr, 100
        )
        row["player"] = player_display_name(player_id, row.get("source_player"))
        row["active_2026"] = player_id in active_ids
        latest = latest_by_player.get(player_id, [])[:RECENT_FORM_INNINGS]
        recent_runs = sum(int(item.get("runs") or 0) for item in latest)
        recent_balls = sum(int(item.get("balls") or 0) for item in latest)
        recent_dismissals = sum(int(item.get("dismissals") or 0) for item in latest)
        row["last10_innings"] = len(latest)
        row["last10_runs"] = recent_runs
        row["last10_balls"] = recent_balls
        row["last10_dismissals"] = recent_dismissals
        row["last10_sr"] = round(100 * recent_runs / recent_balls, 2) if recent_balls else None
        row["last10_average"] = round(recent_runs / recent_dismissals, 2) if recent_dismissals else None
        row["last10_latest_date"] = latest[0].get("match_date") if latest else None
        row["last10_latest_season"] = latest[0].get("season") if latest else None
        if not row["active_2026"]:
            row["selection_reason"] = "No 2026 T20/T20I batting record in the supplied data"
        elif len(latest) < RECENT_FORM_INNINGS:
            row["selection_reason"] = (
                f"Only {len(latest)} T20/T20I batting innings; 10 are required"
            )
        else:
            row["selection_reason"] = "Eligible for the final form-adjusted ranking"
        output.append(row)

    selection_pool = [
        row for row in output
        if row["active_2026"] and row["last10_innings"] >= RECENT_FORM_INNINGS
    ]
    for field in ("pressure_adjusted_sr", "last10_sr", "last10_average"):
        _assign_component_rank(selection_pool, field, higher_is_better=True)
    for row in selection_pool:
        row["blended_rank_score"] = round(
            (
                row["pressure_adjusted_sr_rank"]
                + row["last10_sr_rank"]
                + row["last10_average_rank"]
            ) / 3,
            2,
        )
    selection_pool.sort(
        key=lambda row: (
            row["blended_rank_score"],
            -float(row.get("pressure_adjusted_sr") or 0),
            row.get("player") or "",
            int(row["player_id"]),
        )
    )
    for rank, row in enumerate(selection_pool, 1):
        row["final_rank"] = rank
        row["selected"] = rank <= 10
        if row["selected"]:
            row["selection_reason"] = "Selected: top 10 on pressure record and latest-ten form"
        else:
            row["selection_reason"] = f"Eligible; blended rank {rank}, outside the final 10"

    for row in output:
        row.setdefault("final_rank", None)
        row.setdefault("selected", False)
    output.sort(
        key=lambda row: (
            -float(row.get("pressure_adjusted_sr") or 0),
            -int(row.get("pressure_balls") or 0),
            row.get("player") or "",
        )
    )
    return {
        "rows": output,
        "leaders": selection_pool[:10],
        "eligible_count": len(selection_pool),
        "baseline_sr": round(baseline_sr, 2) if baseline_sr is not None else None,
    }


def current_india_death_bowler_candidates() -> dict[str, Any]:
    """Return India death-over bowlers ranked by career sample and latest-ten form."""
    study_rows = india_death_bowler_study()
    original_rankings = india_death_bowler_rankings(study_rows)
    original_rank_by_id = {
        int(row["player_id"]): rank
        for rank, row in enumerate(original_rankings, 1)
    }
    recent_rows = query(
        """
        SELECT s.player_id, s.match_id, s.innings, m.match_date, m.season,
               SUM(s.runs_proxy) AS runs_proxy, SUM(s.legal_balls) AS legal_balls,
               SUM(s.credited_wickets) AS credited_wickets
        FROM source_bowler_records s JOIN matches m ON m.match_id=s.match_id
        WHERE m.match_format IN ('T20','T20I')
        GROUP BY s.player_id, s.match_id, s.innings
        ORDER BY m.match_date DESC, s.match_id DESC, s.innings DESC
        """
    )
    latest_by_player: dict[int, list[dict[str, Any]]] = {}
    for row in recent_rows:
        latest_by_player.setdefault(int(row["player_id"]), []).append(row)
    active_rows = query(
        """
        SELECT s.player_id
        FROM source_batter_records s JOIN matches m ON m.match_id=s.match_id
        WHERE m.match_format IN ('T20','T20I') AND m.season=?
        UNION
        SELECT s.player_id
        FROM source_bowler_records s JOIN matches m ON m.match_id=s.match_id
        WHERE m.match_format IN ('T20','T20I') AND m.season=?
        """,
        (CURRENT_SEASON, CURRENT_SEASON),
    )
    active_ids = {int(row["player_id"]) for row in active_rows}

    output: list[dict[str, Any]] = []
    for row in study_rows:
        player_id = int(row["player_id"])
        latest = latest_by_player.get(player_id, [])[:RECENT_FORM_INNINGS]
        recent_runs = sum(int(item.get("runs_proxy") or 0) for item in latest)
        recent_balls = sum(int(item.get("legal_balls") or 0) for item in latest)
        recent_wickets = sum(int(item.get("credited_wickets") or 0) for item in latest)
        wicket_innings = sum(int(item.get("credited_wickets") or 0) > 0 for item in latest)
        row["all_time_rank"] = original_rank_by_id.get(player_id)
        row["active_2026"] = player_id in active_ids
        row["last10_innings"] = len(latest)
        row["last10_runs_proxy"] = recent_runs
        row["last10_legal_balls"] = recent_balls
        row["last10_credited_wickets"] = recent_wickets
        row["last10_economy_proxy"] = economy_rate(recent_runs, recent_balls)
        row["last10_balls_per_wicket"] = (
            round(recent_balls / recent_wickets, 2) if recent_wickets else None
        )
        row["last10_wicket_innings_pct"] = share(wicket_innings, len(latest))
        row["last10_latest_date"] = latest[0].get("match_date") if latest else None
        row["last10_latest_season"] = latest[0].get("season") if latest else None
        if (
            int(row.get("legal_balls") or 0) < INDIA_DEATH_MIN_LEGAL_BALLS
            or int(row.get("death_innings") or 0) < INDIA_DEATH_MIN_INNINGS
            or int(row.get("seasons") or 0) < INDIA_DEATH_MIN_SEASONS
        ):
            row["selection_reason"] = (
                "Below the established India death-over minimum: "
                f"{INDIA_DEATH_MIN_LEGAL_BALLS} balls, {INDIA_DEATH_MIN_INNINGS} innings, "
                f"{INDIA_DEATH_MIN_SEASONS} seasons"
            )
        elif not row["active_2026"]:
            row["selection_reason"] = "No 2026 T20/T20I bowling record in the supplied data"
        elif len(latest) < RECENT_FORM_INNINGS:
            row["selection_reason"] = (
                f"Only {len(latest)} T20/T20I bowling innings; 10 are required"
            )
        else:
            row["selection_reason"] = "Eligible for the final form-adjusted ranking"
        row["final_rank"] = None
        row["selected"] = False
        output.append(row)

    selection_pool = [
        row for row in output
        if int(row.get("legal_balls") or 0) >= INDIA_DEATH_MIN_LEGAL_BALLS
        and int(row.get("death_innings") or 0) >= INDIA_DEATH_MIN_INNINGS
        and int(row.get("seasons") or 0) >= INDIA_DEATH_MIN_SEASONS
        and row["active_2026"]
        and row["last10_innings"] >= RECENT_FORM_INNINGS
    ]
    # Re-rank the established death metrics in the gated current-player pool so
    # they share a denominator with the latest-ten form ranks.
    selection_rankings = india_death_bowler_rankings([dict(row) for row in selection_pool])
    selection_rank_by_id = {
        int(row["player_id"]): row["balanced_rank"] for row in selection_rankings
    }
    for field, higher_is_better in (
        ("last10_economy_proxy", False),
        ("last10_balls_per_wicket", False),
        ("last10_wicket_innings_pct", True),
    ):
        _assign_component_rank(selection_pool, field, higher_is_better=higher_is_better)
    for row in selection_pool:
        row["selection_balanced_rank"] = selection_rank_by_id[int(row["player_id"])]
        row["recent_form_rank"] = round(
            (
                row["last10_economy_proxy_rank"]
                + row["last10_balls_per_wicket_rank"]
                + row["last10_wicket_innings_pct_rank"]
            ) / 3,
            2,
        )
        row["blended_rank_score"] = round(
            (row["selection_balanced_rank"] + row["recent_form_rank"]) / 2,
            2,
        )
    selection_pool.sort(
        key=lambda row: (
            row["blended_rank_score"],
            row["selection_balanced_rank"],
            row.get("player") or "",
        )
    )
    for rank, row in enumerate(selection_pool, 1):
        row["final_rank"] = rank
        row["selected"] = rank <= 10
        if row["selected"]:
            row["selection_reason"] = "Selected: top 10 on India death record and latest-ten form"
        else:
            row["selection_reason"] = f"Eligible; blended rank {rank}, outside the final 10"

    selection_by_id = {int(row["player_id"]): row for row in selection_pool}
    for row in output:
        ranked_row = selection_by_id.get(int(row["player_id"]))
        if ranked_row:
            row.update(ranked_row)
        else:
            row.setdefault("selection_balanced_rank", None)
            row.setdefault("recent_form_rank", None)
            row.setdefault("blended_rank_score", None)
    output.sort(
        key=lambda row: (
            row.get("all_time_rank") is None,
            row.get("all_time_rank") or 10**9,
            row.get("player") or "",
        )
    )
    return {
        "rows": output,
        "leaders": selection_pool[:10],
        "eligible_count": len(selection_pool),
        "all_time_eligible_count": len(original_rankings),
    }


# India T20 batting-pressure qualification and recent-form gates.
SCENARIO_MIN_RECENT_INNINGS = 10
SCENARIO_MIN_BATTING_BALLS = 30
SCENARIO_MIN_MATCHES = 2


def _scenario_component_ranks(
    rows: list[dict[str, Any]], components: tuple[tuple[str, bool], ...]
) -> None:
    for field, higher_is_better in components:
        _assign_component_rank(rows, field, higher_is_better=higher_is_better)
    for row in rows:
        row["scenario_rank_score"] = round(
            sum(row[f"{field}_rank"] for field, _ in components) / len(components), 2
        )


def india_scenario_pressure_candidates() -> dict[str, Any]:
    """Rank India T20 batters from deliveries meeting the live pressure flags.

    Runs and strike rate use only qualifying pressure balls. Deep innings means
    the batter was not dismissed before over 16 and the chase reached over 16.
    Match result is not used in selection or ranking.
    """
    innings_rows = query(
        """
        SELECT d.match_id, d.innings, d.striker_id AS player_id,
               MAX(d.striker_name) AS source_player,
               SUM(CASE WHEN d.pressure=1 THEN d.runs ELSE 0 END) AS pressure_runs,
               SUM(CASE WHEN d.pressure=1 THEN d.faced_ball ELSE 0 END) AS pressure_balls,
               MAX(d.pressure) AS saw_pressure,
               MAX(d.over_no) AS last_over,
               MAX(CASE WHEN d.is_wicket=1 AND d.dismissed_player_id=d.striker_id
                              AND d.over_no<16 THEN 1 ELSE 0 END) AS dismissed_before16,
               MAX(m.match_date) AS match_date
        FROM deliveries d JOIN matches m ON m.match_id=d.match_id
        WHERE m.venue_country='India' AND m.match_format='T20'
          AND d.innings=2 AND d.striker_id>=0
        GROUP BY d.match_id, d.innings, d.striker_id
        HAVING MAX(d.pressure)=1
        ORDER BY m.match_date DESC, d.match_id DESC
        """
    )
    by_player: dict[int, dict[str, Any]] = {}
    for item in innings_rows:
        player_id = int(item["player_id"])
        row = by_player.setdefault(
            player_id,
            {
                "player_id": player_id,
                "source_player": item.get("source_player") or "",
                "pressure_matches": 0,
                "pressure_runs": 0,
                "pressure_balls": 0,
                "deep_innings": 0,
                "last10_innings": 0,
                "last10_runs": 0,
                "last10_balls": 0,
                "last10_dismissals": 0,
                "last10_latest_date": None,
                "active_2026": False,
            },
        )
        row["pressure_matches"] += 1
        row["pressure_runs"] += int(item.get("pressure_runs") or 0)
        row["pressure_balls"] += int(item.get("pressure_balls") or 0)
        row["deep_innings"] += int(
            int(item.get("last_over") or 0) >= 16
            and not int(item.get("dismissed_before16") or 0)
        )

    recent_rows = query(
        """
        SELECT s.player_id, s.match_id, s.innings, m.match_date,
               SUM(s.runs) AS runs, SUM(s.balls) AS balls,
               SUM(s.dismissals) AS dismissals
        FROM source_batter_records s JOIN matches m ON m.match_id=s.match_id
        WHERE m.match_format='T20'
        GROUP BY s.player_id, s.match_id, s.innings
        ORDER BY m.match_date DESC, s.match_id DESC, s.innings DESC
        """
    )
    recent_by_player: dict[int, list[dict[str, Any]]] = {}
    for item in recent_rows:
        recent_by_player.setdefault(int(item["player_id"]), []).append(item)
    active_ids = {
        int(item["player_id"])
        for item in query(
            """SELECT DISTINCT s.player_id
               FROM source_batter_records s JOIN matches m ON m.match_id=s.match_id
               WHERE m.match_format='T20' AND m.season=?""",
            (CURRENT_SEASON,),
        )
    }

    for player_id, row in by_player.items():
        recent = recent_by_player.get(player_id, [])[:RECENT_FORM_INNINGS]
        row["player"] = player_display_name(player_id, row["source_player"])
        row["active_2026"] = player_id in active_ids
        row["last10_innings"] = len(recent)
        row["last10_runs"] = sum(int(item.get("runs") or 0) for item in recent)
        row["last10_balls"] = sum(int(item.get("balls") or 0) for item in recent)
        row["last10_dismissals"] = sum(int(item.get("dismissals") or 0) for item in recent)
        row["last10_sr"] = round(100 * row["last10_runs"] / row["last10_balls"], 2) if row["last10_balls"] else None
        row["last10_average"] = round(row["last10_runs"] / row["last10_dismissals"], 2) if row["last10_dismissals"] else None
        row["last10_latest_date"] = recent[0].get("match_date") if recent else None
        row["pressure_sr"] = round(100 * row["pressure_runs"] / row["pressure_balls"], 2) if row["pressure_balls"] else None
        row["runs_per_pressure_match"] = round(row["pressure_runs"] / row["pressure_matches"], 2) if row["pressure_matches"] else None
        row["deep_pct"] = share(row["deep_innings"], row["pressure_matches"])
        reasons = []
        if row["pressure_matches"] < SCENARIO_MIN_MATCHES:
            reasons.append(f"only {row['pressure_matches']} pressure match(es); {SCENARIO_MIN_MATCHES} required")
        if row["pressure_balls"] < SCENARIO_MIN_BATTING_BALLS:
            reasons.append(f"only {row['pressure_balls']} pressure balls; {SCENARIO_MIN_BATTING_BALLS} required")
        if row["deep_innings"] < 1:
            reasons.append("did not reach over 16 in a pressure innings")
        if not row["active_2026"]:
            reasons.append(f"no season {CURRENT_SEASON} T20 batting record in the supplied data")
        if row["last10_innings"] < SCENARIO_MIN_RECENT_INNINGS:
            reasons.append(f"only {row['last10_innings']} recent T20 batting innings; {SCENARIO_MIN_RECENT_INNINGS} required")
        row["eligible"] = not reasons
        row["selection_reason"] = "; ".join(reasons) if reasons else "Eligible for the India T20 batting-pressure ranking"

    eligible = [row for row in by_player.values() if row["eligible"]]
    _scenario_component_ranks(
        eligible,
        (("runs_per_pressure_match", True), ("pressure_sr", True), ("deep_pct", True)),
    )
    eligible.sort(
        key=lambda row: (
            row["scenario_rank_score"],
            -int(row["pressure_matches"]),
            -int(row["pressure_balls"]),
            row["player"],
        )
    )
    for rank, row in enumerate(eligible, 1):
        row["scenario_rank"] = rank
    for row in by_player.values():
        row.setdefault("scenario_rank", None)
        row.setdefault("scenario_rank_score", None)
    all_rows = sorted(
        by_player.values(),
        key=lambda row: (
            row["scenario_rank"] is None,
            row["scenario_rank"] or 10**9,
            -int(row["pressure_matches"]),
            row["player"],
        ),
    )
    pressure_match_rows = query(
        """SELECT COUNT(DISTINCT d.match_id) AS matches, MAX(m.match_date) AS latest
           FROM deliveries d JOIN matches m ON m.match_id=d.match_id
           WHERE d.pressure=1 AND m.match_format='T20' AND m.venue_country='India'"""
    )
    return {
        "batters": {
            "rows": all_rows,
            "leaders": eligible[:10],
            "eligible_count": len(eligible),
            "episode_count": int(pressure_match_rows[0].get("matches") or 0) if pressure_match_rows else 0,
            "candidate_count": len(all_rows),
        },
        "latest_match_date": pressure_match_rows[0].get("latest") if pressure_match_rows else None,
    }


def india_death_bowler_leaderboard() -> dict[str, Any]:
    """Return the current top ten using Indian-venue overs 16–20 only.

    Recent T20/T20I form and 2026 role activity are qualification/context fields;
    they do not enter the death-over ranking score. No other over phase or match
    result is used.
    """
    rows = india_death_bowler_study()
    recent_rows = query(
        """
        SELECT s.player_id, s.match_id, s.innings, m.match_date, m.season,
               SUM(s.runs_proxy) AS runs_proxy, SUM(s.legal_balls) AS legal_balls,
               SUM(s.credited_wickets) AS credited_wickets
        FROM source_bowler_records s JOIN matches m ON m.match_id=s.match_id
        WHERE m.match_format IN ('T20','T20I')
        GROUP BY s.player_id, s.match_id, s.innings
        ORDER BY m.match_date DESC, s.match_id DESC, s.innings DESC
        """
    )
    recent_by_player: dict[int, list[dict[str, Any]]] = {}
    for row in recent_rows:
        recent_by_player.setdefault(int(row["player_id"]), []).append(row)
    active_ids = {
        int(row["player_id"])
        for row in query(
            """
            SELECT DISTINCT s.player_id
            FROM source_bowler_records s JOIN matches m ON m.match_id=s.match_id
            WHERE m.match_format IN ('T20','T20I') AND m.season=?
            """,
            (CURRENT_SEASON,),
        )
    }

    for row in rows:
        player_id = int(row["player_id"])
        recent = recent_by_player.get(player_id, [])[:RECENT_FORM_INNINGS]
        last_runs = sum(int(item.get("runs_proxy") or 0) for item in recent)
        last_balls = sum(int(item.get("legal_balls") or 0) for item in recent)
        last_wickets = sum(int(item.get("credited_wickets") or 0) for item in recent)
        recent_wicket_innings = sum(int(item.get("credited_wickets") or 0) > 0 for item in recent)
        balls = int(row.get("legal_balls") or 0)
        wickets = int(row.get("credited_wickets") or 0)
        row["active_2026"] = player_id in active_ids
        row["last10_innings"] = len(recent)
        row["last10_runs_proxy"] = last_runs
        row["last10_legal_balls"] = last_balls
        row["last10_credited_wickets"] = last_wickets
        row["last10_economy_proxy"] = economy_rate(last_runs, last_balls)
        row["last10_wicket_innings_pct"] = share(recent_wicket_innings, len(recent))
        row["last10_latest_date"] = recent[0].get("match_date") if recent else None
        row["economy_proxy"] = economy_rate(int(row.get("runs_proxy") or 0), balls)
        row["balls_per_wicket"] = round(balls / wickets, 2) if wickets else None
        row["wicket_innings_pct"] = share(
            int(row.get("wicket_innings") or 0), int(row.get("death_innings") or 0)
        )
        row["dot_pct"] = share(int(row.get("dot_balls") or 0), balls)

        reasons = []
        if balls < INDIA_DEATH_MIN_LEGAL_BALLS:
            reasons.append(f"fewer than {INDIA_DEATH_MIN_LEGAL_BALLS} India death legal balls")
        if int(row.get("death_innings") or 0) < INDIA_DEATH_MIN_INNINGS:
            reasons.append(f"fewer than {INDIA_DEATH_MIN_INNINGS} India death innings")
        if int(row.get("seasons") or 0) < INDIA_DEATH_MIN_SEASONS:
            reasons.append(f"fewer than {INDIA_DEATH_MIN_SEASONS} India death seasons")
        if not row["active_2026"]:
            reasons.append(f"no season {CURRENT_SEASON} T20/T20I bowling appearance")
        if len(recent) < RECENT_FORM_INNINGS:
            reasons.append(f"fewer than {RECENT_FORM_INNINGS} recent T20/T20I bowling innings")
        row["eligible"] = not reasons
        row["selection_reason"] = "; ".join(reasons) if reasons else "Eligible for India death-over ranking"

    eligible = [row for row in rows if row["eligible"]]
    ranked = india_death_bowler_rankings([dict(row) for row in eligible])
    rank_by_id = {int(row["player_id"]): rank for rank, row in enumerate(ranked, 1)}
    score_by_id = {int(row["player_id"]): row["balanced_rank"] for row in ranked}
    for row in rows:
        row["death_rank"] = rank_by_id.get(int(row["player_id"]))
        row["death_rank_score"] = score_by_id.get(int(row["player_id"]))
    rows.sort(
        key=lambda row: (
            row["death_rank"] is None,
            row["death_rank"] or 10**9,
            -int(row.get("legal_balls") or 0),
            row.get("player") or "",
        )
    )
    return {
        "rows": rows,
        "leaders": [row for row in rows if row["death_rank"] is not None][:10],
        "eligible_count": len(eligible),
        "candidate_count": len(rows),
        "latest_match_date": query(
            """SELECT MAX(m.match_date) AS latest_match
               FROM matches m JOIN deliveries d ON d.match_id=m.match_id
               WHERE m.venue_country='India' AND m.match_format IN ('T20','T20I')
                 AND d.over_no BETWEEN 16 AND 20"""
        )[0].get("latest_match"),
    }
