"""Weekly market synopsis: what are matched jobs asking for, in aggregate?

Every Monday the pipeline regenerates a synopsis from the past week's
matched postings (score >= threshold, already stored in state) with one
LLM call, and appends it to docs/synopsis.json. The static pages
docs/synopsis.html (current) and docs/archive.html (monthly archive)
render that file client-side.

Payload discipline — this is the one place we send many descriptions in a
single request, so everything is capped: at most MAX_JOBS postings, each
description truncated to PER_JOB_CHARS, total input bounded by
MAX_TOTAL_CHARS. That keeps the request well inside free-tier request
size limits.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import ValidationError

from .models import ScoredJob, Synopsis
from .prompts import SYNOPSIS_SYSTEM_PROMPT
from .scoring import DEFAULT_MODEL, extract_json_object

log = logging.getLogger(__name__)

DEFAULT_SYNOPSIS_PATH = Path("docs/synopsis.json")

LOOKBACK_DAYS = 7          # normal window: matches from the last week
FALLBACK_LOOKBACK_DAYS = 30  # widen if the week was quiet...
MIN_JOBS = 6               # ...i.e. fewer than this many matches
MAX_JOBS = 25              # newest first; cap the LLM payload
PER_JOB_CHARS = 4_000      # per-description truncation
MAX_TOTAL_CHARS = 70_000   # hard ceiling on the whole prompt input
MAX_ATTEMPTS = 2           # one corrective retry on malformed JSON
MAX_HISTORY = 60           # ~14 months of weekly entries in synopsis.json


class SynopsisError(Exception):
    """Raised when the synopsis cannot be generated."""


def select_jobs(
    scored: list[ScoredJob], now: datetime | None = None
) -> tuple[list[ScoredJob], int]:
    """Pick the postings that feed the synopsis.

    Returns (jobs, lookback_days_used). Prefers the last week's matches;
    widens to FALLBACK_LOOKBACK_DAYS when the week was quiet so the
    synopsis never runs on a near-empty sample.
    """
    now = now or datetime.now(timezone.utc)
    for days in (LOOKBACK_DAYS, FALLBACK_LOOKBACK_DAYS):
        cutoff = now - timedelta(days=days)
        window = [j for j in scored if j.scored_at >= cutoff]
        if len(window) >= MIN_JOBS or days == FALLBACK_LOOKBACK_DAYS:
            window.sort(key=lambda j: j.scored_at, reverse=True)
            return window[:MAX_JOBS], days
    return [], FALLBACK_LOOKBACK_DAYS  # unreachable, keeps mypy honest


def build_synopsis_input(jobs: list[ScoredJob]) -> str:
    """Concatenate postings into one bounded text block for the LLM."""
    blocks: list[str] = []
    total = 0
    for i, job in enumerate(jobs, 1):
        p = job.posting
        desc = (p.description or "(no description)")[:PER_JOB_CHARS]
        block = f"--- Posting {i}: {p.company} — {p.title} ---\n{desc}\n"
        if total + len(block) > MAX_TOTAL_CHARS:
            log.info("Synopsis input capped at %d of %d postings "
                     "(size limit)", i - 1, len(jobs))
            break
        blocks.append(block)
        total += len(block)
    return "\n".join(blocks)


def generate_synopsis(
    jobs: list[ScoredJob], model: str | None = None, completion_fn=None
) -> Synopsis:
    """One LLM call (plus one corrective retry) -> validated Synopsis."""
    import litellm  # lazy, same rationale as scoring.py

    if completion_fn is None:
        completion_fn = litellm.completion
    if model is None:
        model = os.environ.get(
            "JOBSCOUT_SYNOPSIS_MODEL",
            os.environ.get("JOBSCOUT_MODEL", DEFAULT_MODEL),
        )

    messages = [
        {"role": "system", "content": SYNOPSIS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Here are {len(jobs)} matched postings from the past week:\n\n"
                + build_synopsis_input(jobs)
            ),
        },
    ]
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = completion_fn(model=model, max_tokens=2000, messages=messages)
            text = response.choices[0].message.content or ""
            return Synopsis.model_validate(extract_json_object(text))
        except (json.JSONDecodeError, ValueError, ValidationError) as exc:
            last_error = exc
            log.warning("Malformed synopsis (attempt %d/%d): %s",
                        attempt, MAX_ATTEMPTS, exc)
            messages = messages + [
                {"role": "assistant", "content": text if "text" in dir() else ""},
                {
                    "role": "user",
                    "content": (
                        "Your previous reply was not a single valid JSON object "
                        "matching the required schema. Respond again with ONLY "
                        "the JSON object."
                    ),
                },
            ]
        except Exception as exc:
            raise SynopsisError(f"Synopsis API call failed: {exc}") from exc
    raise SynopsisError(f"Malformed synopsis after {MAX_ATTEMPTS} attempts: {last_error}")


def _entry(synopsis: Synopsis, jobs: list[ScoredJob], model: str,
           lookback_days: int) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "period_label": f"Week of {(now - timedelta(days=7)).date().isoformat()}",
        "generated_at": now.isoformat(),
        "source": "weekly",
        "model": model,
        "job_count": len(jobs),
        "lookback_days": lookback_days,
        "companies": sorted({j.posting.company for j in jobs}),
        **synopsis.model_dump(),
    }


def refresh_synopsis(
    scored: list[ScoredJob],
    path: Path = DEFAULT_SYNOPSIS_PATH,
    model: str | None = None,
    completion_fn=None,
) -> bool:
    """Regenerate the synopsis and prepend it to docs/synopsis.json.

    Returns True on success, False when skipped (no matches to summarize).
    Raises SynopsisError on API/parse failure so the caller can log it
    without failing the whole run.
    """
    jobs, lookback = select_jobs(scored)
    if not jobs:
        log.info("No matched jobs in the last %d days; keeping existing "
                 "synopsis", FALLBACK_LOOKBACK_DAYS)
        return False

    resolved_model = model or os.environ.get(
        "JOBSCOUT_SYNOPSIS_MODEL",
        os.environ.get("JOBSCOUT_MODEL", DEFAULT_MODEL),
    )
    log.info("Regenerating synopsis from %d matches (last %d days) via %s",
             len(jobs), lookback, resolved_model)
    synopsis = generate_synopsis(jobs, model=resolved_model,
                                 completion_fn=completion_fn)

    path = Path(path)
    history: list[dict] = []
    if path.exists():
        try:
            history = json.loads(path.read_text()).get("history", [])
        except (json.JSONDecodeError, ValueError) as exc:
            log.error("Corrupt %s (%s); starting a fresh history", path, exc)

    entry = _entry(synopsis, jobs, resolved_model, lookback)
    history = [entry] + history
    history = history[:MAX_HISTORY]

    payload = {"generated_at": entry["generated_at"],
               "current": entry, "history": history}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    log.info("Synopsis written: %s (%d history entries)", path, len(history))
    return True
