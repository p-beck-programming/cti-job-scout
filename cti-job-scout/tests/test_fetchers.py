"""Fetcher tests with mocked ATS API responses — no network required."""

from unittest.mock import MagicMock

import pytest
import requests

from jobscout.fetchers import (
    fetch_all,
    fetch_ashby,
    fetch_greenhouse,
    fetch_lever,
    strip_html,
)
from jobscout.models import Company

GH_COMPANY = Company(name="ExampleSec", ats="greenhouse", token="examplesec")
LEVER_COMPANY = Company(name="ExampleIntel", ats="lever", token="exampleintel")
ASHBY_COMPANY = Company(name="ExampleLab", ats="ashby", token="examplelab.io")


def _session_returning(json_payload, status=200):
    session = MagicMock(spec=requests.Session)
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_payload
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}")
    else:
        resp.raise_for_status.return_value = None
    session.get.return_value = resp
    return session


class TestGreenhouse:
    PAYLOAD = {
        "jobs": [
            {
                "id": 111,
                "title": "  Threat Intelligence Analyst ",
                "absolute_url": "https://boards.greenhouse.io/examplesec/jobs/111",
                "content": "<p>Track adversary <b>TTPs</b> &amp; write YARA rules.</p>",
                "location": {"name": "Remote - US"},
                "offices": [{"name": "Austin, TX"}],
                "updated_at": "2026-06-30T12:00:00Z",
            },
            {
                "id": 222,
                "title": "Detection Engineer",
                "absolute_url": "https://boards.greenhouse.io/examplesec/jobs/222",
                "content": "",
                "location": {"name": "Arlington, VA"},
            },
        ]
    }

    def test_parses_jobs(self):
        jobs = fetch_greenhouse(GH_COMPANY, _session_returning(self.PAYLOAD))
        assert len(jobs) == 2
        first = jobs[0]
        assert first.uid == "greenhouse:examplesec:111"
        assert first.title == "Threat Intelligence Analyst"  # stripped
        assert first.description == "Track adversary TTPs & write YARA rules."
        assert any(l.is_remote for l in first.locations)
        austin = next(l for l in first.locations if l.city == "Austin")
        assert austin.state == "TX" and austin.metro == "Austin Metro"

    def test_dc_metro_normalization(self):
        jobs = fetch_greenhouse(GH_COMPANY, _session_returning(self.PAYLOAD))
        arlington = jobs[1].locations[0]
        assert arlington.metro == "Washington DC Metro"
        assert arlington.state == "VA"

    def test_malformed_job_is_skipped_not_fatal(self):
        payload = {"jobs": [{"title": "no id field"}, self.PAYLOAD["jobs"][1]]}
        jobs = fetch_greenhouse(GH_COMPANY, _session_returning(payload))
        assert len(jobs) == 1
        assert jobs[0].title == "Detection Engineer"


class TestLever:
    PAYLOAD = [
        {
            "id": "abc-123",
            "text": "Threat Hunter",
            "hostedUrl": "https://jobs.lever.co/exampleintel/abc-123",
            "descriptionPlain": "Hunt with Sigma and MITRE ATT&CK.",
            "categories": {"location": "New York", "allLocations": ["New York", "Seattle"]},
            "workplaceType": "remote",
            "createdAt": 1751000000000,
        }
    ]

    def test_parses_jobs(self):
        jobs = fetch_lever(LEVER_COMPANY, _session_returning(self.PAYLOAD))
        assert len(jobs) == 1
        job = jobs[0]
        assert job.uid == "lever:exampleintel:abc-123"
        assert job.description == "Hunt with Sigma and MITRE ATT&CK."
        # workplaceType=remote flags every location as remote-eligible.
        assert all(l.is_remote for l in job.locations)
        # "New York" resolves as the city (metro map wins over state name).
        ny = job.locations[0]
        assert ny.metro == "New York Metro" and ny.state == "NY"
        assert job.posted_at is not None

    def test_locations_deduped(self):
        jobs = fetch_lever(LEVER_COMPANY, _session_returning(self.PAYLOAD))
        raws = [l.raw for l in jobs[0].locations]
        assert raws.count("New York") == 1


class TestAshby:
    PAYLOAD = {
        "jobs": [
            {
                "id": "f1e2d3",
                "title": "Threat Intelligence Engineer",
                "jobUrl": "https://jobs.ashbyhq.com/examplelab.io/f1e2d3",
                "descriptionPlain": "Track actors, write YARA, hunt in EDR.",
                "location": "San Francisco",
                "secondaryLocations": [{"location": "New York"}],
                "isRemote": True,
                "isListed": True,
                "publishedAt": "2026-06-30T12:00:15.322+00:00",
            },
            {
                "id": "unlisted-1",
                "title": "Hidden Role",
                "jobUrl": "https://jobs.ashbyhq.com/examplelab.io/unlisted-1",
                "descriptionHtml": "<p>internal</p>",
                "location": "Remote",
                "isListed": False,
            },
        ]
    }

    def test_parses_jobs(self):
        jobs = fetch_ashby(ASHBY_COMPANY, _session_returning(self.PAYLOAD))
        assert len(jobs) == 1  # unlisted job skipped
        job = jobs[0]
        assert job.uid == "ashby:examplelab.io:f1e2d3"
        assert job.ats == "ashby"
        assert job.description == "Track actors, write YARA, hunt in EDR."
        # isRemote=True flags every location as remote-eligible.
        assert all(l.is_remote for l in job.locations)
        assert {l.raw for l in job.locations} == {"San Francisco", "New York"}
        assert job.posted_at is not None

    def test_html_description_fallback(self):
        payload = {"jobs": [{
            "id": "h1",
            "title": "Detection Engineer",
            "jobUrl": "https://jobs.ashbyhq.com/examplelab.io/h1",
            "descriptionHtml": "<p>Write <b>Sigma</b> rules.</p>",
            "location": "Austin",
        }]}
        jobs = fetch_ashby(ASHBY_COMPANY, _session_returning(payload))
        assert jobs[0].description == "Write Sigma rules."

    def test_remote_with_no_locations(self):
        payload = {"jobs": [{
            "id": "r1",
            "title": "Threat Hunter",
            "jobUrl": "https://jobs.ashbyhq.com/examplelab.io/r1",
            "descriptionPlain": "Hunt.",
            "workplaceType": "Remote",
        }]}
        jobs = fetch_ashby(ASHBY_COMPANY, _session_returning(payload))
        assert jobs[0].locations and jobs[0].locations[0].is_remote

    def test_malformed_job_is_skipped_not_fatal(self):
        payload = {"jobs": [{"title": "no id"}, self.PAYLOAD["jobs"][0]]}
        jobs = fetch_ashby(ASHBY_COMPANY, _session_returning(payload))
        assert len(jobs) == 1
        assert jobs[0].title == "Threat Intelligence Engineer"


class TestFetchAll:
    def test_one_company_failing_does_not_crash(self, monkeypatch):
        def boom(company, session):
            raise requests.ConnectionError("dns failure")

        monkeypatch.setattr("jobscout.fetchers._FETCHERS", {
            "greenhouse": boom,
            "lever": lambda c, s: fetch_lever(c, _session_returning(TestLever.PAYLOAD)),
        })
        jobs = fetch_all([GH_COMPANY, LEVER_COMPANY])
        assert len(jobs) == 1  # lever succeeded, greenhouse failure swallowed


@pytest.mark.parametrize("raw,expected", [
    ("<p>Hello &amp; welcome</p>", "Hello & welcome"),
    ("no tags", "no tags"),
    ("", ""),
    ("<div>a</div><div>b</div>", "a b"),
])
def test_strip_html(raw, expected):
    assert strip_html(raw) == expected
