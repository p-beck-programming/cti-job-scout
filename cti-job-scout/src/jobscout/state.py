"""Flat-file JSON state, committed back to the repo by the Actions workflow.

Why a committed JSON file instead of SQLite or an Actions cache/artifact:
- Actions caches are best-effort and evicted under branch/size pressure;
  losing the cache would re-email every posting ever seen. Artifacts expire
  (90 days by default) with the same failure mode.
- A committed file is durable, survives forks/clones, and gives you a free
  audit trail — `git log state/state.json` shows exactly what was seen when.
- SQLite would also work, but binary diffs are unreviewable in git and the
  volume here (hundreds of IDs) doesn't need it. JSON keeps the state
  greppable and hand-editable.

Structure:
{
  "seen": {"<uid>": "<ISO timestamp first seen>"},
  "scored": [<ScoredJob dicts for jobs that ever cleared the threshold>]
}
`scored` accumulates history so the dashboard can show more than one day.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .models import ScoredJob

log = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path("state/state.json")
MAX_SCORED_HISTORY = 500  # keep the dashboard/data file bounded


class StateStore:
    def __init__(self, path: Path = DEFAULT_STATE_PATH):
        self.path = Path(path)
        self.seen: dict[str, str] = {}
        self.scored: list[ScoredJob] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            log.info("No state file at %s; starting fresh", self.path)
            return
        try:
            data = json.loads(self.path.read_text())
            self.seen = data.get("seen", {})
            self.scored = [
                ScoredJob.model_validate(item) for item in data.get("scored", [])
            ]
        except (json.JSONDecodeError, ValueError) as exc:
            # A corrupt state file should be loud but not fatal: back it up
            # and start fresh rather than crashing every run forever.
            backup = self.path.with_suffix(".corrupt.json")
            self.path.rename(backup)
            log.error("Corrupt state file moved to %s (%s); starting fresh",
                      backup, exc)

    def is_seen(self, uid: str) -> bool:
        return uid in self.seen

    def mark_seen(self, uid: str) -> None:
        self.seen[uid] = datetime.now(timezone.utc).isoformat()

    def add_scored(self, job: ScoredJob) -> None:
        self.scored.append(job)
        if len(self.scored) > MAX_SCORED_HISTORY:
            self.scored = self.scored[-MAX_SCORED_HISTORY:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "seen": self.seen,
            "scored": [json.loads(j.model_dump_json()) for j in self.scored],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(self.path)  # atomic on POSIX: no half-written state
        log.info("State saved: %d seen, %d scored", len(self.seen), len(self.scored))
