"""Orchestrator: fetch -> dedup -> prefilter -> score -> digest -> dashboard
-> synopsis (Mondays) -> send -> save.

Run locally with:  python -m jobscout.main
Environment:       see .env.example
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import date

from dotenv import load_dotenv

from .config import Settings, load_companies
from .dashboard import write_dashboard_data
from .digest import build_digest
from .fetchers import fetch_all
from .models import ScoredJob
from .prefilter import is_relevant
from .scoring import ScoringError, score_posting
from .state import StateStore

log = logging.getLogger("jobscout")


def run() -> int:
    # Load .env into the environment (no-op if absent, e.g. in CI). Real
    # environment variables and CI secrets already set are NOT overridden.
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.from_env()
    companies = load_companies()
    state = StateStore()

    # 1. Fetch everything currently open.
    postings = fetch_all(companies)
    log.info("Fetched %d total open postings from %d companies",
             len(postings), len(companies))

    # 2. Dedup against state.
    new_postings = [p for p in postings if not state.is_seen(p.uid)]
    log.info("%d postings are new (unseen)", len(new_postings))

    # 3. Prefilter: obviously irrelevant postings (sales, unrelated
    #    engineering, ...) are marked seen WITHOUT an LLM call — this is
    #    what keeps API usage (and free-tier rate limits) under control.
    to_score: list = []
    for posting in new_postings:
        if is_relevant(posting):
            to_score.append(posting)
        else:
            state.mark_seen(posting.uid)
            log.info("[skip] %s — %s (prefiltered, no LLM call)",
                     posting.company, posting.title)
    log.info("%d of %d new postings passed the prefilter",
             len(to_score), len(new_postings))

    # 4. Score the relevant postings. A ScoringError leaves the posting
    #    unmarked so the next run retries it; everything scored is marked
    #    seen even if below threshold (we've made a decision about it).
    matches: list[ScoredJob] = []
    failures = 0
    for i, posting in enumerate(to_score):
        if i and settings.score_delay:
            time.sleep(settings.score_delay)  # stay under provider RPM caps
        try:
            score = score_posting(posting)
        except ScoringError as exc:
            failures += 1
            log.error("%s", exc)
            continue
        state.mark_seen(posting.uid)
        log.info("[%3d] %s — %s", score.score, posting.company, posting.title)
        if score.score >= settings.score_threshold:
            job = ScoredJob(posting=posting, score=score)
            matches.append(job)
            state.add_scored(job)

    # 5. Refresh dashboard data from full scored history (not just today),
    #    so the filterable UI accumulates a browsable backlog.
    write_dashboard_data(state.scored)

    # 6. Weekly synopsis: on Mondays (or when forced) summarize the last
    #    week's matches into docs/synopsis.json with one LLM call. Failure
    #    is logged but never blocks the digest email.
    if settings.force_synopsis or date.today().weekday() == 0:
        from .synopsis import SynopsisError, refresh_synopsis  # lazy: litellm

        try:
            refresh_synopsis(state.scored)
        except SynopsisError as exc:
            log.error("Synopsis regeneration failed: %s", exc)

    # 7. Email only if there's something new to say — no empty digests.
    if matches:
        subject, body = build_digest(matches, dashboard_url=settings.dashboard_url)
        if settings.dry_run:
            log.info("DRY_RUN: would send %r with %d matches", subject, len(matches))
        else:
            from .mailer import send_digest  # lazy: google libs only when needed

            send_digest(subject, body)
    else:
        log.info("No new matches above threshold %d; no email sent",
                 settings.score_threshold)

    # 8. Persist state last, after the send succeeded (or was skipped), so a
    #    failed send doesn't silently swallow today's matches.
    state.save()

    # Non-zero exit if every scoring call failed — that means the API key or
    # model string is broken and the workflow should show red.
    if to_score and failures == len(to_score):
        log.error("All %d scoring attempts failed; check your provider API key "
                  "and JOBSCOUT_MODEL", failures)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
