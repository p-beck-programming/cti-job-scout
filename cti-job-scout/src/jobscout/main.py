"""Orchestrator: fetch -> dedup -> score -> digest -> dashboard -> send -> save.

Run locally with:  python -m jobscout.main
Environment:       see .env.example
"""

from __future__ import annotations

import logging
import sys

from .config import Settings, load_companies
from .dashboard import write_dashboard_data
from .digest import build_digest
from .fetchers import fetch_all
from .models import ScoredJob
from .scoring import ScoringError, score_posting
from .state import StateStore

log = logging.getLogger("jobscout")


def run() -> int:
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

    # 3. Score new postings. A ScoringError leaves the posting unmarked so
    #    the next run retries it; everything scored is marked seen even if
    #    below threshold (we've made a decision about it).
    matches: list[ScoredJob] = []
    failures = 0
    for posting in new_postings:
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

    # 4. Refresh dashboard data from full scored history (not just today),
    #    so the filterable UI accumulates a browsable backlog.
    write_dashboard_data(state.scored)

    # 5. Email only if there's something new to say — no empty digests.
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

    # 6. Persist state last, after the send succeeded (or was skipped), so a
    #    failed send doesn't silently swallow today's matches.
    state.save()

    # Non-zero exit if every scoring call failed — that means the API key or
    # model string is broken and the workflow should show red.
    if new_postings and failures == len(new_postings):
        log.error("All %d scoring attempts failed; check ANTHROPIC_API_KEY/model",
                  failures)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
