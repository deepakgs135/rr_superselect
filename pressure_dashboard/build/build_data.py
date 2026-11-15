"""Build the local analytics database from the supplied raw cricket CSVs.

Run once from this folder with:
    python build/build_data.py

The dashboard reads only the processed SQLite file and validation JSON.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sqlite3
import statistics
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element

APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = APP_DIR.parent
RAW_DIR = PROJECT_DIR / "Raw_Data"
WORKBOOK_PATH = PROJECT_DIR / "cleaned_data" / "Cricket_Analytics_Matrices.xlsx"
DB_DIR = APP_DIR / "data" / "processed"
QUALITY_DIR = APP_DIR / "data" / "validation"
DB_PATH = DB_DIR / "analytics.sqlite3"
QUALITY_PATH = QUALITY_DIR / "quality.json"

sys.path.insert(0, str(APP_DIR))
from lib.states import bowling_pressure_state, pressure_state

LEGAL_TYPES = {"none", "byes", "legbyes"}
ILLEGAL_TYPES = {"wide", "overstep"}
UNKNOWN_TYPES = {"other", "penalty", ""}
CREDITED_DISMISSALS = {"caught", "bowled", "lbw", "stump", "hit wicket"}
EXPECTED_RAW_FILES = [
    "ball_by_ball.csv",
    "matches.csv",
    "competitions.csv",
    "teams.csv",
    "competition_team_player_mapping.csv",
    "playing_eleven.csv",
]

NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def as_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value or "").strip()
        return int(float(text)) if text else default
    except (TypeError, ValueError):
        return default


def as_optional_int(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = int(float(text))
        return parsed if parsed != 0 else None
    except (TypeError, ValueError):
        return None


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        text = str(value or "").strip()
        return float(text) if text else default
    except (TypeError, ValueError):
        return default


def as_bool(value: Any) -> int:
    return int(str(value or "").strip().casefold() in {"true", "1", "yes"})


def overs_to_balls(value: Any) -> int | None:
    """Interpret a revised-overs field as cricket overs.ball notation."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if "." in text:
            over_text, ball_text = text.split(".", 1)
            overs = int(over_text)
            balls = int((ball_text + "0")[0])
            if balls > 5:
                return None
            return overs * 6 + balls
        return int(float(text)) * 6
    except (TypeError, ValueError):
        return None


def normalized_extra(value: str | None) -> str:
    return (value or "").strip().casefold()


def classify_legality(value: str | None) -> tuple[int, int]:
    kind = normalized_extra(value)
    if kind in LEGAL_TYPES:
        return 1, 0
    if kind in ILLEGAL_TYPES:
        return 0, 0
    if kind in UNKNOWN_TYPES:
        return 0, 1
    return 0, 1


def source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def cell_text(cell: Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        inline = cell.find(f"{NS_MAIN}is")
        if inline is None:
            return ""
        return "".join(node.text or "" for node in inline.iter(f"{NS_MAIN}t"))
    value = cell.find(f"{NS_MAIN}v")
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        index = as_int(value.text, -1)
        return shared_strings[index] if 0 <= index < len(shared_strings) else ""
    if cell_type == "b":
        return "TRUE" if value.text == "1" else "FALSE"
    return value.text


def col_index(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref.upper())
    if not letters:
        return -1
    index = 0
    for char in letters.group(0):
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


def read_pressure_table(path: Path) -> list[dict[str, str]]:
    """Read the workbook's PressureMatrix Excel table using only stdlib XML."""
    if not path.exists():
        return []
    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {
            item.attrib["Id"]: item.attrib["Target"]
            for item in rels.findall(f"{NS_PKG_REL}Relationship")
        }

        sheet_paths: dict[str, str] = {}
        for sheet in workbook.findall(f".//{NS_MAIN}sheet"):
            rel_id = sheet.attrib.get(f"{NS_REL}id", "")
            target = rel_map.get(rel_id, "")
            sheet_paths[sheet.attrib.get("name", "")] = (
                target.lstrip("/") if target.startswith("/") else f"xl/{target}"
            )

        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in shared.findall(f"{NS_MAIN}si"):
                shared_strings.append(
                    "".join(node.text or "" for node in item.iter(f"{NS_MAIN}t"))
                )

        for sheet_name, sheet_path in sheet_paths.items():
            sheet_rels_path = str(Path(sheet_path).parent / "_rels" / (Path(sheet_path).name + ".rels")).replace("\\", "/")
            if sheet_rels_path not in archive.namelist():
                continue
            sheet_rels = ET.fromstring(archive.read(sheet_rels_path))
            table_targets = [
                item.attrib["Target"]
                for item in sheet_rels.findall(f"{NS_PKG_REL}Relationship")
                if item.attrib.get("Type", "").endswith("/table")
            ]
            for target in table_targets:
                table_path = str(Path(sheet_path).parent.joinpath(target)).replace("\\", "/")
                parts: list[str] = []
                for part in table_path.split("/"):
                    if part in {"", "."}:
                        continue
                    if part == "..":
                        if parts:
                            parts.pop()
                    else:
                        parts.append(part)
                table_path = "/".join(parts)
                if table_path not in archive.namelist():
                    continue
                table = ET.fromstring(archive.read(table_path))
                if table.attrib.get("displayName") != "PressureMatrix":
                    continue
                columns_node = table.find(f"{NS_MAIN}tableColumns")
                columns = [
                    item.attrib.get("name", "")
                    for item in (columns_node.findall(f"{NS_MAIN}tableColumn") if columns_node is not None else [])
                ]
                ref = table.attrib.get("ref", "")
                start_row = as_int(re.search(r"[A-Z]+(\d+)", ref).group(1)) if re.search(r"[A-Z]+(\d+)", ref) else 5
                worksheet = ET.fromstring(archive.read(sheet_path))
                output: list[dict[str, str]] = []
                for row in worksheet.findall(f".//{NS_MAIN}sheetData/{NS_MAIN}row"):
                    row_number = as_int(row.attrib.get("r"), 0)
                    if row_number <= start_row:
                        continue
                    values = [""] * len(columns)
                    for cell in row.findall(f"{NS_MAIN}c"):
                        index = col_index(cell.attrib.get("r", ""))
                        if 0 <= index < len(values):
                            values[index] = cell_text(cell, shared_strings)
                    output.append(dict(zip(columns, values)))
                return output
    return []


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode = WAL;
        PRAGMA synchronous = NORMAL;
        CREATE TABLE competitions (
            comp_id INTEGER PRIMARY KEY,
            comp_name TEXT,
            match_format TEXT,
            season TEXT
        );
        CREATE TABLE matches (
            match_id INTEGER PRIMARY KEY,
            comp_id INTEGER,
            match_number TEXT,
            match_date TEXT,
            stage TEXT,
            venue_id TEXT,
            venue_country TEXT,
            home_team_id INTEGER,
            home_team TEXT,
            away_team_id INTEGER,
            away_team TEXT,
            win_team_id INTEGER,
            result TEXT,
            revised_target INTEGER,
            scheduled_balls INTEGER,
            schedule_source TEXT,
            match_format TEXT,
            season TEXT,
            batting_first_team_id INTEGER,
            chasing_team_id INTEGER,
            chase_success INTEGER
        );
        CREATE TABLE staging_deliveries (
            source_order INTEGER,
            match_id INTEGER,
            innings INTEGER,
            over_no INTEGER,
            over_ball_num INTEGER,
            innings_ball_num INTEGER,
            batting_team_id INTEGER,
            striker_id INTEGER,
            striker_name TEXT,
            non_striker_id INTEGER,
            non_striker_name TEXT,
            bowler_id INTEGER,
            bowler_name TEXT,
            runs INTEGER,
            extras2_runs INTEGER,
            extras_type TEXT,
            is_four INTEGER,
            is_six INTEGER,
            is_wicket INTEGER,
            dismissal_type TEXT,
            dismissed_player_id INTEGER,
            pace_or_spin TEXT,
            bowl_speed REAL,
            delivery_time TEXT
        );
        CREATE TABLE deliveries (
            match_id INTEGER,
            innings INTEGER,
            seq INTEGER,
            over_no INTEGER,
            over_ball_num INTEGER,
            innings_ball_num INTEGER,
            batting_team_id INTEGER,
            striker_id INTEGER,
            striker_name TEXT,
            non_striker_id INTEGER,
            non_striker_name TEXT,
            bowler_id INTEGER,
            bowler_name TEXT,
            runs INTEGER,
            extras2_runs INTEGER,
            total_runs_proxy INTEGER,
            extras_type TEXT,
            legal INTEGER,
            unknown_legality INTEGER,
            faced_ball INTEGER,
            is_four INTEGER,
            is_six INTEGER,
            is_wicket INTEGER,
            dismissal_type TEXT,
            dismissed_player_id INTEGER,
            credited_wicket INTEGER,
            team_dot INTEGER,
            batter_dot INTEGER,
            pace_or_spin TEXT,
            bowl_speed REAL,
            score_before INTEGER,
            target INTEGER,
            target_source TEXT,
            scheduled_balls INTEGER,
            schedule_source TEXT,
            balls_remaining INTEGER,
            wickets_lost INTEGER,
            rrr REAL,
            state_known INTEGER,
            pressure INTEGER,
            current_rpo REAL,
            bowling_pressure INTEGER
        );
        CREATE TABLE innings_summary (
            match_id INTEGER,
            innings INTEGER,
            batting_team_id INTEGER,
            batting_team TEXT,
            total_runs_proxy INTEGER,
            known_legal_balls INTEGER,
            unknown_legality_events INTEGER,
            wicket_events INTEGER,
            credited_wickets INTEGER,
            fours INTEGER,
            sixes INTEGER,
            zero_run_legal_events INTEGER,
            delivery_rows INTEGER,
            target INTEGER,
            target_source TEXT,
            scheduled_balls INTEGER,
            schedule_source TEXT,
            rrr_states INTEGER,
            unknown_rrr_states INTEGER,
            mean_rrr REAL,
            peak_rrr REAL,
            peak_rrr_seq INTEGER,
            peak_rrr_over INTEGER,
            pressure_delivery_rows INTEGER,
            pressure_legal_balls INTEGER,
            pressure_raw_runs_proxy INTEGER,
            pressure_wicket_events INTEGER,
            chase_success INTEGER,
            PRIMARY KEY (match_id, innings)
        );
        CREATE TABLE workbook_pressure (
            match_id INTEGER PRIMARY KEY,
            workbook_pressure_count INTEGER,
            workbook_high_extreme_count INTEGER,
            workbook_target INTEGER,
            workbook_mean_rrr REAL,
            workbook_peak_rrr REAL,
            workbook_result TEXT
        );
        CREATE TABLE source_files (
            file_name TEXT PRIMARY KEY,
            row_count INTEGER,
            byte_size INTEGER,
            sha256 TEXT
        );
        CREATE TABLE source_batter_records (
            match_id INTEGER,
            innings INTEGER,
            player_id INTEGER,
            source_name TEXT,
            source_rows INTEGER,
            runs INTEGER,
            balls INTEGER,
            dismissals INTEGER,
            fours INTEGER,
            sixes INTEGER,
            PRIMARY KEY (match_id, innings, player_id)
        );
        CREATE TABLE source_bowler_records (
            match_id INTEGER,
            innings INTEGER,
            player_id INTEGER,
            source_name TEXT,
            source_rows INTEGER,
            runs_proxy INTEGER,
            legal_balls INTEGER,
            wicket_events INTEGER,
            credited_wickets INTEGER,
            PRIMARY KEY (match_id, innings, player_id)
        );
        CREATE TABLE source_player_names (
            role TEXT,
            player_id INTEGER,
            source_name TEXT,
            PRIMARY KEY (role, player_id, source_name)
        );
        CREATE INDEX idx_delivery_match ON deliveries(match_id, innings, seq);
        CREATE INDEX idx_delivery_striker ON deliveries(striker_id, match_id);
        CREATE INDEX idx_delivery_bowler ON deliveries(bowler_id, match_id);
        CREATE INDEX idx_delivery_pressure ON deliveries(pressure, match_id);
        CREATE INDEX idx_delivery_bowling_pressure ON deliveries(bowling_pressure, match_id);
        CREATE INDEX idx_match_filter ON matches(match_format, season, venue_country);
        CREATE INDEX idx_match_venue ON matches(venue_id, match_format, season);
        CREATE INDEX idx_source_batter_player ON source_batter_records(player_id, match_id);
        CREATE INDEX idx_source_bowler_player ON source_bowler_records(player_id, match_id);
        CREATE VIEW chase_states AS SELECT * FROM deliveries WHERE innings = 2;
        """
    )


def load_metadata(conn: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    competitions = read_csv_rows(RAW_DIR / "competitions.csv")
    comp_lookup = {
        as_int(row.get("comp_id")): {
            "comp_name": row.get("comp_name", ""),
            "match_format": row.get("match_format", ""),
            "season": row.get("season", ""),
        }
        for row in competitions
    }
    conn.executemany(
        "INSERT INTO competitions(comp_id, comp_name, match_format, season) VALUES (?, ?, ?, ?)",
        [
            (comp_id, item["comp_name"], item["match_format"], item["season"])
            for comp_id, item in comp_lookup.items()
        ],
    )

    metadata: dict[int, dict[str, Any]] = {}
    for row in read_csv_rows(RAW_DIR / "matches.csv"):
        match_id = as_int(row.get("match_id"), -1)
        comp_id = as_int(row.get("comp_id"))
        competition = comp_lookup.get(comp_id, {})
        format_name = competition.get("match_format", "")
        raw_schedule = row.get("second_inn_revised_overs", "")
        scheduled = overs_to_balls(raw_schedule)
        if scheduled is None or scheduled <= 0:
            scheduled = 120
            schedule_source = "20-over format default"
        else:
            schedule_source = "matches.second_inn_revised_overs"
        target = as_optional_int(row.get("revised_target"))
        data = {
            "match_id": match_id,
            "comp_id": comp_id,
            "match_number": row.get("match_number", ""),
            "match_date": row.get("match_date", ""),
            "stage": row.get("stage", ""),
            "venue_id": (row.get("venue_id") or "").strip(),
            "venue_country": (row.get("venue_country") or "").strip() or "Unknown",
            "home_team_id": as_optional_int(row.get("home_team_id")),
            "home_team": row.get("home_team", ""),
            "away_team_id": as_optional_int(row.get("away_team_id")),
            "away_team": row.get("away_team", ""),
            "win_team_id": as_optional_int(row.get("win_team_id")),
            "result": row.get("result", ""),
            "revised_target": target,
            "scheduled_balls": scheduled,
            "schedule_source": schedule_source,
            "match_format": format_name,
            "season": competition.get("season", ""),
            "batting_first_team_id": None,
            "chasing_team_id": None,
            "chase_success": None,
        }
        metadata[match_id] = data

    conn.executemany(
        """INSERT INTO matches(
            match_id, comp_id, match_number, match_date, stage, venue_id, venue_country,
            home_team_id, home_team, away_team_id, away_team, win_team_id, result,
            revised_target, scheduled_balls, schedule_source, match_format, season,
            batting_first_team_id, chasing_team_id, chase_success
        ) VALUES (
            :match_id, :comp_id, :match_number, :match_date, :stage, :venue_id, :venue_country,
            :home_team_id, :home_team, :away_team_id, :away_team, :win_team_id, :result,
            :revised_target, :scheduled_balls, :schedule_source, :match_format, :season,
            :batting_first_team_id, :chasing_team_id, :chase_success
        )""",
        list(metadata.values()),
    )
    conn.commit()
    return metadata


def ingest_deliveries(conn: sqlite3.Connection) -> tuple[int, Counter[str]]:
    path = RAW_DIR / "ball_by_ball.csv"
    extras_counts: Counter[str] = Counter()
    count = 0
    insert_sql = """INSERT INTO staging_deliveries VALUES (
        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
    )"""
    batch: list[tuple[Any, ...]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            kind = (row.get("extras_type") or "").strip() or ""
            extras_counts[kind or "(blank)"] += 1
            batch.append(
                (
                    count,
                    as_int(row.get("match_id"), -1),
                    as_int(row.get("innings")),
                    as_int(row.get("overid")),
                    as_int(row.get("over_ball_num")),
                    as_int(row.get("innings_ball_num")),
                    as_int(row.get("batting_team_id"), -1),
                    as_int(row.get("striker_id"), -1),
                    row.get("striker_name", ""),
                    as_int(row.get("non_striker_id"), -1),
                    row.get("non_striker_name", ""),
                    as_int(row.get("bowler_id"), -1),
                    row.get("bowler_name", ""),
                    as_int(row.get("runs")),
                    as_int(row.get("extras_2_runs")),
                    kind,
                    as_bool(row.get("is_four")),
                    as_bool(row.get("is_six")),
                    as_bool(row.get("is_wicket")),
                    row.get("dismissal_type", ""),
                    as_int(row.get("dismissed_player_id"), -1),
                    row.get("pace_or_spin", ""),
                    as_float(row.get("bowl_speed")),
                    row.get("delivery_ist_time", ""),
                )
            )
            count += 1
            if len(batch) >= 20_000:
                conn.executemany(insert_sql, batch)
                batch.clear()
        if batch:
            conn.executemany(insert_sql, batch)
    conn.commit()
    return count, extras_counts


def build_source_player_records(conn: sqlite3.Connection) -> dict[str, int]:
    """Aggregate the raw CSV independently of the processed delivery tables."""
    path = RAW_DIR / "ball_by_ball.csv"
    batters: dict[tuple[int, int, int], dict[str, Any]] = {}
    bowlers: dict[tuple[int, int, int], dict[str, Any]] = {}
    player_names: dict[tuple[str, int], set[str]] = {}

    def record(bucket: dict[tuple[int, int, int], dict[str, Any]], key: tuple[int, int, int]) -> dict[str, Any]:
        return bucket.setdefault(
            key,
            {
                "source_names": set(),
                "source_rows": 0,
                "runs": 0,
                "balls": 0,
                "dismissals": 0,
                "fours": 0,
                "sixes": 0,
                "runs_proxy": 0,
                "legal_balls": 0,
                "wicket_events": 0,
                "credited_wickets": 0,
            },
        )

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            innings = as_int(row.get("innings"), -1)
            if innings not in (1, 2):
                continue
            match_id = as_int(row.get("match_id"), -1)
            kind = normalized_extra(row.get("extras_type"))
            legal, _ = classify_legality(kind)
            faced = int(kind not in ({"wide"} | UNKNOWN_TYPES))
            runs = as_int(row.get("runs"))
            runs_proxy = runs + as_int(row.get("extras_2_runs"))
            is_wicket = as_bool(row.get("is_wicket"))
            dismissal = normalized_extra(row.get("dismissal_type"))
            credited_wicket = int(is_wicket and dismissal in CREDITED_DISMISSALS)

            striker_id = as_int(row.get("striker_id"), -1)
            if striker_id >= 0:
                key = (match_id, innings, striker_id)
                item = record(batters, key)
                source_name = str(row.get("striker_name") or "").strip()
                if source_name:
                    item["source_names"].add(source_name)
                    player_names.setdefault(("batter", striker_id), set()).add(source_name)
                item["source_rows"] += 1
                item["runs"] += runs
                item["balls"] += faced
                item["fours"] += as_bool(row.get("is_four"))
                item["sixes"] += as_bool(row.get("is_six"))
                item["dismissals"] += int(
                    is_wicket and as_int(row.get("dismissed_player_id"), -1) == striker_id
                )

            bowler_id = as_int(row.get("bowler_id"), -1)
            if bowler_id >= 0:
                key = (match_id, innings, bowler_id)
                item = record(bowlers, key)
                source_name = str(row.get("bowler_name") or "").strip()
                if source_name:
                    item["source_names"].add(source_name)
                    player_names.setdefault(("bowler", bowler_id), set()).add(source_name)
                item["source_rows"] += 1
                item["runs_proxy"] += runs_proxy
                item["legal_balls"] += legal
                item["wicket_events"] += is_wicket
                item["credited_wickets"] += credited_wicket

    conn.executemany(
        """INSERT INTO source_batter_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                match_id,
                innings,
                player_id,
                sorted(item["source_names"])[-1] if item["source_names"] else "",
                item["source_rows"],
                item["runs"],
                item["balls"],
                item["dismissals"],
                item["fours"],
                item["sixes"],
            )
            for (match_id, innings, player_id), item in batters.items()
        ],
    )
    conn.executemany(
        """INSERT INTO source_bowler_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                match_id,
                innings,
                player_id,
                sorted(item["source_names"])[-1] if item["source_names"] else "",
                item["source_rows"],
                item["runs_proxy"],
                item["legal_balls"],
                item["wicket_events"],
                item["credited_wickets"],
            )
            for (match_id, innings, player_id), item in bowlers.items()
        ],
    )
    conn.executemany(
        "INSERT INTO source_player_names VALUES (?, ?, ?)",
        [
            (role, player_id, source_name)
            for (role, player_id), names in player_names.items()
            for source_name in sorted(names)
        ],
    )
    conn.commit()
    return {
        "batter_record_rows": len(batters),
        "bowler_record_rows": len(bowlers),
        "player_name_keys": len(player_names),
    }


def batting_team_name(meta: dict[str, Any], team_id: int) -> str:
    if team_id == meta.get("home_team_id"):
        return meta.get("home_team", "")
    if team_id == meta.get("away_team_id"):
        return meta.get("away_team", "")
    return f"Team {team_id}" if team_id >= 0 else "Unknown"


def process_innings(conn: sqlite3.Connection, metadata: dict[int, dict[str, Any]]) -> dict[str, Any]:
    delivery_insert = """INSERT INTO deliveries(
        match_id, innings, seq, over_no, over_ball_num, innings_ball_num, batting_team_id,
        striker_id, striker_name, non_striker_id, non_striker_name, bowler_id, bowler_name,
        runs, extras2_runs, total_runs_proxy, extras_type, legal, unknown_legality, faced_ball,
        is_four, is_six, is_wicket, dismissal_type, dismissed_player_id, credited_wicket,
        team_dot, batter_dot, pace_or_spin, bowl_speed, score_before, target, target_source,
        scheduled_balls, schedule_source, balls_remaining, wickets_lost, rrr, state_known,
        pressure, current_rpo, bowling_pressure
    ) VALUES (""" + ",".join("?" for _ in range(42)) + ")"
    chase_targets: dict[int, int | None] = {}
    chase_target_sources: dict[int, str] = {}
    first_totals: dict[int, int] = {}
    counts = {
        "known_rrr_states": 0,
        "unknown_rrr_states": 0,
        "pressure_legal_deliveries": 0,
        "unknown_legality_events": 0,
        "extra_innings_rows": 0,
    }
    current_key: tuple[int, int] | None = None
    group: list[sqlite3.Row] = []

    def flush(items: list[sqlite3.Row], key: tuple[int, int] | None) -> None:
        if not items or key is None:
            return
        match_id, innings = key
        meta = metadata.get(match_id)
        if not meta:
            return
        batting_id = as_int(items[0]["batting_team_id"], -1)
        if innings == 1:
            meta["batting_first_team_id"] = batting_id if batting_id >= 0 else None
            target = meta["revised_target"]
            target_source = "matches.revised_target" if target is not None else ""
        elif innings == 2:
            meta["chasing_team_id"] = batting_id if batting_id >= 0 else None
            first_total = first_totals.get(match_id)
            if meta["revised_target"] is not None:
                target = meta["revised_target"]
                target_source = "matches.revised_target"
            elif first_total is not None:
                target = first_total + 1
                target_source = "first-innings raw run fields + 1"
            else:
                target = None
                target_source = "Unknown"
            chase_targets[match_id] = target
            chase_target_sources[match_id] = target_source
            winner = meta["win_team_id"]
            meta["chase_success"] = (
                int(winner == batting_id) if winner is not None and batting_id >= 0 else None
            )
        else:
            target = None
            target_source = ""

        schedule = meta["scheduled_balls"] if innings == 2 else None
        schedule_source = meta["schedule_source"] if innings == 2 else ""
        if innings == 1:
            schedule = overs_to_balls("")

        score = 0
        legal_elapsed = 0
        wickets_lost = 0
        state_certain = bool(innings == 2 and target is not None and schedule)
        known_legal = 0
        unknown_legality = 0
        wicket_events = 0
        credited_wickets = 0
        fours = 0
        sixes = 0
        zero_legal = 0
        rrr_values: list[tuple[int, int, float]] = []
        pressure_rows = 0
        pressure_legal = 0
        pressure_runs = 0
        pressure_wickets = 0
        output_rows: list[tuple[Any, ...]] = []
        seq = 0

        for item in items:
            seq += 1
            extra = item["extras_type"]
            legal, unknown = classify_legality(extra)
            unknown_legality += unknown
            counts["unknown_legality_events"] += unknown
            faced = int(normalized_extra(extra) not in {"wide"} | UNKNOWN_TYPES)
            is_wicket = int(item["is_wicket"])
            credited = int(
                is_wicket
                and (item["dismissal_type"] or "").strip().casefold() in CREDITED_DISMISSALS
            )
            total_proxy = int(item["runs"] or 0) + int(item["extras2_runs"] or 0)
            batter_runs = int(item["runs"] or 0)
            score_before = score
            remaining: int | None = None
            rrr: float | None = None
            known = 0
            if innings == 2 and target is not None and schedule and state_certain:
                remaining = max(int(schedule) - legal_elapsed, 0)
                if remaining > 0:
                    rrr = max(int(target) - score_before, 0) * 6.0 / remaining
                    known = 1
                else:
                    state_certain = False
            current_rpo = (
                score_before * 6.0 / (int(schedule) - int(remaining))
                if known == 1
                and schedule is not None
                and remaining is not None
                and int(schedule) > int(remaining)
                else None
            )
            pressure = pressure_state(rrr, remaining, wickets_lost, bool(known))
            bowling_pressure = bowling_pressure_state(
                current_rpo, rrr, remaining, wickets_lost, bool(known)
            )
            if innings == 2:
                if known:
                    counts["known_rrr_states"] += 1
                    rrr_values.append((seq, int(item["over_no"]), float(rrr or 0.0)))
                else:
                    counts["unknown_rrr_states"] += 1
                pressure_rows += pressure
                pressure_legal += int(pressure and legal)
                if pressure:
                    pressure_runs += total_proxy
                    pressure_wickets += is_wicket
                if pressure and legal:
                    counts["pressure_legal_deliveries"] += 1
            else:
                known = 0

            team_dot = int(legal and total_proxy == 0)
            batter_dot = int(faced and batter_runs == 0)
            known_legal += legal
            wicket_events += is_wicket
            credited_wickets += credited
            fours += int(item["is_four"])
            sixes += int(item["is_six"])
            zero_legal += team_dot

            output_rows.append(
                (
                    match_id,
                    innings,
                    seq,
                    item["over_no"],
                    item["over_ball_num"],
                    item["innings_ball_num"],
                    batting_id,
                    item["striker_id"],
                    item["striker_name"],
                    item["non_striker_id"],
                    item["non_striker_name"],
                    item["bowler_id"],
                    item["bowler_name"],
                    batter_runs,
                    int(item["extras2_runs"] or 0),
                    total_proxy,
                    extra,
                    legal,
                    unknown,
                    faced,
                    int(item["is_four"]),
                    int(item["is_six"]),
                    is_wicket,
                    item["dismissal_type"],
                    item["dismissed_player_id"],
                    credited,
                    team_dot,
                    batter_dot,
                    item["pace_or_spin"],
                    float(item["bowl_speed"] or 0.0),
                    score_before,
                    target if innings == 2 else None,
                    target_source if innings == 2 else "",
                    schedule,
                    schedule_source,
                    remaining,
                    wickets_lost if innings == 2 else 0,
                    rrr,
                    known,
                    pressure,
                    current_rpo,
                    bowling_pressure,
                )
            )

            # The state is pre-ball. Apply the event only after saving it.
            score += total_proxy
            wickets_lost += is_wicket
            if legal:
                legal_elapsed += 1
            if unknown:
                # Later ball counts can no longer be known exactly.
                state_certain = False

        conn.executemany(delivery_insert, output_rows)
        if innings == 1:
            first_totals[match_id] = score
        chase_success = meta.get("chase_success") if innings == 2 else None
        rrr_mean = statistics.fmean(v[2] for v in rrr_values) if rrr_values else None
        peak = max(rrr_values, key=lambda item: item[2]) if rrr_values else None
        conn.execute(
            """INSERT OR REPLACE INTO innings_summary VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )""",
            (
                match_id,
                innings,
                batting_id,
                batting_team_name(meta, batting_id),
                score,
                known_legal,
                unknown_legality,
                wicket_events,
                credited_wickets,
                fours,
                sixes,
                zero_legal,
                len(items),
                target if innings == 2 else None,
                target_source if innings == 2 else "",
                schedule if innings == 2 else None,
                schedule_source if innings == 2 else "",
                len(rrr_values) if innings == 2 else 0,
                (len(items) - len(rrr_values)) if innings == 2 else 0,
                rrr_mean if innings == 2 else None,
                peak[2] if peak else None,
                peak[0] if peak else None,
                peak[1] if peak else None,
                pressure_rows if innings == 2 else 0,
                pressure_legal if innings == 2 else 0,
                pressure_runs if innings == 2 else 0,
                pressure_wickets if innings == 2 else 0,
                chase_success,
            ),
        )

    query = conn.execute(
        """SELECT * FROM staging_deliveries
        ORDER BY match_id, innings, over_no, innings_ball_num, over_ball_num, source_order"""
    )
    query.row_factory = sqlite3.Row
    for row in query:
        key = (int(row["match_id"]), int(row["innings"]))
        if current_key is None:
            current_key = key
        if key != current_key:
            flush(group, current_key)
            group = []
            current_key = key
        group.append(row)
    flush(group, current_key)

    conn.executemany(
        """UPDATE matches SET batting_first_team_id = ?, chasing_team_id = ?, chase_success = ?
        WHERE match_id = ?""",
        [
            (
                item.get("batting_first_team_id"),
                item.get("chasing_team_id"),
                item.get("chase_success"),
                match_id,
            )
            for match_id, item in metadata.items()
        ],
    )
    conn.execute("DROP TABLE staging_deliveries")
    conn.commit()
    counts["innings_summaries"] = conn.execute("SELECT COUNT(*) FROM innings_summary").fetchone()[0]
    counts["delivery_rows_processed"] = conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]
    counts["matches_with_second_innings"] = conn.execute(
        "SELECT COUNT(*) FROM innings_summary WHERE innings=2"
    ).fetchone()[0]
    return counts


def load_workbook_pressure(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = read_pressure_table(WORKBOOK_PATH)
    count = 0
    for row in rows:
        match_id = as_int(row.get("Match ID"), -1)
        if match_id < 0:
            continue
        severe = as_optional_int(row.get("Severe Pressure Delivery Count (RRR>=15, wickets>=3, balls<=30)"))
        high = as_optional_int(row.get("High/Extreme RRR Delivery Count"))
        target = as_optional_int(row.get("Target (source/derived)"))
        mean_rrr = as_float(row.get("Mean RRR Proxy"), math.nan)
        peak_rrr = as_float(row.get("Peak RRR Proxy"), math.nan)
        result = row.get("Match Result", "")
        conn.execute(
            """INSERT OR REPLACE INTO workbook_pressure VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                match_id,
                severe,
                high,
                target,
                None if math.isnan(mean_rrr) else mean_rrr,
                None if math.isnan(peak_rrr) else peak_rrr,
                result,
            ),
        )
        count += 1
    conn.commit()
    return {"rows_loaded": count, "path": str(WORKBOOK_PATH), "exists": WORKBOOK_PATH.exists()}


def register_sources(conn: sqlite3.Connection) -> dict[str, Any]:
    files = {}
    for name in EXPECTED_RAW_FILES:
        path = RAW_DIR / name
        if not path.exists():
            continue
        row_count = 0
        if name.endswith(".csv"):
            with path.open("r", encoding="utf-8-sig", newline="") as file:
                row_count = max(sum(1 for _ in file) - 1, 0)
        info = {
            "row_count": row_count,
            "byte_size": path.stat().st_size,
            "sha256": source_hash(path),
        }
        files[name] = info
        conn.execute(
            "INSERT OR REPLACE INTO source_files VALUES (?, ?, ?, ?)",
            (name, row_count, path.stat().st_size, info["sha256"]),
        )
    if WORKBOOK_PATH.exists():
        files[WORKBOOK_PATH.name] = {
            "row_count": None,
            "byte_size": WORKBOOK_PATH.stat().st_size,
            "sha256": source_hash(WORKBOOK_PATH),
        }
    conn.commit()
    return files


def validate_database(
    conn: sqlite3.Connection,
    source_rows: int,
    extras_counts: Counter[str],
    processing: dict[str, Any],
    source_player_records: dict[str, int],
    workbook_info: dict[str, Any],
    source_files: dict[str, Any],
) -> dict[str, Any]:
    result_proxy_compare = conn.execute(
        """
        SELECT s1.match_id, s1.total_runs_proxy - s2.total_runs_proxy AS raw_margin, m.result
        FROM innings_summary s1
        JOIN innings_summary s2 ON s1.match_id=s2.match_id AND s2.innings=2
        JOIN matches m ON m.match_id=s1.match_id
        WHERE s1.innings=1 AND lower(m.result) LIKE '%won by%'
        """
    ).fetchall()
    reconciled = 0
    run_comparisons = 0
    for _, raw_margin, result in result_proxy_compare:
        match = re.search(r"won by\s+([\d,]+)\s+run", str(result), re.IGNORECASE)
        if match:
            run_comparisons += 1
            if abs(int(match.group(1).replace(",", ""))) == abs(int(raw_margin or 0)):
                reconciled += 1

    workbook_compare = conn.execute(
        """
        SELECT COUNT(*),
               SUM(CASE WHEN i.pressure_legal_balls = w.workbook_pressure_count THEN 1 ELSE 0 END)
        FROM workbook_pressure w
        LEFT JOIN innings_summary i ON i.match_id=w.match_id AND i.innings=2
        WHERE w.workbook_pressure_count IS NOT NULL
        """
    ).fetchone()
    matches_by_format = [
        {"format": row[0], "matches": row[1], "seasons": row[2]}
        for row in conn.execute(
            "SELECT match_format, COUNT(*), COUNT(DISTINCT season) FROM matches GROUP BY match_format ORDER BY match_format"
        )
    ]
    invalid_dates = conn.execute(
        "SELECT COUNT(*) FROM matches WHERE match_date IS NULL OR length(match_date) < 8"
    ).fetchone()[0]
    extra_innings_rows = conn.execute(
        "SELECT COUNT(*) FROM deliveries WHERE innings > 2"
    ).fetchone()[0]
    ambiguous_players = conn.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT striker_id FROM deliveries
            WHERE striker_id >= 0 AND striker_name <> ''
            GROUP BY striker_id HAVING COUNT(DISTINCT striker_name) > 1
        )
        """
    ).fetchone()[0]
    ambiguous_bowler_names = conn.execute(
        """SELECT COUNT(*) FROM (
            SELECT player_id FROM source_player_names
            WHERE role='bowler' GROUP BY player_id HAVING COUNT(*)>1
        )"""
    ).fetchone()[0]
    ambiguous_batter_names = conn.execute(
        """SELECT COUNT(*) FROM (
            SELECT player_id FROM source_player_names
            WHERE role='batter' GROUP BY player_id HAVING COUNT(*)>1
        )"""
    ).fetchone()[0]
    duplicate_match_ids = conn.execute(
        "SELECT COUNT(*) - COUNT(DISTINCT match_id) FROM matches"
    ).fetchone()[0]

    raw_comparison_count = workbook_compare[0] or 0
    raw_match_count = run_comparisons
    mismatch_count = raw_match_count - reconciled
    return {
        "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_files": source_files,
        "scope": {
            "formats": matches_by_format,
            "matches": conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0],
            "delivery_rows": source_rows,
            "processed_delivery_rows": processing["delivery_rows_processed"],
            "innings_summaries": processing["innings_summaries"],
            "second_innings": processing["matches_with_second_innings"],
            "extra_innings_delivery_rows_excluded_from_standard_views": extra_innings_rows,
        },
        "definitions": {
            "pressure": "Pre-ball state in innings 2 with RRR >= 15, <= 30 known legal balls remaining, and >= 3 wickets lost.",
            "target": "matches.revised_target when present; otherwise first-innings raw run fields (runs + extras_2_runs) + 1.",
            "raw_team_runs_proxy": "runs + extras_2_runs; this is a source-field proxy and does not consistently reconcile to result margins.",
            "legal_ball_map": "None/byes/legbyes are known legal; wide/Overstep are known illegal; other/Penalty/blank/unmapped values have unknown legality.",
            "unknown_state": "After an unknown-legality event, later chase legal-ball states are marked unknown because remaining balls cannot be reconstructed exactly.",
            "regular_innings_scope": "Player, venue, and chase analytics use innings 1 and 2. Extra innings are retained in deliveries and excluded from standard T20 views.",
            "bowler_credited_wickets": sorted(CREDITED_DISMISSALS),
            "balls_faced": "Delivery rows excluding wides and rows with unknown legality; Overstep/no-ball events count as faced.",
            "sample_adjustments": "Display-only shrinkage uses 100 prior balls for batting strike rate, 3 prior dismissals for batting average, and 60 prior legal balls for bowling rates.",
        },
        "quality": {
            "extras_type_counts": dict(extras_counts),
            "unknown_legality_events": sum(extras_counts.get(value, 0) for value in ("other", "Penalty", "(blank)")),
            "source_run_margin_comparisons": raw_match_count,
            "source_run_margin_matches": reconciled,
            "source_run_margin_mismatches": mismatch_count,
            "workbook_pressure_rows": workbook_info["rows_loaded"],
            "workbook_pressure_count_comparisons": raw_comparison_count,
            "workbook_pressure_count_matches": workbook_compare[1] or 0,
            "invalid_date_rows": invalid_dates,
            "ambiguous_striker_ids_with_multiple_names": ambiguous_players,
            "ambiguous_source_batter_ids_with_multiple_names": ambiguous_batter_names,
            "ambiguous_source_bowler_ids_with_multiple_names": ambiguous_bowler_names,
            "duplicate_match_ids": duplicate_match_ids,
            "revised_schedule_matches": conn.execute(
                "SELECT COUNT(*) FROM matches WHERE schedule_source='matches.second_inn_revised_overs'"
            ).fetchone()[0],
            "revised_target_matches": conn.execute(
                "SELECT COUNT(*) FROM matches WHERE revised_target IS NOT NULL"
            ).fetchone()[0],
        },
        "processing": processing,
        "independent_source_player_records": source_player_records,
        "workbook_reference": workbook_info,
    }


def main() -> None:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    QUALITY_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    metadata = load_metadata(conn)
    source_rows, extras_counts = ingest_deliveries(conn)
    processing = process_innings(conn, metadata)
    source_player_records = build_source_player_records(conn)
    workbook_info = load_workbook_pressure(conn)
    sources = register_sources(conn)
    quality = validate_database(
        conn,
        source_rows,
        extras_counts,
        processing,
        source_player_records,
        workbook_info,
        sources,
    )
    conn.close()
    QUALITY_PATH.write_text(json.dumps(quality, indent=2), encoding="utf-8")
    print(f"Built {DB_PATH}")
    print(json.dumps(quality["scope"], indent=2))
    print(json.dumps(quality["quality"], indent=2))


if __name__ == "__main__":
    main()
