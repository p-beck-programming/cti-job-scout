"""Fetch open postings from public ATS APIs (no auth required).

Greenhouse: https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
Lever:      https://api.lever.co/v0/postings/{token}?mode=json
Ashby:      https://api.ashbyhq.com/posting-api/job-board/{token}

Design decisions:
- One company failing (bad token, 5xx, timeout) is logged and skipped —
  a single broken entry in companies.yaml must never kill the daily run.
- Descriptions are HTML-stripped and truncated before scoring; the model only
  needs the text, and truncation caps per-posting token cost.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone

import requests

from .locations import parse_location, parse_locations
from .models import Company, JobPosting

log = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30  # seconds
MAX_DESCRIPTION_CHARS = 12_000  # ~3k tokens; plenty for relevance scoring

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """Reduce ATS HTML descriptions to plain text for scoring."""
    text = html.unescape(text or "")
    text = _TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_greenhouse(company: Company, session: requests.Session) -> list[JobPosting]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{company.token}/jobs"
    resp = session.get(url, params={"content": "true"}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()

    postings: list[JobPosting] = []
    for job in payload.get("jobs", []):
        try:
            raw_locs = []
            loc_obj = job.get("location") or {}
            if loc_obj.get("name"):
                raw_locs.append(loc_obj["name"])
            for office in job.get("offices") or []:
                if office.get("name"):
                    raw_locs.append(office["name"])

            posted_at = None
            if job.get("updated_at"):
                posted_at = datetime.fromisoformat(
                    job["updated_at"].replace("Z", "+00:00")
                )

            postings.append(
                JobPosting(
                    uid=f"greenhouse:{company.token}:{job['id']}",
                    company=company.name,
                    ats="greenhouse",
                    title=job.get("title", "(untitled)"),
                    url=job.get("absolute_url", ""),
                    description=strip_html(job.get("content", ""))[
                        :MAX_DESCRIPTION_CHARS
                    ],
                    locations=parse_locations(raw_locs),
                    posted_at=posted_at,
                )
            )
        except Exception:  # one malformed job shouldn't sink the company
            log.exception("Skipping malformed Greenhouse job for %s", company.name)
    return postings


def fetch_lever(company: Company, session: requests.Session) -> list[JobPosting]:
    url = f"https://api.lever.co/v0/postings/{company.token}"
    resp = session.get(url, params={"mode": "json"}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()

    postings: list[JobPosting] = []
    for job in payload if isinstance(payload, list) else []:
        try:
            cats = job.get("categories") or {}
            raw_locs = []
            if cats.get("location"):
                raw_locs.append(cats["location"])
            raw_locs.extend(cats.get("allLocations") or [])
            locations = parse_locations(raw_locs)
            # Lever exposes remote-ness in a dedicated field; trust it.
            if job.get("workplaceType") == "remote":
                if locations:
                    for loc in locations:
                        loc.is_remote = True
                else:
                    locations = [parse_location("Remote")]

            posted_at = None
            if job.get("createdAt"):
                posted_at = datetime.fromtimestamp(
                    job["createdAt"] / 1000, tz=timezone.utc
                )

            postings.append(
                JobPosting(
                    uid=f"lever:{company.token}:{job['id']}",
                    company=company.name,
                    ats="lever",
                    title=job.get("text", "(untitled)"),
                    url=job.get("hostedUrl", ""),
                    description=strip_html(
                        job.get("descriptionPlain") or job.get("description", "")
                    )[:MAX_DESCRIPTION_CHARS],
                    locations=locations,
                    posted_at=posted_at,
                )
            )
        except Exception:
            log.exception("Skipping malformed Lever job for %s", company.name)
    return postings


def fetch_ashby(company: Company, session: requests.Session) -> list[JobPosting]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company.token}"
    resp = session.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()

    postings: list[JobPosting] = []
    for job in payload.get("jobs", []):
        try:
            if job.get("isListed") is False:
                continue
            raw_locs = []
            if job.get("location"):
                raw_locs.append(job["location"])
            for sec in job.get("secondaryLocations") or []:
                # Entries are {"location": "...", "address": {...}} objects.
                name = sec.get("location") if isinstance(sec, dict) else sec
                if name:
                    raw_locs.append(name)
            locations = parse_locations(raw_locs)
            # Ashby exposes remote-ness in dedicated fields; trust them.
            if job.get("isRemote") is True or job.get("workplaceType") == "Remote":
                if locations:
                    for loc in locations:
                        loc.is_remote = True
                else:
                    locations = [parse_location("Remote")]

            posted_at = None
            if job.get("publishedAt"):
                try:
                    posted_at = datetime.fromisoformat(job["publishedAt"])
                except ValueError:
                    pass  # unexpected timestamp precision; not worth losing the job

            postings.append(
                JobPosting(
                    uid=f"ashby:{company.token}:{job['id']}",
                    company=company.name,
                    ats="ashby",
                    title=job.get("title", "(untitled)"),
                    url=job.get("jobUrl", ""),
                    description=strip_html(
                        job.get("descriptionPlain") or job.get("descriptionHtml", "")
                    )[:MAX_DESCRIPTION_CHARS],
                    locations=locations,
                    posted_at=posted_at,
                )
            )
        except Exception:
            log.exception("Skipping malformed Ashby job for %s", company.name)
    return postings


_FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
}


def fetch_all(companies: list[Company]) -> list[JobPosting]:
    """Fetch every company's open postings; failures are logged, not raised."""
    session = requests.Session()
    session.headers["User-Agent"] = "cti-job-scout/1.0 (personal job-search agent)"
    all_postings: list[JobPosting] = []
    for company in companies:
        try:
            postings = _FETCHERS[company.ats](company, session)
            log.info("%s: %d open postings", company.name, len(postings))
            all_postings.extend(postings)
        except Exception as exc:
            log.error("Fetch failed for %s (%s:%s): %s",
                      company.name, company.ats, company.token, exc)
    return all_postings
