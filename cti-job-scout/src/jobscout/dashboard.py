"""Write docs/jobs.json for the static filterable dashboard.

docs/index.html is a static single-file page (vanilla JS, no build step)
that fetches jobs.json and filters client-side by metro, state, remote,
minimum score, and free-text search. Publish it with GitHub Pages
(Settings -> Pages -> deploy from branch, /docs folder) or just open it
locally with `python -m http.server -d docs`.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .models import ScoredJob

log = logging.getLogger(__name__)

DEFAULT_DATA_PATH = Path("docs/jobs.json")


def write_dashboard_data(
    scored_history: list[ScoredJob], path: Path = DEFAULT_DATA_PATH
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [job.to_dashboard_row() for job in scored_history]
    # Newest first so the dashboard's default view leads with fresh matches.
    rows.sort(key=lambda r: (r["scored_at"], r["score"]), reverse=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "jobs": rows,
    }
    path.write_text(json.dumps(payload, indent=2))
    log.info("Dashboard data written: %d jobs -> %s", len(rows), path)
