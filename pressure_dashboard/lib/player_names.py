"""Audited display names for source player IDs; raw labels remain available."""

from __future__ import annotations

from typing import Any


PLAYER_DISPLAY_OVERRIDES = {
    7897: "Tilak Varma",
    8: "MS Dhoni",
}

PLAYER_SOURCE_LABELS = {
    7897: "Namboori Tilak Varma",
    8: "Mahendra Singh Dhoni",
}

PLAYER_REFERENCE_URLS = {
    7897: "https://www.iplt20.com/teams/mumbai-indians/squad-details/20594",
    8: "https://www.icc-cricket.com/hall-of-fame/hall-of-famers/hall-of-famer-ms-dhoni",
}


def player_display_name(player_id: Any, source_name: Any) -> str:
    """Return a familiar cricket name while preserving the source label elsewhere."""
    try:
        identifier = int(player_id)
    except (TypeError, ValueError):
        identifier = -1
    if identifier in PLAYER_DISPLAY_OVERRIDES:
        return PLAYER_DISPLAY_OVERRIDES[identifier]
    name = str(source_name or "").strip()
    return name or (f"Player {identifier}" if identifier >= 0 else "Unknown player")


def display_player_aggregate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve a source-name column and add the standard cricket display name."""
    for row in rows:
        if "player_id" not in row or "player" not in row:
            continue
        row["source_player"] = row.get("player")
        row["player"] = player_display_name(row.get("player_id"), row.get("player"))
    return rows


def apply_player_display_names(
    rows: list[dict[str, Any]],
    pairs: tuple[tuple[str, str], ...] = (
        ("striker_id", "striker_name"),
        ("non_striker_id", "non_striker_name"),
        ("bowler_id", "bowler_name"),
    ),
) -> list[dict[str, Any]]:
    """Add raw-name fields and use checked display names in player event rows."""
    for row in rows:
        for id_key, name_key in pairs:
            if id_key not in row or name_key not in row:
                continue
            source_name = row.get(name_key)
            row.setdefault(f"source_{name_key}", source_name)
            row[name_key] = player_display_name(row.get(id_key), source_name)
    return rows
