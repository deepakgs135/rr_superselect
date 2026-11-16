"""Load the raw-CSV pressure report artifacts for Streamlit pages."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
REPORT_PATH = APP_DIR / "data" / "pressure_report" / "pressure_report.json"


@lru_cache(maxsize=4)
def _load_report(path: str, modified: int) -> str:
    return Path(path).read_text(encoding="utf-8")


def pressure_report() -> dict[str, Any]:
    if not REPORT_PATH.exists():
        return {}
    return json.loads(_load_report(str(REPORT_PATH), REPORT_PATH.stat().st_mtime_ns))
