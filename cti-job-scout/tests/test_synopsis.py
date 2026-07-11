"""Tests for synopsis job selection and payload capping (no LLM needed)."""

from datetime import datetime, timedelta, timezone

from jobscout.models import JobPosting, Score, ScoredJob
from jobscout.synopsis import (
    FALLBACK_LOOKBACK_DAYS,
    LOOKBACK_DAYS,
    MAX_JOBS,
    MAX_TOTAL_CHARS,
    PER_JOB_CHARS,
    build_synopsis_input,
    select_jobs,
)

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


def scored(days_ago: float, uid: str, desc: str = "desc") -> ScoredJob:
    return ScoredJob(
        posting=JobPosting(
            uid=f"greenhouse:test:{uid}",
            company=f"Co{uid}",
            ats="greenhouse",
            title=f"Threat Analyst {uid}",
            url=f"https://example.com/{uid}",
            description=desc,
        ),
        score=Score(score=80, rationale="Core CTI role."),
        scored_at=NOW - timedelta(days=days_ago),
    )


def test_uses_week_window_when_busy():
    jobs = [scored(i % 6, str(i)) for i in range(10)]  # all within 7 days
    picked, lookback = select_jobs(jobs, now=NOW)
    assert lookback == LOOKBACK_DAYS
    assert len(picked) == 10


def test_widens_lookback_when_week_is_quiet():
    jobs = [scored(2, "a"), scored(20, "b"), scored(25, "c")]
    picked, lookback = select_jobs(jobs, now=NOW)
    assert lookback == FALLBACK_LOOKBACK_DAYS
    assert {j.posting.uid for j in picked} == {
        "greenhouse:test:a", "greenhouse:test:b", "greenhouse:test:c"
    }


def test_ignores_jobs_older_than_fallback():
    jobs = [scored(2, "new"), scored(90, "ancient")]
    picked, _ = select_jobs(jobs, now=NOW)
    assert [j.posting.uid for j in picked] == ["greenhouse:test:new"]


def test_caps_job_count_newest_first():
    jobs = [scored(i * 0.1, str(i)) for i in range(MAX_JOBS + 10)]
    picked, _ = select_jobs(jobs, now=NOW)
    assert len(picked) == MAX_JOBS
    assert picked[0].posting.uid == "greenhouse:test:0"  # newest kept


def test_input_truncates_long_descriptions():
    text = build_synopsis_input([scored(0, "x", desc="A" * (PER_JOB_CHARS * 3))])
    assert len(text) < PER_JOB_CHARS + 200  # header + truncated body only


def test_input_respects_total_cap():
    jobs = [scored(0, str(i), desc="B" * PER_JOB_CHARS) for i in range(MAX_JOBS)]
    text = build_synopsis_input(jobs)
    assert len(text) <= MAX_TOTAL_CHARS


def test_input_labels_each_posting():
    text = build_synopsis_input([scored(0, "1"), scored(0, "2")])
    assert "Posting 1: Co1 — Threat Analyst 1" in text
    assert "Posting 2: Co2 — Threat Analyst 2" in text
