"""Digest builder tests: ordering, sectioning, escaping, threshold display."""

from jobscout.digest import build_digest
from jobscout.locations import parse_location
from jobscout.models import JobPosting, Score, ScoredJob


def _job(title, company, score, loc_raw, url="https://example.com/j/1"):
    return ScoredJob(
        posting=JobPosting(
            uid=f"greenhouse:x:{title}",
            company=company,
            ats="greenhouse",
            title=title,
            url=url,
            locations=[parse_location(loc_raw)],
        ),
        score=Score(score=score, rationale=f"Fit for {title}.", matched_keywords=["CTI"]),
    )


def test_sorted_by_score_descending_within_sections():
    jobs = [
        _job("Analyst", "A Co", 65, "Remote - US"),
        _job("Hunter", "B Co", 95, "Remote"),
        _job("Engineer", "C Co", 80, "Austin, TX"),
    ]
    _, body = build_digest(jobs)
    assert body.index("Hunter") < body.index("Analyst")  # remote section ordering
    assert "Remote-eligible (2)" in body
    assert "On-site / Hybrid (1)" in body


def test_subject_counts_and_pluralization():
    subject, _ = build_digest([_job("Analyst", "A", 70, "Remote")])
    assert "1 new CTI/DE/TH match —" in subject
    subject, _ = build_digest([_job("A", "A", 70, "Remote"), _job("B", "B", 70, "NYC")])
    assert "2 new CTI/DE/TH matches" in subject


def test_html_escaping_of_untrusted_ats_content():
    evil = _job("<script>alert(1)</script>", "Evil & Co", 90, "Remote")
    _, body = build_digest([evil])
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
    assert "Evil &amp; Co" in body


def test_locations_rendered():
    _, body = build_digest([_job("Engineer", "C Co", 80, "Nashville, TN")])
    assert "Nashville, TN" in body


def test_dashboard_link_included_when_configured():
    _, body = build_digest([_job("A", "A", 70, "Remote")],
                           dashboard_url="https://user.github.io/scout/")
    assert "https://user.github.io/scout/" in body


def test_dashboard_link_omitted_when_unset():
    _, body = build_digest([_job("A", "A", 70, "Remote")])
    assert "Open the dashboard" not in body
