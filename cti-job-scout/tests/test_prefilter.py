"""Tests for the keyword prefilter that gates LLM scoring."""

from jobscout.models import JobPosting
from jobscout.prefilter import is_relevant


def posting(title: str, description: str = "") -> JobPosting:
    return JobPosting(
        uid="greenhouse:test:1",
        company="TestCo",
        ats="greenhouse",
        title=title,
        url="https://example.com/1",
        description=description,
    )


def test_specific_title_passes():
    assert is_relevant(posting("Cyber Threat Intelligence Analyst"))
    assert is_relevant(posting("Detection Engineer"))
    assert is_relevant(posting("Threat Hunter II"))
    assert is_relevant(posting("SOC Analyst"))
    assert is_relevant(posting("Malware Reverse Engineer"))
    assert is_relevant(posting("Technical Threat Investigator"))


def test_specific_beats_exclusion():
    # "Solutions Engineer" is excluded, but "Threat Intelligence" wins.
    assert is_relevant(posting("Threat Intelligence Solutions Engineer"))


def test_excluded_titles_fail():
    assert not is_relevant(posting("Enterprise Account Executive - Security"))
    assert not is_relevant(posting("Sales Development Representative"))
    assert not is_relevant(posting("Senior Product Manager, Payments"))
    assert not is_relevant(posting("Technical Recruiter"))
    assert not is_relevant(posting("Solutions Architect"))


def test_generic_security_title_passes():
    assert is_relevant(posting("Security Engineer"))
    assert is_relevant(posting("Cybersecurity Specialist"))


def test_unrelated_engineering_fails():
    assert not is_relevant(posting("Senior Software Engineer, Frontend"))
    assert not is_relevant(posting("Data Engineer"))
    assert not is_relevant(posting("Site Reliability Engineer"))


def test_description_fallback_needs_multiple_hits():
    vague = posting(
        "Member of Technical Staff",
        "You will run threat intelligence collection, support incident "
        "response, and map adversary activity to MITRE ATT&CK.",
    )
    assert is_relevant(vague)

    passing_mention = posting(
        "Backend Engineer",
        "We take security seriously and our SIEM is great.",
    )
    assert not is_relevant(passing_mention)


def test_soc_does_not_match_inside_words():
    # \bsoc\b must not fire on "social" or "associate".
    assert not is_relevant(posting("Social Media Coordinator"))
    assert not is_relevant(posting("Sales Associate"))
